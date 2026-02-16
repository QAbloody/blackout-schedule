#!/usr/bin/env python3
"""
YASNO Графік — Telegram бот для Дніпра
Графіки відключень DTEK з нагадуваннями та статистикою
"""

import os
import time
import json
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Tuple, Optional

import requests
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters, PicklePersistence


# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

KYIV_TZ = ZoneInfo("Europe/Kyiv")

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("❌ Змінна TOKEN не встановлена")

SCHEDULE_URL = os.getenv(
    "SCHEDULE_URL",
    "https://raw.githubusercontent.com/QAbloody/blackout-schedule/main/schedule.json"
)

HISTORY_URL = os.getenv(
    "HISTORY_URL",
    "https://raw.githubusercontent.com/QAbloody/blackout-schedule/main/history.json"
)

CACHE_TTL = 60           # Кеш графіку: 1 хв
CHECK_INTERVAL = 300     # Перевірка оновлень: 5 хв
REMINDER_INTERVAL = 30   # Перевірка нагадувань: 30 сек

PERSISTENCE_FILE = os.getenv("PERSISTENCE_FILE", "bot_state.pickle")

GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
          "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]

# Кнопки
BTN_TODAY = "📊 Сьогодні"
BTN_TOMORROW = "📅 Завтра"
BTN_PREDICT = "🔮 Прогноз"
BTN_STATS = "📈 Статистика"
BTN_SETTINGS = "⚙️ Налаштування"
BTN_BACK = "⬅️ Назад"

BTN_NOTIFY_ON = "🔔 Сповіщення: ВКЛ"
BTN_NOTIFY_OFF = "🔕 Сповіщення: ВИКЛ"
BTN_REMIND_15 = "⏰ За 15 хв"
BTN_REMIND_30 = "⏰ За 30 хв"
BTN_REMIND_OFF = "⏰ Вимкнено"
BTN_COMPARE_ON = "📊 Порівняння: ВКЛ"
BTN_COMPARE_OFF = "📊 Порівняння: ВИКЛ"

BTN_ADD = "➕ Додати"
BTN_GROUPS = "📋 Мої групи"
BTN_REMOVE = "🗑 Видалити"

GROUP_LABELS = ["🏠 Дім", "🏢 Робота", "👨‍👩‍👧 Батьки", "👫 Друзі", "📍 Інше", "✏️ Своя назва"]


# ═══════════════════════════════════════════════════════════════════════════════
# УТИЛІТИ
# ═══════════════════════════════════════════════════════════════════════════════

def now_kyiv() -> datetime:
    return datetime.now(KYIV_TZ)


def parse_interval(iv: str) -> Tuple[int, int]:
    s, e = iv.split("-")
    sh, sm = map(int, s.split(":"))
    eh, em = map(int, e.split(":"))
    return sh * 60 + sm, 24 * 60 if (eh == 24 and em == 0) else eh * 60 + em


def total_minutes(intervals: List[str]) -> int:
    return sum(max(0, parse_interval(i)[1] - parse_interval(i)[0]) for i in intervals)


def fmt_duration(mins: int) -> str:
    h, m = divmod(mins, 60)
    return f"{h}год {m:02d}хв"


def make_hash(data: Any) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# КЕШІ ТА API
# ═══════════════════════════════════════════════════════════════════════════════

_schedule: Dict[str, Any] = {"ts": 0.0, "data": None}
_history: Dict[str, Any] = {"ts": 0.0, "data": None}
_info: Dict[str, Any] = {"currency": None, "currency_ts": 0.0, "weather": None, "weather_ts": 0.0}


def fetch_schedule() -> Dict[str, Any]:
    now = time.time()
    if _schedule["data"] and now - _schedule["ts"] < CACHE_TTL:
        return _schedule["data"]
    try:
        r = requests.get(SCHEDULE_URL, timeout=15, headers={"Cache-Control": "no-cache"})
        r.raise_for_status()
        _schedule["data"], _schedule["ts"] = r.json(), now
        return _schedule["data"]
    except Exception as e:
        print(f"❌ Fetch: {e}")
        return _schedule["data"] or {"today": {"date": "", "groups": {}}, "tomorrow": {"date": "", "groups": {}}}


def fetch_history() -> Dict[str, Any]:
    now = time.time()
    if _history["data"] and now - _history["ts"] < 300:  # 5 хв кеш
        return _history["data"]
    try:
        r = requests.get(HISTORY_URL, timeout=15, headers={"Cache-Control": "no-cache"})
        r.raise_for_status()
        _history["data"], _history["ts"] = r.json(), now
        return _history["data"]
    except Exception as e:
        print(f"❌ History fetch: {e}")
        return _history["data"] or {"days": {}}


def fetch_currency() -> Optional[str]:
    try:
        now = time.time()
        if _info["currency"] and now - _info["currency_ts"] < 300:
            return _info["currency"]
        r = requests.get("https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5", timeout=10)
        r.raise_for_status()
        lines = []
        for item in r.json():
            if item["ccy"] == "USD":
                lines.append(f"🇺🇸 USD: {float(item['buy']):.2f} / {float(item['sale']):.2f}")
            elif item["ccy"] == "EUR":
                lines.append(f"🇪🇺 EUR: {float(item['buy']):.2f} / {float(item['sale']):.2f}")
        _info["currency"], _info["currency_ts"] = "\n".join(lines), now
        return _info["currency"]
    except:
        return _info.get("currency")


def fetch_weather() -> Optional[str]:
    try:
        now = time.time()
        if _info["weather"] and now - _info["weather_ts"] < 300:
            return _info["weather"]
        r = requests.get("https://api.open-meteo.com/v1/forecast?latitude=48.4647&longitude=35.0462&current=temperature_2m,weather_code&timezone=Europe/Kyiv", timeout=10)
        r.raise_for_status()
        cur = r.json().get("current", {})
        temp = round(cur.get("temperature_2m", 0))
        icons = {0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️", 45: "🌫", 51: "🌧", 61: "🌧", 71: "🌨", 95: "⛈"}
        t = f"+{temp}" if temp > 0 else str(temp)
        _info["weather"], _info["weather_ts"] = f"{icons.get(cur.get('weather_code', 0), '🌡')} Дніпро: {t}°C", now
        return _info["weather"]
    except:
        return _info.get("weather")


def footer() -> str:
    parts = [p for p in [fetch_currency(), fetch_weather()] if p]
    return "\n━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОГНОЗУВАННЯ
# ═══════════════════════════════════════════════════════════════════════════════

def predict_schedule(group: str) -> Dict[str, Any]:
    """
    Прогнозує графік на післязавтра на основі того ж дня минулого тижня.
    """
    history = fetch_history()
    days = history.get("days", {})
    
    if len(days) < 7:
        return {"confidence": 0, "error": f"Потрібно мінімум 7 днів історії (зараз: {len(days)})"}
    
    # Визначаємо післязавтра
    target_date = now_kyiv() + timedelta(days=2)
    target_weekday = target_date.weekday()  # 0=пн, 6=нд
    weekday_names = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"]
    target_weekday_name = weekday_names[target_weekday]
    
    # Шукаємо такий же день тижня в історії
    matching_days = []
    
    for date_str, day_data in days.items():
        try:
            # Парсимо дату (формат DD.MM.YYYY)
            d, m, y = map(int, date_str.split("."))
            date_obj = datetime(y, m, d)
            
            if date_obj.weekday() == target_weekday:
                groups = day_data.get("groups", {})
                if group in groups:
                    matching_days.append({
                        "date": date_str,
                        "intervals": groups[group],
                        "days_ago": (target_date.date() - date_obj.date()).days
                    })
        except:
            continue
    
    if not matching_days:
        return {"confidence": 0, "error": f"Немає даних за {target_weekday_name}"}
    
    # Сортуємо по даті (найновіші спочатку)
    matching_days.sort(key=lambda x: x["days_ago"])
    
    # Беремо останній такий день (минулий тиждень)
    last_week = matching_days[0]
    
    # Рахуємо скільки годин відключень
    total_mins = 0
    for iv in last_week["intervals"]:
        parts = iv.split("-")
        if len(parts) == 2:
            sh, sm = map(int, parts[0].split(":"))
            eh, em = map(int, parts[1].split(":"))
            start = sh * 60 + sm
            end = eh * 60 + em if eh != 24 else 24 * 60
            total_mins += end - start
    
    # Впевненість залежить від кількості збігів в історії
    if len(matching_days) >= 3:
        # Перевіряємо чи графіки схожі
        same_count = 0
        for i in range(1, min(len(matching_days), 4)):
            if matching_days[i]["intervals"] == last_week["intervals"]:
                same_count += 1
        confidence = 40 + same_count * 20  # 40-100%
    else:
        confidence = 40
    
    return {
        "confidence": confidence,
        "target_date": target_date.strftime("%d.%m.%Y"),
        "target_weekday": target_weekday_name,
        "based_on_date": last_week["date"],
        "days_ago": last_week["days_ago"],
        "intervals": last_week["intervals"],
        "total_mins": total_mins,
        "matches_found": len(matching_days)
    }


# ═══════════════════════════════════════════════════════════════════════════════
# СТАТИСТИКА
# ═══════════════════════════════════════════════════════════════════════════════

def save_stat(ctx, date: str, mins: int):
    if "stats" not in ctx.user_data:
        ctx.user_data["stats"] = {}
    ctx.user_data["stats"][date] = mins
    while len(ctx.user_data["stats"]) > 30:
        del ctx.user_data["stats"][min(ctx.user_data["stats"])]


def stats_text(ctx) -> str:
    s = ctx.user_data.get("stats", {})
    if not s:
        return "📈 Статистика порожня\n\nНатисни «📊 Сьогодні»"
    total, avg = sum(s.values()), sum(s.values()) // len(s)
    best, worst = min(s, key=s.get), max(s, key=s.get)
    week = (now_kyiv() - timedelta(days=7)).strftime("%d.%m.%Y")
    ws = {k: v for k, v in s.items() if k >= week}
    msg = f"📈 Статистика ({len(s)} дн.)\n\n⏱ Всього: {fmt_duration(total)}\n📊 Середнє: {fmt_duration(avg)}/день\n"
    if ws:
        msg += f"\n📆 За тиждень: {fmt_duration(sum(ws.values()))}\n"
    msg += f"\n✅ Найкращий: {best} ({fmt_duration(s[best])})\n❌ Найгірший: {worst} ({fmt_duration(s[worst])})"
    return msg


# ═══════════════════════════════════════════════════════════════════════════════
# КЛАВІАТУРИ
# ═══════════════════════════════════════════════════════════════════════════════

def kb_main():
    return ReplyKeyboardMarkup([[BTN_TODAY, BTN_TOMORROW], [BTN_PREDICT, BTN_STATS], [BTN_SETTINGS]], resize_keyboard=True)

def kb_groups():
    return ReplyKeyboardMarkup([GROUPS[i:i+3] for i in range(0, 12, 3)] + [[BTN_BACK]], resize_keyboard=True)

def kb_settings(ctx):
    n = BTN_NOTIFY_ON if ctx.user_data.get("notifications", True) else BTN_NOTIFY_OFF
    r = ctx.user_data.get("reminder", 15)
    rm = BTN_REMIND_15 if r == 15 else (BTN_REMIND_30 if r == 30 else BTN_REMIND_OFF)
    c = BTN_COMPARE_ON if ctx.user_data.get("compare", True) else BTN_COMPARE_OFF
    return ReplyKeyboardMarkup([[n, rm], [c], [BTN_GROUPS], [BTN_BACK]], resize_keyboard=True)

def kb_my_groups(ctx):
    g = ctx.user_data.get("my_groups", {})
    rows = [[f"{l}: {v}"] for l, v in g.items()] + [[BTN_ADD]]
    if g:
        rows.append([BTN_REMOVE])
    return ReplyKeyboardMarkup(rows + [[BTN_BACK]], resize_keyboard=True)

def kb_labels():
    return ReplyKeyboardMarkup([[l] for l in GROUP_LABELS] + [[BTN_BACK]], resize_keyboard=True)

def kb_remove(ctx):
    return ReplyKeyboardMarkup([[f"❌ {l}: {v}"] for l, v in ctx.user_data.get("my_groups", {}).items()] + [[BTN_BACK]], resize_keyboard=True)


# ═══════════════════════════════════════════════════════════════════════════════
# КОМАНДИ
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx):
    g = ctx.user_data.get("group")
    if not g:
        await update.message.reply_text("👋 Привіт!\n\nОбери свою групу:", reply_markup=kb_groups())
    else:
        mg = ctx.user_data.get("my_groups", {})
        await update.message.reply_text(f"⚡ DTEK | {', '.join(mg.keys()) if mg else g}", reply_markup=kb_main())


async def cmd_schedule(update: Update, ctx, day: str):
    mg = ctx.user_data.get("my_groups", {}) or ({"": ctx.user_data["group"]} if ctx.user_data.get("group") else {})
    if not mg or not list(mg.values())[0]:
        await cmd_start(update, ctx)
        return
    
    data = fetch_schedule()
    dd = data.get(day, {})
    date, gd = dd.get("date", "—"), dd.get("groups", {})
    dn = "Сьогодні" if day == "today" else "Завтра"
    emergency = data.get("emergency")
    
    # Якщо є екстрене повідомлення і немає графіків
    if emergency and not gd:
        await update.message.reply_text(f"🚨\n{emergency}" + footer(), reply_markup=kb_main())
        return
    
    # Якщо є екстрене повідомлення
    if emergency:
        msg = f"🚨\n{emergency}\n━━━━━━━━━━━━━━━━━━━━\n\n"
    else:
        msg = ""
    
    if not gd:
        await update.message.reply_text(f"{msg}⏳ Графік на {dn.lower()} недоступний" + footer(), reply_markup=kb_main())
        return
    
    msg += f"📊 {dn} ({date})\n"
    first = 0
    for label, grp in mg.items():
        ivs = gd.get(grp, [])
        msg += f"\n{label}\n" if label else f"\nГрупа {grp}\n"
        if not ivs:
            msg += "✅ Відключень немає\n"
            continue
        
        slots = [False] * 48
        for iv in ivs:
            s, e = parse_interval(iv)
            for i in range(s // 30, min(e // 30, 48)):
                slots[i] = True
        
        i = 0
        while i < 48:
            st, start = slots[i], i
            while i < 48 and slots[i] == st:
                i += 1
            sh, sm = divmod(start * 30, 60)
            eh, em = divmod(i * 30, 60)
            msg += f"{'🔴' if st else '🟢'} {sh:02d}:{sm:02d}-{eh:02d}:{em:02d}\n"
        
        total = total_minutes(ivs)
        msg += f"⚠️ Без світла: {fmt_duration(total)}\n"
        if not first:
            first = total
            if day == "today":
                save_stat(ctx, date, total)
    
    if day == "today" and ctx.user_data.get("compare", True) and first:
        yday = (now_kyiv() - timedelta(days=1)).strftime("%d.%m.%Y")
        if yday in ctx.user_data.get("stats", {}):
            diff = first - ctx.user_data["stats"][yday]
            if diff > 0:
                msg += f"\n📈 +{fmt_duration(diff)} ніж вчора"
            elif diff < 0:
                msg += f"\n📉 -{fmt_duration(abs(diff))} ніж вчора"
    
    await update.message.reply_text(msg + footer(), reply_markup=kb_main())


async def cmd_stats(update: Update, ctx):
    await update.message.reply_text(stats_text(ctx), reply_markup=kb_main())


async def cmd_predict(update: Update, ctx):
    """Показує прогноз на післязавтра на основі минулого тижня"""
    mg = ctx.user_data.get("my_groups", {}) or ({"": ctx.user_data["group"]} if ctx.user_data.get("group") else {})
    if not mg or not list(mg.values())[0]:
        await cmd_start(update, ctx)
        return
    
    first_pred = None
    msg = ""
    
    for label, grp in mg.items():
        pred = predict_schedule(grp)
        
        if pred.get("error"):
            msg += f"\n{label or 'Група ' + grp}\n⏳ {pred['error']}\n"
            continue
        
        if not first_pred:
            first_pred = pred
            msg = f"🔮 {pred['target_weekday'].capitalize()}, {pred['target_date']}\n"
        
        msg += f"\n{label or 'Група ' + grp}\n"
        
        if pred['intervals']:
            msg += "Можливі відключення:\n"
            for iv in pred['intervals']:
                msg += f"🔴 {iv}\n"
            msg += f"⚠️ {fmt_duration(pred['total_mins'])}\n"
        else:
            msg += "🟢 Можливо без відключень\n"
    
    msg += "\n💡 На основі минулого тижня"
    
    await update.message.reply_text(msg, reply_markup=kb_main())


async def cmd_settings(update: Update, ctx):
    g = ctx.user_data.get("group", "—")
    n = "✅" if ctx.user_data.get("notifications", True) else "❌"
    r = ctx.user_data.get("reminder", 15)
    c = "✅" if ctx.user_data.get("compare", True) else "❌"
    await update.message.reply_text(f"⚙️ Налаштування\n\n📍 Група: {g}\n🔔 Сповіщення: {n}\n⏰ Нагадування: {f'{r} хв' if r else 'вимк'}\n📊 Порівняння: {c}", reply_markup=kb_settings(ctx))


async def cmd_my_groups(update: Update, ctx):
    g = ctx.user_data.get("my_groups", {})
    await update.message.reply_text("📋 Групи:\n" + "\n".join(f"• {l}: {v}" for l, v in g.items()) if g else "📋 Груп немає", reply_markup=kb_my_groups(ctx))


# ═══════════════════════════════════════════════════════════════════════════════
# ФОНОВІ ЗАДАЧІ
# ═══════════════════════════════════════════════════════════════════════════════

async def job_updates(ctx):
    if ctx.bot_data.get("_lock"):
        return
    ctx.bot_data["_lock"] = True
    try:
        _schedule["ts"] = 0
        data = fetch_schedule()
        
        try:
            users = await ctx.application.persistence.get_user_data()
        except:
            users = {}
        
        # Перевіряємо екстрене повідомлення
        emergency = data.get("emergency")
        old_emergency = ctx.bot_data.get("_emergency")
        
        if emergency and emergency != old_emergency:
            # Нове екстрене повідомлення - сповіщаємо всіх
            for uid, ud in users.items():
                if ud.get("notifications", True) and ud.get("group"):
                    try:
                        await ctx.bot.send_message(uid, f"🚨 УВАГА!\n\n{emergency}")
                    except:
                        pass
            ctx.bot_data["_emergency"] = emergency
        elif not emergency and old_emergency:
            # Екстрене повідомлення зникло
            ctx.bot_data["_emergency"] = None
        
        for uid, ud in users.items():
            if not ud.get("notifications", True) or not ud.get("group"):
                continue
            mg = ud.get("my_groups", {}) or {"": ud["group"]}
            
            # Перевіряємо і сьогодні, і завтра
            for day, day_name in [("today", "сьогодні"), ("tomorrow", "завтра")]:
                gd = data.get(day, {}).get("groups", {})
                date = data.get(day, {}).get("date", "")
                if not gd:
                    continue
                
                changed = []
                for label, grp in mg.items():
                    h = make_hash(gd.get(grp, []))
                    key = f"h_{day}_{uid}_{grp}"
                    old_h = ctx.bot_data.get(key)
                    
                    # Якщо це перша перевірка - просто зберігаємо хеш без сповіщення
                    if old_h is None:
                        ctx.bot_data[key] = h
                        continue
                    
                    # Якщо хеш змінився - додаємо до списку змін
                    if old_h != h:
                        changed.append(label or grp)
                        ctx.bot_data[key] = h
                
                if changed:
                    try:
                        await ctx.bot.send_message(uid, f"🔔 Графік на {day_name} оновлено!\n📅 {date}\n📍 {', '.join(changed)}")
                    except:
                        pass
    finally:
        ctx.bot_data["_lock"] = False


async def job_reminders(ctx):
    try:
        now = now_kyiv()
        cur = now.hour * 60 + now.minute
        today = now.strftime("%Y%m%d")
        try:
            users = await ctx.application.persistence.get_user_data()
        except:
            return
        gd = fetch_schedule().get("today", {}).get("groups", {})
        for uid, ud in users.items():
            rem = ud.get("reminder", 15)
            if not rem:
                continue
            mg = ud.get("my_groups", {}) or ({"": ud["group"]} if ud.get("group") else {})
            for label, grp in mg.items():
                for iv in gd.get(grp, []):
                    s, _ = parse_interval(iv)
                    diff = s - cur
                    # Точне нагадування: рівно за rem хвилин (толерантність 30 сек = 0 хв)
                    if diff == rem:
                        key = f"r_{today}_{uid}_{grp}_{s}"
                        if ctx.bot_data.get(key):
                            continue
                        try:
                            await ctx.bot.send_message(uid, f"⏰ Через {rem} хв відключення!\n🔴 {iv}\n📍 {label or grp}")
                            ctx.bot_data[key] = True
                        except:
                            pass
        if cur < 1:
            for k in [k for k in ctx.bot_data if k.startswith("r_") and not k.startswith(f"r_{today}")]:
                del ctx.bot_data[k]
    except Exception as e:
        print(f"Reminder: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# РОУТЕР
# ═══════════════════════════════════════════════════════════════════════════════

async def router(update: Update, ctx):
    if not update.message or not update.message.text:
        return
    t = update.message.text.strip()

    # Додавання
    if ctx.user_data.get("adding"):
        step = ctx.user_data.get("step")
        if t == BTN_BACK:
            ctx.user_data["adding"] = False
            await cmd_my_groups(update, ctx)
            return
        if step == "label":
            if t == "✏️ Своя назва":
                ctx.user_data["step"] = "custom"
                await update.message.reply_text("Введи назву:", reply_markup=ReplyKeyboardMarkup([[BTN_BACK]], resize_keyboard=True))
            elif t in GROUP_LABELS:
                ctx.user_data["label"] = t
                ctx.user_data["step"] = "group"
                await update.message.reply_text("Обери групу:", reply_markup=kb_groups())
            return
        if step == "custom":
            ctx.user_data["label"] = f"📌 {t}"
            ctx.user_data["step"] = "group"
            await update.message.reply_text("Обери групу:", reply_markup=kb_groups())
            return
        if step == "group" and t in GROUPS:
            lbl = ctx.user_data.get("label", "📍")
            if "my_groups" not in ctx.user_data:
                ctx.user_data["my_groups"] = {}
            ctx.user_data["my_groups"][lbl] = t
            ctx.user_data["group"] = t
            ctx.user_data["adding"] = False
            await update.message.reply_text(f"✅ {lbl} → {t}", reply_markup=kb_my_groups(ctx))
            return

    # Видалення
    if ctx.user_data.get("removing"):
        if t == BTN_BACK:
            ctx.user_data["removing"] = False
            await cmd_my_groups(update, ctx)
            return
        for l, g in list(ctx.user_data.get("my_groups", {}).items()):
            if t == f"❌ {l}: {g}":
                del ctx.user_data["my_groups"][l]
                if not ctx.user_data["my_groups"]:
                    ctx.user_data["group"] = None
                ctx.user_data["removing"] = False
                await update.message.reply_text(f"✅ Видалено: {l}", reply_markup=kb_my_groups(ctx))
                return

    # Команди
    if t.startswith("/"):
        await cmd_start(update, ctx)
    elif t == BTN_TODAY:
        await cmd_schedule(update, ctx, "today")
    elif t == BTN_TOMORROW:
        await cmd_schedule(update, ctx, "tomorrow")
    elif t == BTN_PREDICT:
        await cmd_predict(update, ctx)
    elif t == BTN_STATS:
        await cmd_stats(update, ctx)
    elif t == BTN_SETTINGS:
        await cmd_settings(update, ctx)
    elif t == BTN_GROUPS:
        await cmd_my_groups(update, ctx)
    elif t == BTN_ADD:
        ctx.user_data["adding"], ctx.user_data["step"] = True, "label"
        await update.message.reply_text("Обери назву:", reply_markup=kb_labels())
    elif t == BTN_REMOVE:
        ctx.user_data["removing"] = True
        await update.message.reply_text("Що видалити?", reply_markup=kb_remove(ctx))
    elif t == BTN_BACK:
        await cmd_start(update, ctx)
    elif t in (BTN_NOTIFY_ON, BTN_NOTIFY_OFF):
        ctx.user_data["notifications"] = not ctx.user_data.get("notifications", True)
        await cmd_settings(update, ctx)
    elif t in (BTN_REMIND_15, BTN_REMIND_30, BTN_REMIND_OFF):
        r = ctx.user_data.get("reminder", 15)
        ctx.user_data["reminder"] = 30 if r == 15 else (0 if r == 30 else 15)
        await cmd_settings(update, ctx)
    elif t in (BTN_COMPARE_ON, BTN_COMPARE_OFF):
        ctx.user_data["compare"] = not ctx.user_data.get("compare", True)
        await cmd_settings(update, ctx)
    elif t in GROUPS:
        ctx.user_data["group"] = t
        if not ctx.user_data.get("my_groups"):
            ctx.user_data["my_groups"] = {"🏠 Дім": t}
        await update.message.reply_text(f"✅ Група {t}", reply_markup=kb_main())
    else:
        for l, g in ctx.user_data.get("my_groups", {}).items():
            if t == f"{l}: {g}":
                await cmd_schedule(update, ctx, "today")
                return
        await cmd_start(update, ctx)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("🚀 YASNO Графік Bot")
    print(f"⏱ Оновлення: {CHECK_INTERVAL // 60} хв | Нагадування: {REMINDER_INTERVAL} сек")
    app = Application.builder().token(TOKEN).persistence(PicklePersistence(filepath=PERSISTENCE_FILE)).build()
    app.add_handler(MessageHandler(filters.TEXT, router))
    app.job_queue.run_repeating(job_updates, interval=CHECK_INTERVAL, first=10)
    app.job_queue.run_repeating(job_reminders, interval=REMINDER_INTERVAL, first=5)
    print("✅ Запущено!")
    app.run_polling()


if __name__ == "__main__":
    main()
