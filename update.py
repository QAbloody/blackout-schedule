import os
import re
import json
import html
import time
from datetime import datetime, date, timezone, timedelta
from random import randint
import requests

# ====== НАСТРОЙКИ ======
CHANNEL = os.getenv("TG_CHANNEL", "dnepr_svet_voda").strip()
TG_URL = f"https://t.me/s/{CHANNEL}"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Kyiv")

# Telegram уведомления
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

KEYWORDS = [k.strip().lower() for k in os.getenv(
    "TG_KEYWORDS",
    "онов,оновив,оновились,график,графіки,графік,дтек,yasno,відключення,відключення світла,черга,група"
).split(",") if k.strip()]

LOOKBACK = int(os.getenv("TG_LOOKBACK", "200"))
GITHUB_REPO = os.getenv("GITHUB_REPO", "")


# ====== schedule helpers ======
def load_existing():
    if not os.path.exists(SCHEDULE_PATH):
        return {}
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_schedule(groups: dict, date_str: str):
    """Сохраняет график с датой в формате DD.MM.YYYY"""
    try:
        date_obj = date.fromisoformat(date_str)
        formatted_date = date_obj.strftime("%d.%m.%Y")
    except:
        formatted_date = date_str
    
    data = {"date": formatted_date, "timezone": TIMEZONE_NAME, "groups": groups}
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return formatted_date


def send_telegram_notification(message: str):
    """Отправляет уведомление в Telegram"""
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


# ====== Улучшенный fetch ======
def fetch_with_retry(url: str, retries: int = 3):
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    ]
    
    for i in range(retries):
        try:
            cache_buster = f"?_={int(time.time() * 1000)}"
            headers = {
                'User-Agent': user_agents[i % len(user_agents)],
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
            
            print(f"Fetching {url} (attempt {i+1}/{retries})...")
            r = requests.get(url + cache_buster, headers=headers, timeout=20)
            r.raise_for_status()
            print(f"Successfully fetched page ({len(r.text)} bytes)")
            return r.text
        except Exception as e:
            print(f"Attempt {i+1} failed: {e}")
            if i == retries - 1:
                raise
            time.sleep(randint(2, 5))


# ====== Telegram HTML parsing ======
def extract_messages(page_html: str):
    msgs = []
    
    post_blocks = re.finditer(
        r'data-post="([^"]+)".*?<div[^>]*class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        page_html,
        re.S
    )
    
    for match in post_blocks:
        post_id = match.group(1)
        text_html = match.group(2)
        
        start_pos = max(0, match.start() - 1000)
        context = page_html[start_pos:match.end()]
        
        m_ts = re.search(r'data-unixtime="(\d+)"', context)
        ts = int(m_ts.group(1)) if m_ts else 0
        
        text_html = text_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        text_plain = re.sub(r"<.*?>", "", text_html)
        text_plain = html.unescape(text_plain).strip()
        
        if text_plain:
            msgs.append({"ts": ts, "post": post_id, "text": text_plain})
    
    msgs.sort(key=lambda x: x["ts"])
    return msgs


def has_group_lines(text: str) -> bool:
    return bool(re.search(r'(^|\n)\s*\d+\.\d+\s+\d{2}:\d{2}', text, re.MULTILINE))


def has_keywords(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in KEYWORDS)


def parse_groups(text: str) -> dict:
    groups = {}
    norm = text.replace("–", "-").replace("—", "-").replace("−", "-")

    for line in norm.splitlines():
        line = line.strip()
        line = re.sub(r'^[•🔴❌\-\s]+', '', line)
        
        m = re.match(r'^(\d+\.\d+)\s+(.+)$', line)
        if not m:
            continue

        group_id = m.group(1)
        rest = m.group(2).strip()
        
        parts = [p.strip() for p in re.split(r'[/;]', rest) if p.strip()]
        
        intervals = []
        for part in parts:
            times = re.findall(r'\d{2}:\d{2}', part)
            
            for i in range(0, len(times) - 1, 2):
                interval = f"{times[i]}-{times[i+1]}"
                intervals.append(interval)

        if intervals:
            groups[group_id] = intervals

    if not groups:
        raise RuntimeError("Parsed 0 groups from candidate post")
    
    return groups


# ====== Extract date ======
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


def extract_date_from_text(text: str) -> str | None:
    t = text.lower()
    today = date.today()

    # ПРИОРИТЕТ 0: "сьогодні" / "сегодня" / "today"
    if any(word in t for word in ['сьогодні', 'сегодня', 'today']):
        # Проверяем что это не просто упоминание, а про график
        if any(word in t for word in ['графік', 'график', 'schedule', 'станом', 'змінено', 'изменён']):
            return today.isoformat()

    # ПРИОРИТЕТ 1: dd.mm.yyyy
    m = re.search(r'\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b', t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12 and 2020 <= y <= 2030:
            try:
                return date(y, mo, d).isoformat()
            except Exception:
                pass

    # ПРИОРИТЕТ 2: "24 січня 2026"
    m = re.search(r'\b(\d{1,2})\s+([а-яіїє]+)\s+(\d{4})\b', t)
    if m:
        d = int(m.group(1))
        mon_name = m.group(2)
        y = int(m.group(3))
        mo = MONTHS_UA_RU.get(mon_name)
        if mo and 1 <= d <= 31 and 2020 <= y <= 2030:
            try:
                return date(y, mo, d).isoformat()
            except Exception:
                pass

    # ПРИОРИТЕТ 3: "на 24 січня"
    m = re.search(r'\bна\s+(\d{1,2})\s+([а-яіїє]+)\b', t)
    if m:
        d = int(m.group(1))
        mon_name = m.group(2)
        mo = MONTHS_UA_RU.get(mon_name)
        if mo and 1 <= d <= 31:
            y = today.year
            try:
                parsed_date = date(y, mo, d)
                if parsed_date < today and (today - parsed_date).days > 7:
                    y += 1
                    parsed_date = date(y, mo, d)
                return parsed_date.isoformat()
            except:
                pass

    # ПРИОРИТЕТ 4: dd.mm
    m = re.search(r'\b(\d{1,2})[.\-/](\d{1,2})\b(?![.\-/\d])', t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            y = today.year
            try:
                parsed_date = date(y, mo, d)
                if parsed_date < today and (today - parsed_date).days > 7:
                    y += 1
                    parsed_date = date(y, mo, d)
                return parsed_date.isoformat()
            except:
                pass

    # ПРИОРИТЕТ 5: "24 січня"
    m = re.search(r'\b(\d{1,2})\s+([а-яіїє]+)\b', t)
    if m:
        d = int(m.group(1))
        mon_name = m.group(2)
        mo = MONTHS_UA_RU.get(mon_name)
        if mo and 1 <= d <= 31:
            y = today.year
            try:
                parsed_date = date(y, mo, d)
                if parsed_date < today and (today - parsed_date).days > 7:
                    y += 1
                    parsed_date = date(y, mo, d)
                return parsed_date.isoformat()
            except:
                pass

    return None


def date_from_message_ts(ts: int) -> str:
    if ts and ts > 1000000000:
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return date.today().isoformat()


def main():
    page = fetch_with_retry(TG_URL)
    
    debug_mode = os.getenv("DEBUG_HTML", "0") == "1"
    if debug_mode:
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(page)

    msgs = extract_messages(page)
    if not msgs:
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(page)
        raise RuntimeError("No messages parsed")

    print(f"Total messages parsed: {len(msgs)}")
    print(f"Checking last {min(LOOKBACK, len(msgs))} messages...")
    
    if msgs:
        latest = msgs[-1]
        ts = latest.get('ts', 0)
        if ts > 1000000000:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            print(f"Latest: {dt} UTC (ts={ts})")
        else:
            print(f"Latest: INVALID (ts={ts})")
        print(f"Post ID: {latest.get('post')}")
        print(f"Preview: {latest['text'][:100]}...")

    today = date.today()
    tomorrow = today + timedelta(days=1)
    candidates = []
    
    print(f"\n🔍 Analyzing posts...")
    
    for idx, m in enumerate(reversed(msgs[-LOOKBACK:])):
        if not has_group_lines(m["text"]):
            continue
        
        post_date = extract_date_from_text(m["text"])
        preview = m["text"][:80].replace('\n', ' ')
        
        if not post_date:
            if m.get('ts', 0) > 1000000000:
                post_date = date_from_message_ts(m['ts'])
                print(f"  ⚠️  Using timestamp: {post_date} | {preview}...")
            else:
                post_date = today.isoformat()
                print(f"  ⚠️  Using today: {post_date} | {preview}...")
        else:
            print(f"  ✅ Date from text: {post_date} | {preview}...")
        
        score = 0
        
        # Бонус за позицию (более новые посты важнее)
        # idx=0 это самый новый, idx=15 это самый старый
        score += (LOOKBACK - idx) * 10  # Даёт от 10 до 2000 баллов
        
        if has_keywords(m["text"]):
            score += 1000
        
        if m.get('ts', 0) > 1000000000:
            score += m['ts'] // 1000
        
        try:
            pd = date.fromisoformat(post_date)
            if pd == today:
                score += 100000
                print(f"    📅 TODAY - high priority!")
            elif pd == tomorrow:
                score += 50000
                print(f"    📅 TOMORROW")
            elif pd > tomorrow:
                score += 10000
        except:
            pass
        
        score += len(m["text"]) // 10
        
        candidates.append({'msg': m, 'score': score, 'date': post_date})
    
    if not candidates:
        raise RuntimeError("No posts with schedules found")
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\nFound {len(candidates)} candidates:")
    for i, c in enumerate(candidates[:5]):
        ts = c['msg'].get('ts', 0)
        if ts > 1000000000:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        else:
            dt = "INVALID"
        print(f"  {i+1}. Score={c['score']}, Date={c['date']}, Time={dt}")
        print(f"     Post={c['msg'].get('post')}, Preview={c['msg']['text'][:60]}...")
    
    best = candidates[0]['msg']
    date_str = candidates[0]['date']

    print(f"\n🎯 Selected: {best.get('post')}")
    print(f"Date: {date_str}")

    groups = parse_groups(best["text"])
    print(f"Parsed {len(groups)} groups: {list(groups.keys())}")
    
    # Конвертируем дату для сравнения и сохранения
    try:
        date_obj = date.fromisoformat(date_str)
        formatted_date = date_obj.strftime("%d.%m.%Y")
    except:
        formatted_date = date_str

    existing = load_existing()
    old_groups = existing.get("groups", {})
    old_date = existing.get("date")

    groups_changed = old_groups != groups
    
    # Проверяем формат даты - если старый (YYYY-MM-DD), нужно обновить
    date_format_changed = False
    if old_date and "-" in old_date:  # Старый формат YYYY-MM-DD
        date_format_changed = True
        print(f"📅 Detected old date format: {old_date}, will update to new format")
    
    date_changed = old_date != date_str and old_date != formatted_date
    
    if not groups_changed and not date_changed and not date_format_changed:
        print("✅ No changes")
        return
    
    if groups_changed:
        print(f"📝 Groups changed: {len(old_groups)} -> {len(groups)}")
    
    if date_changed:
        print(f"📅 Date changed: {old_date} -> {formatted_date}")
    
    if date_format_changed:
        print(f"📅 Date format updated: {old_date} -> {formatted_date}")

    saved_date = save_schedule(groups, date_str)

    # Отправляем уведомление
    if groups_changed or date_changed or date_format_changed:
        msg = f"🔔 <b>Обновление графика ДТЭК</b>\n\n"
        msg += f"📅 Дата: <b>{saved_date}</b>\n"
        msg += f"📊 Групп: <b>{len(groups)}</b>\n\n"
        
        if groups_changed:
            msg += "📝 <b>Изменились группы</b>\n"
        if date_changed:
            msg += f"📅 <b>Дата изменилась:</b> {old_date} → {saved_date}\n"
        if date_format_changed:
            msg += f"✨ <b>Обновлён формат даты</b>\n"
        
        msg += f"\n🔗 <a href='https://t.me/s/{CHANNEL}'>Канал ДТЭК</a>"
        
        send_telegram_notification(msg)

    print(f"\n✅ Schedule saved!")
    print(f"Date: {saved_date}, Groups: {len(groups)}")


if __name__ == "__main__":
    main()
