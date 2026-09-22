#!/usr/bin/env python3

import os
import json
import time
import traceback
import requests

from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# НАСТРОЙКИ
# ============================================================

DTEK_URL = "https://www.dtek-dnem.com.ua/ua/shutdowns"

YASNO_API = (
    "https://api.yasno.com.ua/api/v1/pages/home/"
    "schedule-turn-off-electricity"
)

CITY = "м. Дніпро"

SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")


# Групи, які беремо з DTEK
DTEK_GROUPS = {
    "1.1": "пров. Парковий",
    "1.2": "вул. Мохова",
    "3.1": "вул. Центральна",
    "3.2": "вул. Холодильна",
    "5.1": "пров. Морський",
    "5.2": "вул. Автодорожна",
}


# Групи, які беремо з YASNO
YASNO_GROUPS = [
    "2.1",
    "2.2",
    "4.1",
    "4.2",
    "6.1",
    "6.2",
]


ALL_GROUPS = [
    "1.1", "1.2",
    "2.1", "2.2",
    "3.1", "3.2",
    "4.1", "4.2",
    "5.1", "5.2",
    "6.1", "6.2",
]


# ============================================================
# YASNO
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


def yasno_slots_to_intervals(slots):
    if not slots:
        return []

    intervals = []

    for slot in slots:

        start = slot.get("start", 0)
        end = slot.get("end", 0)

        slot_type = slot.get("type", "")

        if "OUTAGE" not in slot_type:
            continue

        sh = int(start)
        sm = int(round((start - sh) * 60))

        eh = int(end)
        em = int(round((end - eh) * 60))

        if eh == 24:
            em = 0

        intervals.append(
            f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"
        )

    return merge_intervals(intervals)


def fetch_yasno_schedule():
    print()
    print("=" * 60)
    print("📡 YASNO API")
    print("=" * 60)

    result = {
        "today": {},
        "tomorrow": {}
    }

    try:

        response = requests.get(
            YASNO_API,
            timeout=30
        )

        print(f"HTTP: {response.status_code}")

        response.raise_for_status()

        data = response.json()

        components = data.get("components", [])

        schedule_data = None

        for component in components:

            if component.get("template_name") == (
                "electricity-outages-daily-schedule"
            ):

                schedule_data = (
                    component
                    .get("schedule", {})
                    .get("dnipro", {})
                )

                break

        if not schedule_data:

            print("❌ Графіки YASNO не знайдені")

            return result

        print("✅ Графіки YASNO знайдені")

        today_weekday = datetime.now().weekday()

        tomorrow_weekday = (
            today_weekday + 1
        ) % 7

        for group in YASNO_GROUPS:

            group_key = f"group_{group}"

            group_data = schedule_data.get(
                group_key,
                []
            )

            if not group_data:

                print(
                    f"⚠️ Група {group}: даних немає"
                )

                continue

            if len(group_data) < 7:

                print(
                    f"⚠️ Група {group}: "
                    f"неочікувана структура"
                )

                continue

            today_slots = group_data[
                today_weekday
            ]

            tomorrow_slots = group_data[
                tomorrow_weekday
            ]

            today_intervals = (
                yasno_slots_to_intervals(
                    today_slots
                )
            )

            tomorrow_intervals = (
                yasno_slots_to_intervals(
                    tomorrow_slots
                )
            )

            result["today"][group] = today_intervals
            result["tomorrow"][group] = tomorrow_intervals

            today_minutes = sum_intervals(
                today_intervals
            )

            tomorrow_minutes = sum_intervals(
                tomorrow_intervals
            )

            print(
                f"📍 {group}: "
                f"сьогодні "
                f"{today_minutes // 60}год "
                f"{today_minutes % 60:02d}хв | "
                f"завтра "
                f"{tomorrow_minutes // 60}год "
                f"{tomorrow_minutes % 60:02d}хв"
            )

        print(
            f"✅ YASNO оброблено: "
            f"{len(result['today'])} груп"
        )

    except Exception as e:

        print(
            f"❌ Помилка YASNO: {e}"
        )

        traceback.print_exc()

    return result


# ============================================================
# SELENIUM / DTEK
# ============================================================

def setup_driver():

    options = Options()

    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    return webdriver.Chrome(
        options=options
    )


def close_popup(driver):

    message = None
    is_emergency = False

    try:

        popup = driver.find_element(
            By.CSS_SELECTOR,
            ".modal__container, "
            ".m-attention__container, "
            "[class*='modal'][class*='container']"
        )

        full_text = popup.text.strip()

        lines = [
            line.strip()
            for line in full_text.split("\n")
            if line.strip()
        ]

        start_index = 0

        skip_phrases = [
            "шановні",
            "увага",
            "dear",
            "дорогі"
        ]

        if lines and any(
            phrase in lines[0].lower()
            for phrase in skip_phrases
        ):
            start_index = 1

        important_lines = lines[
            start_index:start_index + 2
        ]

        message = " ".join(
            important_lines
        )

        if len(message) > 200:

            message = message[:197] + "..."

        emergency_keywords = [
            "екстрен",
            "аварій",
            "терміново",
            "негайно",
            "надзвичайн",
            "без графік",
            "цілодобов",
            "00:00 до 24:00",
            "весь день",
        ]

        text_lower = full_text.lower()

        for keyword in emergency_keywords:

            if keyword in text_lower:

                is_emergency = True
                break

        try:

            close_button = driver.find_element(
                By.CSS_SELECTOR,
                ".modal__close, .m-attention__close"
            )

            close_button.click()

            time.sleep(1)

        except Exception:
            pass

    except Exception:
        pass

    return message, is_emergency


def fill_form(driver, street):

    actions = ActionChains(driver)

    popup_message = None
    is_emergency = False

    try:

        print("    ⏳ Очікуємо форму...")

        WebDriverWait(
            driver,
            15
        ).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".discon-schedule-form #city"
                )
            )
        )

        popup_message, is_emergency = (
            close_popup(driver)
        )

        time.sleep(2)

        # ----------------------------------------------------
        # МІСТО
        # ----------------------------------------------------

        city_input = driver.find_element(
            By.CSS_SELECTOR,
            ".discon-schedule-form #city"
        )

        driver.execute_script(
            """
            arguments[0].scrollIntoView({
                block: 'center'
            });
            """,
            city_input
        )

        time.sleep(0.5)

        driver.execute_script(
            """
            arguments[0].click();
            arguments[0].focus();
            """,
            city_input
        )

        actions.move_to_element(
            city_input
        ).click().send_keys(
            CITY
        ).perform()

        time.sleep(2)

        try:

            autocomplete = WebDriverWait(
                driver,
                5
            ).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "#cityautocomplete-list div, "
                        "[class*='autocomplete'] div"
                    )
                )
            )

            autocomplete.click()

        except Exception:

            city_input.send_keys(
                Keys.RETURN
            )

        time.sleep(2)

        # ----------------------------------------------------
        # ВУЛИЦЯ
        # ----------------------------------------------------

        street_input = driver.find_element(
            By.CSS_SELECTOR,
            ".discon-schedule-form #street"
        )

        if street_input.get_attribute(
            "disabled"
        ):

            driver.execute_script(
                """
                arguments[0].disabled = false;
                """,
                street_input
            )

        driver.execute_script(
            """
            arguments[0].click();
            arguments[0].focus();
            """,
            street_input
        )

        time.sleep(0.5)

        actions = ActionChains(driver)

        actions.move_to_element(
            street_input
        ).click().send_keys(
            street
        ).perform()

        time.sleep(2)

        try:

            autocomplete = WebDriverWait(
                driver,
                5
            ).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "#streetautocomplete-list div, "
                        "[class*='autocomplete'] div"
                    )
                )
            )

            autocomplete.click()

        except Exception:

            street_input.send_keys(
                Keys.RETURN
            )

        time.sleep(2)

        # ----------------------------------------------------
        # БУДИНОК
        # ----------------------------------------------------

        try:

            house_input = driver.find_element(
                By.CSS_SELECTOR,
                ".discon-schedule-form #house_num"
            )

            if house_input.get_attribute(
                "disabled"
            ):

                driver.execute_script(
                    """
                    arguments[0].disabled = false;
                    """,
                    house_input
                )

            driver.execute_script(
                """
                arguments[0].click();
                arguments[0].focus();
                """,
                house_input
            )

            time.sleep(0.5)

            actions = ActionChains(driver)

            actions.move_to_element(
                house_input
            ).click().send_keys(
                "1"
            ).perform()

            time.sleep(2)

            try:

                autocomplete = WebDriverWait(
                    driver,
                    5
                ).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "#house_numautocomplete-list div, "
                            "[class*='autocomplete'] div"
                        )
                    )
                )

                autocomplete.click()

            except Exception:

                house_input.send_keys(
                    Keys.RETURN
                )

        except Exception as e:

            print(
                f"    ⚠️ Будинок: {e}"
            )

        time.sleep(3)

        return (
            True,
            popup_message,
            is_emergency
        )

    except Exception as e:

        print(
            f"    ❌ Помилка форми: {e}"
        )

        return (
            False,
            popup_message,
            is_emergency
        )


# ============================================================
# DTEK PARSER
# ============================================================

def parse_schedule(driver, day="today"):

    slots = [False] * 48

    try:

        if day == "tomorrow":

            tables = driver.find_elements(
                By.CSS_SELECTOR,
                ".discon-fact-table"
            )

            print(
                f"    🔎 Таблиць знайдено: "
                f"{len(tables)}"
            )

            if len(tables) >= 2:

                table = tables[1]

                try:

                    thead = table.find_element(
                        By.TAG_NAME,
                        "thead"
                    )

                    thead.click()

                    time.sleep(1)

                except Exception:
                    pass

                if "active" not in (
                    table.get_attribute("class")
                    or ""
                ):

                    driver.execute_script(
                        """
                        var tabs =
                            document.querySelectorAll(
                                '.discon-fact-table'
                            );

                        tabs.forEach(function(t) {
                            t.classList.remove('active');
                        });

                        arguments[0].classList.add(
                            'active'
                        );
                        """,
                        table
                    )

                    time.sleep(0.5)

        active_table = driver.find_element(
            By.CSS_SELECTOR,
            ".discon-fact-table.active table"
        )

        cells = active_table.find_elements(
            By.CSS_SELECTOR,
            "tbody td[class*='cell-']"
        )

        print(
            f"    🔎 Комірок знайдено: "
            f"{len(cells)}"
        )

        for i, cell in enumerate(
            cells[:24]
        ):

            cls = (
                cell.get_attribute("class")
                or ""
            )

            first = (
                "cell-scheduled" in cls
                and "maybe" not in cls
            )

            second = first

            if "cell-first-half" in cls:

                first = True
                second = False

            if "cell-second-half" in cls:

                first = False
                second = True

            slots[i * 2] = first
            slots[i * 2 + 1] = second

    except Exception as e:

        print(
            f"    ❌ Помилка таблиці "
            f"{day}: {e}"
        )

    return slots


def slots_to_intervals(slots):

    intervals = []

    i = 0

    while i < 48:

        if slots[i]:

            start = i

            while (
                i < 48
                and slots[i]
            ):
                i += 1

            end = i

            sh, sm = divmod(
                start * 30,
                60
            )

            eh, em = divmod(
                end * 30,
                60
            )

            intervals.append(
                f"{sh:02d}:{sm:02d}-"
                f"{eh:02d}:{em:02d}"
            )

        else:

            i += 1

    return intervals


def fetch_dtek_schedule():

    result = {
        "today": {},
        "tomorrow": {}
    }

    announcement = None
    emergency = False

    driver = None

    print()
    print("=" * 60)
    print("📡 DTEK")
    print("=" * 60)

    try:

        print("🌐 Запускаємо Chrome...")

        driver = setup_driver()

        print("✅ Chrome запущено")

        for group, street in DTEK_GROUPS.items():

            print()
            print(
                f"📍 Група {group} "
                f"({street})"
            )

            try:

                print(
                    "    🌐 Відкриваємо DTEK..."
                )

                driver.get(DTEK_URL)

                time.sleep(4)

                print(
                    f"    Заголовок: "
                    f"{driver.title}"
                )

                success, message, is_emergency = (
                    fill_form(
                        driver,
                        street
                    )
                )

                if message and not announcement:

                    announcement = message
                    emergency = is_emergency

                    print(
                        f"    📢 {message}"
                    )

                if not success:

                    print(
                        "    ❌ Форму заповнити "
                        "не вдалося"
                    )

                    continue

                # СЬОГОДНІ

                slots_today = parse_schedule(
                    driver,
                    "today"
                )

                if any(slots_today):

                    intervals = (
                        slots_to_intervals(
                            slots_today
                        )
                    )

                    result[
                        "today"
                    ]["groups"][group] = intervals

                    minutes = (
                        sum_intervals(
                            intervals
                        )
                    )

                    print(
                        f"    📊 Сьогодні: "
                        f"{intervals} "
                        f"({minutes // 60}год "
                        f"{minutes % 60:02d}хв)"
                    )

                else:

                    result[
                        "today"
                    ]["groups"][group] = []

                    print(
                        "    🟢 Сьогодні: "
                        "відключень немає"
                    )

                # ЗАВТРА

                slots_tomorrow = (
                    parse_schedule(
                        driver,
                        "tomorrow"
                    )
                )

                if any(slots_tomorrow):

                    intervals = (
                        slots_to_intervals(
                            slots_tomorrow
                        )
                    )

                    result[
                        "tomorrow"
                    ]["groups"][group] = intervals

                    minutes = (
                        sum_intervals(
                            intervals
                        )
                    )

                    print(
                        f"    📅 Завтра: "
                        f"{intervals} "
                        f"({minutes // 60}год "
                        f"{minutes % 60:02d}хв)"
                    )

                else:

                    result[
                        "tomorrow"
                    ]["groups"][group] = []

                    print(
                        "    🟢 Завтра: "
                        "відключень немає"
                    )

            except Exception as e:

                print(
                    f"    ❌ Група {group}: "
                    f"{e}"
                )

                traceback.print_exc()

        # DEBUG

        try:

            driver.save_screenshot(
                "debug_page.png"
            )

            with open(
                "debug_page.html",
                "w",
                encoding="utf-8"
            ) as file:

                file.write(
                    driver.page_source
                )

            print(
                "\n🐛 Збережено "
                "debug_page.png "
                "і debug_page.html"
            )

        except Exception as e:

            print(
                f"⚠️ Debug не збережено: {e}"
            )

    except Exception as e:

        print(
            f"\n❌ DTEK error: {e}"
        )

        traceback.print_exc()

    finally:

        if driver:

            driver.quit()

            print(
                "🔒 Chrome закрито"
            )

    result["announcement"] = announcement

    if emergency:

        result["emergency"] = announcement

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("🚀 DTEK + YASNO PARSER")
    print("=" * 60)

    now = datetime.now()

    today = now.strftime(
        "%d.%m.%Y"
    )

    tomorrow = now.strftime(
        "%d.%m.%Y"
    )

    print()
    print(f"📅 Сьогодні: {today}")
    print(f"📅 Завтра: {tomorrow}")

    # --------------------------------------------------------
    # DTEK
    # --------------------------------------------------------

    dtek_data = fetch_dtek_schedule()

    # --------------------------------------------------------
    # YASNO
    # --------------------------------------------------------

    yasno_data = fetch_yasno_schedule()

    # --------------------------------------------------------
    # ОБ'ЄДНУЄМО
    # --------------------------------------------------------

    today_groups = {}
    tomorrow_groups = {}

    today_groups.update(
        dtek_data.get(
            "today",
            {}
        ).get(
            "groups",
            {}
        )
    )

    tomorrow_groups.update(
        dtek_data.get(
            "tomorrow",
            {}
        ).get(
            "groups",
            {}
        )
    )

    today_groups.update(
        yasno_data.get(
            "today",
            {}
        )
    )

    tomorrow_groups.update(
        yasno_data.get(
            "tomorrow",
            {}
        )
    )

    # Додаємо порожні групи,
    # щоб JSON завжди мав всі 12

    for group in ALL_GROUPS:

        if group not in today_groups:

            today_groups[group] = []

        if group not in tomorrow_groups:

            tomorrow_groups[group] = []

    # --------------------------------------------------------
    # РЕЗУЛЬТАТ
    # --------------------------------------------------------

    result = {

        "timezone": "Europe/Kyiv",

        "updated": now.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "source": (
            "dtek-dnem.com.ua + "
            "yasno.com.ua"
        ),

        "emergency": dtek_data.get(
            "emergency"
        ),

        "announcement": dtek_data.get(
            "announcement"
        ),

        "today": {

            "date": today,

            "groups": today_groups
        },

        "tomorrow": {

            "date": tomorrow,

            "groups": tomorrow_groups
        }
    }

    # --------------------------------------------------------
    # СОХРАНЕНИЕ
    # --------------------------------------------------------

    with open(
        SCHEDULE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 60)
    print(
        f"💾 Збережено: {SCHEDULE_FILE}"
    )
    print("=" * 60)

    print()
    print("📊 РЕЗУЛЬТАТ")

    for group in ALL_GROUPS:

        today = today_groups[group]
        tomorrow = tomorrow_groups[group]

        print(
            f"{group}: "
            f"сьогодні={today or 'немає'} | "
            f"завтра={tomorrow or 'немає'}"
        )

    print()
    print("✅ PARSER FINISHED")


if __name__ == "__main__":
    main()
