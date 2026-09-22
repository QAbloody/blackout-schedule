# blackout-schedule

Python-проєкт для формування та перевірки розкладу відключень електроенергії за групами ДТЕК.

Поки джерело реальних даних не підключене, бот **не показує тестові інтервали** — українською пише: **«Графіки ще недоступні»**. Генератор випадкових інтервалів збережений у `src/blackout_schedule/schedule.py` лише як заготовка для майбутніх тестів/розробки.

## Що в проєкті

- `update.py` — точка входу CLI
- `src/blackout_schedule/`
  - `cli.py` — команди `update`, `validate`, `notify`
  - `schedule.py` — структура payload і заготовка тестових даних
  - `models.py` — форматування українського повідомлення
  - `history.py` — збереження JSON та історії
  - `parser.py` — розбір дат/інтервалів
- `data/` — актуальне розклад і історія
- `.github/workflows/update.yml` — автоматичний запуск за cron
- `tests/` — перевірки поведінки

## Швидкий старт

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python update.py validate
python update.py notify --group 1.2
```

## Реальні дані

Щоб увімкнути відображення графіків, майбутній парсер має передати в `build_schedule_payload()` реальні групи та встановити `available=True`. До цього часу тестовий генератор не використовується для повідомлень і не видається за реальний графік.

## Перемінні середовища

```bash
TG_CHANNEL=dnepr_svet_voda
TG_BOT_TOKEN=your_bot_token_here
TG_CHAT_ID=your_chat_id_here
TIMEZONE=Europe/Kyiv
SCHEDULE_PATH=data/schedule.json
HISTORY_PATH=data/history.json
CACHE_TTL=300
CHECK_INTERVAL=300
```

## Тести

```bash
pytest
```
