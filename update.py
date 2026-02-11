#!/usr/bin/env python3
"""
DTEK Schedule Parser - Simplified version
"""

import os
import json
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ═══════════════════════════════════════════════════════════════════════════════
# КОНФІГУРАЦІЯ
# ═══════════════════════════════════════════════════════════════════════════════

DTEK_URL = "https://www.dtek-dnem.com.ua/ua/shutdowns"
CITY = "м. Дніпро"
SCHEDULE_FILE = os.getenv("SCHEDULE_FILE", "schedule.json")

GROUP_ADDRESSES = {
    "1.1": "пров. Парковий",
    "1.2": "вул. Мохова",
    "3.1": "вул. Центральна",
    "3.2": "вул. Холодильна",
    "5.1": "пров. Морський",
    "5.2": "вул. Автодорожна",
}


def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def slots_to_intervals(slots):
    """48 слотів → інтервали"""
    if not any(slots):
        return []
    intervals = []
    i = 0
    while i < 48:
        if slots[i]:
            start = i
            while i < 48 and slots[i]:
                i += 1
            end = i
            sh, sm = divmod(start * 30, 60)
            eh, em = divmod(end * 30, 60)
            intervals.append(f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}")
        else:
            i += 1
    return intervals


def fill_form_and_get_schedule(driver, street):
    """Заповнює форму і отримує графік через JavaScript"""
    
    js_code = f"""
    return new Promise((resolve) => {{
        // Закриваємо popup
        var closeBtn = document.querySelector('.modal__close, .m-attention__close');
        if (closeBtn) closeBtn.click();
        
        setTimeout(() => {{
            var form = document.querySelector('.discon-schedule-form');
            if (!form) {{ resolve({{error: 'Form not found'}}); return; }}
            
            var cityInput = form.querySelector('#city');
            var streetInput = form.querySelector('#street');
            
            // Симулюємо введення міста посимвольно
            cityInput.focus();
            var cityText = '{CITY}';
            var cityIndex = 0;
            
            function typeCity() {{
                if (cityIndex < cityText.length) {{
                    cityInput.value += cityText[cityIndex];
                    cityInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                    cityInput.dispatchEvent(new KeyboardEvent('keyup', {{key: cityText[cityIndex], bubbles: true}}));
                    cityIndex++;
                    setTimeout(typeCity, 50);
                }} else {{
                    // Після введення міста - чекаємо і клікаємо на автодоповнення
                    setTimeout(() => {{
                        var cityItems = document.querySelectorAll('#cityautocomplete-list div, .autocomplete-items div');
                        console.log('City autocomplete items:', cityItems.length);
                        if (cityItems.length > 0) {{
                            cityItems[0].click();
                        }}
                        
                        setTimeout(() => {{
                            // Вводимо вулицю
                            streetInput.disabled = false;
                            streetInput.focus();
                            var streetText = '{street}';
                            var streetIndex = 0;
                            
                            function typeStreet() {{
                                if (streetIndex < streetText.length) {{
                                    streetInput.value += streetText[streetIndex];
                                    streetInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                                    streetInput.dispatchEvent(new KeyboardEvent('keyup', {{key: streetText[streetIndex], bubbles: true}}));
                                    streetIndex++;
                                    setTimeout(typeStreet, 50);
                                }} else {{
                                    setTimeout(() => {{
                                        var streetItems = document.querySelectorAll('#streetautocomplete-list div, .autocomplete-items div');
                                        console.log('Street autocomplete items:', streetItems.length);
                                        if (streetItems.length > 0) {{
                                            streetItems[0].click();
                                        }}
                                        
                                        setTimeout(() => {{
                                            // Вводимо будинок
                                            var houseInput = form.querySelector('#house_num');
                                            if (houseInput) {{
                                                houseInput.disabled = false;
                                                houseInput.focus();
                                                houseInput.value = '1';
                                                houseInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                                                
                                                setTimeout(() => {{
                                                    var houseItems = document.querySelectorAll('#house_numautocomplete-list div, .autocomplete-items div');
                                                    if (houseItems.length > 0) houseItems[0].click();
                                                    
                                                    setTimeout(finishAndGetSchedule, 3000);
                                                }}, 1500);
                                            }} else {{
                                                setTimeout(finishAndGetSchedule, 3000);
                                            }}
                                        }}, 2000);
                                    }}, 1500);
                                }}
                            }}
                            typeStreet();
                        }}, 2000);
                    }}, 1500);
                }}
            }}
            
            var finishAndGetSchedule = function() {{
                var tables = document.querySelectorAll('table');
                var result = {{tables: tables.length, slots: [], debug: ''}};
                
                for (var t of tables) {{
                    var html = t.outerHTML;
                    if (!html.includes('head-time') && !html.includes('Понеділок')) {{
                        result.debug = 'Found schedule table';
                        var cells = t.querySelectorAll('tbody td[class*="cell-"]');
                        for (var i = 0; i < cells.length && i < 24; i++) {{
                            var cls = cells[i].className;
                            var first = cls.includes('cell-scheduled') && !cls.includes('maybe');
                            var second = first;
                            if (cls.includes('cell-first-half')) {{ first = true; second = false; }}
                            if (cls.includes('cell-second-half')) {{ first = false; second = true; }}
                            result.slots.push(first);
                            result.slots.push(second);
                        }}
                        break;
                    }}
                }}
                
                if (result.slots.length === 0) {{
                    result.debug = 'No schedule table, tables: ' + tables.length;
                    // Додаємо інфо про форму
                    var city = document.querySelector('#city');
                    var street = document.querySelector('#street');
                    result.debug += ', city=' + (city ? city.value : 'null');
                    result.debug += ', street=' + (street ? street.value : 'null');
                }}
                
                resolve(result);
            }};
            
            typeCity();
        }}, 1500);
    }});
    """
    
    try:
        result = driver.execute_script(js_code)
        return result
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("🚀 DTEK Schedule Parser")
    print("=" * 60)
    
    now = datetime.now()
    today = now.strftime("%d.%m.%Y")
    tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")
    
    print(f"\n📅 Сьогодні: {today}")
    print(f"📅 Завтра: {tomorrow}")
    print(f"📋 Груп: {len(GROUP_ADDRESSES)}\n")
    
    result = {
        "timezone": "Europe/Kyiv",
        "updated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "dtek-dnem.com.ua",
        "emergency": None,
        "today": {"date": today, "groups": {}},
        "tomorrow": {"date": tomorrow, "groups": {}}
    }
    
    driver = None
    
    try:
        driver = setup_driver()
        
        for group, street in GROUP_ADDRESSES.items():
            print(f"📍 Група {group}: {street}...")
            
            driver.get(DTEK_URL)
            time.sleep(3)
            
            # Заповнюємо форму через JavaScript
            js_result = fill_form_and_get_schedule(driver, street)
            
            if "error" in js_result:
                print(f"    ❌ Error: {js_result['error']}")
                continue
            
            print(f"    🔍 Tables: {js_result.get('tables', 0)}, Slots: {len(js_result.get('slots', []))}, Debug: {js_result.get('debug', '')}")
            
            # Зберігаємо скріншот для дебагу (тільки перший раз)
            if group == "1.1":
                try:
                    driver.save_screenshot("debug_page.png")
                    with open("debug_page.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    print(f"    📸 Debug saved")
                except:
                    pass
            
            slots = js_result.get("slots", [])
            if slots:
                while len(slots) < 48:
                    slots.append(False)
                
                intervals = slots_to_intervals(slots)
                if intervals:
                    result["today"]["groups"][group] = intervals
                    total_mins = sum(slots[:48]) * 30
                    print(f"    ✅ {intervals} ({total_mins // 60}год {total_mins % 60:02d}хв)")
                else:
                    print(f"    ✅ Відключень немає")
            else:
                print(f"    ⚠️ No slots data")
        
        # Зберігаємо результат
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 Збережено: {SCHEDULE_FILE}")
        
        print("\n" + "=" * 60)
        print("📊 ПІДСУМОК:")
        print(f"  Сьогодні: {len(result['today']['groups'])} груп")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            driver.quit()
            print("\n👋 Браузер закрито")


if __name__ == "__main__":
    main()
