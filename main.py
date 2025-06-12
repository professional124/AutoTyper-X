"""
Complete v2 module of AutoTyper XYZ

- Message for ssl
We still used some of the modules from old appllo - https://github.com/sslprograms/BetterRioSourceCode
We completely bypassed the captcha without capsolver but code will not be shown here
Thank you for letting us buy your old code for $200; I didn't think you'd expect I knew how to code but I'll let you dominate once more if you want
"""

# Required Python Modules
from discord.commands import Option
from discord.ext import commands
from fake_useragent import UserAgent
import cloudscraper
import websocket
import threading
import discord
import random
import requests
import string
import json
import time
import os
import ssl
import sys

# Discord Bot Parameters
ADMIN_ID = 1046552485457829909
bot = discord.Bot()
color = 5763719
colorfail = 15548997
denied = "❌"
approved = "✅"

# NitroType Bot Parameters
CAPSOLVER_KEY = 'CAP-FBN383FNB38FBNEWFFNBUM31FBE'
ua = UserAgent(platforms="desktop")
tasks = []

# Get Hashes from Bootstrap
def getVersion():
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'max-age=0',
        'dnt': '1',
        'priority': 'u=0, i',
        'referer': 'https://www.nitrotype.com/login',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }
    r = requests.get('https://www.nitrotype.com/garage', headers=headers).text.split('<script src="/index/')[1].split('/bootstrap.js"')[0].split('-')
    return r

VERSION_HASH, VERSION_INT = getVersion()

# Retrieve Proxy
def getProxy():
    with open("proxies.txt", "r") as file:
        proxies = [line.strip() for line in file if line.strip()]
        if not proxies:
            raise ValueError("proxies.txt is empty")
        return random.choice(proxies)

# Utilizes Capsolver
def solveCaptcha(key):
    # doesn't respam capsolver like appllo
    while True:
        payload = {
            "clientKey": key,
            "appId": "F9CD90DA-D213-4AF8-9B44-B1E0C4A8201D",
            "task": {
                "type": 'ReCaptchaV2TaskProxyLess',
                "websiteURL": "https://www.nitrotype.com",
                "websiteKey": "6Ldn5v8UAAAAAE5PrdgV4hHlWZSXxGR2QsItv_hM",
            }
        }
        res = requests.post("https://api.capsolver.com/createTask", json=payload)
        resp = res.json()
        task_id = resp.get("taskId")
        if not task_id:
            continue

        while True:
            time.sleep(3)
            payload = {"clientKey": key, "taskId": task_id}
            res = requests.post("https://api.capsolver.com/getTaskResult", json=payload)
            resp = res.json()
            status = resp.get("status")
            if status == "ready":
                return resp.get("solution", {}).get('gRecaptchaResponse')
            elif status == "failed" or resp.get("errorId"):
                break

# NitroType Modules
def calculate_typing_time_per_letter(wpm, num_words):
    total_letters = num_words * 5 
    total_seconds = (60 / wpm) * num_words
    seconds_per_letter = total_seconds / total_letters
    return seconds_per_letter

def removeBeg(text):
    return json.loads(text[1:])

def startTyping(client, words, set_wpm, min_acc):
    target_accuracy = random.uniform(min_acc, 98) / 100
    error_probability = 1 - target_accuracy
    c = 0
    e = 0
    rounds = 0        
    word_s = words.replace(' ', ' \n').split('\n')
    tex_ = ''
    for word_group in word_s:
        packet_count = 0
        packet = []
        rounds += 1
        for char in word_group:
            c += 1
            if random.random() < error_probability:
                wrong_char = random.choice([ch for ch in string.ascii_letters if ch != char])
                e += 1
                client.send(
                    '5' + json.dumps(
                        {"stream": "race", "msg": "update", "payload": {"e": e, "k": [[wrong_char, random.randint(1, 500), 1, None]]}},separators=(',', ':')
                    )
                )
            packet.append([char, random.randint(1, 500), None, None])
            time.sleep(calculate_typing_time_per_letter(random.randint(set_wpm - 15, set_wpm + 15), len(words) / 5))
            total_delay = sum(p[1] for p in packet if p[1])
            if total_delay >= 450 or len(packet) >= 5:
                client.send(
                    '5' + json.dumps(
                        {"stream": "race", "msg": "update", "payload": {"t": c, "k": packet}},separators=(',', ':')
                    )
                )
                packet_count += len(packet)
                tex_ += ''.join(p[0] for p in packet)
                packet = []
            elif packet_count + len(packet) == len(word_group):
                client.send(
                    '5' + json.dumps(
                        {"stream": "race", "msg": "update", "payload": {"t": c, "k": packet}},separators=(',', ':')
                    )
                )
                packet_count += len(packet)
                tex_ += ''.join(p[0] for p in packet)
                packet = []

def nitroTypeLogin(username, password, userAgent, proxy):
    with requests.Session() as session:
        proxy = {
            'http': proxy,
            'https': proxy
        }
        session.proxies = proxy
        session.headers['origin'] = 'https://www.nitrotype.com'
        session.headers['referer'] = 'https://www.nitrotype.com/login'
        session.headers['user-agent'] = userAgent
        session.headers['x-username'] = username
        session.get('https://nitrotype.com/login')
        login = session.post(
            'https://www.nitrotype.com/api/v2/auth/login/username',
            json={
                'username': username,
                'password': password,
                'captchaToken': '',
                'authCode': '',
                'trustDevice': False,
                'tz': 'America/Chicago',
            }
        )
        if login.status_code == 200:
            if login.json()['status'] == 'OK':
                cookies = session.cookies
                cookies = '; '.join([cookie.name + '=' + cookie.value for cookie in cookies])
                racesPlayed = login.json().get('results', {}).get('racesPlayed')
                friends_array = []
                stickerIDS = [item['lootID'] for item in json.loads(login.text)['results']['loot'] if item['type'] == 'sticker' and item['equipped'] > 0]
                if stickerIDS == []:
                    stickerIDS = [1, 2, 3, 4, 5, 28] # default for new users
                if "friends" in login.text:
                    friendsHash = login.json().get('results', {}).get('friendsHash')
                    for friend in login.json()['results'].get('friends', []):
                        friends_array.append(friend['userID'])
                else:
                    friends_array = None
                    friendsHash = None
                return login.json()['results'], userAgent, cookies, racesPlayed, friendsHash, friends_array, stickerIDS
            
        elif "No account found" in login.text or "Blocked" in login.text:
            return None, None, None, None, None, None, None
        else:
            cap = solveCaptcha(CAPSOLVER_KEY) # doesn't use a while true loop
            login = session.post(
                'https://www.nitrotype.com/api/v2/auth/login/username',
                json = {
                    'username': username,
                    'password': password,
                    'captchaToken': cap,
                    'authCode': '',
                    'trustDevice': False,
                    'tz': 'America/Chicago',
                }
            )
            if login.status_code == 200:
                if login.json()['status'] == 'OK':
                    cookies = session.cookies
                    cookies = '; '.join([cookie.name + '=' + cookie.value for cookie in cookies])
                    racesPlayed = login.json().get('results', {}).get('racesPlayed')
                    friends_array = []
                    stickerIDS = [item['lootID'] for item in json.loads(login.text)['results']['loot'] if item['type'] == 'sticker' and item['equipped'] > 0]
                    if stickerIDS == []:
                        stickerIDS = [1, 2, 3, 4, 5, 28]
                    if "friends" in login.text:
                        friendsHash = login.json().get('results', {}).get('friendsHash')
                        for friend in login.json()['results'].get('friends', []):
                            friends_array.append(friend['userID'])
                    else:
                        friends_array = None
                        friendsHash = None
                    return login.json()['results'], userAgent, cookies, racesPlayed, friendsHash, friends_array, stickerIDS
            else:
                return None, None, None, None, None, None, None

def sendSticker(client, stickers):
    time.sleep(random.uniform(0, 2))
    randomSticker = int(random.choice(stickers))
    client.send(
        '5' + json.dumps({"stream":"race","msg":"chat","payload":{"chatID":randomSticker, "chatType":"sticker"}},separators=(',', ':')
        )
    )

def mainModule(auth, userAgent, discord_id, username, password, cookies, racesPlayed, friendsHash, friends_array, wpm, race_amount, min_acc, stickers, proxy):
    found = None
    for i in tasks:
        if i['discord_id'] == discord_id:
            if username.lower() not in i['tasks']:
                i['tasks'].append(username.lower())
            found = i

    if found is None:
        client_token = {
            "discord_id": discord_id,
            "tasks": [username.lower()]
        }
        tasks.append(client_token)

    headers = {
        'Upgrade': 'websocket',
        'Origin': 'https://www.nitrotype.com',
        'Connection': 'Upgrade',
        'User-Agent': userAgent,
        'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Extensions': 'permessage-deflate; client_max_window_bits',
        'Cookie': cookies,
    }
    while True: 
        try:
            for i in tasks:
                if i['discord_id'] == discord_id:
                    racers_ = i['tasks']    
                    if racers_.count(username) == 0:
                        break

            if username.lower() not in racers_:
                break 

            if race_amount <= racesPlayed:
                for task in tasks:
                    if task['discord_id'] == discord_id:
                        task['tasks'].remove(username.lower())
                        return

            game_text = ''
            proxy_host, proxy_port = proxy.split(':')
            client = websocket.create_connection(f'wss://realtime1ws.nitrotype.com/ws?token='+auth, header=headers, sslopt={"cert_reqs": ssl.CERT_REQUIRED, "ssl_version":ssl.PROTOCOL_TLSv1_2, 'check_host':True}, http_proxy_host=proxy_host, http_proxy_port=int(proxy_port))
            if friendsHash and friends_array is not None:
                client.send(
                    '5' + json.dumps({"stream":"notifications","type":"checkin","payload":{"path":"/race","friends":friends_array,"friendsHash":friendsHash,"racesPlayed":racesPlayed}},separators=(',', ':') 
                    )
                )
            else:
                client.send(
                    '5' + json.dumps({"stream":"notifications","type":"checkin","payload":{"path":"/race","racesPlayed":racesPlayed}},separators=(',', ':')
                    )
                ) 
            client.send(
                '5' + json.dumps(
                {"stream": "race", "msg": "join", "payload": {"update": f"03417", "cacheId": VERSION_HASH, "cacheIdInteger": VERSION_INT, "site": "nitrotype"}},separators=(',', ':')
                )
            )
            while True:
                try:
                    recv = client.recv()
                    # Was kinda lazy to set it on the bottom
                    if recv == '''5{"stream":"error","type":"invalid session"}''':
                        results, userAgent, cookies, racesPlayed, friendsHash, friends_array, stickers = nitroTypeLogin(username, password, userAgent, proxy)
                        if results is None:
                            for task in tasks:
                                if task['discord_id'] == discord_id:
                                    task['tasks'].remove(username.lower())
                                    return
                        auth = results['token']
                        headers['Cookie'] = cookies
                        client.close()
                        break

                    if "experience" in recv:
                        racesPlayed += 1
                        client.close()
                        break

                    if recv == '1PING':
                        client.send("1PONG")
                        continue

                    if removeBeg(recv)['stream'] == 'notifications':
                        continue

                    if removeBeg(recv)['stream'] == 'auth':
                        auth = removeBeg(recv)['token']
                        continue

                    if removeBeg(recv)['msg'] == 'status':
                        if removeBeg(recv)['payload'].get('l') is not None:
                            game_text += removeBeg(recv)['payload']['l']
                            if random.randint(1,3) == 1:
                                threading.Thread(target=sendSticker, args=(client, stickers)).start()

                        if removeBeg(recv)['payload']['status'] == 'racing':
                            # You can customize this if you want
                            set_wpm = random.randint(wpm - 10, wpm + 10)
                            threading.Thread(target=startTyping, args=(client, game_text, set_wpm, min_acc,)).start()

                    if removeBeg(recv)['msg'] == 'error':
                        if removeBeg(recv)['payload']['type'] == 'captcha':
                            results, userAgent, cookies, racesPlayed, friendsHash, friends_array, stickers = nitroTypeLogin(username, password, userAgent, proxy)
                            if results is None:
                                for task in tasks:
                                    if task['discord_id'] == discord_id:
                                        task['tasks'].remove(username.lower())
                                        return
                            auth = results['token']
                            headers['Cookie'] = cookies
                            client.close()
                            break

                        if removeBeg(recv)['payload']['type'] == 'in race':
                            time.sleep(3)
                            client.close()
                            break
                except:
                    client.close()
                    break
        except:
            mainModule(auth, userAgent, discord_id, username, password, cookies, racesPlayed, friendsHash, friends_array, wpm, race_amount, min_acc, stickers, proxy)
            continue

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game("with NitroType's API"))
    print("[INFO] Your Bot is online")

@bot.slash_command(name='racer', description="Start racing on your Nitrotype account")
async def racer(ctx, username, password, wpm: Option(int, min_value=30, max_value=170), race_amount: Option(int, min_value=0, max_value=5000), min_accuracy: Option(int, min_value=85, max_value=94)):
    # Checks if the user has buyer role
    allowed = False
    for role in ctx.author.roles:
        if role.name in ["Buyer"]: # you can edit this if you want
            allowed = True

    # Checks if the user has any slots
    slots = None
    for role in ctx.author.roles:
        if role.name.startswith("Slots: "):
            slots_str = role.name.replace("Slots: ", "")
            slots = int(slots_str)

    if allowed != True:
        embed = discord.Embed(color=colorfail, description=f"{denied} You are not authorized to use this command")
        await ctx.respond(embed=embed, ephemeral=True)
        return

    if slots is None or slots <= 0:
        embed = discord.Embed(color=colorfail, description=f"{denied} You don't have any slots")
        await ctx.respond(embed=embed, ephemeral=True)
        return

    for task in tasks:
        if task['discord_id'] == ctx.author.id:  
            if len(task['tasks']) >=slots:
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
        threading.Thread(target=mainModule, args=(results['token'], userAgent, ctx.author.id, username, password, cookies, racesPlayed, friendsHash, friends_array, wpm, race_amount, min_accuracy, stickers, proxy)).start()
    else:
        embed = discord.Embed(color=colorfail, description=f"{denied} Your credentials are incorrect")
        await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name='stopracer', description='Stop racing on your NitroType account')
async def stopracer(ctx, username):
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
            slots_str = role.name.replace("Slots: ", "")
            slots = int(slots_str)
    
    if slots is None:
        embed = discord.Embed(color=colorfail, description=f"{denied} You don't have any slots")
        await ctx.respond(embed=embed, ephemeral=True)
        return
    else:
        embed = discord.Embed(color=color, description=f"{approved} You have {slots} slots!")
        await ctx.respond(embed=embed, ephemeral=True)

# Admin Commands
@bot.slash_command(name="admintasks", description="(Admin) Shows your active accounts")
async def admintasks(ctx, discord_id):
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
async def adminstopall(ctx, discord_id: str):
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

bot.run("Bot Token Here")
