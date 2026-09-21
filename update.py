#!/usr/bin/env python3

import json
import random
import os
from datetime import datetime, timedelta


SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")


GROUPS = [
    "1.1", "1.2",
    "2.1", "2.2",
    "3.1", "3.2",
    "4.1", "4.2",
    "5.1", "5.2",
    "6.1", "6.2"
]


def generate_intervals():
    """
    Генерирует несколько случайных отключений
    в течение суток.
    """

    intervals = []

    possible_starts = [
        "00:00",
        "00:30",
        "01:00",
        "02:00",
        "03:00",
        "04:00",
        "05:00",
        "06:00",
        "07:00",
        "08:00",
        "09:00",
        "10:00",
        "11:00",
        "12:00",
        "13:00",
        "14:00",
        "15:00",
        "16:00",
        "17:00",
        "18:00",
        "19:00",
        "20:00",
        "21:00",
        "22:00",
        "23:00"
    ]

    random.shuffle(possible_starts)

    count = random.randint(2, 4)

    used = []

    for start in possible_starts:

        hour, minute = map(int, start.split(":"))

        duration = random.choice([30, 60, 90, 120, 150, 180])

        start_minutes = hour * 60 + minute
        end_minutes = start_minutes + duration

        if end_minutes > 1440:
            continue

        end_hour = end_minutes // 60
        end_minute = end_minutes % 60

        end = f"{end_hour:02d}:{end_minute:02d}"

        # Проверяем, чтобы интервалы не пересекались
        new_start = start_minutes
        new_end = end_minutes

        overlap = False

        for old_start, old_end in used:
            if new_start < old_end and new_end > old_start:
                overlap = True
                break

        if overlap:
            continue

        intervals.append(f"{start}-{end}")
        used.append((new_start, new_end))

        if len(intervals) >= count:
            break

    intervals.sort()

    return intervals


def generate_groups():
    """
    Создаёт графики для всех 12 групп.
    """

    groups = {}

    for group in GROUPS:
        groups[group] = generate_intervals()

    return groups


def print_groups(groups, title):
    print()
    print("=" * 50)
    print(title)
    print("=" * 50)

    for group in GROUPS:

        intervals = groups.get(group, [])

        if intervals:
            print(f"📍 Група {group}: {', '.join(intervals)}")
        else:
            print(f"📍 Група {group}: відключень немає")


def main():

    print("=" * 60)
    print("🧪 TEST SCHEDULE GENERATOR")
    print("=" * 60)

    now = datetime.now()

    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")

    print(f"\n📅 Сьогодні: {today}")
    print(f"📅 Завтра: {tomorrow}")

    # Генерируем разные графики
    today_groups = generate_groups()
    tomorrow_groups = generate_groups()

    print_groups(today_groups, "📊 СЬОГОДНІ")

    print_groups(tomorrow_groups, "📅 ЗАВТРА")

    # Создаём результат в том же формате,
    # который использует настоящий update.py
    result = {
        "timezone": "Europe/Kyiv",

        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),

        "source": "TEST DATA",

        "emergency": None,

        "today": {
            "date": today,
            "groups": today_groups
        },

        "tomorrow": {
            "date": tomorrow,
            "groups": tomorrow_groups
        }
    }

    # Сохраняем schedule.json
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 60)
    print(f"💾 Сохранено: {SCHEDULE_FILE}")
    print("=" * 60)

    print(
        f"📊 Сьогодні: "
        f"{len(today_groups)} груп"
    )

    print(
        f"📅 Завтра: "
        f"{len(tomorrow_groups)} груп"
    )

    print()
    print("✅ TEST DATA READY")
    print("👋 Done")


if __name__ == "__main__":
    main()
