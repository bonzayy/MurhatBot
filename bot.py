import os
import json
import asyncio
import random
import re
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
bot.remove_command("help")  # Standard-Help deaktivieren für eigene Übersicht

# --- BLACKLIST (Rassismus / Extremismus) ---
BLACKLIST = [
    "nigga", "nigger", "neger", "niggah",
    "chink", "spic", "kyke", "kike",
    "siegheil", "heilhitler", "hakenkreuz"
]

# --- DATA PERSISTENCE (XP & WARNS) ---
xp_data = {}
warns_data = {}

def load_data():
    global xp_data, warns_data
    if os.path.exists("levels.json"):
        try:
            with open("levels.json", "r") as f:
                xp_data = json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden von levels.json: {e}")

    if os.path.exists("warns.json"):
        try:
            with open("warns.json", "r") as f:
                warns_data = json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden von warns.json: {e}")

def save_xp():
    try:
        with open("levels.json", "w") as f:
            json.dump(xp_data, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern von levels.json: {e}")

def save_warns():
    try:
        with open("warns.json", "w") as f:
            json.dump(warns_data, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern von warns.json: {e}")

load_data()

# --- TWITCH HELIX API ---
twitch_token = None
is_live = False

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

# --- UI VIEWS (BUTTONS) ---
class SocialsView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(discord.ui.Button(label="YouTube", url="https://youtube.com", style=discord.ButtonStyle.link, emoji="🔴"))
        self.add_item(discord.ui.Button(label="Twitch", url=f"https://twitch.tv/{TWITCH_CHANNEL}" if TWITCH_CHANNEL else "https://twitch.tv", style=discord.ButtonStyle.link, emoji="💜"))
        self.add_item(discord.ui.Button(label="TikTok", url="https://tiktok.com", style=discord.ButtonStyle.link, emoji="🎵"))
        self.add_item(discord.ui.Button(label="Instagram", url="https://instagram.com", style=discord.ButtonStyle.link, emoji="📸"))

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user.name} ist eingeloggt und voll einsatzbereit!")
    stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL}" if TWITCH_CHANNEL else "https://www.twitch.tv"
    await bot.change_presence(activity=discord.Streaming(name=f"Twitch: {TWITCH_CHANNEL or 'Stream'}", url=stream_url))
    
    if not check_twitch_live.is_running():
        check_twitch_live.start()

@bot.event
async def on_member_join(member):
    # Auto-Rolle vergeben
    if AUTO_ROLE_ID != 0:
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"Konnte Auto-Rolle nicht vergeben: {e}")

    # Willkommensnachricht im festgelegten Welcome-Kanal
    if NOTIFICATION_CHANNEL_ID != 0:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if channel:
            await channel.send(f"Was geht {member.mention} du junkie")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. AUTO-MOD (BLACK FILTER MIT BYPASS-SCHUTZ)
    cleaned_content = re.sub(r'[^a-zA-Z0-9]', '', message.content.lower())
    if any(word in cleaned_content for word in BLACKLIST):
        try:
            await message.delete()
        except Exception as e:
            print(f"Fehler beim Löschen der Nachricht: {e}")

        try:
            await message.author.kick(reason="Verwendung von verbotener rassistischer Sprache")
            await message.channel.send(f"🚫 **{message.author.mention}** wurde automatisch gekickt (Verbotene Sprache).")
        except Exception as e:
            await message.channel.send(f"⚠️ **{message.author.mention}** hat verbotene Wörter genutzt, konnte aber nicht gekickt werden.")
        return

    # 2. XP SYSTEM
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
@bot.command(name="commands", aliases=["help"])
async def show_commands(ctx):
    """Zeigt eine detaillierte Übersicht aller verfügbaren Befehle an."""
    embed = discord.Embed(
        title="🤖 Murhat Bot – Befehlsübersicht",
        description="Hier ist eine Übersicht aller Befehle, wie du sie nutzt und wofür sie da sind:",
        color=0x3498DB
    )
    
    embed.add_field(
        name="📊 Allgemeine Befehle",
        value=(
            "`!commands` / `!help` – Zeigt diese Befehlsübersicht an.\n"
            "`!ping` – Prüft die aktuelle Latenz des Bots.\n"
            "`!rank [@User]` – Zeigt dein Level & deine Gesamt-XP an.\n"
            "`!socials` – Zeigt das Social-Media Embed mit Anklick-Buttons."
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚠️ Verwarnungssystem",
        value=(
            "`!warn @User [Grund]` – Verwarnt ein Mitglied (ab 3 Warns erfolgt ein Kick).\n"
            "`!warnings [@User]` – Zeigt alle bisherigen Verwarnungen an.\n"
            "`!clearwarns @User` – Setzt alle Verwarnungen eines Mitglieds auf 0 zurück *(Admin)*."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛡️ Moderation & Server-Schutz",
        value=(
            "`!clear <Anzahl>` – Löscht Chat-Nachrichten *(Mod)*.\n"
            "`!kick @User [Grund]` – Kickt ein Mitglied vom Server *(Mod)*.\n"
            "`!ban @User [Grund]` – Bannt ein Mitglied dauerhaft vom Server *(Mod)*."
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Automatische Features (ohne Befehl)",
        value=(
            "• **Auto-Mod Filter:** Löscht rassistische Wörter automatisch und kickt den Absender.\n"
            "• **Twitch Live-Alerts:** Benachrichtigt den Server automatisch bei Live-Streams.\n"
            "• **XP-System:** Vergibt beim Schreiben im Chat automatisch Level-Punkte.\n"
            "• **Auto-Rolle:** Gibt neuen Mitgliedern beim Beitritt automatisch eine Rolle."
        ),
        inline=False
    )

    embed.set_footer(text="Murhat Bot • Community Management")
    await ctx.send(embed=embed)

@bot.command()
async def socials(ctx):
    """Zeigt ein Embed mit Social Media Links und Klick-Buttons."""
    embed = discord.Embed(
        title="🔥 Unsere Socials & Netzwerke",
        description="Verpasse keinen Stream, kein Video und keinen Content mehr!",
        color=0x9B59B6
    )
    embed.add_field(name="YouTube", value="[Lass ein Abo da!](https://youtube.com)", inline=True)
    embed.add_field(name="Twitch", value="[Komm in den Stream!](https://twitch.tv)", inline=True)
    embed.add_field(name="TikTok", value="[Lasst ein Follow da!](https://tiktok.com)", inline=True)
    embed.set_footer(text="Murhat Community — Danke für euren Support! ❤️")
    
    await ctx.send(embed=embed, view=SocialsView())

@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latenz: {round(bot.latency * 1000)}ms")

@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = str(member.id)
    if user_id in xp_data:
        lvl = xp_data[user_id]["level"]
        xp = xp_data[user_id]["xp"]
        await ctx.send(f"📊 **{member.display_name}** ist Level **{lvl}** ({xp} XP total).")
    else:
        await ctx.send(f"📊 **{member.display_name}** hat noch keine XP gesammelt.")

# --- WARN COMMANDS ---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="Kein Grund angegeben"):
    if member.bot:
        await ctx.send("❌ Du kannst keine Bots verwarnen.")
        return

    user_id = str(member.id)
    if user_id not in warns_data:
        warns_data[user_id] = []

    warns_data[user_id].append({"reason": reason, "warned_by": str(ctx.author)})
    save_warns()

    total_warns = len(warns_data[user_id])
    embed = discord.Embed(
        title="⚠️ Mitglied verwarnt",
        description=f"{member.mention} wurde verwarnt!\n**Grund:** {reason}\n**Gesamt-Warns:** {total_warns}",
        color=0xE74C3C
    )
    await ctx.send(embed=embed)

    if total_warns >= 3:
        try:
            await member.kick(reason="3 Verwarnungen erreicht.")
            await ctx.send(f"👢 {member.mention} wurde automatisch gekickt, da 3 Verwarnungen erreicht wurden!")
        except Exception as e:
            await ctx.send(f"❌ Konnte {member.mention} nicht automatisch kicken: {e}")

@bot.command()
async def warnings(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = str(member.id)
    if user_id not in warns_data or not warns_data[user_id]:
        await ctx.send(f"✅ **{member.display_name}** hat keine Verwarnungen.")
        return

    embed = discord.Embed(title=f"⚠️ Verwarnungen von {member.display_name}", color=0xF1C40F)
    for i, warn_info in enumerate(warns_data[user_id], 1):
        embed.add_field(name=f"Warn #{i}", value=f"**Grund:** {warn_info['reason']}\n**Von:** {warn_info['warned_by']}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def clearwarns(ctx, member: discord.Member):
    user_id = str(member.id)
    if user_id in warns_data:
        warns_data[user_id] = []
        save_warns()
        await ctx.send(f"🧹 Alle Verwarnungen von **{member.display_name}** wurden gelöscht.")
    else:
        await ctx.send(f"ℹ️ **{member.display_name}** hat keine Verwarnungen.")

# --- MODERATION COMMANDS ---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"🧹 Es wurden **{amount}** Nachrichten gelöscht.")
    await asyncio.sleep(3)
    await msg.delete()

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Kein Grund angegeben"):
    await member.kick(reason=reason)
    await ctx.send(f"👢 **{member.display_name}** wurde gekickt. Grund: {reason}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Kein Grund angegeben"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.display_name}** wurde gebannt. Grund: {reason}")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ FEHLER: Kein DISCORD_TOKEN in den Env-Variablen gefunden!")
    else:
        bot.run(DISCORD_TOKEN)
