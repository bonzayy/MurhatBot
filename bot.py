import os
import json
import asyncio
import discord
from discord.ext import commands, tasks
import aiohttp

# Zugangsdaten direkt aus den Render-Umgebungsvariablen laden
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL")
NOTIFICATION_CHANNEL_ID = int(os.getenv("NOTIFICATION_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

twitch_token = None
is_live = False

async def get_twitch_token():
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()
            return data.get("access_token")

@tasks.loop(minutes=2)
async def check_twitch_live():
    global twitch_token, is_live
    if not twitch_token:
        twitch_token = await get_twitch_token()

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {twitch_token}"
    }
    url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_CHANNEL}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 401:
                twitch_token = await get_twitch_token()
                return
            data = await resp.json()

    stream_data = data.get("data", [])
    
    # Stream ist LIVE gegangen
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
            embed.set_footer(text="Murhat Bot • Stream Notification", icon_url=bot.user.display_avatar.url if bot.user.avatar else None)
            
            await channel.send(content="@everyone Der Stream startet jetzt!", embed=embed)

    # Stream ist OFFLINE gegangen
    elif not stream_data and is_live:
        is_live = False

@bot.event
async def on_ready():
    print(f"🤖 {bot.user.name} ist erfolgreich eingeloggt und läuft auf Render!")
    await bot.change_presence(activity=discord.Streaming(name="Twitch Stream", url=f"https://twitch.tv/{TWITCH_CHANNEL}"))
    check_twitch_live.start()

bot.run(DISCORD_TOKEN)