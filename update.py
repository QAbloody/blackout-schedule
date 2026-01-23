import os, re, json, hashlib, subprocess
from datetime import date
import requests

CHANNEL = os.getenv("TG_CHANNEL", "dnepr_svet_voda")
TG_URL = f"https://t.me/s/{CHANNEL}"
SCHEDULE_PATH = os.getenv("SCHEDULE_PATH", "schedule.json")

GITHUB_REPO = os.getenv("GITHUB_REPO")          # https://github.com/QAbloody/blackout-schedule.git
GITHUB_PAT = os.getenv("GITHUB_PAT")            # ghp_...
GIT_NAME = os.getenv("GIT_NAME", "Auto Updater")
GIT_EMAIL = os.getenv("GIT_EMAIL", "auto@local")

def sha(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def run(cmd):
    subprocess.check_call(cmd)

def load_existing():
    if not os.path.exists(SCHEDULE_PATH):
        return {}
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schedule(groups: dict):
    data = {"date": str(date.today()), "timezone": "Europe/Kyiv", "groups": groups}
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

def extract_latest_schedule_text(html: str) -> str:
    """
    Берём самый свежий пост, где есть 'Оновились графики' или 'графіки ДТЕК'.
    В HTML Telegram сообщения лежат в блоках с class="tgme_widget_message_text"
    """
    # вытащим все тексты сообщений
    msgs = re.findall(r'<div class="tgme_widget_message_text[^"]*">(.*?)</div>', html, flags=re.S)
    if not msgs:
        raise RuntimeError("No messages found on t.me/s page")

    # чистим от <br> и тегов по минимуму
    def clean(x: str) -> str:
        x = x.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        x = re.sub(r"<.*?>", "", x)
        return x.strip()

    cleaned = [clean(m) for m in msgs]
    # идём с конца (самые новые)
    for text in reversed(cleaned):
        if ("граф" in text.lower() and "дтек" in text.lower()):
            return text
    # fallback: последний пост
    return cleaned[-1]

def parse_groups_from_text(text: str) -> dict:
    """
    Ожидаем строки примерно:
    1.1 — 00:00-02:30, 04:00-13:00, 16:30-22:00
    """
    groups = {}

    # нормализуем тире
    text = text.replace("–", "-").replace("—", "-")

    # найдём все строки, которые начинаются с группы
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+\.\d+)\s*-\s*(.+)$", line)
        if not m:
            continue
        g = m.group(1)
        rest = m.group(2).strip()

        # интервалы разделены запятыми
        intervals = [x.strip() for x in rest.split(",") if x.strip()]
        # немного валидации
        good = []
        for itv in intervals:
            if re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", itv) or re.match(r"^\d{2}:\d{2}-24:00$", itv):
                good.append(itv)
        if good:
            groups[g] = good

    if not groups:
        raise RuntimeError("Could not parse groups from the post text")
    return groups

def main():
    html = requests.get(TG_URL, timeout=20).text
    post_text = extract_latest_schedule_text(html)
    groups = parse_groups_from_text(post_text)

    existing = load_existing()
    new_doc = {"date": str(date.today()), "timezone": "Europe/Kyiv", "groups": groups}

    # сравниваем только groups, чтобы не коммитить каждый день
    if existing.get("groups") == groups:
        print("Groups unchanged.")
        return

    save_schedule(groups)
    git_push_if_changed()
    print("Updated schedule.json from Telegram channel post.")

if __name__ == "__main__":
    main()
