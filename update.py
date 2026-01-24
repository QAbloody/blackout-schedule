#!/usr/bin/env python3
"""
ДТЭК График - Автоматический парсер графиков отключений
Парсит канал @dnepr_svet_voda и обновляет schedule.json
"""

import os
import re
import json
import html
import time
from datetime import datetime, date, timezone, timedelta
from random import randint
from typing import Dict, Any, Optional

import requests


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

CHANNEL = os.getenv("TG_CHANNEL", "dnepr_svet_voda").strip()
TG_URL = f"https://t.me/s/{CHANNEL}"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Kyiv")

# Telegram уведомления (опционально)
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

# Ключевые слова для поиска постов с графиками
KEYWORDS = [
    k.strip().lower() 
    for k in os.getenv(
        "TG_KEYWORDS",
        "онов,оновив,оновились,график,графіки,графік,дтек,yasno,відключення,черга,група"
    ).split(",") 
    if k.strip()
]

# Количество последних постов для проверки
LOOKBACK = int(os.getenv("TG_LOOKBACK", "200"))

# GitHub настройки (для автоматического коммита, не используется если пуш делает workflow)
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

# Словарь месяцев для парсинга дат
MONTHS_UA_RU = {
    "січня": 1, "января": 1,
    "лютого": 2, "февраля": 2,
    "березня": 3, "марта": 3,
    "квітня": 4, "апреля": 4,
    "травня": 5, "мая": 5,
    "червня": 6, "июня": 6,
    "липня": 7, "июля": 7,
    "серпня": 8, "августа": 8,
    "вересня": 9, "сентября": 9,
    "жовтня": 10, "октября": 10,
    "листопада": 11, "ноября": 11,
    "грудня": 12, "декабря": 12,
}


# ═══════════════════════════════════════════════════════════════════════════════
# РАБОТА С ФАЙЛАМИ
# ═══════════════════════════════════════════════════════════════════════════════

def load_existing() -> Dict[str, Any]:
    """Загружает существующий график из файла"""
    if not os.path.exists(SCHEDULE_PATH):
        return {}
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_schedule(groups: Dict[str, list], date_str: str) -> str:
    """
    Сохраняет график в файл с датой в формате DD.MM.YYYY
    
    Args:
        groups: Словарь с группами и интервалами
        date_str: Дата в формате YYYY-MM-DD
        
    Returns:
        Отформатированная дата DD.MM.YYYY
    """
    try:
        date_obj = date.fromisoformat(date_str)
        formatted_date = date_obj.strftime("%d.%m.%Y")
    except Exception:
        formatted_date = date_str
    
    data = {
        "date": formatted_date,
        "timezone": TIMEZONE_NAME,
        "groups": groups
    }
    
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return formatted_date


# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM УВЕДОМЛЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════════

def send_telegram_notification(message: str) -> None:
    """Отправляет уведомление в Telegram (если настроено)"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️  Telegram notifications not configured")
        return
    
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TG_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Telegram notification sent successfully")
    except Exception as e:
        print(f"❌ Failed to send Telegram notification: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ЗАГРУЗКА СТРАНИЦЫ
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_with_retry(url: str, retries: int = 3) -> str:
    """
    Загружает страницу с retry и обходом кэша
    
    Args:
        url: URL для загрузки
        retries: Количество попыток
        
    Returns:
        HTML страницы
    """
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    ]
    
    for attempt in range(retries):
        try:
            # Добавляем timestamp для обхода кэша
            cache_buster = f"?_={int(time.time() * 1000)}"
            
            headers = {
                'User-Agent': user_agents[attempt % len(user_agents)],
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
            
            print(f"Fetching {url} (attempt {attempt + 1}/{retries})...")
            response = requests.get(url + cache_buster, headers=headers, timeout=20)
            response.raise_for_status()
            
            print(f"✅ Successfully fetched page ({len(response.text)} bytes)")
            return response.text
            
        except Exception as e:
            print(f"❌ Attempt {attempt + 1} failed: {e}")
            if attempt == retries - 1:
                raise
            time.sleep(randint(2, 5))
    
    raise RuntimeError("Failed to fetch page after all retries")


# ═══════════════════════════════════════════════════════════════════════════════
# ПАРСИНГ HTML
# ═══════════════════════════════════════════════════════════════════════════════

def extract_messages(page_html: str) -> list:
    """
    Извлекает сообщения из HTML страницы Telegram
    
    Returns:
        Список словарей с полями: ts, post, text
    """
    messages = []
    
    # Ищем все блоки с постами
    post_pattern = re.compile(
        r'data-post="([^"]+)".*?'
        r'<div[^>]*class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        re.S
    )
    
    for match in post_pattern.finditer(page_html):
        post_id = match.group(1)
        text_html = match.group(2)
        
        # Ищем timestamp в окрестностях
        context_start = max(0, match.start() - 1000)
        context = page_html[context_start:match.end()]
        
        ts_match = re.search(r'data-unixtime="(\d+)"', context)
        timestamp = int(ts_match.group(1)) if ts_match else 0
        
        # Очистка HTML
        text_html = text_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        text_plain = re.sub(r"<.*?>", "", text_html)
        text_plain = html.unescape(text_plain).strip()
        
        if text_plain:
            messages.append({
                "ts": timestamp,
                "post": post_id,
                "text": text_plain
            })
    
    messages.sort(key=lambda x: x["ts"])
    return messages


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА И ПАРСИНГ ГРАФИКОВ
# ═══════════════════════════════════════════════════════════════════════════════

def has_group_lines(text: str) -> bool:
    """Проверяет наличие строк с группами отключений (формат: 1.1 HH:MM)"""
    return bool(re.search(r'(^|\n)\s*\d+\.\d+\s+\d{2}:\d{2}', text, re.MULTILINE))


def has_keywords(text: str) -> bool:
    """Проверяет наличие ключевых слов"""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in KEYWORDS)


def parse_groups(text: str) -> Dict[str, list]:
    """
    Парсит группы отключений из текста
    
    Поддерживаемые форматы:
    - 1.1 03:00 - 10:00 / 13:30 - 20:30
    - 1.1 03:00-10:00, 13:30-20:30
    
    Returns:
        Словарь {group_id: [intervals]}
    """
    groups = {}
    normalized = text.replace("–", "-").replace("—", "-").replace("−", "-")

    for line in normalized.splitlines():
        line = line.strip()
        # Убираем маркеры списков
        line = re.sub(r'^[•🔴❌\-\s]+', '', line)
        
        # Формат: "1.1 времена..."
        match = re.match(r'^(\d+\.\d+)\s+(.+)$', line)
        if not match:
            continue

        group_id = match.group(1)
        time_part = match.group(2).strip()
        
        # Разделяем по / или ;
        parts = [p.strip() for p in re.split(r'[/;]', time_part) if p.strip()]
        
        intervals = []
        for part in parts:
            # Извлекаем все времена HH:MM
            times = re.findall(r'\d{2}:\d{2}', part)
            
            # Создаём интервалы из пар
            for i in range(0, len(times) - 1, 2):
                interval = f"{times[i]}-{times[i+1]}"
                intervals.append(interval)

        if intervals:
            groups[group_id] = intervals

    if not groups:
        raise RuntimeError("No groups found in post (format may have changed)")
    
    return groups


# ═══════════════════════════════════════════════════════════════════════════════
# ОПРЕДЕЛЕНИЕ ДАТЫ
# ═══════════════════════════════════════════════════════════════════════════════

def extract_date_from_text(text: str) -> Optional[str]:
    """
    Извлекает дату из текста поста
    
    Поддерживаемые форматы (по приоритету):
    0. "сьогодні" / "сегодня" + контекст графика → сегодня
    1. DD.MM.YYYY / DD-MM-YYYY / DD/MM/YYYY
    2. DD месяц YYYY (24 січня 2026)
    3. "на DD месяц" (на 24 січня)
    4. DD.MM (год текущий)
    5. DD месяц (год текущий)
    
    Returns:
        Дата в формате YYYY-MM-DD или None
    """
    text_lower = text.lower()
    today = date.today()

    # ПРИОРИТЕТ 0: "сьогодні" / "сегодня" в контексте графика
    if any(word in text_lower for word in ['сьогодні', 'сегодня', 'today']):
        if any(word in text_lower for word in ['графік', 'график', 'станом', 'змінено']):
            return today.isoformat()

    # ПРИОРИТЕТ 1: DD.MM.YYYY
    match = re.search(r'\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b', text_lower)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12 and 2020 <= year <= 2030:
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                pass

    # ПРИОРИТЕТ 2: DD месяц YYYY
    match = re.search(r'\b(\d{1,2})\s+([а-яіїє]+)\s+(\d{4})\b', text_lower)
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3))
        month = MONTHS_UA_RU.get(month_name)
        
        if month and 1 <= day <= 31 and 2020 <= year <= 2030:
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                pass

    # ПРИОРИТЕТ 3: "на DD месяц"
    match = re.search(r'\bна\s+(\d{1,2})\s+([а-яіїє]+)\b', text_lower)
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        month = MONTHS_UA_RU.get(month_name)
        
        if month and 1 <= day <= 31:
            year = today.year
            try:
                parsed = date(year, month, day)
                # Если дата в прошлом более чем на неделю - берём следующий год
                if parsed < today and (today - parsed).days > 7:
                    parsed = date(year + 1, month, day)
                return parsed.isoformat()
            except ValueError:
                pass

    # ПРИОРИТЕТ 4: DD.MM
    match = re.search(r'\b(\d{1,2})[.\-/](\d{1,2})\b(?![.\-/\d])', text_lower)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            year = today.year
            try:
                parsed = date(year, month, day)
                if parsed < today and (today - parsed).days > 7:
                    parsed = date(year + 1, month, day)
                return parsed.isoformat()
            except ValueError:
                pass

    # ПРИОРИТЕТ 5: DD месяц
    match = re.search(r'\b(\d{1,2})\s+([а-яіїє]+)\b', text_lower)
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        month = MONTHS_UA_RU.get(month_name)
        
        if month and 1 <= day <= 31:
            year = today.year
            try:
                parsed = date(year, month, day)
                if parsed < today and (today - parsed).days > 7:
                    parsed = date(year + 1, month, day)
                return parsed.isoformat()
            except ValueError:
                pass

    return None


def date_from_message_ts(timestamp: int) -> str:
    """Извлекает дату из Unix timestamp сообщения"""
    if timestamp and timestamp > 1000000000:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
    return date.today().isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# ОСНОВНАЯ ЛОГИКА
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Основная функция парсинга и обновления графика"""
    
    # Загружаем страницу канала
    page_html = fetch_with_retry(TG_URL)
    
    # Парсим сообщения
    messages = extract_messages(page_html)
    if not messages:
        raise RuntimeError("No messages parsed from page")

    print(f"\n📊 Total messages parsed: {len(messages)}")
    print(f"🔍 Checking last {min(LOOKBACK, len(messages))} messages...")
    
    # Показываем последнее сообщение
    if messages:
        latest = messages[-1]
        ts = latest.get('ts', 0)
        if ts > 1000000000:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            print(f"📅 Latest message: {dt} UTC (ts={ts})")
        else:
            print(f"⚠️  Latest message: INVALID timestamp (ts={ts})")
        print(f"📝 Post ID: {latest.get('post')}")
        print(f"💬 Preview: {latest['text'][:100]}...")

    # Собираем кандидатов
    today = date.today()
    tomorrow = today + timedelta(days=1)
    candidates = []
    
    print(f"\n🔍 Analyzing posts for schedules...")
    
    for idx, msg in enumerate(reversed(messages[-LOOKBACK:])):
        if not has_group_lines(msg["text"]):
            continue
        
        # Определяем дату
        post_date = extract_date_from_text(msg["text"])
        preview = msg["text"][:80].replace('\n', ' ')
        
        if not post_date:
            if msg.get('ts', 0) > 1000000000:
                post_date = date_from_message_ts(msg['ts'])
                print(f"  ⚠️  Using timestamp: {post_date} | {preview}...")
            else:
                post_date = today.isoformat()
                print(f"  ⚠️  Using today: {post_date} | {preview}...")
        else:
            print(f"  ✅ Date from text: {post_date} | {preview}...")
        
        # Рассчитываем приоритет
        score = 0
        
        # Бонус за позицию (новые посты важнее)
        score += (LOOKBACK - idx) * 10
        
        # Бонус за ключевые слова
        if has_keywords(msg["text"]):
            score += 1000
        
        # Бонус за валидный timestamp
        if msg.get('ts', 0) > 1000000000:
            score += msg['ts'] // 1000
        
        # БОЛЬШОЙ бонус за актуальность даты
        try:
            post_date_obj = date.fromisoformat(post_date)
            if post_date_obj == today:
                score += 100000
                print(f"    📅 Date is TODAY - high priority!")
            elif post_date_obj == tomorrow:
                score += 50000
                print(f"    📅 Date is TOMORROW")
            elif post_date_obj > tomorrow:
                score += 10000
        except ValueError:
            pass
        
        # Небольшой бонус за длину (более детальные посты)
        score += len(msg["text"]) // 10
        
        candidates.append({
            'msg': msg,
            'score': score,
            'date': post_date
        })
    
    if not candidates:
        raise RuntimeError("No posts with schedules found")
    
    # Сортируем по приоритету
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # Показываем топ кандидатов
    print(f"\n🏆 Found {len(candidates)} candidates (showing top 5):")
    for i, candidate in enumerate(candidates[:5], 1):
        ts = candidate['msg'].get('ts', 0)
        time_str = "INVALID"
        if ts > 1000000000:
            time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        
        print(f"  {i}. Score={candidate['score']}, Date={candidate['date']}, Time={time_str}")
        print(f"     Post={candidate['msg'].get('post')}")
        print(f"     Preview={candidate['msg']['text'][:60]}...")
    
    # Выбираем лучший
    best = candidates[0]['msg']
    date_str = candidates[0]['date']

    print(f"\n🎯 Selected post: {best.get('post')}")
    print(f"📅 Post date: {date_str}")

    # Парсим группы
    groups = parse_groups(best["text"])
    print(f"📊 Parsed {len(groups)} groups: {list(groups.keys())}")
    
    # Детальный вывод
    print("\n📋 Parsed schedule details:")
    for group_id, intervals in sorted(groups.items()):
        print(f"  {group_id}: {intervals}")
    
    # Форматируем дату для сохранения
    try:
        date_obj = date.fromisoformat(date_str)
        formatted_date = date_obj.strftime("%d.%m.%Y")
    except Exception:
        formatted_date = date_str

    # Сравниваем с существующим
    existing = load_existing()
    old_groups = existing.get("groups", {})
    old_date = existing.get("date")
    
    print(f"\n🔍 Comparing with existing schedule:")
    print(f"  Old date: {old_date}")
    print(f"  New date: {formatted_date}")
    
    groups_changed = old_groups != groups
    
    # Детальное сравнение
    if groups_changed:
        print("\n📝 Changes detected:")
        all_group_ids = set(list(old_groups.keys()) + list(groups.keys()))
        for group_id in sorted(all_group_ids):
            old_intervals = old_groups.get(group_id, [])
            new_intervals = groups.get(group_id, [])
            if old_intervals != new_intervals:
                print(f"  {group_id}: {old_intervals} → {new_intervals}")
    
    # Проверяем формат даты
    date_format_changed = False
    if old_date and "-" in old_date:
        date_format_changed = True
        print(f"📅 Detected old date format: {old_date}")
    
    date_changed = old_date != formatted_date
    
    # Нужно ли обновление?
    if not groups_changed and not date_changed and not date_format_changed:
        print("\n✅ No changes detected")
        return
    
    # Логируем изменения
    if groups_changed:
        print(f"\n📝 Groups changed: {len(old_groups)} → {len(groups)}")
    
    if date_changed:
        print(f"📅 Date changed: {old_date} → {formatted_date}")
    
    if date_format_changed:
        print(f"✨ Date format updated: {old_date} → {formatted_date}")

    # Сохраняем
    saved_date = save_schedule(groups, date_str)
    print(f"\n💾 Schedule saved to {SCHEDULE_PATH}")
    print(f"   Date: {saved_date}")
    print(f"   Groups: {len(groups)}")

    # Отправляем уведомление
    if groups_changed or date_changed or date_format_changed:
        message = f"🔔 <b>Обновление графика ДТЭК</b>\n\n"
        message += f"📅 Дата: <b>{saved_date}</b>\n"
        message += f"📊 Групп: <b>{len(groups)}</b>\n\n"
        
        if groups_changed:
            message += "📝 <b>Изменились группы отключений</b>\n"
        if date_changed:
            message += f"📅 <b>Дата изменилась:</b> {old_date} → {saved_date}\n"
        if date_format_changed:
            message += "✨ <b>Обновлён формат даты</b>\n"
        
        message += f"\n🔗 <a href='https://t.me/s/{CHANNEL}'>Канал ДТЭК</a>"
        
        send_telegram_notification(message)

    print("\n✅ Update completed successfully!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
