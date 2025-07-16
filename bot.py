import os
import discord
from flask import Flask
from discord.commands import Option
from discord.ext import commands
import threading
from dotenv import load_dotenv
from fake_useragent import UserAgent
import random

app = Flask(__name__)  # ← This line defines 'app'

# Use the port Render provides, default to 8080 locally
port = int(os.environ.get("PORT", "8080"))
app.run(host='0.0.0.0', port=port)

# If you use your own NitroType logic, import it here
# from main import nitroTypeLogin, mainModule, getProxy

load_dotenv()

ADMIN_ID = int(os.getenv("ADMIN_ID", "1046552485457829909"))
CAPSOLVER_KEY = os.getenv("CAPSOLVER_KEY")
color = 5763719
colorfail = 15548997
denied = "❌"
approved = "✅"

bot = discord.Bot()
ua = UserAgent(platforms="desktop")
tasks = []

def getProxy():
    with open("proxies.txt", "r") as file:
        proxies = [line.strip() for line in file if line.strip()]
        if not proxies:
            raise ValueError("proxies.txt is empty")
        return random.choice(proxies)

def nitroTypeLogin(username, password, userAgent, proxy):
    # Placeholder: You should use your websocket/CAPSOLVER logic here
    # Return (results, userAgent, cookies, racesPlayed, friendsHash, friends_array, stickers)
    return ({"token":"demo"}, userAgent, "cookie", 0, None, None, [1,2,3,4,5])

def mainModule(auth, userAgent, discord_id, username, password, cookies, racesPlayed, friendsHash, friends_array, wpm, race_amount, min_acc, stickers, proxy):
    # Placeholder: Start the racing logic here (use your websocket code for actual NitroType racing)
    pass

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("with NitroType's API"))
    print("[INFO] Your Bot is online")

@bot.slash_command(name='racer', description="Start racing on your Nitrotype account")
async def racer(
    ctx,
    username: Option(str, "Your NitroType username"),
    password: Option(str, "Your NitroType password"),
    wpm: Option(int, "WPM (30-170)", min_value=30, max_value=170),
    race_amount: Option(int, "Number of races (0-5000)", min_value=0, max_value=5000),
    min_accuracy: Option(int, "Minimum accuracy (85-94)", min_value=85, max_value=94)
):
    # Buyer role check
    allowed = any(role.name == "Buyer" for role in ctx.author.roles)
    slots = None
    for role in ctx.author.roles:
        if role.name.startswith("Slots: "):
            slots = int(role.name.replace("Slots: ", ""))
    if not allowed:
        embed = discord.Embed(color=colorfail, description=f"{denied} You are not authorized to use this command")
        await ctx.respond(embed=embed, ephemeral=True)
        return
    if slots is None or slots <= 0:
        embed = discord.Embed(color=colorfail, description=f"{denied} You don't have any slots")
        await ctx.respond(embed=embed, ephemeral=True)
        return
    for task in tasks:
        if task['discord_id'] == ctx.author.id:
            if len(task['tasks']) >= slots:
                embed = discord.Embed(color=colorfail, description=f"{denied} You have used all your slots")
                await ctx.respond(embed=embed, ephemeral=True)
                return
    for task in tasks:
        if task['discord_id'] == ctx.author.id and username.lower() in task['tasks']:
            embed = discord.Embed(color=colorfail, description="You are already botting on this account")
            await ctx.respond(embed=embed, ephemeral=True)
            return
    userAgent = ua.random
    proxy = getProxy()
    embed = discord.Embed(color=color, description="💭 Attempting to login")
    await ctx.respond(embed=embed, ephemeral=True)
    results, userAgent, cookies, racesPlayed, friendsHash, friends_array, stickers = nitroTypeLogin(username, password, userAgent, proxy)
    if results:
        embed = discord.Embed(color=color, description=f"{approved} AutoTyper Z is now running on your account")
        embed.set_footer(text="Thank you for supporting us!")
        await ctx.respond(embed=embed, ephemeral=True)
        race_amount += racesPlayed
        # Start race in a thread
        threading.Thread(target=mainModule, args=(
            results['token'], userAgent, ctx.author.id, username, password, cookies, racesPlayed, friendsHash,
            friends_array, wpm, race_amount, min_accuracy, stickers, proxy
        )).start()
        # Track the task
        found = None
        for i in tasks:
            if i['discord_id'] == ctx.author.id:
                if username.lower() not in i['tasks']:
                    i['tasks'].append(username.lower())
                found = i
        if found is None:
            client_token = {"discord_id": ctx.author.id, "tasks": [username.lower()]}
            tasks.append(client_token)
    else:
        embed = discord.Embed(color=colorfail, description=f"{denied} Your credentials are incorrect")
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name='stopracer', description='Stop racing on your NitroType account')
async def stopracer(ctx, username: Option(str, "NitroType username")):
    for task in tasks:
        if task['discord_id'] == ctx.author.id and username.lower() in task['tasks']:
            task['tasks'].remove(username.lower())
            embed = discord.Embed(color=color, description=f"{approved} Stopped racing for {username}!")
            await ctx.respond(embed=embed, ephemeral=True)
            return
    embed = discord.Embed(color=colorfail, description=f"{denied} {username} isn't on the list")
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name='stopall', description='Stop all races on your accounts')
async def stopall(ctx):
    found = False
    for task in tasks:
        if task['discord_id'] == ctx.author.id:
            task['tasks'].clear()
            found = True
    if found:
        embed = discord.Embed(color=color, description=f"{approved} Stopped racing on all of your accounts")
        await ctx.respond(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(color=colorfail, description=f"{denied} You aren't botting on any accounts")
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="tasks", description="Show your active accounts")
async def task(ctx):
    user_tasks = [task['tasks'] for task in tasks if ctx.author.id == task['discord_id']]
    if user_tasks and user_tasks[0]:
        usernames = user_tasks[0]
        response = f"{approved} Accounts being botted:\n" + "\n".join(f"{idx + 1}. {username}" for idx, username in enumerate(usernames))
        await ctx.respond(response, ephemeral=True)
    else:
        await ctx.respond(f"{denied} You have no accounts being botted", ephemeral=True)

@bot.slash_command(name="slots", description="Check how many slots you have")
async def slots(ctx):
    slots = None
    for role in ctx.author.roles:
        if role.name.startswith("Slots: "):
            slots = int(role.name.replace("Slots: ", ""))
    if slots is None:
        embed = discord.Embed(color=colorfail, description=f"{denied} You don't have any slots")
        await ctx.respond(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(color=color, description=f"{approved} You have {slots} slots!")
        await ctx.respond(embed=embed, ephemeral=True)

# Admin commands
@bot.slash_command(name="admintasks", description="(Admin) Shows your active accounts")
async def admintasks(ctx, discord_id: Option(str, "Discord user ID")):
    if ctx.author.id == ADMIN_ID:
        discord_id = int(discord_id)
        user_tasks = [task['tasks'] for task in tasks if discord_id == task['discord_id']]
        if user_tasks and user_tasks[0]:
            usernames = user_tasks[0]
            response = f"{approved} Accounts being botted:\n" + "\n".join(f"{idx + 1}. {username}" for idx, username in enumerate(usernames))
            await ctx.respond(response, ephemeral=True)
        else:
            await ctx.respond(f"{denied} That person has no accounts being botted", ephemeral=True)
    else:
        embed = discord.Embed(color=colorfail, description="You are unauthorized to use this command")
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name='adminstopall', description='(Admin) Stop all races on your accounts')
async def adminstopall(ctx, discord_id: Option(str, "Discord user ID")):
    if ctx.author.id == ADMIN_ID:
        found = False
        for task in tasks:
            if task['discord_id'] == int(discord_id):
                task['tasks'].clear()
                found = True
        if found:
            embed = discord.Embed(color=color, description=f"{approved} Stopped racing on all of your accounts")
            await ctx.respond(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(color=colorfail, description=f"{denied} You aren't botting on any accounts")
            await ctx.respond(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(color=colorfail, description=f"{denied} You are unauthorized to use this command")
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name='stats', description="(Admin) Show bot usage stats")
async def stats(ctx):
    if ctx.author.id == ADMIN_ID:
        bot_stats = {}
        for task in tasks:
            user_id = task['discord_id']
            num_bots = len(task['tasks'])
            if num_bots > 0:
                bot_stats[f"<@{user_id}>"] = num_bots
        total_bots = sum(bot_stats.values())
        stats_message = "\n".join(f"{user}: {num_bots} bots" for user, num_bots in bot_stats.items())
        stats_message += f"\nTotal bots: {total_bots}"
        await ctx.respond(content=stats_message, ephemeral=True)
    else:
        embed = discord.Embed(color=colorfail, description=f"{denied} You are unauthorized to use this command")
        await ctx.respond(embed=embed, ephemeral=True)

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
