# bot.py
import os
import sys
import uuid
import random
import shutil
import signal
import logging
import subprocess
import tempfile

from datetime import datetime
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Dict

import structlog
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------
# CONFIG & ENV
# --------------------------
from dotenv import load_dotenv
load_dotenv()

API_TOKEN   = os.getenv("API_TOKEN", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", API_TOKEN)
CHROME_BIN  = os.getenv("CHROME_BIN", "/usr/bin/chromium")
PROXY_FILE  = "proxies.txt"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))

# --------------------------
# LOGGING (structlog JSON)
# --------------------------
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

# --------------------------
# METRICS
# --------------------------
METRICS = {
    "races_started":     Counter("races_started", "Number of race sessions started"),
    "races_completed":   Counter("races_completed", "Number of successful races"),
    "races_failed":      Counter("races_failed", "Number of failed race sessions"),
}

# --------------------------
# APP & MIDDLEWARE
# --------------------------
app = FastAPI(
    title="AutoTyper-X API",
    description="🚀 Fast, schema-driven NitroType racing bot",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Graceful shutdown of executor
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
def _shutdown(*args):
    executor.shutdown(wait=False)
    logger.info("Shutting down executor")
signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)

# --------------------------
# SECURITY DEPENDENCY
# --------------------------
def require_token(admin: bool = False):
    def dep(token: str = ""):
        expected = ADMIN_TOKEN if admin else API_TOKEN
        if token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return Depends(dep)

# --------------------------
# Pydantic Models
# --------------------------
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

# --------------------------
# PROXY PICKER
# --------------------------
def _get_proxy() -> Optional[str]:
    try:
        with open(PROXY_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]
        return random.choice(lines) if lines else None
    except:
        return None

# --------------------------
# BOT SESSION CLASS
# --------------------------
class BotSession:
    def __init__(self, cfg: RacerIn):
        self.cfg   = cfg
        self.id    = uuid.uuid4().hex
        self.proxy = _get_proxy()
        METRICS["races_started"].inc()
        self.log = logger.bind(session_id=self.id, user=cfg.username)

    def _chrome_version(self) -> Optional[str]:
        try:
            out = subprocess.check_output([CHROME_BIN, "--version"])
            return out.decode().strip().split(" ")[1]
        except:
            self.log.warning("chrome_version_fail")
            return None

    @contextmanager
    def _driver(self):
        ver = self._chrome_version()
        mgr_kwargs = {"version": ver} if ver else {}
        opts = Options()
        opts.binary_location = CHROME_BIN
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        if self.proxy:
            opts.add_argument(f"--proxy-server=http://{self.proxy}")

        profile = tempfile.mkdtemp(prefix="profile-")
        opts.add_argument(f"--user-data-dir={profile}")
        self.log.info("launching_driver", profile=profile)

        driver_path = ChromeDriverManager(**mgr_kwargs).install()
        service     = Service(driver_path)
        driver      = webdriver.Chrome(service=service, options=opts)
        driver.set_window_size(1200, 800)

        try:
            yield driver
        finally:
            try: driver.quit()
            except: pass
            shutil.rmtree(profile, ignore_errors=True)
            self.log.info("driver_cleaned", profile=profile)

    def run(self):
        self.log.info("session_start", races=self.cfg.race_amount, wpm=self.cfg.wpm, acc=self.cfg.min_accuracy)
        with self._driver() as d:
            # LOGIN
            d.get("https://www.nitrotype.com/login"); time.sleep(2)
            d.find_element(By.NAME, "username").send_keys(self.cfg.username)
            d.find_element(By.NAME, "password").send_keys(self.cfg.password)
            d.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
            time.sleep(4)
            if not any(x in d.current_url for x in ("race","garage")):
                self.log.error("login_fail"); METRICS["races_failed"].inc(); return

            # RACING
            for i in range(1, self.cfg.race_amount + 1):
                d.get("https://www.nitrotype.com/race"); time.sleep(3)
                words = d.find_elements(By.CSS_SELECTOR, "[data-test='race-word']")
                text  = " ".join(w.text for w in words if w.text)
                if not text:
                    self.log.warning("no_text", race=i); continue

                box = d.find_elements(By.CSS_SELECTOR, "[contenteditable='true']")
                elem = box[0] if box else d.find_element(By.TAG_NAME, "body")
                for w in text.split():
                    if random.randint(1,100) <= self.cfg.min_accuracy:
                        for ch in w:
                            elem.send_keys(ch); time.sleep(random.uniform(60/self.cfg.wpm/5,60/self.cfg.wpm/2))
                    else:
                        elem.send_keys("x")
                    elem.send_keys(" ")
                self.log.debug("race_done", race=i)

            METRICS["races_completed"].inc()
            self.log.info("session_complete")

# --------------------------
# IN-MEMORY TRACKERS
# --------------------------
tasks: Dict[str, list] = {}
# --------------------------
# ROUTES
# --------------------------

@app.get("/health")
async def health(): return {"status":"ok"}

@app.post(
    "/racer",
    response_model=StatusOut,
    dependencies=[require_token()]
)
async def start_racer(body: RacerIn):
    session = BotSession(body)
    executor.submit(session.run)

    tasks.setdefault(body.owner, []).append(body.username.lower())
    return StatusOut(status="started", owner=body.owner, username=body.username)

@app.get("/tasks", dependencies=[require_token()])
async def get_tasks(owner: str="default"):
    return {"owner": owner, "tasks": tasks.get(owner, [])}

@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# (Add /stopracer, /stopall, /tracker, /stats, /admintasks, /adminstopall similarly)

# --------------------------
# RUN
# --------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
