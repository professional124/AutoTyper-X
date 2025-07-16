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
from selenium.webdriver.common.keys import Keys

#
# Keep-alive HTTP server (for Render Free Web Service)
#
app = Flask("")
@app.route("/")
def home():
    return "I'm alive!"

def run_keep_alive():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_keep_alive).start()

#
# Load environment variables
#
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "1046552485457829909"))

#
# Discord bot setup
#
bot = discord.Bot()
ua = UserAgent(platforms="desktop")

# Track which accounts are actively racing per user
tasks = []            # [{ discord_id: int, tasks: [username, ...] }, …]
race_tracker = []     # [{ discord_id: int, username: str, races: int }, …]

#
# Logging configuration
#
os.makedirs("logs", exist_ok=True)
log_file = f"logs/{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    filemode="w"
)
console = logging.getLogger()
console.setLevel(logging.INFO)

#
# UI colors
#
COLOR_SUCCESS = 5763719
COLOR_FAIL    = 15548997
EMOJI_FAIL    = "❌"
EMOJI_OK      = "✅"

#
# Proxy utility
#
def get_proxy():
    with open("proxies.txt", "r") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
        raise ValueError("proxies.txt is empty")
    return random.choice(lines)

#
# Selenium setup and NitroType logic
#
def setup_driver(proxy: str = None):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(1200, 800)
    return driver

def login(driver, username: str, password: str) -> bool:
    driver.get("https://www.nitrotype.com/login")
    time.sleep(3)
    try:
        driver.find_element(By.NAME, "username").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password + Keys.RETURN)
        time.sleep(5)
        url = driver.current_url
        success = "race" in url or "garage" in url
        logging.info(f"Login for {username}: {'OK' if success else 'FAIL'} ({url})")
        return success
    except Exception as e:
        logging.error(f"Login exception for {username}: {e}")
        return False

def get_race_text(driver) -> str:
    for _ in range(20):
        try:
            el = driver.find_element(By.CSS_SELECTOR, '[data-test="race-word"]')
            if el.text:
                break
        except:
            time.sleep(0.5)
    words = driver.find_elements(By.CSS_SELECTOR, '[data-test="race-word"]')
    text = " ".join(w.text for w in words if w.text)
    logging.info(f"Fetched race text ({len(text)} chars)")
    return text

def run_race(driver, number: int, wpm: int, acc: int) -> bool:
    try:
        driver.get("https://www.nitrotype.com/race")
        time.sleep(4)
        logging.info(f"Starting race #{number}")
        text = get_race_text(driver)
        if not text:
            logging.warning(f"No text for race #{number}")
            return False

        try:
            box = driver.find_element(By.CSS_SELECTOR, 'input[type="text"], textarea')
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

        logging.info(f"Completed race #{number} @WPM {wpm}, ACC {acc}%")
        return True
    except Exception as e:
        logging.error(f"Error in race #{number}: {e}")
        return False

def main_module(
    auth, userAgent, discord_id, username, password,
    cookies, racesPlayed, friendsHash, friends_array,
    wpm, race_amount, min_acc, stickers, proxy
):
    driver = None
    try:
        driver = setup_driver(proxy)
        if not login(driver, username, password):
            logging.warning(f"[{username}] Login failed, aborting")
            return

        for i in range(1, race_amount + 1):
            ok = run_race(driver, i, wpm, min_acc)
            if ok:
                # track completed races
                rec = next((r for r in race_tracker
                            if r["discord_id"] == discord_id
                            and r["username"] == username.lower()), None)
                if rec:
                    rec["races"] += 1
                else:
                    race_tracker.append({
                        "discord_id": discord_id,
                        "username": username.lower(),
                        "races": 1
                    })
            time.sleep(random.randint(3, 8))

        logging.info(f"Finished all {race_amount} races for {username}")
    except Exception as e:
        logging.error(f"main_module fatal for {username}: {e}")
    finally:
        if driver:
            driver.quit()

#
# Discord event
#
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("NitroType Botting"))
    print("[INFO] Bot is online and ready!")

#
# Slash commands
#

@bot.slash_command(
    name="racer",
    description="Start racing on your NitroType account"
)
async def racer(
    ctx,
    username: Option(str, "NitroType username"),
    password: Option(str, "NitroType password"),
    wpm: Option(int, "WPM (30–170)", min_value=30, max_value=170),
    race_amount: Option(int, "Races (1–5000)", min_value=1, max_value=5000),
    min_accuracy: Option(int, "Accuracy (85–100)", min_value=85, max_value=100)
):
    # permission & slot check
    allowed = any(r.name == "Buyer" for r in ctx.author.roles)
    slots = next((int(r.name.split(": ")[1])
                  for r in ctx.author.roles if r.name.startswith("Slots: ")), 0)
    if not allowed or slots < 1:
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_FAIL,
                description=f"{EMOJI_FAIL} Unauthorized or no slots."
            ), ephemeral=True
        )

    user_tasks = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if user_tasks:
        if username.lower() in user_tasks["tasks"]:
            return await ctx.respond(
                embed=discord.Embed(
                    color=COLOR_FAIL,
                    description=f"{EMOJI_FAIL} Already racing `{username}`."
                ), ephemeral=True
            )
        if len(user_tasks["tasks"]) >= slots:
            return await ctx.respond(
                embed=discord.Embed(
                    color=COLOR_FAIL,
                    description=f"{EMOJI_FAIL} Slot limit reached."
                ), ephemeral=True
            )

    proxy = get_proxy()
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_SUCCESS,
            description="💭 Logging in..."
        ), ephemeral=True
    )
    # launch thread
    threading.Thread(target=main_module, args=(
        "auth", ua.random, ctx.author.id,
        username, password, None, 0, None, None,
        wpm, race_amount, min_accuracy, None, proxy
    )).start()

    # track active
    if user_tasks:
        user_tasks["tasks"].append(username.lower())
    else:
        tasks.append({
            "discord_id": ctx.author.id,
            "tasks": [username.lower()]
        })

    await ctx.followup.send(
        embed=discord.Embed(
            color=COLOR_SUCCESS,
            description=f"{EMOJI_OK} Started racing `{username}`!"
        ), ephemeral=True
    )


@bot.slash_command(
    name="stopracer",
    description="Stop racing a specific NitroType account"
)
async def stopracer(
    ctx,
    username: Option(str, "NitroType username")
):
    user_tasks = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if user_tasks and username.lower() in user_tasks["tasks"]:
        user_tasks["tasks"].remove(username.lower())
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_SUCCESS,
                description=f"{EMOJI_OK} Stopped `{username}`."
            ), ephemeral=True
        )
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_FAIL,
            description=f"{EMOJI_FAIL} No active task for `{username}`."
        ), ephemeral=True
    )


@bot.slash_command(
    name="stopall",
    description="Stop racing all NitroType accounts"
)
async def stopall(ctx):
    user_tasks = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if user_tasks:
        user_tasks["tasks"].clear()
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_SUCCESS,
                description=f"{EMOJI_OK} All races stopped."
            ), ephemeral=True
        )
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_FAIL,
            description=f"{EMOJI_FAIL} You have no active races."
        ), ephemeral=True
    )


@bot.slash_command(
    name="tasks",
    description="List your active racing accounts"
)
async def tasks_cmd(ctx):
    user_tasks = next((t for t in tasks if t["discord_id"] == ctx.author.id), None)
    if not user_tasks or not user_tasks["tasks"]:
        return await ctx.respond(
            f"{EMOJI_FAIL} You have no active racing accounts.", ephemeral=True
        )
    lines = "\n".join(f"{i+1}. {u}" for i, u in enumerate(user_tasks["tasks"]))
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_SUCCESS,
            description=f"{EMOJI_OK} Active accounts:\n{lines}"
        ), ephemeral=True
    )


@bot.slash_command(
    name="tracker",
    description="Show how many races an account has completed"
)
async def tracker(ctx, username: Option(str, "NitroType username")):
    rec = next((r for r in race_tracker
                if r["discord_id"] == ctx.author.id
                and r["username"] == username.lower()), None)
    if rec:
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_SUCCESS,
                description=f"{EMOJI_OK} `{username}` completed {rec['races']} races."
            ), ephemeral=True
        )
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_FAIL,
            description=f"{EMOJI_FAIL} No race data for `{username}`."
        ), ephemeral=True
    )


@bot.slash_command(
    name="slots",
    description="Show how many slots you have"
)
async def slots(ctx):
    slots = next((int(r.name.split(": ")[1])
                  for r in ctx.author.roles if r.name.startswith("Slots: ")), None)
    if slots:
        await ctx.respond(
            embed=discord.Embed(
                color=COLOR_SUCCESS,
                description=f"{EMOJI_OK} You have {slots} slots."
            ), ephemeral=True
        )
    else:
        await ctx.respond(
            embed=discord.Embed(
                color=COLOR_FAIL,
                description=f"{EMOJI_FAIL} You have no slots."
            ), ephemeral=True
        )


@bot.slash_command(
    name="stats",
    description="Admin: Show overall bot usage stats"
)
async def stats(ctx):
    if ctx.author.id != ADMIN_ID:
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_FAIL,
                description=f"{EMOJI_FAIL} Unauthorized."
            ), ephemeral=True
        )
    lines = []
    total = 0
    for rec in race_tracker:
        mention = f"<@{rec['discord_id']}>"
        lines.append(f"{mention} • {rec['username']}: {rec['races']} races")
        total += rec['races']
    lines.append(f"**Total races:** {total}")
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_SUCCESS,
            description="\n".join(lines) or "No races tracked yet."
        ), ephemeral=True
    )


@bot.slash_command(
    name="admintasks",
    description="Admin: Show users' active tasks"
)
async def admintasks(ctx, discord_id: Option(str, "Discord User ID")):
    if ctx.author.id != ADMIN_ID:
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_FAIL,
                description=f"{EMOJI_FAIL} Unauthorized."
            ), ephemeral=True
        )
    uid    = int(discord_id)
    record = next((t for t in tasks if t["discord_id"] == uid), None)
    if not record or not record["tasks"]:
        return await ctx.respond(f"{EMOJI_FAIL} No active tasks for <@{uid}>", ephemeral=True)
    lines = "\n".join(f"{i+1}. {u}" for i, u in enumerate(record["tasks"]))
    await ctx.respond(
        embed=discord.Embed(
            color=COLOR_SUCCESS,
            description=f"Tasks for <@{uid}>:\n{lines}"
        ), ephemeral=True
    )


@bot.slash_command(
    name="adminstopall",
    description="Admin: Stop all tasks for a user"
)
async def adminstopall(ctx, discord_id: Option(str, "Discord User ID")):
    if ctx.author.id != ADMIN_ID:
        return await ctx.respond(
            embed=discord.Embed(
                color=COLOR_FAIL,
                description=f"{EMOJI_FAIL} Unauthorized."
            ), ephemeral=True
        )
    uid = int(discord_id)
    record = next((t for t in tasks if t["discord_id"] == uid), None)
    if record:
        record["tasks"].clear()
        return await ctx.respond(f"{EMOJI_OK} All tasks cleared for <@{uid}>.", ephemeral=True)
    await ctx.respond(f"{EMOJI_FAIL} No tasks to stop for <@{uid}>.", ephemeral=True)


#
# Run the bot
#
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
