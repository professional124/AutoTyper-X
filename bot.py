# bot.py
import os
import sys
import uuid
import random
import subprocess
import tempfile
import shutil
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import (
    CollectorRegistry, Counter, generate_latest, CONTENT_TYPE_LATEST
)
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# CONFIG & ENV
# -----------------------------------------------------------------------------
load_dotenv()
API_TOKEN   = os.getenv("API_TOKEN", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", API_TOKEN)
CHROME_BIN  = os.getenv("CHROME_BIN", "/usr/bin/chromium")
PROXY_FILE  = os.getenv("PROXY_FILE", "proxies.txt")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
PORT        = int(os.getenv("PORT", "10000"))

if not API_TOKEN:
    print("ERROR: API_TOKEN must be set", file=sys.stderr)
    sys.exit(1)

# -----------------------------------------------------------------------------
# PROMETHEUS METRICS (custom registry)
# -----------------------------------------------------------------------------
registry = CollectorRegistry()
races_started   = Counter("races_started_total",
                          "Number of race sessions started",
                          registry=registry)
races_completed = Counter("races_completed_total",
                          "Number of successful races",
                          registry=registry)
races_failed    = Counter("races_failed_total",
                          "Number of failed race sessions",
                          registry=registry)

# -----------------------------------------------------------------------------
# FASTAPI APP & THREAD POOL
# -----------------------------------------------------------------------------
app = FastAPI(
    title="AutoTyper-X API",
    description="FastAPI NitroType racing bot"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def require_token(admin: bool = False):
    def dep(token: str = ""):
        expected = ADMIN_TOKEN if admin else API_TOKEN
        if token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return Depends(dep)

# -----------------------------------------------------------------------------
# REQUEST & RESPONSE MODELS
# -----------------------------------------------------------------------------
class RacerIn(BaseModel):
    owner:       str = Field("default")
    username:    str
    password:    str
    wpm:         int = Field(60, ge=30, le=170)
    race_amount: int = Field(10, alias="races", ge=1, le=5000)
    min_accuracy:int = Field(90, alias="min_acc", ge=0, le=100)

class StatusOut(BaseModel):
    status:   str
    owner:    str
    username: str

# -----------------------------------------------------------------------------
# IN-MEMORY STATE
# -----------------------------------------------------------------------------
# Active tasks per owner
tasks: Dict[str, List[str]] = {}
# Completed races tracker: owner -> username -> count
race_tracker: Dict[str, Dict[str, int]] = {}

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
        out = subprocess.check_output([CHROME_BIN, "--version"],
                                      stderr=subprocess.DEVNULL)
        return out.decode().strip().split(" ")[1]
    except:
        return None

@contextmanager
def _driver(proxy: Optional[str]):
    """Yields a Selenium WebDriver and cleans up."""
    chrome_ver = _get_chrome_version()
    mgr_kwargs = {"version": chrome_ver} if chrome_ver else {}
    opts = Options()
    opts.binary_location = CHROME_BIN
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")

    profile = tempfile.mkdtemp(prefix="profile-")
    opts.add_argument(f"--user-data-dir={profile}")

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
        shutil.rmtree(profile, ignore_errors=True)

def _record_success(owner: str, username: str):
    """Increment in-memory race count."""
    user = username.lower()
    owner_map = race_tracker.setdefault(owner, {})
    owner_map[user] = owner_map.get(user, 0) + 1

# -----------------------------------------------------------------------------
# CORE WORKER FUNCTION
# -----------------------------------------------------------------------------
def _run_session(cfg: RacerIn):
    races_started.inc()
    proxy = _get_proxy()
    with _driver(proxy) as d:
        # 1) LOGIN
        d.get("https://www.nitrotype.com/login"); time.sleep(2)
        d.find_element(By.NAME, "username").send_keys(cfg.username)
        d.find_element(By.NAME, "password").send_keys(cfg.password)
        d.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
        time.sleep(4)
        if not any(x in d.current_url for x in ("race", "garage")):
            races_failed.inc()
            return

        # 2) RACING LOOP
        successes = 0
        for i in range(1, cfg.race_amount + 1):
            d.get("https://www.nitrotype.com/race"); time.sleep(3)
            words = d.find_elements(By.CSS_SELECTOR, "[data-test='race-word']")
            text  = " ".join(w.text for w in words if w.text)
            if not text:
                continue

            box_elems = d.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
            box = box_elems[0] if box_elems else d.find_element(By.TAG_NAME, "body")

            for w in text.split():
                if random.randint(1, 100) <= cfg.min_accuracy:
                    for ch in w:
                        box.send_keys(ch)
                        time.sleep(random.uniform(60/cfg.wpm/5, 60/cfg.wpm/2))
                else:
                    box.send_keys("x")
                box.send_keys(" ")
            successes += 1
            _record_success(cfg.owner, cfg.username)
            time.sleep(random.uniform(2, 5))

        # 3) METRICS
        if successes == cfg.race_amount:
            races_completed.inc()
        else:
            races_failed.inc()

# -----------------------------------------------------------------------------
# API ENDPOINTS
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
    executor.submit(_run_session, body)
    tasks.setdefault(body.owner, []).append(body.username.lower())
    return StatusOut(status="started", owner=body.owner, username=body.username)

@app.post("/stopracer", dependencies=[require_token()])
async def stop_racer(owner: str = Field("default"), username: str = Field(...)):
    lst = tasks.get(owner, [])
    uname = username.lower()
    if uname in lst:
        lst.remove(uname)
        return {"status": "stopped", "owner": owner, "username": uname}
    raise HTTPException(status_code=404, detail="task not found")

@app.post("/stopall", dependencies=[require_token()])
async def stop_all(owner: str = Field("default")):
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
    results = [
        {"owner": owner, "username": uname, "races": cnt}
        for owner, users in race_tracker.items()
        for uname, cnt in users.items()
    ]
    total = sum(item["races"] for item in results)
    return {"total_races": total, "results": results}

@app.get("/admintasks", dependencies=[require_token(admin=True)])
async def admin_tasks(target_owner: str = ""):
    return {"owner": target_owner, "tasks": tasks.get(target_owner, [])}

@app.post("/adminstopall", dependencies=[require_token(admin=True)])
async def admin_stop_all(target_owner: str = ""):
    tasks.get(target_owner, []).clear()
    return {"status": "cleared", "owner": target_owner}

@app.get("/metrics")
async def metrics():
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# -----------------------------------------------------------------------------
# RUN AS SCRIPT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
