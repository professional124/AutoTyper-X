import os
import sys
import random
import threading
import logging
import time
import tempfile
import shutil
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# webdriver-manager
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------------------------------------------------------
#  ENVIRONMENT & CONFIG
# -----------------------------------------------------------------------------
load_dotenv()
API_TOKEN   = os.getenv("API_TOKEN")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", API_TOKEN)
PROXY_FILE  = "proxies.txt"
CHROME_BIN  = os.getenv("CHROME_BIN", "/usr/bin/chromium")

# -----------------------------------------------------------------------------
#  STATE TRACKERS (IN-MEMORY)
# -----------------------------------------------------------------------------
tasks        = []  # [ {owner, tasks:[username,...]}, ... ]
race_tracker = []  # [ {owner, username, races}, ... ]

# -----------------------------------------------------------------------------
#  LOGGING (file + stdout)
# -----------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
logfile = f"logs/{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(logfile),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

# -----------------------------------------------------------------------------
#  FLASK SETUP
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=".", static_url_path="")

def require_token(fn):
    def wrapper(*args, **kwargs):
        token = request.args.get("token", "")
        if token != API_TOKEN:
            return jsonify(error="Unauthorized"), 401
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(os.getcwd(), "index.html")

# -----------------------------------------------------------------------------
#  API ENDPOINTS
# -----------------------------------------------------------------------------
@app.route("/racer", methods=["POST"])
@require_token
def http_racer():
    data     = request.get_json() or {}
    owner    = data.get("owner", "default")
    user     = data.get("username")
    pw       = data.get("password")
    wpm      = int(data.get("wpm", 60))
    races    = int(data.get("race_amount", data.get("races", 10)))
    acc      = int(data.get("min_accuracy", data.get("min_acc", 90)))

    if not user or not pw:
        return jsonify(error="username & password required"), 400

    # Kick off thread
    proxy = _get_proxy()
    try:
        t = threading.Thread(
            target=_main_module,
            args=(owner, user, pw, wpm, races, acc, proxy),
            daemon=True
        )
        t.start()
        logger.info(f"Racer thread launched for {user}@{owner} ✔️")
    except Exception as e:
        logger.error(f"Failed to launch racer for {user}@{owner} ❌: {e}")
        return jsonify(error="internal error"), 500

    # Track active job
    rec = next((r for r in tasks if r["owner"] == owner), None)
    if not rec:
        rec = {"owner": owner, "tasks": []}
        tasks.append(rec)
    rec["tasks"].append(user.lower())

    return jsonify(
        status="started",
        owner=owner,
        username=user,
        wpm=wpm,
        race_amount=races,
        min_accuracy=acc
    ), 200

@app.route("/stopracer", methods=["POST"])
@require_token
def http_stopracer():
    data     = request.get_json() or {}
    owner    = data.get("owner", "default")
    user     = data.get("username", "").lower()
    rec = next((r for r in tasks if r["owner"] == owner), None)
    if rec and user in rec["tasks"]:
        rec["tasks"].remove(user)
        return jsonify(status="stopped", owner=owner, username=user), 200
    return jsonify(error="task not found"), 404

@app.route("/stopall", methods=["POST"])
@require_token
def http_stopall():
    owner = request.get_json().get("owner", "default")
    rec   = next((r for r in tasks if r["owner"] == owner), None)
    if rec:
        rec["tasks"].clear()
    return jsonify(status="stopped_all", owner=owner), 200

@app.route("/tasks", methods=["GET"])
@require_token
def http_tasks():
    owner = request.args.get("owner", "default")
    rec   = next((r for r in tasks if r["owner"] == owner), None)
    return jsonify(owner=owner, tasks=rec["tasks"] if rec else []), 200

@app.route("/tracker", methods=["GET"])
@require_token
def http_tracker():
    owner    = request.args.get("owner", "default")
    username = request.args.get("username", "").lower()
    rec = next((r for r in race_tracker
                if r["owner"] == owner and r["username"] == username), None)
    if rec:
        return jsonify(owner=owner, username=username, races=rec["races"]), 200
    return jsonify(error="no data"), 404

@app.route("/stats", methods=["GET"])
@require_token
def http_stats():
    total = sum(r["races"] for r in race_tracker)
    return jsonify(total_races=total, results=race_tracker), 200

@app.route("/admintasks", methods=["GET"])
@require_token
def http_admintasks():
    target = request.args.get("target_owner", "")
    rec    = next((r for r in tasks if r["owner"] == target), None)
    if rec:
        return jsonify(owner=target, tasks=rec["tasks"]), 200
    return jsonify(error="no tasks"), 404

@app.route("/adminstopall", methods=["POST"])
@require_token
def http_adminstopall():
    target = request.get_json().get("target_owner", "")
    rec    = next((r for r in tasks if r["owner"] == target), None)
    if rec:
        rec["tasks"].clear()
        return jsonify(status="cleared", owner=target), 200
    return jsonify(error="no tasks"), 404

# -----------------------------------------------------------------------------
#  SELENIUM & NITROTYPE LOGIC
# -----------------------------------------------------------------------------
def _get_proxy() -> str:
    try:
        lines = [l.strip() for l in open(PROXY_FILE) if l.strip()]
        return random.choice(lines) if lines else None
    except:
        return None

def _record_success(owner: str, username: str):
    uname = username.lower()
    rec = next((r for r in race_tracker
                if r["owner"] == owner and r["username"] == uname), None)
    if rec:
        rec["races"] += 1
    else:
        race_tracker.append({"owner": owner, "username": uname, "races": 1})

def _setup_driver(proxy: str = None):
    """
    Each session gets a fresh ChromeDriver via webdriver-manager
    and a unique user-data-dir for profile isolation.
    """
    # new Options() per call
    opts = Options()
    opts.binary_location = CHROME_BIN
    # use new headless mode for Chrome 109+
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")

    # unique profile dir
    profile_dir = tempfile.mkdtemp(prefix="selenium-profile-")
    opts.add_argument(f"--user-data-dir={profile_dir}")
    logger.info(f"Using profile dir: {profile_dir}")

    # let webdriver-manager install and start the matching driver
    driver = webdriver.Chrome(
        executable_path=ChromeDriverManager().install(),
        options=opts
    )
    driver.set_window_size(1200, 800)
    return driver, profile_dir

def _login(driver, user: str, pw: str) -> bool:
    driver.get("https://www.nitrotype.com/login")
    time.sleep(2)
    driver.find_element(By.NAME, "username").send_keys(user)
    driver.find_element(By.NAME, "password").send_keys(pw)
    driver.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
    time.sleep(4)
    ok = any(x in driver.current_url for x in ("race", "garage"))
    logger.info(f"[{user}] login {'OK ✔️' if ok else 'FAIL ❌'}")
    return ok

def _get_race_text(driver) -> str:
    for _ in range(20):
        try:
            el = driver.find_element(By.CSS_SELECTOR, "[data-test='race-word']")
            if el.text:
                break
        except:
            time.sleep(0.3)
    words = driver.find_elements(By.CSS_SELECTOR, "[data-test='race-word']")
    return " ".join(w.text for w in words if w.text)

def _run_race(driver, idx: int, wpm: int, acc: int) -> bool:
    driver.get("https://www.nitrotype.com/race")
    time.sleep(3)
    text = _get_race_text(driver)
    if not text:
        logger.warning(f"Race #{idx}: no text ❗")
        return False

    # find the typing box
    inputs = driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
    box = inputs[0] if inputs else driver.find_element(By.TAG_NAME, "body")

    for w in text.split():
        if random.randint(1, 100) <= acc:
            for ch in w:
                box.send_keys(ch)
                time.sleep(random.uniform(60 / wpm / 5, 60 / wpm / 2))
        else:
            box.send_keys("x")
        box.send_keys(" ")
    logger.debug(f"Race #{idx} done")
    return True

def _main_module(owner, user, pw, wpm, races, acc, proxy):
    driver = profile_dir = None
    success = 0
    logger.info(f"[{user}] session start: {races} races @ {wpm}wpm, {acc}% acc, proxy={proxy}")

    try:
        driver, profile_dir = _setup_driver(proxy)
        if not _login(driver, user, pw):
            return

        for i in range(1, races + 1):
            if _run_race(driver, i, wpm, acc):
                _record_success(owner, user)
                success += 1
            time.sleep(random.randint(3, 8))

        if success == races:
            logger.info(f"[{user}] completed all {races} races ✔️")
        else:
            logger.warning(f"[{user}] completed {success}/{races} races ❗")

    except Exception as e:
        logger.error(f"[{user}] session error ❌: {e}")
    finally:
        if driver:
            driver.quit()
        if profile_dir:
            shutil.rmtree(profile_dir, ignore_errors=True)

# -----------------------------------------------------------------------------
#  RUN SERVER
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        debug=False
    )
