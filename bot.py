#!/usr/bin/env python3
import os
import sys
import random
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import (
    CollectorRegistry,
    Counter,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# ENVIRONMENT & CONFIGURATION
# -----------------------------------------------------------------------------
load_dotenv()

API_TOKEN   = os.getenv("API_TOKEN", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", API_TOKEN).strip()
CHROME_BIN  = os.getenv("CHROME_BIN", "/usr/bin/chromium").strip()
PROXY_FILE  = os.getenv("PROXY_FILE", "proxies.txt").strip()
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
PORT        = int(os.getenv("PORT", "10000"))

if not API_TOKEN:
    print("ERROR: API_TOKEN must be set in environment", file=sys.stderr)
    sys.exit(1)

# -----------------------------------------------------------------------------
# PROMETHEUS METRICS (single custom registry)
# -----------------------------------------------------------------------------
registry = CollectorRegistry()
races_started   = Counter("races_started_total",
                          "Number of race sessions started",
                          registry=registry)
races_completed = Counter("races_completed_total",
                          "Number of successfully completed race sessions",
                          registry=registry)
races_failed    = Counter("races_failed_total",
                          "Number of failed race sessions",
                          registry=registry)

# -----------------------------------------------------------------------------
# FASTAPI APP & MIDDLEWARE
# -----------------------------------------------------------------------------
app = FastAPI(
    title="AutoTyper-X Bot API",
    description="Automated NitroType racing bot",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
tasks_lock   = threading.Lock()
tracker_lock = threading.Lock()

# -----------------------------------------------------------------------------
# IN-MEMORY STATE
# -----------------------------------------------------------------------------
# Active tasks per owner
tasks: Dict[str, List[str]] = {}
# Completed races: owner -> username -> count
race_tracker: Dict[str, Dict[str, int]] = {}

# -----------------------------------------------------------------------------
# SECURITY DEPENDENCY
# -----------------------------------------------------------------------------
def require_token(admin: bool = False):
    def dep(token: str = ""):
        expected = ADMIN_TOKEN if admin else API_TOKEN
        if token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return Depends(dep)

# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------
class RacerIn(BaseModel):
    owner:       str = Field("default")
    username:    str
    password:    str
    wpm:         int = Field(60, ge=30, le=170)
    races:       int = Field(10, alias="race_amount", ge=1, le=5000)
    min_acc:     int = Field(90, alias="min_accuracy", ge=0, le=100)

class StatusOut(BaseModel):
    status:   str
    owner:    str
    username: str

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------
def _get_proxy() -> Optional[str]:
    try:
        with open(PROXY_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]
        return random.choice(lines) if lines else None
    except:
        return None

def _get_chrome_version() -> Optional[str]:
    try:
        out = subprocess.check_output([CHROME_BIN, "--version"], stderr=subprocess.DEVNULL)
        return out.decode().split(" ")[1].strip()
    except:
        return None

@contextmanager
def _driver(proxy: Optional[str]):
    """
    Yields a headless Chrome WebDriver with a unique user-data-dir.
    Cleans up the temp profile on exit.
    """
    chrome_ver = _get_chrome_version()
    mgr_kwargs = {"version": chrome_ver} if chrome_ver else {}
    opts = Options()
    opts.binary_location = CHROME_BIN
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    # random user agent to reduce fingerprinting
    opts.add_argument(f"--user-agent={UserAgent().random}")
    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")

    profile_dir = tempfile.mkdtemp(prefix="selenium-profile-")
    opts.add_argument(f"--user-data-dir={profile_dir}")

    driver_path = ChromeDriverManager(**mgr_kwargs).install()
    service     = Service(driver_path)
    driver      = webdriver.Chrome(service=service, options=opts)
    driver.set_window_size(1200, 800)

    try:
        yield driver
    finally:
        try:
            driver.quit()
        except:
            pass
        shutil.rmtree(profile_dir, ignore_errors=True)

def _record_success(owner: str, username: str):
    """Increment the in-memory race count for a user."""
    uname = username.lower()
    with tracker_lock:
        owner_map = race_tracker.setdefault(owner, {})
        owner_map[uname] = owner_map.get(uname, 0) + 1

# -----------------------------------------------------------------------------
# CORE WORKER
# -----------------------------------------------------------------------------
def _run_session(cfg: RacerIn):
    races_started.inc()
    proxy = _get_proxy()
    successes = 0

    with _driver(proxy) as driver:
        # LOGIN
        driver.get("https://www.nitrotype.com/login")
        time.sleep(2)
        driver.find_element(By.NAME, "username").send_keys(cfg.username)
        driver.find_element(By.NAME, "password").send_keys(cfg.password)
        driver.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
        time.sleep(4)
        if not any(x in driver.current_url for x in ("race", "garage")):
            races_failed.inc()
            return

        # RACING LOOP
        for i in range(1, cfg.races + 1):
            driver.get("https://www.nitrotype.com/race")
            time.sleep(3)
            words = driver.find_elements(By.CSS_SELECTOR, "[data-test='race-word']")
            text = " ".join(w.text for w in words if w.text)
            if not text:
                continue

            # find input box
            boxes = driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
            box = boxes[0] if boxes else driver.find_element(By.TAG_NAME, "body")

            for w in text.split():
                if random.randint(1, 100) <= cfg.min_acc:
                    for ch in w:
                        box.send_keys(ch)
                        time.sleep(random.uniform(60 / cfg.wpm / 5, 60 / cfg.wpm / 2))
                else:
                    box.send_keys("x")
                box.send_keys(" ")
            successes += 1
            _record_success(cfg.owner, cfg.username)
            time.sleep(random.uniform(2, 5))

    if successes == cfg.races:
        races_completed.inc()
    else:
        races_failed.inc()

# -----------------------------------------------------------------------------
# ROUTES
# -----------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post(
    "/racer",
    response_model=StatusOut,
    dependencies=[require_token()]
)
async def start_racer(body: RacerIn):
    # enqueue job
    executor.submit(_run_session, body)

    # track active task
    uname = body.username.lower()
    with tasks_lock:
        lst = tasks.setdefault(body.owner, [])
        if uname not in lst:
            lst.append(uname)

    return StatusOut(status="started", owner=body.owner, username=body.username)

@app.post("/stopracer", dependencies=[require_token()])
async def stop_racer(owner: str = Field("default"), username: str = Field(...)):
    uname = username.lower()
    with tasks_lock:
        lst = tasks.get(owner, [])
        if uname in lst:
            lst.remove(uname)
            return {"status": "stopped", "owner": owner, "username": uname}
    raise HTTPException(status_code=404, detail="task not found")

@app.post("/stopall", dependencies=[require_token()])
async def stop_all(owner: str = Field("default")):
    with tasks_lock:
        tasks.get(owner, []).clear()
    return {"status": "stopped_all", "owner": owner}

@app.get("/tasks", dependencies=[require_token()])
async def get_tasks(owner: str = "default"):
    return {"owner": owner, "tasks": tasks.get(owner, [])}

@app.get("/tracker", dependencies=[require_token()])
async def get_tracker(owner: str = "default", username: str = ""):
    uname = username.lower()
    count = race_tracker.get(owner, {}).get(uname)
    if count is not None:
        return {"owner": owner, "username": uname, "races": count}
    raise HTTPException(status_code=404, detail="no data")

@app.get("/stats", dependencies=[require_token()])
async def stats():
    results = []
    for owner, usermap in race_tracker.items():
        for user, cnt in usermap.items():
            results.append({"owner": owner, "username": user, "races": cnt})
    total = sum(r["races"] for r in results)
    return {"total_races": total, "results": results}

@app.get("/admintasks", dependencies=[require_token(admin=True)])
async def admin_tasks(target_owner: str = ""):
    return {"owner": target_owner, "tasks": tasks.get(target_owner, [])}

@app.post("/adminstopall", dependencies=[require_token(admin=True)])
async def admin_stop_all(target_owner: str = ""):
    with tasks_lock:
        tasks.get(target_owner, []).clear()
    return {"status": "cleared", "owner": target_owner}

@app.get("/metrics")
async def metrics():
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# -----------------------------------------------------------------------------
# RUN THE APP
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
