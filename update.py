#!/usr/bin/env python3

import os
import sys
import json
import traceback
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Telegram-канали ДТЕК (tg_source.py лежить поруч з цим файлом)
try:
    from tg_source import fetch_via_telegram
except ImportError:
    fetch_via_telegram = None


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Порядок джерел через кому: telegram, table, browser, api.
# Перше джерело, де вже є графік, перемагає; решта — запасні.
SCHEDULE_SOURCES = os.getenv("SCHEDULE_SOURCES", "telegram,table,browser,api")

# Яке джерело дало дані в останньому запуску (пишеться в schedule.json)
LAST_SOURCE = "app.yasno.ua"

PLANNED_OUTAGES_ENDPOINT = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/"
    "regions/{region_id}/dsos/{dso_id}/planned-outages"
)

SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

# Файл зі станом сповіщень (що вже надіслано), щоб не дублювати повідомлення.
# Його треба зберігати між запусками.
STATE_FILE = os.getenv("STATE_FILE", "notify_state.json")

KYIV_TZ = ZoneInfo("Europe/Kyiv")

# Дніпро, оператор ДнЕМ
REGION_ID = 3
PROVIDER_ID = 301

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
# REGION / PROVIDER
# ============================================================

def resolve_region_and_provider():
    print(f"📍 Дніпро (ДнЕМ): region={REGION_ID}, dso={PROVIDER_ID}")
    return REGION_ID, PROVIDER_ID


# ============================================================
# ДЖЕРЕЛА ДАНИХ: браузер (основне) -> прямий API (запасне)
# ============================================================

PAGE_URL = os.getenv("YASNO_PAGE_URL", "https://static.yasno.ua/dnipro/outages/")


def looks_like_schedule(data):
    """JSON з графіком: ключі-групи ('1.1', '3.2'...) з блоками today/tomorrow."""
    if not isinstance(data, dict):
        return False
    group = data.get("1.1") or data.get("3.1")
    return isinstance(group, dict) and "today" in group


def has_real_schedule(data):
    """Є хоча б один день, де графік уже застосовується."""
    if not looks_like_schedule(data):
        return False
    for group in data.values():
        if not isinstance(group, dict):
            continue
        for day in ("today", "tomorrow"):
            status = (group.get(day) or {}).get("status")
            if schedule_ready(status):
                return True
    return False


# ------------------------------------------------------------
# Розбір таблиці "Заплановані відключення" прямо зі сторінки
# ------------------------------------------------------------

# JS виконується у браузері. Він не залежить від верстки (table/div):
# шукає підписи рядків ("3.1"), підписи колонок ("8 - 9") та іконки
# "світла немає", і зіставляє їх за координатами на екрані.
TABLE_JS = r"""
() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const center = el => {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2,
             w: r.width, h: r.height };
  };
  const ownText = el => (el.textContent || "").replace(/\s+/g, " ").trim();
  const leaves = [...document.querySelectorAll("body *")]
    .filter(e => e.children.length === 0 && visible(e));

  const rows = leaves
    .filter(e => /^[1-6]\.[12]$/.test(ownText(e)))
    .map(e => ({ group: ownText(e), ...center(e) }));

  const cols = leaves
    .filter(e => /^\d{1,2}\s*[-–]\s*\d{1,2}$/.test(ownText(e)))
    .map(e => ({ hour: parseInt(ownText(e), 10), ...center(e) }));

  // іконки: svg / img / елементи з фоновою картинкою
  const iconEls = [];
  for (const e of document.querySelectorAll("body *")) {
    if (!visible(e)) continue;
    if (e.closest("svg") && e.tagName.toLowerCase() !== "svg") continue;
    const tag = e.tagName.toLowerCase();
    let isIcon = tag === "svg" || tag === "img";
    if (!isIcon) {
      const bg = getComputedStyle(e).backgroundImage;
      isIcon = bg && bg !== "none" && bg.includes("url");
    }
    if (!isIcon) continue;
    const c = center(e);
    if (c.w > 70 || c.h > 70) continue;   // не іконка
    iconEls.push(c);
  }

  return { rows, cols, icons: iconEls };
}
"""


def hours_to_intervals_slots(hour_states):
    """hour_states: {година: 'full' | 'half'} для одного рядка (черги).
    Повертає список слотів {"start","end","type"} у хвилинах.

    Повна іконка = година без світла. Мала іконка = пів години;
    яка саме половина — визначаємо за сусідами:
      сусід ліворуч відключений  -> перша половина (h:00-h:30)
      сусід праворуч відключений -> друга половина (h:30-h+1:00)
    """

    half_hours = [False] * 48

    for h, state in hour_states.items():
        if not 0 <= h <= 23:
            continue

        if state == "full":
            half_hours[h * 2] = True
            half_hours[h * 2 + 1] = True
            continue

        left = hour_states.get(h - 1)
        right = hour_states.get(h + 1)

        if left and not right:
            half_hours[h * 2] = True            # перша половина
        elif right and not left:
            half_hours[h * 2 + 1] = True        # друга половина
        elif left and right:
            half_hours[h * 2] = True
            half_hours[h * 2 + 1] = True
        else:
            half_hours[h * 2 + 1] = True        # ізольована — друга половина

    slots = []
    i = 0
    while i < 48:
        if half_hours[i]:
            j = i
            while j < 48 and half_hours[j]:
                j += 1
            slots.append({"start": i * 30, "end": j * 30, "type": "Definite"})
            i = j
        else:
            i += 1

    return slots


def parse_table_snapshot(snapshot):
    """snapshot з TABLE_JS -> {група: [слоти]} або None, якщо таблицю
    не знайдено."""

    rows = snapshot.get("rows") or []
    cols = snapshot.get("cols") or []
    icons = snapshot.get("icons") or []

    if len(rows) < 6 or len(cols) < 12:
        return None

    # унікальні колонки за годиною
    col_by_hour = {}
    for c in cols:
        col_by_hour.setdefault(c["hour"], c)

    col_list = sorted(col_by_hour.values(), key=lambda c: c["x"])
    col_w = (col_list[-1]["x"] - col_list[0]["x"]) / max(len(col_list) - 1, 1)

    row_by_group = {}
    for r in rows:
        row_by_group.setdefault(r["group"], r)

    row_list = sorted(row_by_group.values(), key=lambda r: r["y"])
    row_h = (row_list[-1]["y"] - row_list[0]["y"]) / max(len(row_list) - 1, 1)

    # іконки з легенди лежать нижче останнього рядка / вище першого — відсікаємо
    cells = {}
    widths = []

    for ic in icons:
        row = min(row_list, key=lambda r: abs(r["y"] - ic["y"]))
        col = min(col_list, key=lambda c: abs(c["x"] - ic["x"]))

        if abs(row["y"] - ic["y"]) > row_h * 0.6:
            continue
        if abs(col["x"] - ic["x"]) > col_w * 0.6:
            continue

        key = (row["group"], col["hour"])
        cells[key] = max(cells.get(key, 0), ic["w"])
        widths.append(ic["w"])

    if not widths:
        return {r["group"]: [] for r in row_list}

    max_w = max(widths)

    result = {}

    for r in row_list:
        states = {}
        for (group, hour), w in cells.items():
            if group != r["group"]:
                continue
            states[hour] = "full" if w >= max_w * 0.75 else "half"
        result[r["group"]] = hours_to_intervals_slots(states)

    return result


def fetch_via_table(timeout_ms=30000):
    """Читає таблицю "Заплановані відключення" зі сторінки Yasno.
    Повертає дані у тому ж форматі, що й API (today/tomorrow зі слотами)."""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ playwright не встановлено — таблицю не прочитати")
        return None

    snapshots = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(PAGE_URL, wait_until="networkidle", timeout=timeout_ms)

            try:
                page.wait_for_selector("text=Черга", timeout=15000)
            except Exception:
                pass

            page.wait_for_timeout(1500)
            snapshots["today"] = page.evaluate(TABLE_JS)

            try:
                page.get_by_text("Завтра").first.click(timeout=5000)
                page.wait_for_timeout(1500)
                snapshots["tomorrow"] = page.evaluate(TABLE_JS)
            except Exception as e:
                print(f"⚠️ Не вдалося відкрити вкладку 'Завтра': {e}")

            if os.getenv("YASNO_DEBUG") or not snapshots.get("today", {}).get("rows"):
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                page.screenshot(path="debug_page.png", full_page=True)
                print("🐛 Збережено debug_page.html / debug_page.png")

            browser.close()
    except Exception as e:
        print(f"⚠️ Помилка при читанні сторінки: {e}")
        return None

    today_tbl = parse_table_snapshot(snapshots.get("today", {}))

    if not today_tbl:
        print("⚠️ Таблицю з графіком на сторінці не знайдено")
        return None

    tomorrow_tbl = (
        parse_table_snapshot(snapshots["tomorrow"])
        if "tomorrow" in snapshots else None
    ) or {}

    now = datetime.now(KYIV_TZ)
    today_iso = now.strftime("%Y-%m-%dT00:00:00")
    tomorrow_iso = (now + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")

    def block(tbl, group, date_iso):
        slots = tbl.get(group)
        # порожня таблиця на день = графік ще не опубліковано
        # (так само, як статус WaitingForSchedule в API)
        published = any(tbl.values()) if tbl else False
        return {
            "slots": slots or [],
            "date": date_iso,
            "status": "ScheduleApplies" if published else "WaitingForSchedule",
        }

    data = {}

    for group in YASNO_GROUPS:
        data[group] = {
            "today": block(today_tbl, group, today_iso),
            "tomorrow": block(tomorrow_tbl, group, tomorrow_iso),
        }

    print(f"📋 Таблицю зі сторінки прочитано: {len(today_tbl)} груп")
    return data


def fetch_via_browser(timeout_ms=30000):
    """Відкриває сторінку Yasno і перехоплює JSON, який вона сама завантажує."""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ playwright не встановлено — пропускаємо браузерний спосіб")
        return None

    found = []

    def on_response(response):
        try:
            if "json" not in response.headers.get("content-type", ""):
                return
            data = response.json()
        except Exception:
            return
        if looks_like_schedule(data):
            found.append((response.url, data))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("response", on_response)
            page.goto(PAGE_URL, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(3000)
            browser.close()
    except Exception as e:
        print(f"⚠️ Браузерний спосіб не спрацював: {e}")
        return None

    if not found:
        print("⚠️ Браузер не перехопив JSON з графіком")
        return None

    url, data = found[-1]
    print(f"🌐 Перехоплено API зі сторінки: {url}")
    return data


def fetch_via_api():
    """Прямий запит до API (Дніпро, ДнЕМ)."""

    region_id, provider_id = resolve_region_and_provider()

    url = PLANNED_OUTAGES_ENDPOINT.format(
        region_id=region_id,
        dso_id=provider_id,
    )

    try:
        response = requests.get(url, timeout=30)
        print(f"HTTP: {response.status_code} ({url})")
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"⚠️ Прямий запит до API не вдався: {e}")
        return None

    return data if looks_like_schedule(data) else None


def get_schedule_data():
    """Повертає найкращі доступні дані: перевага — тим, де вже є графік."""

    global LAST_SOURCE

    available = {
        "telegram": ("Telegram-канали ДТЕК", "t.me/dp_dtek_*", fetch_via_telegram),
        "table": ("таблиця на сторінці", "app.yasno.ua", fetch_via_table),
        "browser": ("перехоплення API", "app.yasno.ua", fetch_via_browser),
        "api": ("прямий API", "app.yasno.ua", fetch_via_api),
    }

    order = [s.strip() for s in SCHEDULE_SOURCES.split(",") if s.strip()]

    candidates = []

    for key in order:
        if key not in available:
            print(f"⚠️ Невідоме джерело '{key}' у SCHEDULE_SOURCES — пропущено")
            continue

        name, source_label, fetcher = available[key]

        if fetcher is None:
            print(f"⚠️ Джерело '{name}' недоступне (немає tg_source.py?) — пропущено")
            continue

        print(f"🔎 Джерело: {name}")
        data = fetcher()
        if data is None:
            continue
        if has_real_schedule(data):
            print(f"✅ Графік знайдено ({name})")
            LAST_SOURCE = source_label
            return data
        print(f"ℹ️ ({name}) відповідь є, але графік ще не опубліковано")
        candidates.append((source_label, data))

    if candidates:
        LAST_SOURCE, data = candidates[0]
        return data

    raise RuntimeError("Жодне джерело не повернуло дані з графіком")


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

        data = get_schedule_data()

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
    print("🚀 YASNO PARSER (Дніпро, ДнЕМ)")
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

        "source": LAST_SOURCE,

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
