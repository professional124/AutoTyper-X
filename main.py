import os
import time
import random
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException
from dotenv import load_dotenv
const port = process.env.PORT || 4000 

# Load environment variables
load_dotenv()
USERNAME = os.getenv("NITROTYPE_USER")
PASSWORD = os.getenv("NITROTYPE_PASS")
AVG_WPM = int(os.getenv("AVG_WPM", 90))
MIN_ACC = int(os.getenv("MIN_ACC", 95))
TOTAL_RACES = int(os.getenv("TOTAL_RACES", 50))
CAPSOLVER_KEY = os.getenv("CAPSOLVER_KEY")
PROXIES_FILE = "proxies.txt"

# Setup logs directory and logging
os.makedirs("logs", exist_ok=True)
log_filename = f"logs/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
logging.basicConfig(
    filename=log_filename,
    filemode='w',
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
)
console = logging.getLogger()
console.setLevel(logging.INFO)

# Load proxies
def load_proxies():
    if os.path.exists(PROXIES_FILE):
        with open(PROXIES_FILE) as f:
            return [line.strip() for line in f if line.strip()]
    return []

proxies = load_proxies()
proxy_index = 0

def get_proxy():
    global proxy_index
    if proxies:
        proxy = proxies[proxy_index % len(proxies)]
        proxy_index += 1
        logging.info(f"Using proxy: {proxy}")
        return proxy
    return None

def setup_driver(proxy=None):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if proxy:
        options.add_argument(f'--proxy-server=http://{proxy}')
    driver = webdriver.Chrome(options=options)
    driver.set_window_size(1200, 800)
    return driver

def login(driver):
    driver.get("https://www.nitrotype.com/login")
    time.sleep(3)
    try:
        driver.find_element(By.NAME, "username").send_keys(USERNAME)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD + Keys.RETURN)
        time.sleep(5)
        if "race" in driver.current_url:
            logging.info(f"Successfully logged in as {USERNAME}")
            return True
        else:
            logging.warning("Login failed, URL did not redirect to race.")
            return False
    except Exception as e:
        logging.error(f"Login error: {e}")
        return False

def solve_captcha():
    # Placeholder for CAPTCHA solving
    logging.warning("CAPTCHA solving required — implement capsolver logic here.")
    return True

def click_random_sticker(driver):
    try:
        sticker_buttons = driver.find_elements(By.CSS_SELECTOR, '[class*=Sticker]')
        if sticker_buttons:
            random.choice(sticker_buttons).click()
            logging.info("🎯 Sticker clicked!")
    except Exception:
        pass

def run_race(driver, race_number):
    try:
        driver.get("https://www.nitrotype.com/race")
        time.sleep(4)
        logging.info(f"Race #{race_number} started")
        race_text = "This is sample race text used for testing"
        wpm = AVG_WPM + random.randint(-5, 5)
        acc = MIN_ACC + random.randint(-2, 2)

        for word in race_text.split():
            if random.randint(1, 100) <= acc:
                for char in word:
                    driver.find_element(By.TAG_NAME, "body").send_keys(char)
                    time.sleep(random.uniform(60/wpm/5, 60/wpm/2))
            else:
                driver.find_element(By.TAG_NAME, "body").send_keys("x")
            driver.find_element(By.TAG_NAME, "body").send_keys(" ")

        click_random_sticker(driver)
        time.sleep(5)
        logging.info(f"Race #{race_number} completed — WPM: {wpm}, Accuracy: {acc}%")
        return True
    except Exception as e:
        logging.error(f"Error during race #{race_number}: {e}")
        return False

def main():
    races_done = 0
    retry_attempts = 0
    while races_done < TOTAL_RACES:
        proxy = get_proxy()
        try:
            driver = setup_driver(proxy)
            success = login(driver)

            if not success:
                retry_attempts += 1
                driver.quit()
                if retry_attempts >= 3:
                    logging.critical("❌ Login failed 3 times — exiting.")
                    break
                continue

            for i in range(TOTAL_RACES):
                if i > 0 and i % 50 == 0:
                    logging.info("CAPTCHA likely after 50 races, solving...")
                    if not solve_captcha():
                        logging.critical("Failed to solve CAPTCHA")
                        break
                if run_race(driver, i + 1):
                    races_done += 1
                else:
                    logging.warning(f"Race #{i + 1} failed — retrying")
                time.sleep(random.randint(3, 8))

            logging.info("🎉 All races completed successfully!")
            driver.quit()
            break

        except WebDriverException as we:
            logging.error(f"WebDriver error: {we}")
            continue
        except Exception as e:
            logging.critical(f"Fatal error: {e}")
            break
        finally:
            try:
                driver.quit()
            except:
                pass

if __name__ == "__main__":
    main()
