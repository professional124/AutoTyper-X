#!/usr/bin/env python3
import os
import sys
import random
import threading
import logging
import time
import tempfile
import shutil
import subprocess
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Set, Tuple
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from fake_useragent import UserAgent

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------------------------------------------------------
# CONFIG & ENV
# -----------------------------------------------------------------------------
load_dotenv()
API_TOKEN   = os.getenv("API_TOKEN", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", API_TOKEN)
PROXY_FILE  = os.getenv("PROXY_FILE", "proxies.txt")
CHROME_BIN  = os.getenv("CHROME_BIN", "/usr/bin/chromium")
PORT        = int(os.getenv("PORT", "10000"))
MAX_THREADS = int(os.getenv("MAX_THREADS", "5"))

if not API_TOKEN:
    print("ERROR: API_TOKEN must be set in .env", file=sys.stderr)
    sys.exit(1)

# -----------------------------------------------------------------------------
# DATA MODELS & STATE (THREAD-SAFE)
# -----------------------------------------------------------------------------
@dataclass
class OwnerTasks:
    owner: str
    tasks: Set[str] = field(default_factory=set)

@dataclass
class RaceRecord:
    owner: str
    username: str
    races: int = 0

tasks_lock = threading.Lock()
tracker_lock = threading.Lock()

# maps owner → OwnerTasks
_tasks: Dict[str, OwnerTasks] = {}
# maps (owner, username) → RaceRecord
_record_map: Dict[Tuple[str,str], RaceRecord] = {}

# ThreadPool for handling racer threads
executor = ThreadPoolExecutor(max_workers=MAX_THREADS)

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
handler = RotatingFileHandler(
    filename=f"logs/{datetime.now():%Y-%m-%d}.log",
    maxBytes=5*1024*1024, backupCount=3
)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler, logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AutoTyperX")

# -----------------------------------------------------------------------------
# FLASK APP
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=".", static_url_path="")

def require_token(fn):
    def wrapper(*args, **kwargs):
        if request.args.get("token","") not in {API_TOKEN, ADMIN_TOKEN}:
            return jsonify(error="Unauthorized"), 401
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(os.getcwd(), "index.html")

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def _get_proxy() -> Optional[str]:
    try:
        lines = [l.strip() for l in open(PROXY_FILE) if l.strip()]
        return random.choice(lines) if lines else None
    except Exception as e:
        logger.warning(f"Proxy load error: {e}")
        return None

def _record_race(owner: str, username: str):
    key = (owner, username.lower())
    with tracker_lock:
        rec = _record_map.get(key)
        if not rec:
            rec = RaceRecord(owner, username.lower(), 1)
            _record_map[key] = rec
        else:
            rec.races += 1

def _get_chrome_version() -> Optional[str]:
    try:
        out = subprocess.check_output([CHROME_BIN, "--version"], stderr=subprocess.DEVNULL)
        # e.g. "Chromium 138.0.7204.157\n"
        return out.decode().strip().split(" ")[1]
    except Exception as e:
        logger.warning(f"Chrome version detect failed: {e}")
        return None

def _setup_driver(proxy: Optional[str]=None) -> Tuple[webdriver.Chrome,str]:
    chrome_ver = _get_chrome_version()
    mgr_kwargs = {"version": chrome_ver} if chrome_ver else {}
    temp_profile = None

    for attempt in range(1,4):
        opts = Options()
        opts.binary_location = CHROME_BIN
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        # random UA
        ua = UserAgent().random
        opts.add_argument(f"--user-agent={ua}")
        if proxy:
            opts.add_argument(f"--proxy-server=http://{proxy}")

        temp_profile = tempfile.mkdtemp(prefix="selenium-profile-")
        opts.add_argument(f"--user-data-dir={temp_profile}")
        logger.debug(f"[Setup] Attempt {attempt}, profile: {temp_profile}")

        try:
            driver_bin = ChromeDriverManager(**mgr_kwargs).install()
            service    = Service(executable_path=driver_bin)
            driver     = webdriver.Chrome(service=service, options=opts)
            driver.set_window_size(1200, 800)
            return driver, temp_profile
        except Exception as ex:
            logger.warning(f"[Setup] Attempt {attempt} failed: {ex}")
            if temp_profile:
                shutil.rmtree(temp_profile, ignore_errors=True)
            time.sleep(0.5)

    raise RuntimeError("Could not initialize ChromeDriver after 3 tries")

def _login(driver: webdriver.Chrome, user: str, pw: str) -> bool:
    driver.get("https://www.nitrotype.com/login")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.NAME, "username"))
    ).send_keys(user)
    driver.find_element(By.NAME, "password").send_keys(pw)
    driver.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
    # wait for redirect
    try:
        WebDriverWait(driver, 10).until(
            EC.url_contains("race")  # or "garage"
        )
        logger.info(f"[{user}] login OK ✔️")
        return True
    except:
        logger.error(f"[{user}] login FAIL ❌")
        return False

def _run_race(driver: webdriver.Chrome, index: int, wpm: int, acc: int) -> bool:
    driver.get("https://www.nitrotype.com/race")
    WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "[data-test='race-word']"))
    )
    words = driver.find_elements(By.CSS_SELECTOR, "[data-test='race-word']")
    text  = " ".join(w.text for w in words if w.text)
    if not text:
        logger.warning(f"Race #{index}: no text")
        return False

    box = driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
    box = box[0] if box else driver.find_element(By.TAG_NAME, "body")

    for word in text.split():
        if random.randint(1,100) <= acc:
            for ch in word:
                box.send_keys(ch)
                time.sleep(random.uniform(60/wpm/5, 60/wpm/2))
        else:
            box.send_keys("x")
        box.send_keys(" ")
    logger.debug(f"Race #{index} done")
    return True

def _cleanup(driver: webdriver.Chrome, profile_dir: str):
    try:
        driver.quit()
    except:
        pass
    shutil.rmtree(profile_dir, ignore_errors=True)

# -----------------------------------------------------------------------------
# CORE WORKER
# -----------------------------------------------------------------------------
def _main_module(owner: str, username: str, password: str,
                 wpm: int, races: int, acc: int, proxy: Optional[str]):
    logger.info(f"[{username}] start: {races} races @ {wpm}wpm, {acc}% acc, proxy={proxy}")
    driver = None
    profile_dir = None
    success = 0

    try:
        driver, profile_dir = _setup_driver(proxy)
        if not _login(driver, username, password):
            return

        for i in range(1, races+1):
            if _run_race(driver, i, wpm, acc):
                _record_race(owner, username)
                success += 1
            time.sleep(random.uniform(2,5))

        if success == races:
            logger.info(f"[{username}] completed all {races} races ✔️")
        else:
            logger.warning(f"[{username}] completed {success}/{races} races ❗")

    except Exception as ex:
        logger.error(f"[{username}] session error: {ex}")
    finally:
        if driver and profile_dir:
            _cleanup(driver, profile_dir)

# -----------------------------------------------------------------------------
# API ROUTES
# -----------------------------------------------------------------------------
@app.route("/racer", methods=["POST"])
@require_token
def route_racer():
    data     = request.get_json() or {}
    owner    = data.get("owner","default")
    username = data.get("username")
    password = data.get("password")
    wpm      = int(data.get("wpm",60))
    races    = int(data.get("race_amount", data.get("races",10)))
    acc      = int(data.get("min_accuracy", data.get("min_acc",90)))

    # input validation
    if not username or not password:
        return jsonify(error="username & password required"), 400
    if not (30 <= wpm <= 170):
        return jsonify(error="wpm must be 30–170"), 400
    if not (1 <= races <= 5000):
        return jsonify(error="race_amount must be 1–5000"), 400
    if not (0 <= acc <= 100):
        return jsonify(error="min_accuracy must be 0–100"), 400

    proxy = _get_proxy()
    # record task
    with tasks_lock:
        ot = _tasks.setdefault(owner, OwnerTasks(owner))
        ot.tasks.add(username.lower())

    executor.submit(_main_module, owner, username, password, wpm, races, acc, proxy)
    logger.info(f"Enqueued racer for {username}@{owner}")
    return jsonify(status="started"), 200

@app.route("/stopracer", methods=["POST"])
@require_token
def route_stopracer():
    data     = request.get_json() or {}
    owner    = data.get("owner","default")
    username = data.get("username","").lower()
    with tasks_lock:
        ot = _tasks.get(owner)
        if ot and username in ot.tasks:
            ot.tasks.remove(username)
            return jsonify(status="stopped"), 200
    return jsonify(error="task not found"), 404

@app.route("/stopall", methods=["POST"])
@require_token
def route_stopall():
    owner = request.get_json().get("owner","default")
    with tasks_lock:
        ot = _tasks.get(owner)
        if ot:
            ot.tasks.clear()
    return jsonify(status="stopped_all"), 200

@app.route("/tasks", methods=["GET"])
@require_token
def route_tasks():
    owner = request.args.get("owner","default")
    with tasks_lock:
        ot = _tasks.get(owner)
        lst = sorted(ot.tasks) if ot else []
    return jsonify(owner=owner, tasks=lst), 200

@app.route("/tracker", methods=["GET"])
@require_token
def route_tracker():
    owner    = request.args.get("owner","default")
    username = request.args.get("username","").lower()
    with tracker_lock:
        rec = _record_map.get((owner,username))
    if rec:
        return jsonify(owner=owner, username=username, races=rec.races), 200
    return jsonify(error="no data"), 404

@app.route("/stats", methods=["GET"])
@require_token
def route_stats():
    with tracker_lock:
        results = [
            {"owner":r.owner, "username":r.username, "races":r.races}
            for r in _record_map.values()
        ]
    total = sum(r["races"] for r in results)
    return jsonify(total_races=total, results=results), 200

@app.route("/admintasks", methods=["GET"])
@require_token
def route_admintasks():
    target = request.args.get("target_owner","")
    with tasks_lock:
        ot = _tasks.get(target)
        lst = sorted(ot.tasks) if ot else []
    return jsonify(owner=target, tasks=lst), 200

@app.route("/adminstopall", methods=["POST"])
@require_token
def route_adminstopall():
    target = request.get_json().get("target_owner","")
    with tasks_lock:
        ot = _tasks.get(target)
        if ot:
            ot.tasks.clear()
    return jsonify(status="cleared"), 200

# -----------------------------------------------------------------------------
# RUN APP
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Starting AutoTyper-X on port {PORT} with max threads={MAX_THREADS}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
