import os
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

LOOKBACK = int(os.getenv("TG_LOOKBACK", "200"))  # Увеличено с 80 до 200

# Если хочешь коммитить даже при тех же группах, но новая дата — 1
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

        # Pull перед push чтобы избежать конфликтов
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
            # Добавляем timestamp чтобы обойти кэш
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
    """
    Улучшенный парсер с поддержкой разных вариантов HTML структуры Telegram
    """
    msgs = []
    
    # Пробуем найти все div с классом tgme_widget_message
    # Используем более гибкий паттерн
    message_divs = re.findall(
        r'<div[^>]*class="[^"]*tgme_widget_message[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        page_html,
        re.S
    )
    
    # Если не нашли, пробуем альтернативный паттерн
    if not message_divs:
        message_divs = re.findall(
            r'<div[^>]*data-post="[^"]+?"[^>]*>(.*?)</section>',
            page_html,
            re.S
        )
    
    # Если всё ещё ничего не нашли, пробуем искать по data-post напрямую
    if not message_divs:
        # Ищем блоки с data-post
        post_blocks = re.finditer(
            r'data-post="([^"]+)"[^>]*>.*?data-unixtime="(\d+)".*?<div[^>]*class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            page_html,
            re.S
        )
        
        for match in post_blocks:
            post_id = match.group(1)
            ts = int(match.group(2))
            text_html = match.group(3)
            
            # Очистка HTML
            text_html = text_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            text_plain = re.sub(r"<.*?>", "", text_html)
            text_plain = html.unescape(text_plain).strip()
            
            if text_plain:
                msgs.append({"ts": ts, "post": post_id, "text": text_plain})
        
        if msgs:
            msgs.sort(key=lambda x: x["ts"])
            return msgs
    
    # Обработка найденных блоков (старый метод)
    for block in message_divs:
        # Извлекаем timestamp
        m_ts = re.search(r'data-unixtime="(\d+)"', block)
        ts = int(m_ts.group(1)) if m_ts else 0
        
        # Извлекаем post ID
        m_post = re.search(r'data-post="([^"]+)"', block)
        post_id = m_post.group(1) if m_post else ""
        
        # Извлекаем текст сообщения
        m_text = re.search(r'<div[^>]*class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if not m_text:
            # Пробуем альтернативный паттерн
            m_text = re.search(r'class="js-message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        
        if not m_text:
            continue
        
        text_html = m_text.group(1)
        text_html = text_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        text_plain = re.sub(r"<.*?>", "", text_html)
        text_plain = html.unescape(text_plain).strip()
        
        if text_plain:
            msgs.append({"ts": ts, "post": post_id, "text": text_plain})
    
    msgs.sort(key=lambda x: x["ts"])
    return msgs


def has_group_lines(text: str) -> bool:
    return bool(re.search(r'(^|\n)\s*\d+\.\d+\s*[-–—]\s*\d{2}:\d{2}\s*-\s*(\d{2}:\d{2}|24:00)', text))


def has_keywords(text: str) -> bool:
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
        line = line.lstrip("•").lstrip("🔴").lstrip("❌").lstrip("-").strip()
        
        # Паттерн 1: "1.1 03:00 - 10:00 / 13:30 - 20:30"
        m = re.match(r"^(\d+\.\d+)\s+(.+)$", line)
        if not m:
            continue

        group_id = m.group(1)
        rest = m.group(2).strip()
        
        # Убираем все после двоеточия или тире в начале
        rest = re.sub(r"^[-:]\s*", "", rest)
        
        # Разделяем интервалы по /, ; или запятой
        parts = [p.strip() for p in re.split(r"[/;,]", rest) if p.strip()]
        
        intervals = []
        for part in parts:
            # Убираем пробелы вокруг тире
            part = re.sub(r"\s*-\s*", "-", part)
            # Убираем лишние пробелы
            part = re.sub(r"\s+", " ", part).strip()
            
            # Ищем паттерны времени
            # Формат: 03:00-10:00 или 03:00 - 10:00
            time_matches = re.findall(r"\d{2}:\d{2}", part)
            
            if len(time_matches) >= 2:
                # Создаём интервалы из пар времён
                for i in range(0, len(time_matches), 2):
                    if i + 1 < len(time_matches):
                        interval = f"{time_matches[i]}-{time_matches[i+1]}"
                        intervals.append(interval)
            elif len(time_matches) == 1:
                # Если только одно время, возможно формат "до 24:00"
                if "24:00" in part or "00:00" in part:
                    interval = f"{time_matches[0]}-24:00"
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
    """
    Пытаемся найти дату в тексте поста и вернуть YYYY-MM-DD.
    Поддержка:
      - 24.01.2026 / 24/01/2026 / 24-01-2026
      - 24.01 (год берём текущий)
      - 24 січня 2026 / 24 января 2026
      - 24 січня (год текущий)
    """
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
            y = date.today().year
            try:
                return date(y, mo, d).isoformat()
            except Exception:
                pass

    return None


def date_from_message_ts(ts: int) -> str:
    if ts:
        # ts в UTC, но для даты нам достаточно локального дня (Kyiv).
        # Простейший способ без pytz: применим фиксированный сдвиг +2/+3 сложно.
        # Поэтому используем UTC-дату как fallback — обычно совпадает.
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return date.today().isoformat()


def main():
    # Используем улучшенный fetch
    page = fetch_with_retry(TG_URL)
    
    # Сохраняем HTML для отладки (опционально)
    debug_mode = os.getenv("DEBUG_HTML", "0") == "1"
    if debug_mode:
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(page)
        print("Debug: Saved page HTML to debug_page.html")

    msgs = extract_messages(page)
    if not msgs:
        # Сохраняем HTML при ошибке для анализа
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(page)
        print("ERROR: Saved failing page to error_page.html for analysis")
        
        # Попробуем найти хоть что-то с data-post
        data_posts = re.findall(r'data-post="([^"]+)"', page)
        print(f"Found {len(data_posts)} data-post attributes in HTML")
        
        # Попробуем найти message_text
        text_divs = re.findall(r'class="[^"]*message_text[^"]*"', page)
        print(f"Found {len(text_divs)} message_text divs in HTML")
        
        raise RuntimeError("No messages parsed from t.me/s page (maybe blocked or HTML changed)")

    # Логирование для диагностики
    print(f"Total messages parsed: {len(msgs)}")
    print(f"Checking last {LOOKBACK} messages...")
    if msgs:
        latest_msg = msgs[-1]
        latest_dt = datetime.fromtimestamp(latest_msg['ts'], tz=timezone.utc)
        print(f"Latest message timestamp: {latest_dt} UTC")
        print(f"Latest message post ID: {latest_msg.get('post')}")
        print(f"Latest message preview: {latest_msg['text'][:150]}...")

    # НОВАЯ ЛОГИКА: ищем самый свежий график за последние 24 часа
    now = datetime.now(timezone.utc)
    one_day_ago = now - timedelta(days=1)
    
    candidates = []
    
    # Собираем все подходящие посты
    for m in reversed(msgs[-LOOKBACK:]):
        msg_time = datetime.fromtimestamp(m['ts'], tz=timezone.utc)
        
        # Пропускаем сообщения старше 24 часов
        if msg_time < one_day_ago:
            continue
        
        # Проверяем наличие групп
        if not has_group_lines(m["text"]):
            continue
        
        # Извлекаем дату из поста
        post_date = extract_date_from_text(m["text"])
        if not post_date:
            post_date = date_from_message_ts(m.get("ts", 0))
        
        # Добавляем в кандидаты
        score = 0
        
        # Бонус за наличие ключевых слов
        if has_keywords(m["text"]):
            score += 100
        
        # Бонус за свежесть (последние сообщения важнее)
        score += m['ts']
        
        # Бонус если дата в посте = сегодня или завтра
        today = date.today()
        tomorrow = today + timedelta(days=1)
        try:
            post_date_obj = date.fromisoformat(post_date)
            if post_date_obj == today:
                score += 1000
            elif post_date_obj == tomorrow:
                score += 500
        except:
            pass
        
        candidates.append({
            'msg': m,
            'score': score,
            'date': post_date
        })
    
    if not candidates:
        print("WARNING: No candidates found in last 24 hours, falling back to old logic")
        # Старая логика как fallback
        best = None
        for m in reversed(msgs[-LOOKBACK:]):
            if has_group_lines(m["text"]) and has_keywords(m["text"]):
                best = m
                break
        
        if best is None:
            for m in reversed(msgs[-LOOKBACK:]):
                if has_group_lines(m["text"]):
                    print("WARNING: no keyword match; using latest post that contains group lines")
                    best = m
                    break
        
        if best is None:
            raise RuntimeError("No suitable post found in last LOOKBACK messages")
        
        date_str = extract_date_from_text(best["text"])
        if not date_str:
            date_str = date_from_message_ts(best.get("ts", 0))
    else:
        # Выбираем кандидата с наивысшим score
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        print(f"\nFound {len(candidates)} candidates:")
        for i, c in enumerate(candidates[:5]):  # Показываем топ-5
            msg_dt = datetime.fromtimestamp(c['msg']['ts'], tz=timezone.utc)
            print(f"  {i+1}. Score={c['score']}, Date={c['date']}, Time={msg_dt}, Post={c['msg'].get('post')}")
            print(f"     Preview: {c['msg']['text'][:80]}...")
        
        best = candidates[0]['msg']
        date_str = candidates[0]['date']

    print(f"\n🎯 Selected post ID: {best.get('post')}")
    print(f"Post timestamp: {datetime.fromtimestamp(best.get('ts', 0), tz=timezone.utc)}")
    print(f"Post date: {date_str}")
    print(f"Post preview:\n{best['text'][:300]}...\n")

    groups = parse_groups(best["text"])
    print(f"Parsed {len(groups)} groups: {list(groups.keys())}")

    existing = load_existing()
    old_groups = existing.get("groups", {})
    old_date = existing.get("date")

    # Проверяем нужно ли обновление
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
    
    # Git push теперь делает workflow, не скрипт
    # git_push_if_changed()

    print(f"\n✅ Updated from channel={CHANNEL}, post={best.get('post')}, ts={best.get('ts')}, date={date_str}")

if __name__ == "__main__":
    main()
