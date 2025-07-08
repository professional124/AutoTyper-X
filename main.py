# main.py
"""
AutoTyper-Z v1.1 - Full NitroType bot with proxy rotation, CAPTCHA solving, and stickers
Usage:
- put your proxies in proxies.txt (one per line, format: http://user:pass@ip:port or ip:port)
- set env vars in .env:
    CAPSOLVER_KEY=your_capsolver_api_key
    NITROTYPE_USER=your_username
    NITROTYPE_PASS=your_password
    AVG_WPM=90
    MIN_ACC=95
    TOTAL_RACES=10
- install dependencies: pip install undetected-chromedriver selenium requests python-dotenv
- run: python main.py
"""

import os
import time
import random
import traceback
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
import undetected_chromedriver.v2 as uc
from dotenv import load_dotenv

load_dotenv()

CAPSOLVER_KEY = os.getenv("CAPSOLVER_KEY")
PROXIES_FILE = "proxies.txt"
NITROTYPE_USER = os.getenv("NITROTYPE_USER")
NITROTYPE_PASS = os.getenv("NITROTYPE_PASS")
AVG_WPM = int(os.getenv("AVG_WPM", "90"))
MIN_ACC = int(os.getenv("MIN_ACC", "95"))
TOTAL_RACES = int(os.getenv("TOTAL_RACES", "10"))

CAPSOLVER_API_IN = "https://api.capsolver.com/in"
CAPSOLVER_API_RES = "https://api.capsolver.com/res"

class AutoTyperZ:
    def __init__(self, username, password, avg_wpm=90, min_acc=95, total_races=10, proxies_file=PROXIES_FILE):
        self.username = username
        self.password = password
        self.avg_wpm = avg_wpm
        self.min_acc = min_acc
        self.total_races = total_races
        self.driver = None
        self.running = False
        self.proxies = self.load_proxies(proxies_file)
        self.current_proxy_index = 0

    def load_proxies(self, filename):
        proxies = []
        try:
            with open(filename, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        proxies.append(line)
            print(f"[+] Loaded {len(proxies)} proxies from {filename}")
        except FileNotFoundError:
            print(f"[-] Proxy file {filename} not found. Continuing without proxies.")
        return proxies

    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy

    def _setup_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        options = Options()
        options.headless = True
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--mute-audio")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        proxy = self.get_next_proxy()
        if proxy:
            print(f"[+] Using proxy: {proxy}")
            options.add_argument(f'--proxy-server={proxy}')
        else:
            print("[*] No proxy used for this session")

        self.driver = uc.Chrome(options=options)
        self.driver.set_page_load_timeout(60)

    def _solve_captcha(self):
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
            r = requests.post(CAPSOLVER_API_IN, json=payload)
            if r.status_code != 200:
                print("[-] Capsolver task submission failed:", r.text)
                return False
            task_id = r.json().get("taskId")
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
                    self.driver.execute_script(f'document.getElementById("g-recaptcha-response").innerHTML="{token}";')
                    self.driver.execute_script(f'___grecaptcha_cfg.clients[0].callback("{token}");')
                    print("[+] CAPTCHA solved and submitted.")
                    return True
            print("[-] CAPTCHA solving timed out.")
            return False
        except Exception as e:
            print("[!] Exception during captcha solve:", e)
            traceback.print_exc()
            return False

    def _random_sticker_click(self):
        try:
            stickers = self.driver.find_elements(By.CSS_SELECTOR, ".sticker-button, .sticker-item, .sticker")
            if not stickers:
                return
            sticker = random.choice(stickers)
            sticker.click()
            print("[+] Sticker clicked during race.")
        except Exception:
            pass

    def _human_typing_delay(self, wpm):
        return 60 / (wpm * 5)

    def _type_text(self, text):
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
        return paragraph

    def _wait_for_race_finish(self):
        print("[*] Waiting for race to finish...")
        timeout = time.time() + 20
        while time.time() < timeout:
            try:
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
        race_num = 0
        try:
            while race_num < self.total_races:
                print(f"[+] Starting race {race_num + 1}/{self.total_races}...")
                self._setup_driver()
                self.login()
                self.driver.get("https://www.nitrotype.com/race")
                time.sleep(5)

                if not self._check_for_captcha_during_race():
                    print("[-] Failed to solve captcha during race.")
                    self.driver.quit()
                    continue

                race_text = self._wait_for_race_text()
                if not race_text:
                    print("[-] Race text not found, skipping...")
                    self.driver.quit()
                    continue

                print(f"[+] Typing text (first 50 chars): {race_text[:50]}...")
                self._type_text(race_text)

                if random.random() < 0.3:
                    self._random_sticker_click()

                if not self._wait_for_race_finish():
                    print("[-] Race did not finish in expected time, retrying...")
                    self.driver.quit()
                    continue

                race_num += 1
                self.driver.quit()

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
    run_bot(
        username=NITROTYPE_USER,
        password=NITROTYPE_PASS,
        avg_wpm=AVG_WPM,
        min_acc=MIN_ACC,
        total_races=TOTAL_RACES,
    )
