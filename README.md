# blackout-schedule

Python-проект для формирования и проверки расписания отключений электроэнергии по группам ДТЭК.

Сейчас репозиторий рассчитан на разработчиков и локальную работу с данными: он генерирует JSON с расписанием на сегодня и завтра, валидирует структуру, хранит историю и умеет формировать Telegram-уведомление.

Важно: это не готовый сервис для пользователей, а инструмент для генерации/проверки данных. В текущей версии источник данных — тестовый генератор (`source: "TEST DATA"`), а не реальный канал ДТЭК.
Репозиторий не подлежит для открытого показа и доступен только составу старших разработчиков, слив/нарушение прав приведёт к моментальному реагированию и ограничению доступа

## Что в проекте

- `update.py` — точка входа CLI
- `src/blackout_schedule/`
  - `cli.py` — команды `update`, `validate`, `notify`
  - `config.py` — переменные окружения
  - `schedule.py` — генерация и валидация расписания
  - `history.py` — сохранение JSON и истории
  - `models.py` — структуры интервалов и форматирование текста
  - `parser.py` — разбор дат/интервалов
  - `notifier.py` — работа с историей
- `data/`
  - `schedule.json` — актуальное расписание
  - `history.json` — история по датам
- `.github/workflows/update.yml` — автоматический запуск по cron
- `tests/` — проверка поведения

## Быстрый старт

```bash
git clone https://github.com/QAbloody/blackout-schedule.git
cd blackout-schedule

python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Команды

```bash
python update.py update
python update.py validate
python update.py notify --group 1.2
```

### Что делает каждая команда

- `update` — генерирует расписание и записывает в `data/schedule.json` + `data/history.json`
- `validate` — проверяет корректность временных интервалов `HH:MM-HH:MM`
- `notify` — формирует Telegram-сообщение и отправляет его, если заданы `TG_BOT_TOKEN` и `TG_CHAT_ID`

## Переменные окружения

Скопируйте пример:

```bash
cp .env.example .env
```

Основные:

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

## Формат данных

```json
{
  "timezone": "Europe/Kyiv",
  "updated": "2026-09-21 16:49:20",
  "source": "TEST DATA",
  "emergency": null,
  "today": {
    "date": "21.09.2026",
    "groups": {
      "1.1": ["15:00-15:30", "16:00-19:00"],
      "1.2": []
    }
  },
  "tomorrow": {
    "date": "22.09.2026",
    "groups": {
      "1.1": ["10:00-11:00"],
      "1.2": []
    }
  }
}
```

Формат интервалов: `HH:MM-HH:MM`.

## GitHub Actions

Workflow `.github/workflows/update.yml` запускается по расписанию и обновляет JSON в репозитории.

Используется `python update.py` и последующий коммит изменений в `schedule.json`/`history.json`.

## Тесты

```bash
pytest
```

## Важное для разработчика

- проект пишется под Python 3.11+
- в коде уже есть структура для Telegram-уведомлений и логики хранения истории
- сейчас реализация не парсит реальный канал ДТЭК; для этого нужно заменить `build_schedule_payload()` на реальный источник
- репозиторий сейчас больше про формат данных и инфраструктуру, чем про готовый пользовательский продукт

## Лицензия

Лицензия пока не добавлена. Если проект будет использоваться публично, нужно добавить `LICENSE`.
