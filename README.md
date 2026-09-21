# blackout-schedule

Генератор, валидатор и архиватор графиков отключений электроэнергии для групп ДТЭК Дніпро.

Проект написан на Python и формирует JSON-файлы с расписанием на сегодня и завтра для 12 групп (`1.1`–`6.2`). Репозиторий также содержит CLI, отправку уведомлений в Telegram и GitHub Actions для регулярного обновления данных.

> **Важно:** текущая реализация генерирует тестовые интервалы (`source: "TEST DATA"`). Она не извлекает расписание из Telegram или с сайта ДТЭК. Поэтому `schedule.json` в репозитории следует рассматривать как пример формата и результат тестового запуска.

## Возможности

- генерация расписания на сегодня и завтра;
- поддержка групп ДТЭК `1.1`–`6.2`;
- проверка интервалов на корректный формат и диапазон времени;
- сохранение актуального расписания в `data/schedule.json`;
- ведение истории по датам в `data/history.json`;
- формирование HTML-сообщения для Telegram;
- необязательная отправка уведомлений через Telegram Bot API;
- автоматический запуск через GitHub Actions каждые 30 минут;
- тесты для парсинга дат, расписания, истории и уведомлений.

## Требования

- Python 3.11 или новее;
- `pip`;
- для уведомлений — Telegram-бот и ID чата.

Основная зависимость проекта — `requests`. Для запуска тестов используется `pytest`.

## Установка

```bash
git clone https://github.com/QAbloody/blackout-schedule.git
cd blackout-schedule

python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\\Scripts\\activate      # Windows

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Также проект можно установить как Python-пакет:

```bash
python -m pip install -e .
```

## Использование CLI

Точка входа для командной строки — `update.py`.

### Сгенерировать расписание

```bash
python update.py update
```

Команда создаёт или обновляет:

- `data/schedule.json` — расписание на сегодня и завтра;
- `data/history.json` — историю для обеих дат.

Если команда не указана, используется `update`:

```bash
python update.py
```

### Проверить расписание

```bash
python update.py validate
```

Команда проверяет интервалы вида `HH:MM-HH:MM`, порядок начала и окончания, а также допустимый диапазон суток. При ошибках процесс завершается с кодом `1`.

### Отправить уведомление в Telegram

```bash
python update.py notify --group 1.2
```

Для отправки необходимо задать `TG_BOT_TOKEN` и `TG_CHAT_ID`. Без этих переменных команда только сообщит, что уведомление пропущено.

## Конфигурация

Скопируйте пример переменных окружения:

```bash
cp .env.example .env
```

Файл `.env` автоматически не загружается приложением, поэтому переменные нужно экспортировать самостоятельно или передать их окружению процесса.

| Переменная | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `TG_CHANNEL` | Имя Telegram-канала источника | `dnepr_svet_voda` |
| `TG_BOT_TOKEN` | Токен Telegram-бота | пусто |
| `TG_CHAT_ID` | ID чата для уведомлений | пусто |
| `TIMEZONE` | Часовой пояс | `Europe/Kyiv` |
| `SCHEDULE_PATH` | Путь к файлу расписания | `data/schedule.json` |
| `HISTORY_PATH` | Путь к файлу истории | `data/history.json` |
| `CACHE_TTL` | Время кэширования в секундах | `300` |
| `CHECK_INTERVAL` | Интервал проверки в секундах | `300` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |

Пример запуска с настройками:

```bash
TG_BOT_TOKEN="123456:token" \
TG_CHAT_ID="-1001234567890" \
python update.py notify --group 1.2
```

Не добавляйте реальные токены в репозиторий. Для GitHub Actions используйте **Settings → Secrets and variables → Actions**.

## Формат данных

Пример `schedule.json`:

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

Пустой список означает, что плановых отключений для группы нет. Интервалы хранятся в формате `HH:MM-HH:MM`.

`history.json` хранит данные по датам:

```json
{
  "days": {
    "21.09.2026": {
      "groups": {
        "1.1": ["15:00-15:30"]
      },
      "updated": "2026-09-21 16:49:20"
    }
  }
}
```

## Структура проекта

```text
blackout-schedule/
├── .github/workflows/update.yml       # регулярный запуск и коммит JSON
├── data/
│   ├── schedule.json                  # актуальное расписание
│   └── history.json                   # история расписаний
├── src/blackout_schedule/
│   ├── cli.py                         # команды update, validate, notify
│   ├── config.py                      # настройки из переменных окружения
│   ├── history.py                     # запись расписания и истории
│   ├── models.py                      # интервалы и форматирование статуса
│   ├── notifier.py                    # работа с историей
│   ├── parser.py                      # разбор дат и интервалов
│   └── schedule.py                    # генерация и валидация расписания
├── tests/                             # тесты pytest
├── update.py                          # скрипт-обёртка для CLI
├── pyproject.toml
├── requirements.txt
└── .env.example
```

## GitHub Actions

Workflow `Update Schedule` запускается:

- по расписанию в `:05` и `:35` каждого часа;
- вручную через **Actions → Update Schedule → Run workflow**;
- при push в `main`, если изменены `update.py` или workflow.

Workflow устанавливает Python 3.11, запускает `python update.py`, а затем коммитит изменения `schedule.json` и `history.json`. Для текущего генератора дополнительные секреты не требуются; они нужны только для Telegram-уведомлений.

При сбое workflow загружает отладочные файлы `debug_page.html` и `debug_page.png`, если они были созданы.

## Тесты

Запустить весь набор тестов:

```bash
pytest
```

Или с подробным выводом:

```bash
pytest -v
```

## Архитектура

1. `schedule.build_schedule_payload()` формирует данные на две даты.
2. `schedule.validate_schedule()` проверяет интервалы.
3. `history.update_schedule()` сохраняет расписание и историю.
4. `cli.py` предоставляет команды для ручного запуска и Telegram-уведомлений.
5. GitHub Actions повторяет процесс автоматически и сохраняет изменения в репозитории.

## Ограничения и планы

- источник данных пока тестовый, а не реальное расписание ДТЭК;
- `TG_CHANNEL` уже предусмотрен в конфигурации, но текущий генератор не загружает посты канала;
- при подключении реального источника необходимо заменить `build_schedule_payload()` на загрузку и разбор актуальных публикаций, сохранив последующую валидацию формата.

## Лицензия

Лицензия в репозитории пока не указана. Если проект распространяется публично, добавьте файл `LICENSE` с выбранными условиями использования.

## Ссылки

- [Репозиторий](https://github.com/QAbloody/blackout-schedule)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Документация GitHub Actions](https://docs.github.com/en/actions)
- [Документация pytest](https://docs.pytest.org/)
