#!/usr/bin/env python3

import os
import sys
import json
import traceback
import requests

from datetime import datetime, timedelta


# ============================================================
# НАСТРОЙКИ
# ============================================================

REGIONS_ENDPOINT = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/"
    "addresses/v2/regions"
)

PLANNED_OUTAGES_ENDPOINT = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/"
    "regions/{region_id}/dsos/{dso_id}/planned-outages"
)

SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

# Якщо відомі — постав сюди готові id, і скрипт більше не буде
# щоразу ходити за списком регіонів/провайдерів (швидше і надійніше).
# Дізнатись їх можна з першого запуску скрипта — він виведе їх у консоль.
REGION_ID = os.getenv("YASNO_REGION_ID")
PROVIDER_ID = os.getenv("YASNO_PROVIDER_ID")

# Підрядок для пошуку потрібного регіону/міста, якщо ID не задані напряму
REGION_QUERY = os.getenv("YASNO_REGION_QUERY", "дніпро")

# Групи, які нас цікавлять
YASNO_GROUPS = [
    "1.1", "1.2",
    "2.1", "2.2",
    "3.1", "3.2",
    "4.1", "4.2",
    "5.1", "5.2",
    "6.1", "6.2",
]

ALL_GROUPS = YASNO_GROUPS


# ============================================================
# HELPERS
# ============================================================

def merge_intervals(intervals):
    if not intervals:
        return []

    intervals = sorted(intervals)

    result = [intervals[0]]

    for current in intervals[1:]:
        last = result[-1]

        last_start, last_end = last.split("-")
        current_start, current_end = current.split("-")

        if last_end == current_start:
            result[-1] = last_start + "-" + current_end
        else:
            result.append(current)

    return result


def sum_intervals(intervals):
    total = 0

    for interval in intervals:
        parts = interval.split("-")

        if len(parts) != 2:
            continue

        sh, sm = map(int, parts[0].split(":"))
        eh, em = map(int, parts[1].split(":"))

        start = sh * 60 + sm

        if eh == 24:
            end = 24 * 60
        else:
            end = eh * 60 + em

        total += end - start

    return total


def minutes_to_hhmm(minutes):
    minutes = int(minutes)

    if minutes >= 24 * 60:
        return "24:00"

    h, m = divmod(minutes, 60)

    return f"{h:02d}:{m:02d}"


def iso_date_to_ddmmyyyy(iso_date):
    try:
        return datetime.fromisoformat(iso_date).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso_date


ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID")


def send_telegram_alert(message):
    """Шле повідомлення в Telegram про збій парсера. Тихо пропускає,
    якщо ALERT_BOT_TOKEN / ALERT_CHAT_ID не задані (наприклад, локально)."""

    if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
        print("⚠️ ALERT_BOT_TOKEN / ALERT_CHAT_ID не задані — сповіщення пропущено")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ALERT_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
    except Exception as e:
        print(f"⚠️ Не вдалося надіслати сповіщення в Telegram: {e}")


def slots_to_intervals(slots):
    """slots: list of {"start": int_minutes, "end": int_minutes, "type": str}."""

    intervals = []

    for slot in slots or []:

        # враховуємо лише підтверджені (не "ймовірні") відключення
        if slot.get("type") != "Definite":
            continue

        start = minutes_to_hhmm(slot.get("start", 0))
        end = minutes_to_hhmm(slot.get("end", 0))

        intervals.append(f"{start}-{end}")

    return merge_intervals(intervals)


# ============================================================
# RESOLVE REGION / PROVIDER
# ============================================================

def resolve_region_and_provider():

    if REGION_ID and PROVIDER_ID:
        return int(REGION_ID), int(PROVIDER_ID)

    print("🔎 Шукаємо регіон/провайдера за запитом:", REGION_QUERY)

    response = requests.get(REGIONS_ENDPOINT, timeout=30)
    response.raise_for_status()

    regions = response.json()

    matches = [
        r for r in regions
        if REGION_QUERY.lower() in str(r.get("value", "")).lower()
    ]

    if not matches:
        raise RuntimeError(
            f"Регіон за запитом '{REGION_QUERY}' не знайдено. "
            f"Доступні регіони: "
            f"{[r.get('value') for r in regions]}"
        )

    if len(matches) > 1:
        print("⚠️ Знайдено декілька регіонів, беремо перший:")
        for r in matches:
            print(f"   - {r.get('value')} (id={r.get('id')})")

    region = matches[0]
    dsos = region.get("dsos", [])

    if not dsos:
        raise RuntimeError(
            f"У регіону '{region.get('value')}' немає провайдерів (dsos)"
        )

    if len(dsos) > 1:
        print("⚠️ Знайдено декілька провайдерів, беремо перший:")
        for d in dsos:
            print(f"   - {d.get('name')} (id={d.get('id')})")

    provider = dsos[0]

    print(
        f"✅ Регіон: {region.get('value')} (id={region.get('id')}) | "
        f"Провайдер: {provider.get('name')} (id={provider.get('id')})"
    )
    print(
        "💡 Щоб не робити цей пошук щоразу, задай змінні оточення:\n"
        f"   YASNO_REGION_ID={region.get('id')}\n"
        f"   YASNO_PROVIDER_ID={provider.get('id')}"
    )

    return region.get("id"), provider.get("id")


# ============================================================
# FETCH SCHEDULE
# ============================================================

def fetch_yasno_schedule():
    print()
    print("=" * 60)
    print("📡 YASNO API (app.yasno.ua)")
    print("=" * 60)

    result = {
        "today": {},
        "tomorrow": {},
        "statuses": {"today": {}, "tomorrow": {}},
        "dates": {"today": None, "tomorrow": None},
        "error": None,
    }

    try:

        region_id, provider_id = resolve_region_and_provider()

        url = PLANNED_OUTAGES_ENDPOINT.format(
            region_id=region_id,
            dso_id=provider_id,
        )

        response = requests.get(url, timeout=30)

        print(f"HTTP: {response.status_code}")

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            print("❌ Неочікуваний формат відповіді")
            return result

        if os.getenv("YASNO_DEBUG"):
            sample_group = YASNO_GROUPS[0]
            print(
                f"🐛 DEBUG сирі дані для групи {sample_group}:\n"
                + json.dumps(
                    data.get(sample_group, {}),
                    ensure_ascii=False,
                    indent=2,
                )
            )

        for group in YASNO_GROUPS:

            group_data = data.get(group)

            if not group_data:
                print(f"⚠️ Група {group}: даних немає")
                continue

            today_block = group_data.get("today", {}) or {}
            tomorrow_block = group_data.get("tomorrow", {}) or {}

            today_status = today_block.get("status")
            tomorrow_status = tomorrow_block.get("status")

            print(
                f"    ℹ️ {group}: статус сьогодні={today_status}, "
                f"завтра={tomorrow_status}"
            )

            today_slots = today_block.get("slots", [])
            tomorrow_slots = tomorrow_block.get("slots", [])

            today_intervals = slots_to_intervals(today_slots)
            tomorrow_intervals = slots_to_intervals(tomorrow_slots)

            result["today"][group] = today_intervals
            result["tomorrow"][group] = tomorrow_intervals

            result["statuses"]["today"][group] = today_status
            result["statuses"]["tomorrow"][group] = tomorrow_status

            if not result["dates"]["today"] and today_block.get("date"):
                result["dates"]["today"] = iso_date_to_ddmmyyyy(
                    today_block["date"]
                )

            if not result["dates"]["tomorrow"] and tomorrow_block.get("date"):
                result["dates"]["tomorrow"] = iso_date_to_ddmmyyyy(
                    tomorrow_block["date"]
                )

            today_minutes = sum_intervals(today_intervals)
            tomorrow_minutes = sum_intervals(tomorrow_intervals)

            print(
                f"📍 {group}: "
                f"сьогодні "
                f"{today_minutes // 60}год "
                f"{today_minutes % 60:02d}хв | "
                f"завтра "
                f"{tomorrow_minutes // 60}год "
                f"{tomorrow_minutes % 60:02d}хв"
            )

        print(f"✅ YASNO оброблено: {len(result['today'])} груп")

    except Exception as e:

        print(f"❌ Помилка YASNO: {e}")
        traceback.print_exc()
        result["error"] = str(e)

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🚀 YASNO PARSER (new API)")
    print("=" * 60)

    now = datetime.now()

    yasno_data = fetch_yasno_schedule()

    # дата береться з відповіді API, якщо вона там є;
    # інакше рахуємо локально (сьогодні / сьогодні+1)
    today = yasno_data.get("dates", {}).get("today") or now.strftime(
        "%d.%m.%Y"
    )
    tomorrow = yasno_data.get("dates", {}).get("tomorrow") or (
        now + timedelta(days=1)
    ).strftime("%d.%m.%Y")

    print()
    print(f"📅 Сьогодні: {today}")
    print(f"📅 Завтра: {tomorrow}")

    today_groups = dict(yasno_data.get("today", {}))
    tomorrow_groups = dict(yasno_data.get("tomorrow", {}))

    today_statuses = dict(yasno_data.get("statuses", {}).get("today", {}))
    tomorrow_statuses = dict(
        yasno_data.get("statuses", {}).get("tomorrow", {})
    )

    # якщо групи взагалі немає в даних API (запит не вдався,
    # або групу не знайдено) — статус явно позначаємо як "невідомо",
    # щоб бот міг написати "графіки не надходили" замість "світло весь день"
    for group in ALL_GROUPS:

        if group not in today_groups:
            today_groups[group] = []
            today_statuses.setdefault(group, None)

        if group not in tomorrow_groups:
            tomorrow_groups[group] = []
            tomorrow_statuses.setdefault(group, None)

    # ------------------------------------------------------------
    # ПЕРЕВІРКА НА ПОВНИЙ ЗБІЙ
    # ------------------------------------------------------------

    all_missing = all(
        v is None for v in today_statuses.values()
    ) and all(
        v is None for v in tomorrow_statuses.values()
    )

    if yasno_data.get("error") or all_missing:

        reason = yasno_data.get("error") or (
            "Дані по жодній групі не отримано "
            "(порожня/неочікувана відповідь API)"
        )

        alert_text = (
            "🚨 YASNO PARSER: збій оновлення графіка\n\n"
            f"Час: {now.strftime('%Y-%m-%d %H:%M:%S')} (лок.)\n"
            f"Причина: {reason}\n\n"
            "schedule.json НЕ перезаписано — залишено попередню версію."
        )

        print()
        print("=" * 60)
        print(alert_text)
        print("=" * 60)

        send_telegram_alert(alert_text)

        # не перезаписуємо schedule.json порожніми даними —
        # хай краще лишиться остання робоча версія
        sys.exit(1)

    result = {

        "timezone": "Europe/Kyiv",

        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),

        "source": "app.yasno.ua",

        "today": {
            "date": today,
            "groups": today_groups,
            "statuses": today_statuses
        },

        "tomorrow": {
            "date": tomorrow,
            "groups": tomorrow_groups,
            "statuses": tomorrow_statuses
        }
    }

    with open(SCHEDULE_FILE, "w", encoding="utf-8") as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 60)
    print(f"💾 Збережено: {SCHEDULE_FILE}")
    print("=" * 60)

    print()
    print("📊 РЕЗУЛЬТАТ")

    for group in ALL_GROUPS:

        today_v = today_groups[group]
        tomorrow_v = tomorrow_groups[group]

        print(
            f"{group}: "
            f"сьогодні={today_v or 'немає'} | "
            f"завтра={tomorrow_v or 'немає'}"
        )

    print()
    print("✅ PARSER FINISHED")


if __name__ == "__main__":
    main()
