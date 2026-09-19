import os
import json
import asyncio
import random
import discord
from discord.ext import commands, tasks
import aiohttp

# --- ENVIRONMENT VARIABLES ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL")

try:
    NOTIFICATION_CHANNEL_ID = int(os.getenv("NOTIFICATION_CHANNEL_ID", "0"))
except ValueError:
    NOTIFICATION_CHANNEL_ID = 0

try:
    AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "0"))
except ValueError:
    AUTO_ROLE_ID = 0

# --- INTENTS CONFIGURATION ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

twitch_token = None
is_live = False
xp_data = {}

# --- XP SYSTEM (MEE6) ---
def load_xp():
    global xp_data
    if os.path.exists("levels.json"):
        try:
            with open("levels.json", "r") as f:
                xp_data = json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden der levels.json: {e}")
            xp_data = {}

def save_xp():
    try:
        with open("levels.json", "w") as f:
            json.dump(xp_data, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern der levels.json: {e}")

load_xp()

# --- TWITCH HELIX API ---
async def get_twitch_token():
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        return None
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("access_token")
    except Exception as e:
        print(f"Twitch Token Fehler: {e}")
    return None

@tasks.loop(minutes=2)
async def check_twitch_live():
    global twitch_token, is_live
    if not TWITCH_CLIENT_ID or not TWITCH_CHANNEL or NOTIFICATION_CHANNEL_ID == 0:
        return

    if not twitch_token:
        twitch_token = await get_twitch_token()
        if not twitch_token:
            return

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {twitch_token}"
    }
    url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_CHANNEL}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    twitch_token = await get_twitch_token()
                    return
                if resp.status == 200:
                    data = await resp.json()
                    stream_data = data.get("data", [])

                    if stream_data and not is_live:
                        is_live = True
                        stream_info = stream_data[0]
                        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
                        if channel:
                            embed = discord.Embed(
                                title=f"🔴 {TWITCH_CHANNEL} ist jetzt LIVE auf Twitch!",
                                description=stream_info.get("title", "Kommt vorbei!"),
                                color=0x9146FF,
                                url=f"https://twitch.tv/{TWITCH_CHANNEL}"
                            )
                            embed.set_field(name="Kategorie", value=stream_info.get("game_name", "Unbekannt"))
                            embed.set_image(url=stream_info.get("thumbnail_url", "").format(width=1280, height=720))
                            embed.set_footer(text="Murhat Bot • Twitch Notification")
                            await channel.send(content="@everyone Der Stream startet jetzt!", embed=embed)

                    elif not stream_data and is_live:
                        is_live = False
    except Exception as e:
        print(f"Fehler beim Twitch-Loop: {e}")

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user.name} ist eingeloggt und voll einsatzbereit!")
    await bot.change_presence(activity=discord.Streaming(name=f"Twitch: {TWITCH_CHANNEL or 'Stream'}", url=f"https://twitch.tv/{TWITCH_CHANNEL or ''}"))
    if not check_twitch_live.is_running():
        check_twitch_live.start()

@bot.event
async def on_member_join(member):
    if AUTO_ROLE_ID != 0:
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"Konnte Auto-Rolle nicht vergeben: {e}")

    if NOTIFICATION_CHANNEL_ID != 0:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="👋 Willkommen auf dem Server!",
                description=f"Hey {member.mention}, schön dass du am Start bist!",
                color=0x3498DB
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # XP System
    user_id = str(message.author.id)
    if user_id not in xp_data:
        xp_data[user_id] = {"xp": 0, "level": 1}

    xp_data[user_id]["xp"] += random.randint(10, 20)
    current_xp = xp_data[user_id]["xp"]
    current_level = xp_data[user_id]["level"]

    next_level_xp = current_level * 100
    if current_xp >= next_level_xp:
        xp_data[user_id]["level"] += 1
        save_xp()
        await message.channel.send(f"🎉 Gratulation {message.author.mention}, du bist jetzt **Level {current_level + 1}**!")
    else:
        save_xp()

    await bot.process_commands(message)

# --- BOT COMMANDS ---
@bot.command()
async def ping(ctx):
    """Test-Befehl um die Latenz zu prüfen."""
    await ctx.send(f"🏓 Pong! Latenz: {round(bot.latency * 1000)}ms")

@bot.command()
async def rank(ctx, member: discord.Member = None):
    """Zeigt dein aktuelles Level und deine XP an."""
    member = member or ctx.author
    user_id = str(member.id)
    if user_id in xp_data:
        lvl = xp_data[user_id]["level"]
        xp = xp_data[user_id]["xp"]
        await ctx.send(f"📊 **{member.display_name}** ist Level **{lvl}** ({xp} XP total).")
    else:
        await ctx.send(f"📊 **{member.display_name}** hat noch keine XP gesammelt.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    """Löscht eine bestimmte Anzahl an Nachrichten."""
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"🧹 Es wurden **{amount}** Nachrichten gelöscht.")
    await asyncio.sleep(3)
    await msg.delete()

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Kein Grund angegeben"):
    """Kickt ein Mitglied vom Server."""
    await member.kick(reason=reason)
    await ctx.send(f"👢 **{member.display_name}** wurde gekickt. Grund: {reason}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Kein Grund angegeben"):
    """Bannt ein Mitglied vom Server."""
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.display_name}** wurde gebannt. Grund: {reason}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ FEHLER: Kein DISCORD_TOKEN in den Env-Variablen gefunden!")
    else:
        bot.run(DISCORD_TOKEN)
