# bot.py
import os
import sys
import uuid
import random
import shutil
import tempfile
import subprocess
from datetime import datetime
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from prometheus_client import (
    CollectorRegistry, Counter, generate_latest, CONTENT_TYPE_LATEST
)
from webdriver_manager.chrome import ChromeDriverManager
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
# PROMETHEUS METRICS (single custom registry)
# -----------------------------------------------------------------------------
registry = CollectorRegistry()

races_started   = Counter(
    "races_started_total",
    "Number of race sessions started",
    registry=registry
)
races_completed = Counter(
    "races_completed_total",
    "Number of successful races",
    registry=registry
)
races_failed    = Counter(
    "races_failed_total",
    "Number of failed race sessions",
    registry=registry
)

# -----------------------------------------------------------------------------
# FASTAPI APP & MIDDLEWARE
# -----------------------------------------------------------------------------
app = FastAPI(title="AutoTyper-X API")
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
# Pydantic Models
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
    Context manager that yields a Selenium driver and cleans up profile.
    """
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

def _run_session(cfg: RacerIn):
    """
    Orchestrates one NitroType racing session in a thread.
    """
    races_started.inc()
    proxy = _get_proxy()

    with _driver(proxy) as d:
        # LOGIN
        d.get("https://www.nitrotype.com/login"); time.sleep(2)
        d.find_element(By.NAME, "username").send_keys(cfg.username)
        d.find_element(By.NAME, "password").send_keys(cfg.password)
        d.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
        time.sleep(4)
        if not any(x in d.current_url for x in ("race", "garage")):
            races_failed.inc()
            return

        # RACING LOOP
        success = 0
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
            success += 1
            time.sleep(random.uniform(2, 5))

        if success == cfg.race_amount:
            races_completed.inc()
        else:
            races_failed.inc()

# -----------------------------------------------------------------------------
# IN‐MEMORY STATE
# -----------------------------------------------------------------------------
tasks: Dict[str, list] = {}

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
    executor.submit(_run_session, body)
    tasks.setdefault(body.owner, []).append(body.username.lower())
    return StatusOut(status="started", owner=body.owner, username=body.username)

@app.get("/tasks", dependencies=[require_token()])
async def get_tasks(owner: str = "default"):
    return {"owner": owner, "tasks": tasks.get(owner, [])}

@app.get("/metrics")
async def metrics():
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# (You can add /stopracer, /stopall, /tracker, /stats, /admintasks, /adminstopall here…)

# -----------------------------------------------------------------------------
# RUN
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
