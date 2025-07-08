# auto_typer_z.py
"""
AutoTyper-Z v1.0 - Powerful NitroType bot script
Features:
- Headless undetected chromedriver with stealth
- NitroType login and multi-race automation
- Configurable avg WPM & accuracy
- Random sticker claiming during races
- CAPTCHA solving via Capsolver API (CAPSOLVER_KEY env var)
- Proxy support hooks
- Graceful error handling and retries

Required packages:
pip install undetected-chromedriver selenium requests python-dotenv

Usage:
- Put CAPSOLVER_KEY=your_key in .env
- Optionally set PROXY=http://user:pass@ip:port in .env
- Run with python auto_typer_z.py
"""

import os
import time
import random
import json
import traceback
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
import undetected_chromedriver.v2 as uc
from dotenv import load_dotenv

load_dotenv()  # load env vars from .env

CAPSOLVER_KEY = os.getenv("CAPSOLVER_KEY")
PROXY = os.getenv("PROXY")  # optional

# Capsolver API constants
CAPSOLVER_API_IN = "https://api.capsolver.com/in"
CAPSOLVER_API_RES = "https://api.capsolver.com/res"

class AutoTyperZ:
    def __init__(self, username, password, avg_wpm=90, min_acc=95, total_races=10):
        self.username = username
        self.password = password
        self.avg_wpm = avg_wpm
        self.min_acc = min_acc
        self.total_races = total_races
        self.driver = None
        self.running = False

    def _setup_driver(self):
        options = Options()
        options.headless = True
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--mute-audio")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        if PROXY:
            options.add_argument(f'--proxy-server={PROXY}')
        self.driver = uc.Chrome(options=options)
        self.driver.set_page_load_timeout(60)

    def _solve_captcha(self):
        """
        Detect captcha, submit sitekey to Capsolver and wait for solution.
        Inject solution to the page to bypass captcha.
        """
        print("[!] CAPTCHA detected, solving with Capsolver...")
        try:
            self.driver.switch_to.frame(self.driver.find_element(By.CSS_SELECTOR, "iframe[src*='captcha']"))
            sitekey = self.driver.execute_script("return document.querySelector('.g-recaptcha').getAttribute('data-sitekey');")
            page_url = self.driver.current_url
            payload = {
                "clientKey": CAPSOLVER_KEY,
                "task": {
                    "type": "NoCaptchaTaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey
                }
            }
            # Submit captcha task
            r = requests.post(CAPSOLVER_API_IN, json=payload)
            if r.status_code != 200:
                print("[-] Capsolver task submission failed:", r.text)
                return False
            task_id = r.json().get("taskId")
            # Poll for result
            for _ in range(60):
                time.sleep(5)
                r2 = requests.post(CAPSOLVER_API_RES, json={"clientKey": CAPSOLVER_KEY, "taskId": task_id})
                if r2.status_code != 200:
                    continue
                res = r2.json()
                if res.get("status") == "processing":
                    continue
                if res.get("status") == "ready":
                    token = res["solution"]["gRecaptchaResponse"]
                    # Inject token into page
                    self.driver.execute_script(f'document.getElementById("g-recaptcha-response").innerHTML="{token}";')
                    self.driver.execute_script('___grecaptcha_cfg.clients[0].callback("{0}");'.format(token))
                    print("[+] CAPTCHA solved and submitted.")
                    return True
            print("[-] CAPTCHA solving timed out.")
            return False
        except Exception as e:
            print("[!] Exception during captcha solve:", e)
            traceback.print_exc()
            return False

    def _random_sticker_click(self):
        """
        Randomly clicks on one available sticker during the race.
        Assumes stickers show as buttons or elements with a specific selector.
        """
        try:
            stickers = self.driver.find_elements(By.CSS_SELECTOR, ".sticker-button, .sticker-item, .sticker")
            if not stickers:
                return
            sticker = random.choice(stickers)
            sticker.click()
            print("[+] Sticker clicked during race.")
        except Exception:
            # Ignore failures to click sticker
            pass

    def _human_typing_delay(self, wpm):
        """
        Calculate delay between characters based on WPM.
        """
        return 60 / (wpm * 5)

    def _type_text(self, text):
        """
        Types text with realistic errors and corrections based on min accuracy.
        """
        textbox = self.driver.find_element(By.CLASS_NAME, "dash-input")
        actions = ActionChains(self.driver)
        total_chars = len(text)
        delay = self._human_typing_delay(self.avg_wpm)
        accuracy_threshold = int(total_chars * (self.min_acc / 100))
        error_chance = 1 - (self.min_acc / 100)

        for i, char in enumerate(text):
            if i < accuracy_threshold or random.random() > error_chance:
                actions.send_keys(char)
            else:
                wrong_char = random.choice("abcdefghijklmnopqrstuvwxyz")
                actions.send_keys(wrong_char)
                actions.send_keys(Keys.BACKSPACE)
                actions.send_keys(char)
            actions.pause(delay)
        actions.perform()

    def login(self):
        print("[+] Navigating to login page...")
        self.driver.get("https://www.nitrotype.com/login")
        time.sleep(3)
        print(f"[+] Logging in as {self.username}...")
        self.driver.find_element(By.NAME, "username").send_keys(self.username)
        self.driver.find_element(By.NAME, "password").send_keys(self.password + Keys.ENTER)
        time.sleep(5)
        # Check for captcha presence after login attempt
        if "captcha" in self.driver.page_source.lower():
            solved = self._solve_captcha()
            if not solved:
                raise Exception("CAPTCHA solve failed during login.")

    def _wait_for_race_text(self):
        paragraph = ""
        timeout = time.time() + 15
        while paragraph.strip() == "" and time.time() < timeout:
            try:
                paragraph = self.driver.find_element(By.CLASS_NAME, "dash-copy").text.strip()
            except Exception:
                time.sleep(1)
                continue
        return paragraph

    def _wait_for_race_finish(self):
        print("[*] Waiting for race to finish...")
        timeout = time.time() + 20
        while time.time() < timeout:
            try:
                # Detect race finish condition (e.g. scoreboard visible)
                finished = self.driver.find_element(By.CLASS_NAME, "finish-screen")
                if finished.is_displayed():
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _check_for_captcha_during_race(self):
        if "captcha" in self.driver.page_source.lower():
            print("[!] CAPTCHA detected during race!")
            return self._solve_captcha()
        return True

    def run(self):
        self.running = True
        try:
            self._setup_driver()
            self.login()
            race_num = 0

            while race_num < self.total_races:
                print(f"[+] Starting race {race_num + 1}/{self.total_races}...")
                self.driver.get("https://www.nitrotype.com/race")
                time.sleep(5)

                # Check for captcha
                if not self._check_for_captcha_during_race():
                    print("[-] Failed to solve captcha during race.")
                    break

                race_text = self._wait_for_race_text()
                if not race_text:
                    print("[-] Race text not found, skipping...")
                    continue

                print(f"[+] Typing text (first 50 chars): {race_text[:50]}...")
                self._type_text(race_text)

                # Random sticker click chance (~30%)
                if random.random() < 0.3:
                    self._random_sticker_click()

                # Wait for race to finish or timeout
                if not self._wait_for_race_finish():
                    print("[-] Race did not finish in expected time, retrying...")
                    continue

                race_num += 1

                # Capsolver recommends max 50 races before captcha trigger,
                # we rely on _check_for_captcha_during_race to solve when it happens.

            print("[+] All races completed successfully!")
        except Exception as e:
            print("[!] Error during bot run:", e)
            traceback.print_exc()
        finally:
            if self.driver:
                self.driver.quit()
            self.running = False

def run_bot(username, password, avg_wpm, min_acc, total_races):
    bot = AutoTyperZ(username, password, avg_wpm, min_acc, total_races)
    bot.run()

if __name__ == "__main__":
    # Example test run
    run_bot(
        username=os.getenv("NITROTYPE_USER", "your_username"),
        password=os.getenv("NITROTYPE_PASS", "your_password"),
        avg_wpm=int(os.getenv("AVG_WPM", "90")),
        min_acc=int(os.getenv("MIN_ACC", "95")),
        total_races=int(os.getenv("TOTAL_RACES", "10"))
    )
