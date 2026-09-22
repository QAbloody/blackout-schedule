#!/usr/bin/env python3

import json
import random
import os
import requests
from datetime import datetime, timedelta

SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
CHAT_ID = os.getenv("CHAT_ID", "ВАШ_CHAT_ID")

GROUPS = [
    "1.1", "1.2",
    "2.1", "2.2",
    "3.1", "3.2",
    "4.1", "4.2",
    "5.1", "5.2",
    "6.1", "6.2"
]

WEEKDAYS_UA = [
    "Понеділок", "Вівторок", "Середа", "Четвер", 
    "П'ятниця", "Субота", "Неділя"
]

def generate_intervals():
    possible_starts = [
        "00:00", "00:30", "01:00", "02:00", "03:00", "04:00", "05:00",
        "06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00",
        "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00",
        "20:00", "21:00", "22:00", "23:00"
    ]
    random.shuffle(possible_starts)
    count = random.randint(0, 3)  # Сделали возможность 0 отключений
    intervals = []
    used = []

    for start in possible_starts:
        if len(intervals) >= count:
            break

        hour, minute = map(int, start.split(":"))
        duration = random.choice([30, 60, 90, 120, 180])
        start_minutes = hour * 60 + minute
        end_minutes = start_minutes + duration

        if end_minutes > 1440:
            continue

        overlap = False
        for old_start, old_end in used:
            if start_minutes < old_end and end_minutes > old_start:
                overlap = True
                break

        if overlap:
            continue

        end_hour = end_minutes // 60
        end_minute = end_minutes % 60
        intervals.append(f"{start}-{end_hour:02d}:{end_minute:02d}")
        used.append((start_minutes, end_minutes))

    intervals.sort()
    return intervals

def generate_groups():
    return {group: generate_intervals() for group in GROUPS}

def calculate_off_minutes(intervals):
    """Считает общее время отключений в минутах."""
    total = 0
    for interval in intervals:
        start_str, end_str = interval.split("-")
        h1, m1 = map(int, start_str.split(":"))
        h2, m2 = map(int, end_str.split(":"))
        total += (h2 * 60 + m2) - (h1 * 60 + m1)
    return total

def format_day_status(date_str, intervals):
    """Формирует блок статуса на один день в стиле шаблона."""
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    day_name = WEEKDAYS_UA[dt.weekday()]
    
    off_minutes = calculate_off_minutes(intervals)
    on_minutes = 1440 - off_minutes
    
    off_hours = round(off_minutes / 60, 1)
    on_hours = round(on_minutes / 60, 1)

    if off_minutes == 0:
        header_icon = "📝"
        status_icon = "🟢"
        intervals_str = "00:00 - 00:00 (24 год.)"
    else:
        header_icon = "⚠️"
        status_icon = "🔴"
        formatted_list = ", ".join(intervals)
        intervals_str = f"{formatted_list} ({off_hours:g} год.)"

    return (
        f"{header_icon} <b>{day_name}, {date_str}</b>\n"
        f"{status_icon} {intervals_str}\n"
        f"📊 <i>Світло є: {on_hours:g} год. | Немає: {off_hours:g} год.</i>"
    )

def create_telegram_message(group_name, today_date, today_intervals, tomorrow_date, tomorrow_intervals):
    """Собирает полный шаблон сообщения."""
    today_block = format_day_status(today_date, today_intervals)
    tomorrow_block = format_day_status(tomorrow_date, tomorrow_intervals)

    message = (
        f"<b>📍 Група {group_name} ДТЕК Дніпро</b>\n\n"
        f"{today_block}\n\n"
        f"{tomorrow_block}\n"
        f"_____________________\n\n"
        f"👉 <b>Графіки ДТЕК Дніпро</b> 👈"
    )
    return message

def send_telegram(text):
    """Отправка сообщения в Telegram чат/канал."""
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА":
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("📲 Уведомление отправлено в Telegram")
    except Exception as e:
        print(f"❌ Ошибка отправки Telegram: {e}")

def main():
    now = datetime.now()
    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")

    today_groups = generate_groups()
    tomorrow_groups = generate_groups()

    # Сохраняем JSON
    result = {
        "timezone": "Europe/Kyiv",
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "TEST DATA",
        "emergency": None,
        "today": {"date": today, "groups": today_groups},
        "tomorrow": {"date": tomorrow, "groups": tomorrow_groups}
    }

    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Выбираем группу для отправки сообщения (например, 1.2 из скриншота)
    target_group = "1.2"
    msg_text = create_telegram_message(
        group_name=target_group,
        today_date=today,
        today_intervals=today_groups[target_group],
        tomorrow_date=tomorrow,
        tomorrow_intervals=tomorrow_groups[target_group]
    )

    print("\nСформированный текст уведомления:\n")
    print(msg_text)

    # Отправляем в Telegram
    send_telegram(msg_text)

if __name__ == "__main__":
    main()
