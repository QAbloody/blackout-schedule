#!/usr/bin/env python3
"""
Источник графиков отключений: публичные Telegram-каналы ДТЭК Днепр
(по одному каналу на группу: t.me/dp_dtek_1_1 ... t.me/dp_dtek_6_2).

Читает веб-превью https://t.me/s/<канал> (без API-ключей и без состояния между
запусками) и возвращает данные в том же формате, что и основной парсер:

    {"1.1": {"today":    {"slots": [{"start": 90, "end": 120, "type": "Definite"}],
                          "date": "2026-11-11T00:00:00",
                          "status": "ScheduleApplies"},
             "tomorrow": {...}},
     "1.2": {...}, ...}

Как выбирается график на дату:
  * пост может содержать один день или два (сверху сегодня, снизу завтра) —
    каждый блок с датой разбирается отдельно;
  * для каждой даты берётся блок из самого свежего поста (по id поста), поэтому
    если «сегодняшний» блок в новом двухдневном посте не изменился, он просто
    совпадёт с уже известным, а новым будет только нижний блок (завтра);
  * посты без графика (оперативное сводка, статус «Світло є ще…») игнорируются;
  * блок принимается, только если интервалы покрывают ровно сутки без дыр.

Зависимости: requests, beautifulsoup4
"""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

KYIV_TZ = ZoneInfo("Europe/Kyiv")

GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
          "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]

CHANNEL_PREFIX = os.getenv("TG_CHANNEL_PREFIX", "dp_dtek")
CHANNELS = {g: f"{CHANNEL_PREFIX}_{g.replace('.', '_')}" for g in GROUPS}

TG_RETRIES = int(os.getenv("TG_RETRIES", "3"))
TG_TIMEOUT = int(os.getenv("TG_TIMEOUT", "20"))
TG_RETRY_DELAY = float(os.getenv("TG_RETRY_DELAY", "2"))
TG_PAUSE = float(os.getenv("TG_PAUSE", "0.3"))   # пауза между каналами

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "uk,ru;q=0.8,en;q=0.5",
}

# Маркеры в постах. На скриншотах «нет света» — красное КОЛЬЦО (⭕), а не 🔴,
# поэтому принимаем оба варианта (и пару запасных на случай смены оформления).
ON_MARKS = ("🟢", "✅", "💡")
OFF_MARKS = ("⭕", "🔴", "❌", "🟥", "⛔")

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
INTERVAL_RE = re.compile(
    r"(?P<mark>[^\s\d()]{1,4})?\s*"
    r"(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*[-–—]\s*(?P<h2>\d{1,2}):(?P<m2>\d{2})"
)


# ============================================================
# РАЗБОР ТЕКСТА ПОСТА
# ============================================================

def _state(mark):
    if not mark:
        return None
    if any(c in mark for c in OFF_MARKS):
        return "off"
    if any(c in mark for c in ON_MARKS):
        return "on"
    return None


def _fill_unknown_states(iv):
    """Интервалы в постах строго чередуются (свет/нет света), поэтому
    неизвестный маркер можно вывести из соседа."""
    for i in range(1, len(iv)):
        if iv[i][0] is None and iv[i - 1][0] is not None:
            iv[i][0] = "off" if iv[i - 1][0] == "on" else "on"
    for i in range(len(iv) - 2, -1, -1):
        if iv[i][0] is None and iv[i + 1][0] is not None:
            iv[i][0] = "off" if iv[i + 1][0] == "on" else "on"


def _is_full_day(iv):
    """Интервалы идут подряд от 00:00 до 24:00 без дыр и наложений."""
    if not iv or any(s is None for s, _, _ in iv):
        return False
    if iv[0][1] != 0 or iv[-1][2] != 24 * 60:
        return False
    for (_, _, prev_end), (_, start, _) in zip(iv, iv[1:]):
        if start != prev_end:
            return False
    return all(stop > start for _, start, stop in iv)


def parse_post(text):
    """Текст поста -> [(date, [(state, start_min, end_min), ...]), ...].

    state: 'on' (свет есть) / 'off' (нет света); конец 00:00 = 24:00.
    Возвращает только блоки, где интервалы покрывают сутки целиком."""
    results = []
    headers = list(DATE_RE.finditer(text))

    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[h.end():end]

        intervals = []
        for m in INTERVAL_RE.finditer(block):
            start = int(m["h1"]) * 60 + int(m["m1"])
            stop = int(m["h2"]) * 60 + int(m["m2"])
            if stop == 0:
                stop = 24 * 60
            intervals.append([_state(m["mark"]), start, stop])

        if not intervals:
            continue

        intervals.sort(key=lambda x: x[1])
        _fill_unknown_states(intervals)

        if not _is_full_day(intervals):
            print(f"⚠️ Telegram: блок {h.group(0)} пропущено "
                  f"(інтервали не покривають добу): {intervals}")
            continue

        try:
            day = date(int(h.group(3)), int(h.group(2)), int(h.group(1)))
        except ValueError:
            continue

        results.append((day, [tuple(x) for x in intervals]))

    return results


def outage_slots(intervals):
    """Только интервалы «нет света», склеенные между собой, в формате парсера."""
    slots = []
    for state, start, stop in intervals:
        if state != "off":
            continue
        if slots and slots[-1]["end"] == start:
            slots[-1]["end"] = stop
        else:
            slots.append({"start": start, "end": stop, "type": "Definite"})
    return slots


# ============================================================
# ЗАГРУЗКА КАНАЛА
# ============================================================

def parse_channel_html(html):
    """HTML ленты t.me/s/<канал> -> [(post_id, text)], по возрастанию id."""
    soup = BeautifulSoup(html, "html.parser")
    posts = []

    for wrap in soup.select("div.tgme_widget_message[data-post]"):
        text_el = wrap.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        try:
            post_id = int(wrap["data-post"].rsplit("/", 1)[-1])
        except ValueError:
            continue

        for br in text_el.find_all("br"):
            br.replace_with("\n")

        posts.append((post_id, text_el.get_text()))

    posts.sort(key=lambda p: p[0])
    return posts


def fetch_channel_posts(username):
    last_error = None

    for attempt in range(1, TG_RETRIES + 1):
        try:
            response = requests.get(
                f"https://t.me/s/{username}",
                headers=HEADERS,
                timeout=TG_TIMEOUT,
            )
            response.raise_for_status()
            return parse_channel_html(response.text)
        except Exception as e:
            last_error = e
            if attempt < TG_RETRIES:
                time.sleep(TG_RETRY_DELAY * attempt)

    raise RuntimeError(f"{TG_RETRIES} спроби невдалі: {last_error}")


def latest_schedule_per_date(posts):
    """{date: (post_id, intervals)} — для каждой даты блок из самого свежего поста."""
    by_date = {}
    for post_id, text in posts:           # posts отсортированы по id
        for day, intervals in parse_post(text):
            by_date[day] = (post_id, intervals)
    return by_date


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

def fetch_via_telegram(now=None):
    """Читает 12 каналов. Возвращает данные в формате парсера или None,
    если хотя бы один канал не удалось прочитать (чтобы не получить
    «половинчатый» график — тогда сработает запасной источник)."""

    now = now or datetime.now(KYIV_TZ)
    today = now.date()
    tomorrow = today + timedelta(days=1)

    data = {}

    for group, username in CHANNELS.items():
        try:
            posts = fetch_channel_posts(username)
        except Exception as e:
            print(f"⚠️ Telegram: канал {username} недоступний: {e}")
            return None

        by_date = latest_schedule_per_date(posts)

        def block(day):
            found = by_date.get(day)
            return {
                "slots": outage_slots(found[1]) if found else [],
                "date": f"{day.isoformat()}T00:00:00",
                "status": "ScheduleApplies" if found else "WaitingForSchedule",
            }

        data[group] = {"today": block(today), "tomorrow": block(tomorrow)}

        src_today = by_date.get(today)
        src_tomorrow = by_date.get(tomorrow)
        print(f"    📨 {group} ({username}): "
              f"сьогодні=пост #{src_today[0] if src_today else '—'}, "
              f"завтра=пост #{src_tomorrow[0] if src_tomorrow else '—'}")

        time.sleep(TG_PAUSE)

    print(f"📨 Telegram: прочитано {len(data)} каналів")
    return data


if __name__ == "__main__":
    # Ручная проверка: python tg_source.py
    result = fetch_via_telegram()
    if result is None:
        sys.exit(1)

    def fmt(slots):
        return ", ".join(
            f"{s['start'] // 60:02d}:{s['start'] % 60:02d}-"
            f"{s['end'] // 60:02d}:{s['end'] % 60:02d}" for s in slots
        ) or "—"

    for g, days in result.items():
        print(f"{g}: сьогодні [{days['today']['status']}] {fmt(days['today']['slots'])}"
              f" | завтра [{days['tomorrow']['status']}] {fmt(days['tomorrow']['slots'])}")
