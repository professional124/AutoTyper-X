import os
import discord
from discord.ext import commands
import threading

# Import your NitroType racing logic as a module.
import main

# Load Discord bot token from environment
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Helper to run races in a thread so Discord doesn't freeze
def run_races_async(ctx, num_races):
    try:
        ctx.send(f"Starting {num_races} NitroType races...")  # Will not actually send outside of async
        main.TOTAL_RACES = num_races
        main.main()
        # You may want to send a final message via Discord after completion
        # Use bot.loop.create_task for sending messages asynchronously
        bot.loop.create_task(ctx.send(f"✅ Finished {num_races} races! Check logs for details."))
    except Exception as e:
        bot.loop.create_task(ctx.send(f"❌ Error: {str(e)}"))

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def race(ctx, races: int = 1):
    """
    Starts NitroType races.
    Usage: !race 10
    """
    await ctx.send(f"Preparing to run {races} races. This may take a while!")
    thread = threading.Thread(target=run_races_async, args=(ctx, races))
    thread.start()

@bot.command()
async def status(ctx):
    """
    Check bot status/logs.
    """
    await ctx.send("Bot is running. See logs for race history and errors.")

@bot.command()
async def ping(ctx):
    """
    Ping test.
    """
    await ctx.send("🏓 Pong!")

# Run the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in environment variables.")
    else:
        bot.run(DISCORD_TOKEN)
