#!/usr/bin/env python3

import os
import sys
import json
import traceback
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


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

# Файл зі станом сповіщень (що вже надіслано), щоб не дублювати повідомлення.
# Його треба зберігати між запусками (див. коментар у кінці відповіді).
STATE_FILE = os.getenv("STATE_FILE", "notify_state.json")

KYIV_TZ = ZoneInfo("Europe/Kyiv")

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
# НАСТРОЙКИ СПОВІЩЕНЬ
# ============================================================

ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID")

# Куди слати сповіщення про графіки та відключення.
# Якщо окремо не задано — використовується той самий бот/чат, що й для алертів.
NOTIFY_BOT_TOKEN = os.getenv("NOTIFY_BOT_TOKEN") or ALERT_BOT_TOKEN
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID") or ALERT_CHAT_ID

# Для яких груп слати сповіщення, через кому: NOTIFY_GROUPS="3.1,3.2"
# Якщо не задано — для всіх груп (це буде багато повідомлень, краще задати свою).
NOTIFY_GROUPS = [
    g.strip()
    for g in os.getenv("NOTIFY_GROUPS", "").split(",")
    if g.strip()
] or list(YASNO_GROUPS)

# За скільки хвилин попереджати про відключення
REMIND_MINUTES = int(os.getenv("REMIND_MINUTES", "30"))


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


def hhmm_to_minutes(value):
    h, m = map(int, value.split(":"))
    return h * 60 + m


def iso_date_to_ddmmyyyy(iso_date):
    try:
        return datetime.fromisoformat(iso_date).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso_date


def parse_ddmmyyyy(value):
    try:
        return datetime.strptime(value, "%d.%m.%Y")
    except (ValueError, TypeError):
        return None


def send_telegram_message(token, chat_id, message):
    """Шле повідомлення в Telegram. Повертає True, якщо відправлено."""

    if not token or not chat_id:
        print("⚠️ Токен/чат Telegram не задані — повідомлення пропущено")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        if response.status_code != 200:
            print(
                f"⚠️ Telegram відповів {response.status_code}: "
                f"{response.text[:200]}"
            )
            return False

        return True

    except Exception as e:
        print(f"⚠️ Не вдалося надіслати повідомлення в Telegram: {e}")
        return False


def send_telegram_alert(message):
    """Шле повідомлення в Telegram про збій парсера. Тихо пропускає,
    якщо ALERT_BOT_TOKEN / ALERT_CHAT_ID не задані (наприклад, локально)."""

    if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
        print("⚠️ ALERT_BOT_TOKEN / ALERT_CHAT_ID не задані — сповіщення пропущено")
        return

    send_telegram_message(ALERT_BOT_TOKEN, ALERT_CHAT_ID, message)


def send_notification(message):
    return send_telegram_message(NOTIFY_BOT_TOKEN, NOTIFY_CHAT_ID, message)


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
# NOTIFICATIONS
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    state.setdefault("schedules", {})   # {дата: {група: хеш графіка}}
    state.setdefault("reminders", [])   # ключі вже надісланих нагадувань

    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def schedule_ready(status):
    """Графік на день уже опубліковано (а не 'очікується')."""
    return status is not None and status != "WaitingForSchedule"


def format_intervals(intervals):
    if not intervals:
        return "відключень не заплановано ✅"

    return ", ".join(i.replace("-", "–") for i in intervals)


def notify_schedules(days, state):
    """Повідомляє, коли з'явився (або змінився) графік на сьогодні/завтра.

    Стан зберігається по даті, тому графік, про який уже повідомили
    як про "завтра", не дублюється наступного дня як "сьогодні".
    """

    for label, date_str, groups, statuses in days:

        known = state["schedules"].setdefault(date_str, {})

        new_lines = []
        changed_lines = []
        pending = {}

        for group in NOTIFY_GROUPS:

            if not schedule_ready(statuses.get(group)):
                continue

            intervals = groups.get(group, [])
            digest = "|".join(intervals) or "none"
            previous = known.get(group)

            if previous == digest:
                continue

            line = f"🔹 Група {group}: {format_intervals(intervals)}"

            if previous is None:
                new_lines.append(line)
            else:
                changed_lines.append(line)

            pending[group] = digest

        if not pending:
            continue

        sent_all = True

        if new_lines:
            text = (
                f"📅 З'явився графік на {label} ({date_str})\n\n"
                + "\n".join(new_lines)
            )
            sent_all = send_notification(text) and sent_all

        if changed_lines:
            text = (
                f"⚠️ Графік на {label} ({date_str}) змінився\n\n"
                + "\n".join(changed_lines)
            )
            sent_all = send_notification(text) and sent_all

        # запам'ятовуємо лише після успішної відправки,
        # інакше наступний запуск спробує ще раз
        if sent_all:
            known.update(pending)


def build_outage_events(group, days):
    """Повертає список (початок, кінець) відключень групи як datetime,
    зливаючи інтервали через північ (24:00 → 00:00)."""

    events = []

    for _label, date_str, groups, statuses in days:

        day = parse_ddmmyyyy(date_str)

        if day is None or not schedule_ready(statuses.get(group)):
            continue

        for interval in groups.get(group, []):

            start_s, end_s = interval.split("-")

            start = day + timedelta(minutes=hhmm_to_minutes(start_s))

            if end_s == "24:00":
                end = day + timedelta(days=1)
            else:
                end = day + timedelta(minutes=hhmm_to_minutes(end_s))

            events.append((start, end))

    events.sort()

    merged = []

    for start, end in events:
        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    return merged


def notify_upcoming_outages(now, days, state):
    """Попереджає за REMIND_MINUTES хвилин до початку відключення."""

    sent_keys = set(state["reminders"])

    lines = []
    new_keys = []

    for group in NOTIFY_GROUPS:

        for start, end in build_outage_events(group, days):

            minutes_left = (start - now).total_seconds() / 60

            if not (0 < minutes_left <= REMIND_MINUTES):
                continue

            key = f"{group}|{start:%Y-%m-%d %H:%M}"

            if key in sent_keys:
                continue

            end_text = end.strftime("%H:%M")
            if end_text == "00:00":
                end_text = "24:00"

            lines.append(
                f"🔹 Група {group}: {start:%H:%M}–{end_text} "
                f"(через ~{int(round(minutes_left))} хв)"
            )
            new_keys.append(key)

    if not lines:
        return

    text = (
        f"⏰ Скоро відключення світла (менше ніж за {REMIND_MINUTES} хв)\n\n"
        + "\n".join(lines)
    )

    if send_notification(text):
        state["reminders"].extend(new_keys)


def prune_state(state, now):
    """Видаляє застарілі записи зі стану."""

    cutoff = (now - timedelta(days=2)).date()

    state["schedules"] = {
        d: v
        for d, v in state["schedules"].items()
        if (parse_ddmmyyyy(d) is not None
            and parse_ddmmyyyy(d).date() >= cutoff)
    }

    cutoff_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    state["reminders"] = [
        k for k in state["reminders"]
        if k.split("|")[-1][:10] >= cutoff_str
    ]


def process_notifications(now, days):
    print()
    print("=" * 60)
    print("🔔 СПОВІЩЕННЯ")
    print("=" * 60)
    print(f"Групи: {', '.join(NOTIFY_GROUPS)}")

    state = load_state()

    try:
        notify_schedules(days, state)
        notify_upcoming_outages(now, days, state)
    except Exception as e:
        print(f"❌ Помилка сповіщень: {e}")
        traceback.print_exc()
    finally:
        prune_state(state, now)
        save_state(state)


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

    # завжди київський час, незалежно від часового поясу сервера
    now = datetime.now(KYIV_TZ).replace(tzinfo=None)

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
            f"Час: {now.strftime('%Y-%m-%d %H:%M:%S')} (Київ)\n"
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

    # ------------------------------------------------------------
    # СПОВІЩЕННЯ В TELEGRAM
    # ------------------------------------------------------------

    process_notifications(
        now,
        [
            ("сьогодні", today, today_groups, today_statuses),
            ("завтра", tomorrow, tomorrow_groups, tomorrow_statuses),
        ],
    )

    print()
    print("✅ PARSER FINISHED")


if __name__ == "__main__":
    main()
