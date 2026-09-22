#!/usr/bin/env python3

import os
import json
import traceback
import requests

from datetime import datetime


# ============================================================
# НАСТРОЙКИ
# ============================================================

YASNO_API = (
    "https://api.yasno.com.ua/api/v1/pages/home/"
    "schedule-turn-off-electricity"
)

SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")


# Групи, які беремо з YASNO
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
# YASNO
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


def yasno_slots_to_intervals(slots):
    if not slots:
        return []

    intervals = []

    for slot in slots:

        start = slot.get("start", 0)
        end = slot.get("end", 0)

        slot_type = slot.get("type", "")

        if "OUTAGE" not in slot_type:
            continue

        sh = int(start)
        sm = int(round((start - sh) * 60))

        eh = int(end)
        em = int(round((end - eh) * 60))

        if eh == 24:
            em = 0

        intervals.append(
            f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"
        )

    return merge_intervals(intervals)


def fetch_yasno_schedule():
    print()
    print("=" * 60)
    print("📡 YASNO API")
    print("=" * 60)

    result = {
        "today": {},
        "tomorrow": {}
    }

    try:

        response = requests.get(
            YASNO_API,
            timeout=30
        )

        print(f"HTTP: {response.status_code}")

        response.raise_for_status()

        data = response.json()

        components = data.get("components", [])

        schedule_data = None

        for component in components:

            if component.get("template_name") == (
                "electricity-outages-daily-schedule"
            ):

                schedule_data = (
                    component
                    .get("schedule", {})
                    .get("dnipro", {})
                )

                break

        if not schedule_data:

            print("❌ Графіки YASNO не знайдені")

            return result

        print("✅ Графіки YASNO знайдені")

        today_weekday = datetime.now().weekday()

        tomorrow_weekday = (
            today_weekday + 1
        ) % 7

        for group in YASNO_GROUPS:

            group_key = f"group_{group}"

            group_data = schedule_data.get(
                group_key,
                []
            )

            if not group_data:

                print(
                    f"⚠️ Група {group}: даних немає"
                )

                continue

            if len(group_data) < 7:

                print(
                    f"⚠️ Група {group}: "
                    f"неочікувана структура"
                )

                continue

            today_slots = group_data[
                today_weekday
            ]

            tomorrow_slots = group_data[
                tomorrow_weekday
            ]

            today_intervals = (
                yasno_slots_to_intervals(
                    today_slots
                )
            )

            tomorrow_intervals = (
                yasno_slots_to_intervals(
                    tomorrow_slots
                )
            )

            result["today"][group] = today_intervals
            result["tomorrow"][group] = tomorrow_intervals

            today_minutes = sum_intervals(
                today_intervals
            )

            tomorrow_minutes = sum_intervals(
                tomorrow_intervals
            )

            print(
                f"📍 {group}: "
                f"сьогодні "
                f"{today_minutes // 60}год "
                f"{today_minutes % 60:02d}хв | "
                f"завтра "
                f"{tomorrow_minutes // 60}год "
                f"{tomorrow_minutes % 60:02d}хв"
            )

        print(
            f"✅ YASNO оброблено: "
            f"{len(result['today'])} груп"
        )

    except Exception as e:

        print(
            f"❌ Помилка YASNO: {e}"
        )

        traceback.print_exc()

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🚀 YASNO PARSER")
    print("=" * 60)

    now = datetime.now()

    today = now.strftime("%d.%m.%Y")
    tomorrow = now.strftime("%d.%m.%Y")

    print()
    print(f"📅 Сьогодні: {today}")
    print(f"📅 Завтра: {tomorrow}")

    # --------------------------------------------------------
    # YASNO
    # --------------------------------------------------------

    yasno_data = fetch_yasno_schedule()

    today_groups = dict(yasno_data.get("today", {}))
    tomorrow_groups = dict(yasno_data.get("tomorrow", {}))

    # Додаємо порожні групи,
    # щоб JSON завжди мав всі групи

    for group in ALL_GROUPS:

        if group not in today_groups:
            today_groups[group] = []

        if group not in tomorrow_groups:
            tomorrow_groups[group] = []

    # --------------------------------------------------------
    # РЕЗУЛЬТАТ
    # --------------------------------------------------------

    result = {

        "timezone": "Europe/Kyiv",

        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),

        "source": "yasno.com.ua",

        "today": {
            "date": today,
            "groups": today_groups
        },

        "tomorrow": {
            "date": tomorrow,
            "groups": tomorrow_groups
        }
    }

    # --------------------------------------------------------
    # СОХРАНЕНИЕ
    # --------------------------------------------------------

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
