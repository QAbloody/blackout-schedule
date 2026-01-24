def extract_date_from_text(text: str) -> str | None:
    """Извлекает дату из текста поста"""
    t = text.lower()

    # 1) dd.mm.yyyy / dd-mm-yyyy / dd/mm/yyyy
    m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})', t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except Exception:
            pass

    # 2) dd.mm (год текущий)
    m = re.search(r'(\d{1,2})[.\-/](\d{1,2})(?!\d)', t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            y = date.today().year
            try:
                return date(y, mo, d).isoformat()
            except Exception:
                pass

    # 3) "24 січня 2026" / "24 января 2026"
    m = re.search(r'\b(\d{1,2})\s+([а-яіїє]+)\s+(\d{4})\b', t)
    if m:
        d = int(m.group(1))
        mon_name = m.group(2)
        y = int(m.group(3))
        mo = MONTHS_UA_RU.get(mon_name)
        if mo and 1 <= d <= 31:
            try:
                return date(y, mo, d).isoformat()
            except Exception:
                pass

    # 4) "24 січня" (год текущий) - используем \b для границы слова
    m = re.search(r'\b(\d{1,2}import os
import re
import json
import html
import subprocess
import time
from datetime import datetime, date, timezone, timedelta
from random import randint
import requests

# ====== НАСТРОЙКИ ======
CHANNEL = os.getenv("TG_CHANNEL", "dnepr_svet_voda").strip()
TG_URL = f"https://t.me/s/{CHANNEL}"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Kyiv")

KEYWORDS = [k.strip().lower() for k in os.getenv(
    "TG_KEYWORDS",
    "онов,оновив,оновились,график,графіки,графік,дтек,yasno,відключення,відключення світла,черга,група"
).split(",") if k.strip()]

LOOKBACK = int(os.getenv("TG_LOOKBACK", "200"))

UPDATE_IF_DATE_CHANGED = os.getenv("UPDATE_IF_DATE_CHANGED", "0") == "1"

GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GIT_NAME = os.getenv("GIT_NAME", "Auto Updater")
GIT_EMAIL = os.getenv("GIT_EMAIL", "auto@local")


# ====== git helpers ======
def run(cmd: list[str]):
    subprocess.check_call(cmd)

def git_push_if_changed():
    try:
        status = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        if not status:
            print("No changes to commit.")
            return

        run(["git", "config", "user.name", GIT_NAME])
        run(["git", "config", "user.email", GIT_EMAIL])
        run(["git", "add", SCHEDULE_PATH])
        run(["git", "commit", "-m", f"update schedule {date.today()}"])

        try:
            run(["git", "pull", "--rebase"])
        except subprocess.CalledProcessError:
            print("Warning: git pull failed, trying to push anyway...")

        if GITHUB_REPO and GITHUB_PAT:
            repo_with_pat = re.sub(r"^https://", f"https://{GITHUB_PAT}@", GITHUB_REPO)
            run(["git", "push", repo_with_pat, "HEAD:main"])
        else:
            run(["git", "push"])
        
        print("✅ Successfully pushed changes to repository")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git operation failed: {e}")
        raise


# ====== schedule helpers ======
def load_existing():
    if not os.path.exists(SCHEDULE_PATH):
        return {}
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schedule(groups: dict, date_str: str):
    data = {"date": date_str, "timezone": TIMEZONE_NAME, "groups": groups}
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ====== Улучшенный fetch с обходом кэша ======
def fetch_with_retry(url: str, retries: int = 3):
    """Пытаемся обойти кэш через разные User-Agent и timestamp"""
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    
    for i in range(retries):
        try:
            cache_buster = f"?_={int(time.time() * 1000)}"
            headers = {
                'User-Agent': user_agents[i % len(user_agents)],
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7'
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
    """Улучшенный парсер с поддержкой разных вариантов HTML структуры Telegram"""
    msgs = []
    
    # Ищем блоки с data-post
    post_blocks = re.finditer(
        r'data-post="([^"]+)".*?<div[^>]*class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        page_html,
        re.S
    )
    
    for match in post_blocks:
        post_id = match.group(1)
        text_html = match.group(2)
        
        # Ищем timestamp в окрестностях (ищем в 1000 символах до match)
        start_pos = max(0, match.start() - 1000)
        context = page_html[start_pos:match.end()]
        
        m_ts = re.search(r'data-unixtime="(\d+)"', context)
        ts = int(m_ts.group(1)) if m_ts else 0
        
        # Очистка HTML
        text_html = text_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        text_plain = re.sub(r"<.*?>", "", text_html)
        text_plain = html.unescape(text_plain).strip()
        
        if text_plain:
            msgs.append({"ts": ts, "post": post_id, "text": text_plain})
    
    msgs.sort(key=lambda x: x["ts"])
    return msgs


def has_group_lines(text: str) -> bool:
    """Проверяет наличие строк с группами отключений"""
    # Паттерны: "1.1 03:00" или "1.1 - 08:00"
    return bool(re.search(r'(^|\n)\s*\d+\.\d+\s+\d{2}:\d{2}', text, re.MULTILINE))


def has_keywords(text: str) -> bool:
    """Проверяет наличие ключевых слов"""
    low = text.lower()
    return any(k in low for k in KEYWORDS)


def parse_groups(text: str) -> dict:
    """
    Парсит графики отключений из текста.
    Поддерживает форматы:
    - 1.1 03:00 - 10:00 / 13:30 - 20:30
    - 1.1 - 08:00-12:00, 16:00-20:00
    - 1.1: 08:00-12:00; 16:00-20:00
    """
    groups = {}
    norm = text.replace("–", "-").replace("—", "-").replace("−", "-")

    for line in norm.splitlines():
        line = line.strip()
        # Убираем эмодзи и маркеры
        line = re.sub(r'^[•🔴❌\-\s]+', '', line)
        
        # Паттерн: "1.1 03:00 - 10:00 / 13:30 - 20:30"
        m = re.match(r'^(\d+\.\d+)\s+(.+)$', line)
        if not m:
            continue

        group_id = m.group(1)
        rest = m.group(2).strip()
        
        # Разделяем интервалы по / или ;
        parts = [p.strip() for p in re.split(r'[/;]', rest) if p.strip()]
        
        intervals = []
        for part in parts:
            # Ищем все времена в формате HH:MM
            times = re.findall(r'\d{2}:\d{2}', part)
            
            # Создаём интервалы из пар времён
            for i in range(0, len(times) - 1, 2):
                interval = f"{times[i]}-{times[i+1]}"
                intervals.append(interval)

        if intervals:
            groups[group_id] = intervals

    if not groups:
        raise RuntimeError("Parsed 0 groups from candidate post (format changed?)")
    
    return groups


# ====== Extract date from post text ======
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
    """Извлекает дату из текста поста"""
    t = text.lower()

    # 1) dd.mm.yyyy / dd-mm-yyyy / dd/mm/yyyy
    m = re.search(r'(^|\D)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})(\D|$)', t)
    if m:
        d, mo, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            return date(y, mo, d).isoformat()
        except Exception:
            pass

    # 2) dd.mm (год текущий)
    m = re.search(r'(^|\D)(\d{1,2})[.\-/](\d{1,2})(\D|$)', t)
    if m:
        d, mo = int(m.group(2)), int(m.group(3))
        y = date.today().year
        try:
            return date(y, mo, d).isoformat()
        except Exception:
            pass

    # 3) "24 січня 2026" / "24 января 2026"
    m = re.search(r'(^|\D)(\d{1,2})\s+([а-яіїє]+)\s+(\d{4})(\D|$)', t)
    if m:
        d = int(m.group(2))
        mon_name = m.group(3)
        y = int(m.group(4))
        mo = MONTHS_UA_RU.get(mon_name)
        if mo:
            try:
                return date(y, mo, d).isoformat()
            except Exception:
                pass

    # 4) "24 січня" (год текущий)
    m = re.search(r'(^|\D)(\d{1,2})\s+([а-яіїє]+)(\D|$)', t)
    if m:
        d = int(m.group(2))
        mon_name = m.group(3)
        mo = MONTHS_UA_RU.get(mon_name)
        if mo:
            today = date.today()
            y = today.year
            
            # Если дата в прошлом (например, нашли "24 января" а сейчас конец января)
            # и разница больше 20 дней - значит это следующий год
            try:
                parsed_date = date(y, mo, d)
                if parsed_date < today and (today - parsed_date).days > 20:
                    y += 1
                    parsed_date = date(y, mo, d)
                return parsed_date.isoformat()
            except Exception:
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
        print("Debug: Saved page HTML to debug_page.html")

    msgs = extract_messages(page)
    if not msgs:
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(page)
        print("ERROR: Saved failing page to error_page.html for analysis")
        raise RuntimeError("No messages parsed from t.me/s page")

    print(f"Total messages parsed: {len(msgs)}")
    print(f"Checking last {min(LOOKBACK, len(msgs))} messages...")
    
    if msgs:
        latest_msg = msgs[-1]
        ts = latest_msg.get('ts', 0)
        if ts > 1000000000:
            latest_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            print(f"Latest message timestamp: {latest_dt} UTC (ts={ts})")
        else:
            print(f"Latest message timestamp: INVALID (ts={ts})")
        print(f"Latest message post ID: {latest_msg.get('post')}")
        print(f"Latest message preview: {latest_msg['text'][:150]}...")

    # Собираем кандидатов
    today = date.today()
    tomorrow = today + timedelta(days=1)
    candidates = []
    
    print(f"\n🔍 Analyzing posts for schedules...")
    
    for m in reversed(msgs[-LOOKBACK:]):
        if not has_group_lines(m["text"]):
            continue
        
        # Извлекаем дату с логированием
        post_date = extract_date_from_text(m["text"])
        post_preview = m["text"][:100].replace('\n', ' ')
        
        if not post_date:
            if m.get('ts', 0) > 1000000000:
                post_date = date_from_message_ts(m['ts'])
                print(f"  ⚠️  No date in text, using timestamp: {post_date} | {post_preview}...")
            else:
                post_date = today.isoformat()
                print(f"  ⚠️  No date found, using today: {post_date} | {post_preview}...")
        else:
            print(f"  ✅ Found date in text: {post_date} | {post_preview}...")
        
        score = 0
        
        if has_keywords(m["text"]):
            score += 1000
        
        if m.get('ts', 0) > 1000000000:
            score += m['ts'] // 1000
        
        try:
            post_date_obj = date.fromisoformat(post_date)
            if post_date_obj == today:
                score += 100000
                print(f"    📅 Date is TODAY - high priority!")
            elif post_date_obj == tomorrow:
                score += 50000
                print(f"    📅 Date is TOMORROW - medium priority")
            elif post_date_obj > tomorrow:
                score += 10000
        except:
            pass
        
        score += len(m["text"]) // 10
        
        candidates.append({
            'msg': m,
            'score': score,
            'date': post_date
        })
    
    if not candidates:
        raise RuntimeError("No posts with schedules found")
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\nFound {len(candidates)} candidates:")
    for i, c in enumerate(candidates[:5]):
        ts = c['msg'].get('ts', 0)
        if ts > 1000000000:
            msg_dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        else:
            msg_dt = "INVALID_TS"
        print(f"  {i+1}. Score={c['score']}, Date={c['date']}, Time={msg_dt}, Post={c['msg'].get('post')}")
        print(f"     Preview: {c['msg']['text'][:80]}...")
    
    best = candidates[0]['msg']
    date_str = candidates[0]['date']

    print(f"\n🎯 Selected post ID: {best.get('post')}")
    ts = best.get('ts', 0)
    if ts > 1000000000:
        print(f"Post timestamp: {datetime.fromtimestamp(ts, tz=timezone.utc)}")
    else:
        print(f"Post timestamp: INVALID (ts={ts})")
    print(f"Post date: {date_str}")
    print(f"Post preview:\n{best['text'][:300]}...\n")

    groups = parse_groups(best["text"])
    print(f"Parsed {len(groups)} groups: {list(groups.keys())}")

    existing = load_existing()
    old_groups = existing.get("groups", {})
    old_date = existing.get("date")

    groups_changed = old_groups != groups
    date_changed = old_date != date_str
    
    if not groups_changed and not date_changed:
        print("✅ Groups and date unchanged -> no update needed.")
        return
    
    if groups_changed:
        print(f"📝 Groups changed: {len(old_groups)} -> {len(groups)}")
    
    if date_changed:
        print(f"📅 Date changed: {old_date} -> {date_str}")

    save_schedule(groups, date_str)

    print(f"\n✅ Schedule saved to {SCHEDULE_PATH}")
    print(f"Channel: {CHANNEL}")
    print(f"Post: {best.get('post')}")
    print(f"Date: {date_str}")
    print(f"Groups: {len(groups)}")

if __name__ == "__main__":
    main()
