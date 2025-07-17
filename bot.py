import os
import random
import threading
import logging
import time
from datetime import datetime

from flask import Flask
from threading import Thread
from dotenv import load_dotenv
from fake_useragent import UserAgent

import discord
from discord.commands import Option

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys

# -------------------- KEEP-ALIVE (Render Free) --------------------
app = Flask("")
@app.route("/")
def home():
    return "I'm alive!"

def run_keep_alive():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_keep_alive, daemon=True).start()

# -------------------- ENVIRONMENT & BOT SETUP --------------------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID      = int(os.getenv("ADMIN_ID", "0"))

bot = discord.Bot()
ua  = UserAgent(platforms="desktop")

# -------------------- STATE TRACKERS --------------------
tasks        = []  # [ {discord_id: int, tasks: [username,...]}, ... ]
race_tracker = []  # [ {discord_id: int, username: str, races: int}, ... ]

# -------------------- LOGGING CONFIG --------------------
os.makedirs("logs", exist_ok=True)
logfile = f"logs/{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
logging.basicConfig(
    filename=logfile,
    filemode="w",
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
console = logging.getLogger()
console.setLevel(logging.INFO)

# -------------------- UI CONSTANTS --------------------
COLOR_OK    = 0x2ECC71
COLOR_FAIL  = 0xE74C3C
EMOJI_OK    = "✅"
EMOJI_FAIL  = "❌"

# -------------------- HELPER FUNCTIONS --------------------
def slot_count(member) -> int:
    """Extract slot count from roles named 'Slots: X'."""
    for r in member.roles:
        if r.name.startswith("Slots: "):
            try:
                return int(r.name.split(": ")[1])
            except ValueError:
                pass
    return 0

def record_success(discord_id: int, username: str):
    uname = username.lower()
    rec = next((r for r in race_tracker
                if r["discord_id"] == discord_id and r["username"] == uname), None)
    if rec:
        rec["races"] += 1
    else:
        race_tracker.append({"discord_id": discord_id, "username": uname, "races": 1})

def send_dm(discord_id: int, message: str):
    """Send a direct message to the user."""
    async def _dm():
        user = await bot.fetch_user(discord_id)
        if user:
            try:
                await user.send(message)
            except Exception as e:
                logging.error(f"Failed to DM {discord_id}: {e}")
    bot.loop.create_task(_dm())

# -------------------- PROXY MANAGEMENT --------------------
def get_proxy() -> str:
    """Read and return a random proxy from proxies.txt."""
    with open("proxies.txt", "r") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        raise RuntimeError("proxies.txt is empty")
    return random.choice(lines)

# -------------------- SELENIUM / NITROTYPE LOGIC --------------------
def setup_driver(proxy: str = None):
    """Initialize headless Chrome WebDriver with optional proxy."""
    chrome_bin = "/usr/bin/chromium"
    driver_bin = "/usr/bin/chromedriver"
    opts = Options()
    opts.headless = True
    opts.binary_location = chrome_bin
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")
    service = Service(driver_bin)
    driver  = webdriver.Chrome(service=service, options=opts)
    driver.set_window_size(1200, 800)
    return driver

def login(driver, username: str, password: str) -> bool:
    """Perform NitroType login, return True on success."""
    driver.get("https://www.nitrotype.com/login")
    time.sleep(2)
    try:
        driver.find_element(By.NAME, "username").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, 'button[data-cy="login-button"]').click()
        time.sleep(4)
        url = driver.current_url
        success = "race" in url or "garage" in url
        logging.info(f"[{username}] Login {'OK' if success else 'FAIL'} → {url}")
        return success
    except Exception as e:
        logging.error(f"[{username}] Login error: {e}")
        return False

def get_race_text(driver) -> str:
    """Fetch the full race text as a string."""
    for _ in range(20):
        try:
            el = driver.find_element(By.CSS_SELECTOR, '[data-test="race-word"]')
            if el.text:
                break
        except:
            time.sleep(0.3)
    words = driver.find_elements(By.CSS_SELECTOR, '[data-test="race-word"]')
    text  = " ".join(w.text for w in words if w.text)
    logging.info(f"Fetched race text: {len(words)} words")
    return text

def run_race(driver, number: int, wpm: int, acc: int) -> bool:
    """Navigate to race page and simulate typing."""
    try:
        driver.get("https://www.nitrotype.com/race")
        time.sleep(3)
        logging.info(f"Starting race #{number}")
        text = get_race_text(driver)
        if not text:
            logging.warning(f"[Race {number}] No text found")
            return False

        # NitroType uses a contenteditable div for input
        try:
            box = driver.find_element(By.CSS_SELECTOR, '[contenteditable="true"]')
        except:
            box = driver.find_element(By.TAG_NAME, "body")

        for word in text.split():
            if random.randint(1, 100) <= acc:
                for ch in word:
                    box.send_keys(ch)
                    time.sleep(random.uniform(60/wpm/5, 60/wpm/2))
            else:
                box.send_keys("x")
            box.send_keys(" ")

        logging.info(f"Completed race #{number} @ {wpm} WPM, {acc}% ACC")
        return True
    except Exception as e:
        logging.error(f"[Race {number}] Error: {e}")
        return False

def main_module(discord_id, username, password, wpm, race_amount, min_acc, proxy):
    """Thread target: runs the full racing session."""
    driver = None
    try:
        logging.info(f"[{username}] Session start (proxy={proxy})")
        driver = setup_driver(proxy)
        if not login(driver, username, password):
            raise RuntimeError("Login failed")

        for i in range(1, race_amount + 1):
            success = run_race(driver, i, wpm, min_acc)
            if success:
                record_success(discord_id, username)
            else:
                logging.warning(f"[{username}] Race #{i} failed")
            time.sleep(random.randint(3, 8))

        logging.info(f"[{username}] Completed {race_amount} races")
    except Exception as e:
        logging.exception(f"[{username}] main_module crashed")
        send_dm(discord_id, f"🚨 AutoTyper crashed on `{username}`:\n```{e}```")
    finally:
        if driver:
            driver.quit()

# -------------------- DISCORD BOT EVENTS & COMMANDS --------------------
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("NitroType Botting"))
    print("[INFO] Bot is online and ready!")

@bot.slash_command(name="racer", description="Start racing on NitroType")
async def racer(
    ctx,
    username:   Option(str, "NitroType username"),
    password:   Option(str, "NitroType password"),
    wpm:        Option(int, "WPM (30–170)", min_value=30, max_value=170),
    race_amount:Option(int, "Number of races (1–5000)", min_value=1, max_value=5000),
    min_acc:    Option(int, "Min accuracy % (85–100)", min_value=85, max_value=100)
):
    # Permission & slot check
    allowed = any(r.name == "Buyer" for r in ctx.author.roles)
    slots  = slot_count(ctx.author)
    if not allowed or slots < 1:
        return await ctx.respond(
            embed=discord.Embed(color=COLOR_FAIL, description=f"{EMOJI_FAIL} Unauthorized or no slots."),
            ephemeral=True
        )

    ut = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if ut:
        if username.lower() in ut["tasks"]:
            return await ctx.respond(
                embed=discord.Embed(color=COLOR_FAIL, description=f"{EMOJI_FAIL} Already racing `{username}`."),
                ephemeral=True
            )
        if len(ut["tasks"]) >= slots:
            return await ctx.respond(
                embed=discord.Embed(color=COLOR_FAIL, description=f"{EMOJI_FAIL} Slot limit reached."),
                ephemeral=True
            )

    # Acquire proxy
    try:
        proxy = get_proxy()
    except Exception as e:
        return await ctx.respond(
            embed=discord.Embed(color=COLOR_FAIL, description=f"{EMOJI_FAIL} Proxy error: {e}"),
            ephemeral=True
        )

    await ctx.respond(embed=discord.Embed(
        color=COLOR_OK,
        description="💭 Launching racing session..."
    ), ephemeral=True)

    # Start racing in background
    threading.Thread(
        target=main_module,
        args=(ctx.author.id, username, password, wpm, race_amount, min_acc, proxy),
        daemon=True
    ).start()

    # Track active account
    if ut:
        ut["tasks"].append(username.lower())
    else:
        tasks.append({"discord_id": ctx.author.id, "tasks": [username.lower()]})

    await ctx.followup.send(embed=discord.Embed(
        color=COLOR_OK,
        description=f"{EMOJI_OK} Started racing `{username}`!"
    ), ephemeral=True)

@bot.slash_command(name="stopracer", description="Stop racing a NitroType account")
async def stopracer(ctx, username: Option(str, "NitroType username")):
    ut = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if ut and username.lower() in ut["tasks"]:
        ut["tasks"].remove(username.lower())
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_OK, description=f"{EMOJI_OK} Stopped `{username}`."
        ), ephemeral=True)
    await ctx.respond(embed=discord.Embed(
        color=COLOR_FAIL, description=f"{EMOJI_FAIL} `{username}` not active."
    ), ephemeral=True)

@bot.slash_command(name="stopall", description="Stop all racing sessions")
async def stopall(ctx):
    ut = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if ut:
        ut["tasks"].clear()
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_OK, description=f"{EMOJI_OK} All races stopped."
        ), ephemeral=True)
    await ctx.respond(embed=discord.Embed(
        color=COLOR_FAIL, description=f"{EMOJI_FAIL} No active races."
    ), ephemeral=True)

@bot.slash_command(name="tasks", description="List your active racing accounts")
async def tasks_cmd(ctx):
    ut = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if not ut or not ut["tasks"]:
        return await ctx.respond(f"{EMOJI_FAIL} No active accounts.", ephemeral=True)
    lines = "\n".join(f"{i+1}. {u}" for i, u in enumerate(ut["tasks"]))
    await ctx.respond(embed=discord.Embed(
        color=COLOR_OK, description=f"{EMOJI_OK} Active accounts:\n{lines}"
    ), ephemeral=True)

@bot.slash_command(name="tracker", description="Show how many races you’ve completed")
async def tracker(ctx, username: Option(str, "NitroType username")):
    rec = next((r for r in race_tracker
                if r["discord_id"] == ctx.author.id and r["username"] == username.lower()), None)
    if rec:
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_OK,
            description=f"{EMOJI_OK} `{username}` completed {rec['races']} races."
        ), ephemeral=True)
    await ctx.respond(embed=discord.Embed(
        color=COLOR_FAIL,
        description=f"{EMOJI_FAIL} No data for `{username}`."
    ), ephemeral=True)

@bot.slash_command(name="slots", description="Check how many slots you have")
async def slots(ctx):
    cnt = slot_count(ctx.author)
    if cnt > 0:
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_OK,
            description=f"{EMOJI_OK} You have {cnt} slots."
        ), ephemeral=True)
    await ctx.respond(embed=discord.Embed(
        color=COLOR_FAIL,
        description=f"{EMOJI_FAIL} You have no slots."
    ), ephemeral=True)

@bot.slash_command(name="stats", description="(Admin) Show overall race stats")
async def stats(ctx):
    if ctx.author.id != ADMIN_ID:
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_FAIL, description=f"{EMOJI_FAIL} Unauthorized."
        ), ephemeral=True)
    lines, total = [], 0
    for r in race_tracker:
        mention = f"<@{r['discord_id']}>"
        lines.append(f"{mention} • {r['username']}: {r['races']} races")
        total += r['races']
    lines.append(f"**Total races:** {total}")
    await ctx.respond(embed=discord.Embed(
        color=COLOR_OK, description="\n".join(lines)
    ), ephemeral=True)

@bot.slash_command(name="admintasks", description="(Admin) Show users' active tasks")
async def admintasks(ctx, discord_id: Option(str, "Discord user ID")):
    if ctx.author.id != ADMIN_ID:
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_FAIL, description=f"{EMOJI_FAIL} Unauthorized."
        ), ephemeral=True)
    uid = int(discord_id)
    rec = next((t for t in tasks if t["discord_id"] == uid), None)
    if not rec or not rec["tasks"]:
        return await ctx.respond(f"{EMOJI_FAIL} No tasks for <@{uid}>", ephemeral=True)
    lines = "\n".join(f"{i+1}. {u}" for i, u in enumerate(rec["tasks"]))
    await ctx.respond(embed=discord.Embed(
        color=COLOR_OK, description=f"Tasks for <@{uid}>:\n{lines}"
    ), ephemeral=True)

@bot.slash_command(name="adminstopall", description="(Admin) Stop all tasks for a user")
async def adminstopall(ctx, discord_id: Option(str, "Discord user ID")):
    if ctx.author.id != ADMIN_ID:
        return await ctx.respond(embed=discord.Embed(
            color=COLOR_FAIL, description=f"{EMOJI_FAIL} Unauthorized."
        ), ephemeral=True)
    uid = int(discord_id)
    rec = next((t for t in tasks if t["discord_id"] == uid), None)
    if rec:
        rec["tasks"].clear()
        return await ctx.respond(f"{EMOJI_OK} Cleared tasks for <@{uid}>", ephemeral=True)
    await ctx.respond(f"{EMOJI_FAIL} No tasks to clear for <@{uid}>", ephemeral=True)

# -------------------- RUN BOT --------------------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
