import os
import sys
import random
import threading
import logging
import time
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from fake_useragent import UserAgent
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys

# -----------------------------------------------------------------------------
#  ENVIRONMENT & CONFIG
# -----------------------------------------------------------------------------
load_dotenv()
API_TOKEN    = os.getenv("API_TOKEN")              # Your secret API key
ADMIN_TOKEN  = os.getenv("ADMIN_TOKEN", API_TOKEN) # Optional separate admin key
PROXY_FILE   = "proxies.txt"                       # Must exist with ip:port lines
CHROME_BIN   = os.getenv("CHROME_BIN", "/usr/bin/chromium")
DRIVER_BIN   = os.getenv("DRIVER_BIN", "/usr/bin/chromedriver")

# -----------------------------------------------------------------------------
#  STATE TRACKERS (IN-MEMORY)
# -----------------------------------------------------------------------------
tasks        = []   # [ {owner: str, tasks: [username,…]}, … ]
race_tracker = []   # [ {owner: str, username: str, races: int}, … ]

# -----------------------------------------------------------------------------
#  LOGGING SETUP (file + stdout for Render)
# -----------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
logfile = f"logs/{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

# Remove default handlers, then log to file and console
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(logfile),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -----------------------------------------------------------------------------
#  FLASK APP (serving root + API)
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
    """Serve the frontend index.html"""
    return send_from_directory(os.getcwd(), "index.html")

# -----------------------------------------------------------------------------
#  HTTP API ENDPOINTS
# -----------------------------------------------------------------------------
@app.route("/racer", methods=["POST"])
@require_token
def http_racer():
    data     = request.get_json() or {}
    owner    = data.get("owner", "default")
    username = data.get("username")
    password = data.get("password")
    wpm      = int(data.get("wpm", 60))
    races    = int(data.get("race_amount", data.get("races", 10)))
    min_acc  = int(data.get("min_accuracy", data.get("min_acc", 90)))

    # Validation
    if not username or not password:
        return jsonify(error="username & password required"), 400
    if races < 1 or races > 5000:
        return jsonify(error="race_amount must be 1–5000"), 400
    if wpm < 30 or wpm > 170:
        return jsonify(error="wpm must be 30–170"), 400
    if min_acc < 0 or min_acc > 100:
        return jsonify(error="min_accuracy must be 0–100"), 400

    proxy = _get_proxy()
    try:
        t = threading.Thread(
            target=_main_module,
            args=(owner, username, password, wpm, races, min_acc, proxy),
            daemon=True
        )
        t.start()
        logger.info(f"Racer thread launched for {username}@{owner} ✔️")
    except Exception as e:
        logger.error(f"Failed to launch racer for {username}@{owner} ❌: {e}")
        return jsonify(error="internal error"), 500

    # Track active task
    rec = next((t for t in tasks if t["owner"] == owner), None)
    if not rec:
        rec = {"owner": owner, "tasks": []}
        tasks.append(rec)
    rec["tasks"].append(username.lower())

    return jsonify(
        status="started",
        owner=owner,
        username=username,
        wpm=wpm,
        race_amount=races,
        min_accuracy=min_acc
    ), 200

@app.route("/stopracer", methods=["POST"])
@require_token
def http_stopracer():
    data     = request.get_json() or {}
    owner    = data.get("owner", "default")
    username = data.get("username", "").lower()
    rec = next((t for t in tasks if t["owner"] == owner), None)
    if rec and username in rec["tasks"]:
        rec["tasks"].remove(username)
        return jsonify(status="stopped", owner=owner, username=username), 200
    return jsonify(error="task not found"), 404

@app.route("/stopall", methods=["POST"])
@require_token
def http_stopall():
    data  = request.get_json() or {}
    owner = data.get("owner", "default")
    rec = next((t for t in tasks if t["owner"] == owner), None)
    if rec:
        rec["tasks"].clear()
    return jsonify(status="stopped_all", owner=owner), 200

@app.route("/tasks", methods=["GET"])
@require_token
def http_tasks():
    owner = request.args.get("owner", "default")
    rec = next((t for t in tasks if t["owner"] == owner), None)
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
    summary = []
    total   = 0
    for r in race_tracker:
        summary.append({
            "owner":    r["owner"],
            "username": r["username"],
            "races":    r["races"]
        })
        total += r["races"]
    return jsonify(total_races=total, results=summary), 200

@app.route("/admintasks", methods=["GET"])
@require_token
def http_admintasks():
    target = request.args.get("target_owner", "")
    rec    = next((t for t in tasks if t["owner"] == target), None)
    if rec:
        return jsonify(owner=target, tasks=rec["tasks"]), 200
    return jsonify(error="no tasks"), 404

@app.route("/adminstopall", methods=["POST"])
@require_token
def http_adminstopall():
    data   = request.get_json() or {}
    target = data.get("target_owner", "")
    rec    = next((t for t in tasks if t["owner"] == target), None)
    if rec:
        rec["tasks"].clear()
        return jsonify(status="cleared", owner=target), 200
    return jsonify(error="no tasks"), 404

# -----------------------------------------------------------------------------
#  SELENIUM & NITROTYPE LOGIC
# -----------------------------------------------------------------------------
def _get_proxy() -> str:
    """Pick a random proxy or return None."""
    try:
        with open(PROXY_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]
        return random.choice(lines) if lines else None
    except:
        return None

def _record_success(owner: str, username: str):
    """Increment completed race count."""
    uname = username.lower()
    rec = next((r for r in race_tracker
                if r["owner"] == owner and r["username"] == uname), None)
    if rec:
        rec["races"] += 1
    else:
        race_tracker.append({"owner": owner, "username": uname, "races": 1})

def _setup_driver(proxy: str = None):
    opts = Options()
    opts.headless        = True
    opts.binary_location = CHROME_BIN
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")
    svc    = Service(DRIVER_BIN)
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_window_size(1200, 800)
    return driver

def _login(driver, username: str, password: str) -> bool:
    driver.get("https://www.nitrotype.com/login")
    time.sleep(2)
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
    time.sleep(4)
    ok = "race" in driver.current_url or "garage" in driver.current_url
    if ok:
        logger.info(f"[{username}] login OK ✔️")
    else:
        logger.error(f"[{username}] login FAIL ❌")
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
    try:
        box = driver.find_element(By.CSS_SELECTOR, "[contenteditable='true']")
    except:
        box = driver.find_element(By.TAG_NAME, "body")

    for w in text.split():
        if random.randint(1,100) <= acc:
            for ch in w:
                box.send_keys(ch)
                time.sleep(random.uniform(60/wpm/5, 60/wpm/2))
        else:
            box.send_keys("x")
        box.send_keys(" ")
    logger.debug(f"Race #{idx} done")
    return True

def _main_module(owner, username, password, wpm, races, acc, proxy):
    driver = None
    success_count = 0

    logger.info(f"[{username}] session start: {races} races @ {wpm}wpm, {acc}% acc, proxy={proxy}")

    try:
        driver = _setup_driver(proxy)
        if not _login(driver, username, password):
            return

        for i in range(1, races+1):
            if _run_race(driver, i, wpm, acc):
                _record_success(owner, username)
                success_count += 1
            time.sleep(random.randint(3, 8))

        if success_count == races:
            logger.info(f"[{username}] all {races} races completed ✔️")
        else:
            logger.warning(f"[{username}] completed {success_count}/{races} races ❗")

    except Exception as e:
        logger.error(f"[{username}] session error ❌: {e}")
    finally:
        if driver:
            driver.quit()

# -----------------------------------------------------------------------------
#  RUN FLASK APP
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        debug=False
    )
