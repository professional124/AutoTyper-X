import discord
from discord.ext import commands
import main  # import your existing NitroType racing logic

TOKEN = os.getenv("DISCORD_TOKEN")  # Set this in Render environment variables

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def race(ctx, races: int = 1):
    """Starts NitroType races"""
    await ctx.send(f"Starting {races} races!")
    # You need to run your main function asynchronously if possible (use asyncio)
    # For demonstration, let's assume main.main() starts races synchronously
    result = main.main(races)
    await ctx.send(f"Finished {races} races!")

@bot.command()
async def status(ctx):
    """Check bot status/logs"""
    # You could read and send a log file, or stats
    await ctx.send("Bot is running. See logs for details.")

bot.run(TOKEN)
