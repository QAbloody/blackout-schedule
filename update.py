import os
import re
import json
import html
import subprocess
from datetime import datetime, date, timezone, timedelta
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

LOOKBACK = int(os.getenv("TG_LOOKBACK", "80"))

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
    status = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    if not status:
        print("No changes to commit.")
        return

    run(["git", "config", "user.name", GIT_NAME])
    run(["git", "config", "user.email", GIT_EMAIL])
    run(["git", "add", SCHEDULE_PATH])
    run(["git", "commit", "-m", f"update schedule {date.today()}"])

    if GITHUB_REPO and GITHUB_PAT:
        repo_with_pat = re.sub(r"^https://", f"https://{GITHUB_PAT}@", GITHUB_REPO)
        run(["git", "push", repo_with_pat, "HEAD:main"])
    else:
        run(["git", "push"])


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


# ====== Telegram HTML parsing ======
WRAP_RE = re.compile(r'<div class="tgme_widget_message_wrap".*?</div>\s*</div>\s*</div>', re.S)

def extract_messages(page_html: str):
    wraps = WRAP_RE.findall(page_html)
    msgs = []
    for w in wraps:
        m_ts = re.search(r'data-unixtime="(\d+)"', w)
        ts = int(m_ts.group(1)) if m_ts else 0

        m_post = re.search(r'data-post="([^"]+)"', w)
        post_id = m_post.group(1) if m_post else ""

        m_text = re.search(r'<div class="tgme_widget_message_text[^"]*">(.*?)</div>', w, re.S)
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
    groups = {}
    norm = text.replace("–", "-").replace("—", "-")

    for line in norm.splitlines():
        line = line.strip()
        line = line.lstrip("•").lstrip("🔴").lstrip("❌").strip()

        m = re.match(r"^(\d+\.\d+)\s*-\s*(.+)$", line)
        if not m:
            continue

        g = m.group(1)
        rest = m.group(2).strip()

        parts = [p.strip() for p in re.split(r"[;,]", rest) if p.strip()]
        good = []
        for itv in parts:
            itv = itv.replace("–", "-").replace("—", "-")
            itv = re.sub(r"\s+", "", itv)
            if re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", itv) or re.match(r"^\d{2}:\d{2}-24:00$", itv):
                good.append(itv)

        if good:
            groups[g] = good

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
    r = requests.get(
        TG_URL,
        timeout=20,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    r.raise_for_status()
    page = r.text

    msgs = extract_messages(page)
    if not msgs:
        raise RuntimeError("No messages parsed from t.me/s page (maybe blocked or HTML changed)")

    # 1) ключевые слова + группы
    best = None
    for m in reversed(msgs[-LOOKBACK:]):
        if has_group_lines(m["text"]) and has_keywords(m["text"]):
            best = m
            break

    # 2) fallback: просто группы
    if best is None:
        for m in reversed(msgs[-LOOKBACK:]):
            if has_group_lines(m["text"]):
                print("WARNING: no keyword match; using latest post that contains group lines")
                best = m
                break

    if best is None:
        raise RuntimeError("No suitable post found in last LOOKBACK messages")

    groups = parse_groups(best["text"])

    # ДАТА: 1) из текста поста, 2) из времени поста, 3) текущая
    date_str = extract_date_from_text(best["text"])
    if not date_str:
        date_str = date_from_message_ts(best.get("ts", 0))

    existing = load_existing()
    old_groups = existing.get("groups", {})
    old_date = existing.get("date")

    if old_groups == groups and (not UPDATE_IF_DATE_CHANGED or old_date == date_str):
        print("Groups (and date) unchanged -> no update.")
        return

    save_schedule(groups, date_str)
    git_push_if_changed()

    print(f"Updated from channel={CHANNEL}, post={best.get('post')}, ts={best.get('ts')}, date={date_str}")

if __name__ == "__main__":
    main()
