import os
import json
import asyncio
import random
import re
import datetime
import discord
from discord.ext import commands, tasks
import aiohttp

# --- ENVIRONMENT VARIABLES ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL")

try:
    TWITCH_CHANNEL_ID = int(os.getenv("TWITCH_CHANNEL_ID", os.getenv("NOTIFICATION_CHANNEL_ID", "0")))
except ValueError:
    TWITCH_CHANNEL_ID = 0

try:
    WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
except ValueError:
    WELCOME_CHANNEL_ID = 0

try:
    AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "0"))
except ValueError:
    AUTO_ROLE_ID = 0

# Kanal-ID für die Beichten (privater Mod-Kanal)
try:
    CONFESSION_CHANNEL_ID = int(os.getenv("CONFESSION_CHANNEL_ID", "0"))
except ValueError:
    CONFESSION_CHANNEL_ID = 0

# --- INTENTS CONFIGURATION ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

# --- BLACKLIST ---
BLACKLIST = [
    "nigga", "nigger", "neger", "niggah",
    "chink", "spic", "kyke", "kike",
    "siegheil", "heilhitler", "hakenkreuz"
]

# --- DATA PERSISTENCE (WARNS & ECONOMY) ---
warns_data = {}
economy_data = {}

def load_data():
    global warns_data, economy_data
    if os.path.exists("warns.json"):
        try:
            with open("warns.json", "r") as f:
                warns_data = json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden von warns.json: {e}")

    if os.path.exists("economy.json"):
        try:
            with open("economy.json", "r") as f:
                economy_data = json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden von economy.json: {e}")

def save_warns():
    try:
        with open("warns.json", "w") as f:
            json.dump(warns_data, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern von warns.json: {e}")

def save_economy():
    try:
        with open("economy.json", "w") as f:
            json.dump(economy_data, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern von economy.json: {e}")

def get_balance(user_id: str) -> int:
    if user_id not in economy_data:
        economy_data[user_id] = {"coins": 500, "last_daily": None}
        save_economy()
    return economy_data[user_id]["coins"]

def update_balance(user_id: str, amount: int):
    get_balance(user_id)
    economy_data[user_id]["coins"] += amount
    save_economy()

load_data()

# --- ANONYMES BEICHTSTUHL MODAL (POPUP) ---
class ConfessionModal(discord.ui.Modal, title="🤫 Anonyme Beichte einreichen"):
    confession_text = discord.ui.TextInput(
        label="Deine Geschichte / Beichte",
        style=discord.TextStyle.paragraph,
        placeholder="Schreib deine Beichte hier rein... (Keine Namen oder IPs werden gespeichert!)",
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        target_channel_id = CONFESSION_CHANNEL_ID
        if target_channel_id == 0:
            await interaction.response.send_message("❌ Es wurde noch keine `CONFESSION_CHANNEL_ID` in den Umgebungsvariablen eingerichtet!", ephemeral=True)
            return

        channel = interaction.client.get_channel(target_channel_id)
        if not channel:
            try:
                channel = await interaction.client.fetch_channel(target_channel_id)
            except Exception as e:
                print(f"Fehler beim Laden des Beichtstuhl-Kanals: {e}")
                channel = None

        if not channel:
            await interaction.response.send_message("❌ Der Mod-Kanal für Beichten konnte nicht gefunden werden.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🤫 Neue Anonyme Beichte",
            description=self.confession_text.value,
            color=0x9146FF,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text="Anonymer Beichtstuhl • Live-Stream Content")

        await channel.send(embed=embed)
        await interaction.response.send_message("✅ Deine Beichte wurde **komplett anonym** an das Mod-Team geschickt! Danke!", ephemeral=True)

# --- UI VIEWS ---
class TwitchStreamView(discord.ui.View):
    def __init__(self, stream_url):
        super().__init__()
        self.add_item(discord.ui.Button(
            label="Watch Stream",
            url=stream_url,
            style=discord.ButtonStyle.link,
            emoji="📺"
        ))

class SocialsView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(discord.ui.Button(label="YouTube", url="https://youtube.com", style=discord.ButtonStyle.link, emoji="🔴"))
        self.add_item(discord.ui.Button(label="Twitch", url=f"https://twitch.tv/{TWITCH_CHANNEL}" if TWITCH_CHANNEL else "https://twitch.tv", style=discord.ButtonStyle.link, emoji="💜"))
        self.add_item(discord.ui.Button(label="TikTok", url="https://tiktok.com", style=discord.ButtonStyle.link, emoji="🎵"))
        self.add_item(discord.ui.Button(label="Instagram", url="https://instagram.com", style=discord.ButtonStyle.link, emoji="📸"))

# --- TWITCH HELIX API & LOOP ---
twitch_token = None
is_live = False

async def get_twitch_token():
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        print("❌ FEHLER: TWITCH_CLIENT_ID oder TWITCH_CLIENT_SECRET fehlt!")
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
                else:
                    print(f"❌ Twitch Token API Fehler Status: {resp.status}")
    except Exception as e:
        print(f"Twitch Token Fehler: {e}")
    return None

@tasks.loop(minutes=1)
async def check_twitch_live():
    global twitch_token, is_live
    if not TWITCH_CLIENT_ID or not TWITCH_CHANNEL or TWITCH_CHANNEL_ID == 0:
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
                        
                        channel = bot.get_channel(TWITCH_CHANNEL_ID)
                        if not channel:
                            try:
                                channel = await bot.fetch_channel(TWITCH_CHANNEL_ID)
                            except Exception as fetch_err:
                                print(f"❌ Konnte Kanal {TWITCH_CHANNEL_ID} nicht laden: {fetch_err}")
                                channel = None

                        if channel:
                            stream_url = f"https://twitch.tv/{TWITCH_CHANNEL}"
                            title = stream_info.get("title", "Komm rein!")
                            
                            avatar_url = ""
                            user_url = f"https://api.twitch.tv/helix/users?login={TWITCH_CHANNEL}"
                            async with session.get(user_url, headers=headers) as u_resp:
                                if u_resp.status == 200:
                                    u_data = await u_resp.json()
                                    if u_data.get("data"):
                                        avatar_url = u_data["data"][0].get("profile_image_url", "")

                            embed = discord.Embed(
                                title=title,
                                url=stream_url,
                                color=0x9146FF
                            )
                            if avatar_url:
                                embed.set_author(name=TWITCH_CHANNEL, icon_url=avatar_url, url=stream_url)
                            else:
                                embed.set_author(name=TWITCH_CHANNEL, url=stream_url)

                            thumb_url = stream_info.get("thumbnail_url", "").format(width=1280, height=720)
                            if thumb_url:
                                embed.set_image(url=f"{thumb_url}?r={random.randint(1, 10000)}")

                            await channel.send(
                                content=f"@everyone\n**{TWITCH_CHANNEL}** Ich bin jetzt Live komm ran!\n{stream_url}",
                                embed=embed,
                                view=TwitchStreamView(stream_url)
                            )

                    elif not stream_data and is_live:
                        is_live = False
    except Exception as e:
        print(f"Fehler beim Twitch-Loop: {e}")

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
    if AUTO_ROLE_ID != 0:
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"Konnte Auto-Rolle nicht vergeben: {e}")

    if WELCOME_CHANNEL_ID != 0:
        channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            try:
                channel = await bot.fetch_channel(WELCOME_CHANNEL_ID)
            except Exception:
                channel = None
        if channel:
            await channel.send(f"Was geht {member.mention} du junkie")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

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

    await bot.process_commands(message)

# --- BEICHTSTUHL BEFEHL ---
@bot.command(name="beichte", aliases=["beichtstuhl", "confess"])
async def confession_command(ctx):
    """Öffnet das Anonyme Beichtstuhl-Popup"""
    # Da Modals eine Interaction benötigen, funktioniert das sauberer per Application Command / Slash-Command oder Direct Message, aber wir senden ein Interface.
    modal = ConfessionModal()
    # Hinweis an den User: Bei Präfix-Befehlen kann das Modal per Slash Command aufgerufen werden oder direkt genutzt werden.
    await ctx.interaction.response.send_modal(modal) if ctx.interaction else await ctx.send("ℹ️ Tippe bitte den Slash Command `/beichte` oder nutze die Beichtstuhl-Webseite für das Formular!")

# --- SLOTS & ECONOMY SYSTEM ---
SLOT_EMOJIS = ["🍋", "🍒", "🔔", "💎", "7️⃣"]

@bot.command(aliases=["bal", "money"])
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    coins = get_balance(str(member.id))
    embed = discord.Embed(
        title=f"💰 Kontostand von {member.display_name}",
        description=f"Aktuelles Guthaben: **{coins} Coins** 🪙",
        color=0xF1C40F
    )
    await ctx.send(embed=embed)

@bot.command()
async def daily(ctx):
    user_id = str(ctx.author.id)
    get_balance(user_id)
    
    last_daily_str = economy_data[user_id].get("last_daily")
    now = datetime.datetime.utcnow()

    if last_daily_str:
        last_daily = datetime.datetime.fromisoformat(last_daily_str)
        if (now - last_daily).total_seconds() < 86400:
            remaining = datetime.timedelta(seconds=int(86400 - (now - last_daily).total_seconds()))
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await ctx.send(f"⏳ Du hast deinen täglichen Bonus schon geholt! Warte noch **{hours}h {minutes}m**.")
            return

    reward = 250
    update_balance(user_id, reward)
    economy_data[user_id]["last_daily"] = now.isoformat()
    save_economy()

    await ctx.send(f"🎁 **{ctx.author.mention}**, du hast deinen täglichen Bonus von **{reward} Coins** abgeholt! 🪙")

@bot.command()
async def slots(ctx, bet: int):
    user_id = str(ctx.author.id)
    current_bal = get_balance(user_id)

    if bet <= 0:
        await ctx.send("❌ Der Einsatz muss mindestens 1 Coin betragen!")
        return

    if bet > current_bal:
        await ctx.send(f"❌ Du hast nicht genug Coins! Dein Guthaben: **{current_bal} Coins**.")
        return

    slot1 = random.choice(SLOT_EMOJIS)
    slot2 = random.choice(SLOT_EMOJIS)
    slot3 = random.choice(SLOT_EMOJIS)

    embed = discord.Embed(title="🎰 SLOTS 🎰", description="[ 🔄 | 🔄 | 🔄 ]", color=0x3498DB)
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(1)

    win_multiplier = 0
    if slot1 == slot2 == slot3:
        if slot1 == "7️⃣":
            win_multiplier = 10
        elif slot1 == "💎":
            win_multiplier = 5
        else:
            win_multiplier = 3
    elif slot1 == slot2 or slot2 == slot3 or slot1 == slot3:
        win_multiplier = 1.5

    result_text = f"[ {slot1} | {slot2} | {slot3} ]\n\n"

    if win_multiplier > 0:
        winnings = int(bet * win_multiplier)
        profit = winnings - bet
        update_balance(user_id, profit)
        
        if win_multiplier >= 5:
            result_text += f"🎉 **JACKPOT!** Du hast **{winnings} Coins** gewonnen! (+{profit} Coins) 🪙"
            color = 0x2ECC71
        else:
            result_text += f"✅ **Gewonnen!** Du hast **{winnings} Coins** erhalten! (+{profit} Coins) 🪙"
            color = 0x2ECC71
    else:
        update_balance(user_id, -bet)
        result_text += f"💥 **Verloren!** -{bet} Coins."
        color = 0xE74C3C

    final_embed = discord.Embed(title="🎰 SLOTS ERGEBNIS 🎰", description=result_text, color=color)
    final_embed.set_footer(text=f"Neues Guthaben: {get_balance(user_id)} Coins")
    await msg.edit(embed=final_embed)

@bot.command(aliases=["lb", "top"])
async def leaderboard(ctx):
    sorted_users = sorted(economy_data.items(), key=lambda x: x[1].get("coins", 0), reverse=True)[:5]
    
    embed = discord.Embed(title="🏆 Server Coin-Leaderboard", color=0xF1C40F)
    description = ""
    for idx, (user_id, data) in enumerate(sorted_users, 1):
        user = bot.get_user(int(user_id))
        name = user.display_name if user else f"User ID {user_id}"
        description += f"**#{idx} {name}** — {data.get('coins', 0)} Coins 🪙\n"

    embed.description = description or "Noch keine Daten vorhanden."
    await ctx.send(embed=embed)

# --- BOT COMMANDS ---
@bot.command(name="commands", aliases=["help"])
async def show_commands(ctx):
    embed = discord.Embed(
        title="🤖 Murhat Bot – Befehlsübersicht",
        description="Hier ist eine Übersicht aller Befehle:",
        color=0x3498DB
    )
    
    embed.add_field(
        name="🎰 Casino & Games",
        value=(
            "`!slots <Einsatz>` – Spiele an der Slot-Maschine.\n"
            "`!daily` – Hole deinen täglichen Coin-Bonus ab.\n"
            "`!balance` / `!coins` – Zeigt dein Guthaben.\n"
            "`!leaderboard` – Zeigt die reichsten User."
        ),
        inline=False
    )

    embed.add_field(
        name="🤫 Community Content",
        value=(
            "`!beichte` – Reiche eine anonyme Beichte für den Stream ein."
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Allgemeine Befehle",
        value=(
            "`!commands` / `!help` – Zeigt diese Befehlsübersicht an.\n"
            "`!ping` – Prüft die Latenz des Bots.\n"
            "`!socials` – Zeigt das Social-Media Embed mit Buttons.\n"
            "`!testlive` – Sendet manuell eine Test-Benachrichtigung."
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚠️ Verwarnungssystem & Moderation",
        value=(
            "`!warn @User [Grund]` – Verwarnt ein Mitglied.\n"
            "`!warnings [@User]` – Zeigt Verwarnungen an.\n"
            "`!clear <Anzahl>` – Löscht Chat-Nachrichten.\n"
            "`!kick` / `!ban` – Mitglieder vom Server kicken/bannen."
        ),
        inline=False
    )

    embed.set_footer(text="Murhat Bot • Community Management")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def testlive(ctx):
    channel = bot.get_channel(TWITCH_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(TWITCH_CHANNEL_ID)
        except Exception as e:
            await ctx.send(f"❌ Fehler beim Laden von Kanal-ID `{TWITCH_CHANNEL_ID}`: {e}")
            return

    stream_url = f"https://twitch.tv/{TWITCH_CHANNEL}"
    embed = discord.Embed(
        title="TEST: Stream ist jetzt live!",
        url=stream_url,
        color=0x9146FF
    )
    embed.set_author(name=TWITCH_CHANNEL, url=stream_url)
    
    await channel.send(
        content=f"@everyone\n**{TWITCH_CHANNEL}** Ich bin jetzt Live komm ran!\n{stream_url}",
        embed=embed,
        view=TwitchStreamView(stream_url)
    )
    await ctx.send(f"✅ Test-Benachrichtigung gesendet in: <#{TWITCH_CHANNEL_ID}>")

@bot.command()
async def socials(ctx):
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
