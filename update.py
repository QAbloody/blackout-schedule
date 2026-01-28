#!/usr/bin/env python3
"""
YASNO Графік - Telegram бот
Графіки відключень + нагадування, статистика, порівняння
"""

import os
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

import requests
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
    PicklePersistence,
)


TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("❌ TOKEN environment variable is required")

SCHEDULE_URL = os.getenv(
    "SCHEDULE_URL",
    "https://raw.githubusercontent.com/QAbloody/blackout-schedule/refs/heads/main/schedule.json",
)

CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
PERSISTENCE_FILE = os.getenv("PERSISTENCE_FILE", "bot_state.pickle")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
REMINDER_CHECK_INTERVAL = 60  # Перевірка нагадувань кожну хвилину

GROUPS = [
    "1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
    "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"
]

# Кнопки
BTN_TODAY = "📊 Сьогодні"
BTN_TOMORROW = "📅 Завтра"
BTN_GROUPS = "🔢 Група"
BTN_SETTINGS = "⚙️ Налаштування"
BTN_STATS = "📈 Статистика"
BTN_BACK = "⬅️ Назад"

# Налаштування
BTN_NOTIFY_ON = "🔔 Сповіщення: ВКЛ"
BTN_NOTIFY_OFF = "🔕 Сповіщення: ВИКЛ"
BTN_REMINDER_ON = "⏰ Нагадування: ВКЛ"
BTN_REMINDER_OFF = "⏰ Нагадування: ВИКЛ"
BTN_REMINDER_15 = "⏰ За 15 хв"
BTN_REMINDER_30 = "⏰ За 30 хв"
BTN_COMPARE_ON = "🔄 Порівняння: ВКЛ"
BTN_COMPARE_OFF = "🔄 Порівняння: ВИКЛ"

# Групи
BTN_ADD_GROUP = "➕ Додати групу"
BTN_MY_GROUPS = "📋 Мої групи"
BTN_REMOVE_GROUP = "🗑 Видалити групу"

# Мітки для груп
GROUP_LABELS = ["🏠 Дім", "🏢 Робота", "👨‍👩‍👧 Батьки", "👫 Друзі", "📍 Інше", "✏️ Своя назва"]

# Цікаве
BTN_CURRENCY = "💵 Курс валют"
BTN_WEATHER = "🌤 Погода"

INTERESTING_OPTIONS = {
    "currency": BTN_CURRENCY,
    "weather": BTN_WEATHER,
}


# ═══════════════════════════════════════════════════════════════════════════════
# КЕШІ
# ═══════════════════════════════════════════════════════════════════════════════

_cache: Dict[str, Any] = {"ts": 0.0, "data": None, "hash": None}
_info_cache: Dict[str, Any] = {"currency": None, "currency_ts": 0.0, "weather": None, "weather_ts": 0.0}
INFO_CACHE_TTL = 300  # 5 хвилин


def fetch_schedule() -> Dict[str, Any]:
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["data"]

    response = requests.get(SCHEDULE_URL, timeout=15, headers={"Cache-Control": "no-cache"})
    response.raise_for_status()
    
    data = response.json()
    _cache["data"] = data
    _cache["ts"] = now
    _cache["hash"] = hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data


def get_schedule_hash() -> str:
    fetch_schedule()
    return _cache.get("hash", "")


# ═══════════════════════════════════════════════════════════════════════════════
# ЗОВНІШНІ API
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_currency() -> Optional[str]:
    """Курс валют від ПриватБанку"""
    try:
        now = time.time()
        if _info_cache["currency"] and now - _info_cache["currency_ts"] < INFO_CACHE_TTL:
            return _info_cache["currency"]
        
        response = requests.get(
            "https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        result = ""
        for item in data:
            if item["ccy"] == "USD":
                result += f"🇺🇸 USD: {float(item['buy']):.2f} / {float(item['sale']):.2f}\n"
            elif item["ccy"] == "EUR":
                result += f"🇪🇺 EUR: {float(item['buy']):.2f} / {float(item['sale']):.2f}\n"
        
        _info_cache["currency"] = result.strip()
        _info_cache["currency_ts"] = now
        return _info_cache["currency"]
    except Exception as e:
        print(f"Currency API error: {e}")
        return None


def fetch_weather() -> Optional[str]:
    """Погода в Дніпрі від Open-Meteo"""
    try:
        now = time.time()
        if _info_cache["weather"] and now - _info_cache["weather_ts"] < INFO_CACHE_TTL:
            return _info_cache["weather"]
        
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast?"
            "latitude=48.4647&longitude=35.0462&current=temperature_2m,weather_code&timezone=Europe/Kyiv",
            timeout=10,
            headers={"Cache-Control": "no-cache"}
        )
        response.raise_for_status()
        data = response.json()
        
        current = data.get("current", {})
        temp = current.get("temperature_2m", "?")
        code = current.get("weather_code", 0)
        
        weather_icons = {
            0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️",
            45: "🌫", 48: "🌫",
            51: "🌦", 53: "🌧", 55: "🌧",
            61: "🌧", 63: "🌧", 65: "🌧",
            71: "🌨", 73: "🌨", 75: "❄️",
            80: "🌦", 81: "🌧", 82: "⛈",
            95: "⛈", 96: "⛈", 99: "⛈",
        }
        icon = weather_icons.get(code, "🌡")
        
        result = f"{icon} Дніпро: {temp}°C"
        _info_cache["weather"] = result
        _info_cache["weather_ts"] = now
        return result
    except Exception as e:
        print(f"Weather API error: {e}")
        return None


def get_interesting_info() -> str:
    """Отримує курс валют і погоду"""
    parts = []
    
    currency = fetch_currency()
    if currency:
        parts.append(currency)
    
    weather = fetch_weather()
    if weather:
        parts.append(weather)
    
    if parts:
        return "\n\n" + "━" * 20 + "\n" + "\n".join(parts)
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# ДОПОМІЖНІ ФУНКЦІЇ
# ═══════════════════════════════════════════════════════════════════════════════

def parse_interval(interval: str) -> Tuple[int, int]:
    start, end = interval.split("-")
    start_h, start_m = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    
    start_min = start_h * 60 + start_m
    end_min = (24 * 60) if (end_h == 24 and end_m == 0) else (end_h * 60 + end_m)
    
    return start_min, end_min


def interval_duration(interval: str) -> int:
    start, end = parse_interval(interval)
    return max(0, end - start)


def total_minutes(intervals: List[str]) -> int:
    return sum(interval_duration(i) for i in intervals)


def format_duration(mins: int) -> str:
    hours, minutes = divmod(mins, 60)
    return f"{hours}год {minutes:02d}хв"


def format_time(minutes: int) -> str:
    """Конвертує хвилини в HH:MM"""
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def get_next_outage(intervals: List[str], current_min: int) -> Optional[Tuple[int, int]]:
    """Знаходить наступне відключення після поточного часу"""
    for interval in intervals:
        start, end = parse_interval(interval)
        if start > current_min:
            return (start, end)
    return None


def get_comparison(today_intervals: List[str], yesterday_total: int) -> str:
    """Порівнює з вчорашнім днем"""
    today_total = total_minutes(today_intervals)
    diff = today_total - yesterday_total
    
    if diff > 0:
        return f"📈 На {format_duration(abs(diff))} більше ніж вчора"
    elif diff < 0:
        return f"📉 На {format_duration(abs(diff))} менше ніж вчора"
    else:
        return "➡️ Так само як вчора"


# ═══════════════════════════════════════════════════════════════════════════════
# СТАТИСТИКА
# ═══════════════════════════════════════════════════════════════════════════════

def update_stats(context: ContextTypes.DEFAULT_TYPE, group: str, date_str: str, minutes: int):
    """Оновлює статистику користувача"""
    if "stats" not in context.user_data:
        context.user_data["stats"] = {}
    
    stats = context.user_data["stats"]
    
    # Зберігаємо по датах
    if date_str not in stats:
        stats[date_str] = minutes
    
    # Обмежуємо до 30 днів
    dates = sorted(stats.keys())
    while len(dates) > 30:
        del stats[dates[0]]
        dates = dates[1:]


def get_stats(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Повертає статистику"""
    stats = context.user_data.get("stats", {})
    
    if not stats:
        return "📈 Статистика поки недоступна\n\nПочніть користуватися ботом і вона з'явиться!"
    
    dates = sorted(stats.keys())
    
    # Загальна статистика
    total_mins = sum(stats.values())
    avg_mins = total_mins // len(dates) if dates else 0
    
    # За останній тиждень
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%d.%m.%Y")
    week_dates = [d for d in dates if d >= week_ago]
    week_total = sum(stats[d] for d in week_dates)
    
    # Мінімум і максимум
    if stats:
        min_date = min(stats, key=stats.get)
        max_date = max(stats, key=stats.get)
    
    msg = "📈 **Статистика відключень**\n\n"
    
    msg += f"📅 Днів у статистиці: {len(dates)}\n"
    msg += f"⏱ Всього без світла: {format_duration(total_mins)}\n"
    msg += f"📊 В середньому на день: {format_duration(avg_mins)}\n\n"
    
    if week_dates:
        msg += f"📆 За останній тиждень: {format_duration(week_total)}\n"
        msg += f"   ({len(week_dates)} днів)\n\n"
    
    if stats:
        msg += f"✅ Найкращий день: {min_date}\n"
        msg += f"   ({format_duration(stats[min_date])})\n"
        msg += f"❌ Найгірший день: {max_date}\n"
        msg += f"   ({format_duration(stats[max_date])})\n"
    
    return msg


# ═══════════════════════════════════════════════════════════════════════════════
# КЛАВІАТУРИ
# ═══════════════════════════════════════════════════════════════════════════════

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [BTN_TODAY, BTN_TOMORROW],
            [BTN_STATS, BTN_SETTINGS],
        ],
        resize_keyboard=True,
    )


def groups_keyboard() -> ReplyKeyboardMarkup:
    rows = [GROUPS[i:i+3] for i in range(0, len(GROUPS), 3)]
    rows.append([BTN_BACK])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def settings_keyboard(context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    notifications = context.user_data.get("notifications", True)
    reminder = context.user_data.get("reminder", 15)
    compare = context.user_data.get("compare", True)
    
    notify_btn = BTN_NOTIFY_ON if notifications else BTN_NOTIFY_OFF
    compare_btn = BTN_COMPARE_ON if compare else BTN_COMPARE_OFF
    
    if reminder == 15:
        reminder_btn = BTN_REMINDER_15
    elif reminder == 30:
        reminder_btn = BTN_REMINDER_30
    else:
        reminder_btn = BTN_REMINDER_OFF
    
    return ReplyKeyboardMarkup(
        [
            [notify_btn, reminder_btn],
            [compare_btn],
            [BTN_MY_GROUPS],
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )


def my_groups_keyboard(context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    """Клавіатура для управління групами"""
    my_groups = context.user_data.get("my_groups", {})
    
    rows = []
    
    # Показуємо збережені групи
    for label, group in my_groups.items():
        rows.append([f"{label}: {group}"])
    
    rows.append([BTN_ADD_GROUP])
    if my_groups:
        rows.append([BTN_REMOVE_GROUP])
    rows.append([BTN_BACK])
    
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def labels_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура вибору мітки для групи"""
    rows = [[label] for label in GROUP_LABELS]
    rows.append([BTN_BACK])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def remove_groups_keyboard(context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    """Клавіатура для видалення груп"""
    my_groups = context.user_data.get("my_groups", {})
    
    rows = []
    for label, group in my_groups.items():
        rows.append([f"❌ {label}: {group}"])
    rows.append([BTN_BACK])
    
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def interesting_keyboard(selected: List[str]) -> ReplyKeyboardMarkup:
    rows = []
    for key, label in INTERESTING_OPTIONS.items():
        check = "✓ " if key in selected else ""
        rows.append([f"{check}{label}"])
    rows.append([BTN_BACK])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ═══════════════════════════════════════════════════════════════════════════════
# КОМАНДИ
# ═══════════════════════════════════════════════════════════════════════════════

async def show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group = context.user_data.get("group")

    if group:
        await update.message.reply_text(
            f"👋 Твоя група: {group}\nОбери дію 👇",
            reply_markup=main_keyboard(),
        )
    else:
        await update.message.reply_text(
            "👋 Привіт! Обери групу 👇",
            reply_markup=groups_keyboard(),
        )


async def show_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, day: str):
    group = context.user_data.get("group")
    my_groups = context.user_data.get("my_groups", {})
    compare_enabled = context.user_data.get("compare", True)
    
    # Якщо є збережені групи - показуємо всі
    groups_to_show = {}
    if my_groups:
        groups_to_show = my_groups
    elif group:
        groups_to_show = {"": group}
    else:
        await show_welcome(update, context)
        return

    data = fetch_schedule()
    
    day_data = data.get(day, {})
    schedule_date = day_data.get("date", "")
    groups_data = day_data.get("groups", {})
    
    day_name = "Сьогодні" if day == "today" else "Завтра"
    
    if day == "tomorrow" and not groups_data:
        msg = f"⏳ Графік на завтра ще не опублікований\n\nОчікуємо оновлення..."
        msg += get_interesting_info()
        await update.message.reply_text(msg, reply_markup=main_keyboard())
        return
    
    message = f"📊 {day_name} ({schedule_date})\n"
    
    total_all = 0
    
    for label, grp in groups_to_show.items():
        intervals = groups_data.get(grp, [])
        
        if label:
            message += f"\n{label} (група {grp})\n"
        else:
            message += f"\nГрупа {grp}\n"
        
        if not intervals:
            message += "✅ Відключень немає\n"
        else:
            for interval in intervals:
                mins = interval_duration(interval)
                message += f"🔴 {interval} ({format_duration(mins)})\n"

            total = total_minutes(intervals)
            total_all += total
            message += f"⚠️ Разом: {format_duration(total)}\n"
            
            # Оновлюємо статистику для першої групи
            if day == "today" and list(groups_to_show.values())[0] == grp:
                update_stats(context, grp, schedule_date, total)
    
    # Порівняння (тільки для першої групи)
    if compare_enabled and day == "today" and groups_to_show:
        first_group = list(groups_to_show.values())[0]
        first_intervals = groups_data.get(first_group, [])
        stats = context.user_data.get("stats", {})
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
        if yesterday in stats and first_intervals:
            comparison = get_comparison(first_intervals, stats[yesterday])
            message += f"\n{comparison}"
    
    message += get_interesting_info()

    await update.message.reply_text(message, reply_markup=main_keyboard())


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує повний графік на сьогодні з 30-хвилинною точністю"""
    group = context.user_data.get("group")
    my_groups = context.user_data.get("my_groups", {})
    
    groups_to_show = {}
    if my_groups:
        groups_to_show = my_groups
    elif group:
        groups_to_show = {"": group}
    else:
        await show_welcome(update, context)
        return

    data = fetch_schedule()
    
    today_data = data.get("today", {})
    schedule_date = today_data.get("date", "")
    groups_data = today_data.get("groups", {})
    
    msg = f"📋 Повний графік ({schedule_date})\n"
    
    for label, grp in groups_to_show.items():
        intervals = groups_data.get(grp, [])
        
        group_name = f"{label}" if label else f"Група {grp}"
        msg += f"\n{group_name}\n"
        
        # Створюємо масив 30-хвилинних слотів (48 слотів на добу)
        # 0 = світло є, 1 = світла немає
        slots = [0] * 48
        
        for interval in intervals:
            start, end = parse_interval(interval)
            start_slot = start // 30
            end_slot = end // 30
            for s in range(start_slot, min(end_slot, 48)):
                slots[s] = 1
        
        # Групуємо послідовні слоти
        i = 0
        while i < 48:
            state = slots[i]
            start_slot = i
            
            # Знаходимо кінець блоку
            while i < 48 and slots[i] == state:
                i += 1
            end_slot = i
            
            # Конвертуємо слоти в час
            start_h, start_m = divmod(start_slot * 30, 60)
            end_h, end_m = divmod(end_slot * 30, 60)
            
            if state == 0:
                emoji = "🟢"
            else:
                emoji = "🔴"
            
            msg += f"{emoji} {start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}\n"
    
    msg += get_interesting_info()

    await update.message.reply_text(msg, reply_markup=main_keyboard())


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "⚙️ **Налаштування**\n\n"
    
    group = context.user_data.get("group", "не обрано")
    notifications = "ВКЛ" if context.user_data.get("notifications", True) else "ВИКЛ"
    reminder = context.user_data.get("reminder", 15)
    reminder_str = f"за {reminder} хв" if reminder else "ВИКЛ"
    compare = "ВКЛ" if context.user_data.get("compare", True) else "ВИКЛ"
    
    msg += f"👥 Група: {group}\n"
    msg += f"🔔 Сповіщення: {notifications}\n"
    msg += f"⏰ Нагадування: {reminder_str}\n"
    msg += f"🔄 Порівняння: {compare}\n"
    
    await update.message.reply_text(msg, reply_markup=settings_keyboard(context))


async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("notifications", True)
    context.user_data["notifications"] = not current
    await show_settings(update, context)


async def toggle_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("reminder", 15)
    # Цикл: 15 -> 30 -> 0 -> 15
    if current == 15:
        context.user_data["reminder"] = 30
    elif current == 30:
        context.user_data["reminder"] = 0
    else:
        context.user_data["reminder"] = 15
    await show_settings(update, context)


async def toggle_compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("compare", True)
    context.user_data["compare"] = not current
    await show_settings(update, context)


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_stats(context)
    await update.message.reply_text(msg, reply_markup=main_keyboard(), parse_mode="Markdown")


async def show_my_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_groups = context.user_data.get("my_groups", {})
    
    if not my_groups:
        msg = "📋 У вас поки немає збережених груп\n\n"
        msg += "Натисніть ➕ Додати групу"
    else:
        msg = "📋 Ваші групи:\n\n"
        for label, group in my_groups.items():
            msg += f"{label}: група {group}\n"
    
    await update.message.reply_text(msg, reply_markup=my_groups_keyboard(context))


async def start_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adding_group"] = True
    context.user_data["adding_group_step"] = "label"
    
    msg = "Оберіть мітку для нової групи:"
    await update.message.reply_text(msg, reply_markup=labels_keyboard())


async def handle_group_label(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    context.user_data["adding_group_label"] = label
    context.user_data["adding_group_step"] = "number"
    
    msg = f"Мітка: {label}\n\nТепер оберіть номер групи:"
    await update.message.reply_text(msg, reply_markup=groups_keyboard())


async def finish_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE, group: str):
    label = context.user_data.get("adding_group_label", "📍 Інше")
    
    if "my_groups" not in context.user_data:
        context.user_data["my_groups"] = {}
    
    context.user_data["my_groups"][label] = group
    context.user_data["group"] = group  # Основна група
    
    # Очищаємо стан
    context.user_data["adding_group"] = False
    context.user_data["adding_group_step"] = None
    context.user_data["adding_group_label"] = None
    
    msg = f"✅ Додано: {label} — група {group}"
    await update.message.reply_text(msg, reply_markup=my_groups_keyboard(context))


async def start_remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["removing_group"] = True
    
    msg = "Оберіть групу для видалення:"
    await update.message.reply_text(msg, reply_markup=remove_groups_keyboard(context))


async def remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    my_groups = context.user_data.get("my_groups", {})
    
    # Парсимо "❌ 🏠 Дім: 1.1"
    for label, group in list(my_groups.items()):
        if f"❌ {label}: {group}" == text:
            del context.user_data["my_groups"][label]
            context.user_data["removing_group"] = False
            
            msg = f"✅ Видалено: {label}"
            await update.message.reply_text(msg, reply_markup=my_groups_keyboard(context))
            return True
    
    return False


async def show_interesting_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected = context.user_data.get("interesting", [])
    
    msg = "🎯 Оберіть що показувати під графіком:\n\n"
    msg += "Натисніть щоб увімкнути/вимкнути\n"
    msg += "✓ = увімкнено"
    
    await update.message.reply_text(msg, reply_markup=interesting_keyboard(selected))


async def toggle_interesting_option(update: Update, context: ContextTypes.DEFAULT_TYPE, option: str):
    selected = context.user_data.get("interesting", [])
    
    if option in selected:
        selected.remove(option)
    else:
        selected.append(option)
    
    context.user_data["interesting"] = selected
    await show_interesting_menu(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# ФОНОВІ ЗАДАЧІ
# ═══════════════════════════════════════════════════════════════════════════════

async def check_schedule_updates(context: ContextTypes.DEFAULT_TYPE):
    """Перевіряє оновлення графіку"""
    try:
        old_hash = context.bot_data.get("schedule_hash")
        
        # Примусово оновлюємо кеш
        _cache["ts"] = 0
        new_hash = get_schedule_hash()
        
        print(f"📊 Check: old={old_hash[:8] if old_hash else 'None'}... new={new_hash[:8] if new_hash else 'None'}...")
        
        if old_hash and old_hash != new_hash:
            print(f"📢 Schedule updated! Notifying users...")
            
            data = fetch_schedule()
            today_date = data.get("today", {}).get("date", "")
            
            # Отримуємо користувачів
            try:
                user_data = await context.application.persistence.get_user_data()
            except:
                user_data = {}
            
            notified = 0
            for user_id, udata in user_data.items():
                if udata.get("notifications", True):
                    my_groups = udata.get("my_groups", {})
                    group = udata.get("group")
                    
                    if my_groups or group:
                        try:
                            group_info = list(my_groups.values())[0] if my_groups else group
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"🔔 Графік оновлено!\n\n📅 {today_date}\n\nНатисни 📊 Сьогодні щоб переглянути."
                            )
                            notified += 1
                        except Exception as e:
                            print(f"Failed to notify {user_id}: {e}")
            
            print(f"📢 Notified {notified} users")
        
        context.bot_data["schedule_hash"] = new_hash
        
    except Exception as e:
        print(f"Check schedule error: {e}")
        import traceback
        traceback.print_exc()


async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Перевіряє і надсилає нагадування про відключення"""
    try:
        data = fetch_schedule()
        today_data = data.get("today", {})
        groups_data = today_data.get("groups", {})
        
        now = datetime.now()
        current_min = now.hour * 60 + now.minute
        
        try:
            user_data = await context.application.persistence.get_user_data()
        except:
            user_data = {}
        
        for user_id, udata in user_data.items():
            reminder_mins = udata.get("reminder", 15)
            if not reminder_mins:
                continue
            
            # Отримуємо всі групи користувача
            my_groups = udata.get("my_groups", {})
            if not my_groups:
                group = udata.get("group")
                if group:
                    my_groups = {"": group}
                else:
                    continue
            
            for label, group in my_groups.items():
                intervals = groups_data.get(group, [])
                
                for interval in intervals:
                    start, end = parse_interval(interval)
                    mins_until = start - current_min
                    
                    if reminder_mins - 1 <= mins_until <= reminder_mins + 1:
                        reminder_key = f"reminder_{user_id}_{group}_{start}"
                        if context.bot_data.get(reminder_key):
                            continue
                        
                        try:
                            group_name = f"{label} ({group})" if label else f"Група {group}"
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"⏰ Нагадування!\n\n"
                                     f"Через {mins_until} хв відключення\n"
                                     f"🔴 {interval}\n"
                                     f"{group_name}"
                            )
                            context.bot_data[reminder_key] = True
                        except Exception as e:
                            print(f"Failed to send reminder to {user_id}: {e}")
        
        # Очищаємо старі ключі нагадувань опівночі
        if current_min < 5:
            keys_to_delete = [k for k in context.bot_data.keys() if k.startswith("reminder_")]
            for k in keys_to_delete:
                del context.bot_data[k]
                
    except Exception as e:
        print(f"Check reminders error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# РОУТЕР
# ═══════════════════════════════════════════════════════════════════════════════

async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # Перевіряємо чи додаємо групу
    if context.user_data.get("adding_group"):
        step = context.user_data.get("adding_group_step")
        
        if text == BTN_BACK:
            context.user_data["adding_group"] = False
            context.user_data["adding_group_step"] = None
            await show_my_groups(update, context)
            return
        
        if step == "label":
            if text == "✏️ Своя назва":
                context.user_data["adding_group_step"] = "custom_label"
                await update.message.reply_text(
                    "Введіть свою назву для групи:",
                    reply_markup=ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True)
                )
                return
            elif text in GROUP_LABELS:
                await handle_group_label(update, context, text)
                return
        elif step == "custom_label":
            # Користувач ввів свою назву
            custom_label = f"📌 {text}"
            await handle_group_label(update, context, custom_label)
            return
        elif step == "number" and text in GROUPS:
            await finish_add_group(update, context, text)
            return
    
    # Перевіряємо чи видаляємо групу
    if context.user_data.get("removing_group"):
        if text == BTN_BACK:
            context.user_data["removing_group"] = False
            await show_my_groups(update, context)
            return
        if await remove_group(update, context, text):
            return

    if text.startswith("/"):
        await show_welcome(update, context)
        return

    if text == BTN_TODAY:
        await today_cmd(update, context)
        return

    if text == BTN_TOMORROW:
        await show_schedule(update, context, "tomorrow")
        return

    if text == BTN_STATS:
        await show_stats(update, context)
        return

    if text == BTN_SETTINGS:
        await show_settings(update, context)
        return

    if text == BTN_GROUPS:
        await update.message.reply_text("Оберіть групу 👇", reply_markup=groups_keyboard())
        return

    if text == BTN_MY_GROUPS:
        await show_my_groups(update, context)
        return

    if text == BTN_ADD_GROUP:
        await start_add_group(update, context)
        return

    if text == BTN_REMOVE_GROUP:
        await start_remove_group(update, context)
        return

    if text == BTN_BACK:
        # Повертаємось на головний екран
        group = context.user_data.get("group")
        my_groups = context.user_data.get("my_groups", {})
        if group or my_groups:
            await update.message.reply_text(
                f"👋 Обери дію 👇",
                reply_markup=main_keyboard(),
            )
        else:
            await update.message.reply_text(
                "👋 Обери групу 👇",
                reply_markup=groups_keyboard(),
            )
        return

    # Налаштування
    if text in (BTN_NOTIFY_ON, BTN_NOTIFY_OFF):
        await toggle_notifications(update, context)
        return

    if text in (BTN_REMINDER_ON, BTN_REMINDER_OFF, BTN_REMINDER_15, BTN_REMINDER_30):
        await toggle_reminder(update, context)
        return

    if text in (BTN_COMPARE_ON, BTN_COMPARE_OFF):
        await toggle_compare(update, context)
        return

    # Вибір групи (при першому налаштуванні)
    if text in GROUPS:
        context.user_data["group"] = text
        # Якщо немає збережених груп — додаємо як "Дім"
        if not context.user_data.get("my_groups"):
            context.user_data["my_groups"] = {"🏠 Дім": text}
        await show_welcome(update, context)
        return

    # Клік на збережену групу — показуємо деталі
    my_groups = context.user_data.get("my_groups", {})
    for label, group in my_groups.items():
        if text == f"{label}: {group}":
            await show_schedule(update, context, "today")
            return

    await show_welcome(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("🚀 Starting YASNO Графік Bot...")
    
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)
    app = Application.builder() \
        .token(TOKEN) \
        .persistence(persistence) \
        .build()
    
    app.add_handler(MessageHandler(filters.TEXT, router))
    
    job_queue = app.job_queue
    job_queue.run_repeating(check_schedule_updates, interval=CHECK_INTERVAL, first=10)
    job_queue.run_repeating(check_reminders, interval=REMINDER_CHECK_INTERVAL, first=30)
    
    print(f"✅ Bot started!")
    print(f"📊 Schedule URL: {SCHEDULE_URL}")
    print(f"🔔 Schedule check: {CHECK_INTERVAL}s")
    print(f"⏰ Reminder check: {REMINDER_CHECK_INTERVAL}s")
    
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
