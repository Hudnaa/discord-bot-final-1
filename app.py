import os
import time
import asyncio
import threading
import sqlite3
import secrets

import requests
from flask import Flask, request, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import discord
from discord.ext import commands

# ---------- ค่าคงที่จาก Environment Variables ----------
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

OWNER_GUILD_IDS = []

AUTHORIZED_USER_IDS = [1526937904423764030, 1526503693690601592]

def is_authorized():
    async def predicate(ctx):
        return ctx.author.id in AUTHORIZED_USER_IDS
    return commands.check(predicate)


# ---------- ฐานข้อมูล (ใช้เก็บแค่ token ผู้ใช้ ไม่ต้องพึ่ง guild_config อีกแล้ว) ----------
conn = sqlite3.connect("data.db", check_same_thread=False)
conn.execute("""
CREATE TABLE IF NOT EXISTS user_tokens (
    user_id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL
)
""")
conn.commit()


def save_user_token(user_id, access_token, refresh_token, expires_in):
    expires_at = int(time.time()) + expires_in
    conn.execute(
        "INSERT OR REPLACE INTO user_tokens (user_id, access_token, refresh_token, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, access_token, refresh_token, expires_at)
    )
    conn.commit()


def get_valid_access_token(user_id):
    row = conn.execute(
        "SELECT access_token, refresh_token, expires_at FROM user_tokens WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not row:
        return None

    access_token, refresh_token, expires_at = row

    if time.time() < expires_at - 60:
        return access_token

    res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    data = res.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")

    if not new_access:
        return None

    save_user_token(user_id, new_access, new_refresh, expires_in)
    return new_access


def join_user_to_guild(user_id, guild_id, role_id=None):
    access_token = get_valid_access_token(user_id)
    if not access_token:
        return False, "ไม่พบข้อมูลการยืนยันตัวตน หรือ token ใช้ไม่ได้แล้ว"

    payload = {"access_token": access_token}
    if role_id:
        payload["roles"] = [role_id]

    res = requests.put(
        f"https://discord.com/api/guilds/{guild_id}/members/{user_id}",
        headers={
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
    )

    if res.status_code in (201, 204):
        return True, "สำเร็จ"
    else:
        return False, f"{res.status_code} {res.text}"


def get_all_verified_users():
    rows = conn.execute("SELECT user_id FROM user_tokens").fetchall()
    return [row[0] for row in rows]


# ---------- ส่วนเว็บ Flask ----------
app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["30 per minute"]
)


@app.route("/")
def home():
    return "Bot verify server is running."


@app.route("/callback")
@limiter.limit("10 per minute")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return "ไม่ได้รับอนุญาต", 400

    guild_id = None
    role_id = None
    if state and ":" in state:
        guild_id, role_id = state.split(":", 1)

    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")

    if not access_token:
        return f"แลก token ไม่สำเร็จ: {token_data}", 400

    user_res = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_id = user_res.json()["id"]

    save_user_token(user_id, access_token, refresh_token, expires_in)

    if guild_id:
        success, message = join_user_to_guild(user_id, guild_id, role_id)
        if success:
            return "รับยศสำเร็จแล้ว! กลับไปที่ Discord ได้เลย 🎉"
        else:
            return f"ยืนยันตัวตนสำเร็จ แต่รับยศไม่สำเร็จ: {message}"

    return "ยืนยันตัวตนสำเร็จแล้ว! กลับไปที่ Discord ได้เลย 🎉"


@app.errorhandler(429)
def ratelimit_handler(e):
    return "คำขอถี่เกินไป กรุณาลองใหม่ภายหลัง", 429


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# ---------- ส่วนบอท Discord ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


class VerifyView(discord.ui.View):
    def __init__(self, guild_id, role_id):
        super().__init__(timeout=None)

        state_value = f"{guild_id}:{role_id}"

        direct_auth_url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=identify+guilds.join"
            f"&state={state_value}"
        )

        self.add_item(discord.ui.Button(
            label="รับยศ",
            emoji="✅",
            style=discord.ButtonStyle.link,
            url=direct_auth_url
        ))


@bot.event
async def on_ready():
    print(f"บอทออนไลน์แล้ว: {bot.user}")


@bot.event
async def on_guild_join(guild):
    if OWNER_GUILD_IDS and guild.id not in OWNER_GUILD_IDS:
        print(f"บอทถูกเชิญเข้าเซิร์ฟที่ไม่อนุญาต: {guild.name} ({guild.id}) — กำลังออก...")
        await guild.leave()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ ใส่ข้อมูลไม่ครบ: ขาด `{error.param.name}`")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send(f"❌ ไม่พบยศที่ระบุ: {error.argument}")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(f"❌ ไม่พบสมาชิกที่ระบุ: {error.argument}")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        await ctx.send(f"❌ เกิดข้อผิดพลาด: `{error}`")
        print(f"Unhandled error: {error}")


@bot.command()
@is_authorized()
async def setup_verify(ctx, role: discord.Role):
    embed = discord.Embed(
        title="🔐 รับยศ",
        description=f"กดปุ่มด้านล่างเลยKub กดรับยศจะได้ยศ {role.mention}",
        color=discord.Color.blurple()
    )

    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)

    embed.set_image(
        url="https://cdn.discordapp.com/attachments/1528016838842122344/1528149105543745758/file_0000000038447209a7fe0ab84d413e2a.png"
    )
    embed.set_footer(
        text=f"{ctx.guild.name} • ระบบยืนยันตัวตน",
        icon_url=ctx.guild.icon.url if ctx.guild.icon else None
    )
    embed.timestamp = discord.utils.utcnow()

    await ctx.send(embed=embed, view=VerifyView(ctx.guild.id, role.id))


@bot.command()
@is_authorized()
async def pull(ctx, member: discord.Member, guild_id: str, role_id: str = None):
    success, message = join_user_to_guild(str(member.id), guild_id, role_id)
    if success:
        await ctx.send(f"✅ ดึง {member.mention} เข้าเซิร์ฟ `{guild_id}` สำเร็จแล้ว")
    else:
        await ctx.send(f"❌ ล้มเหลว: {message}")


@bot.command()
@is_authorized()
async def pullall(ctx, guild_id: str, role_id: str = None):
    user_ids = get_all_verified_users()
    total = len(user_ids)

    if total == 0:
        await ctx.send("ยังไม่มีใครยืนยันตัวตนไว้เลย")
        return

    await ctx.send(f"กำลังดึง {total} คนเข้าเซิร์ฟ `{guild_id}` ...")

    success_count = 0
    fail_count = 0
    fail_list = []

    for user_id in user_ids:
        success, message = join_user_to_guild(user_id, guild_id, role_id)
        if success:
            success_count += 1
        else:
            fail_count += 1
            fail_list.append(f"{user_id}: {message}")
        await asyncio.sleep(1)

    result_text = f"✅ สำเร็จ {success_count} คน / ❌ ล้มเหลว {fail_count} คน"
    await ctx.send(result_text)

    if fail_list:
        chunk = "\n".join(fail_list[:10])
        await ctx.send(f"ตัวอย่างที่ล้มเหลว:\n```{chunk}```")


@bot.command()
@is_authorized()
async def countverified(ctx):
    count = len(get_all_verified_users())
    await ctx.send(f"มีผู้ยืนยันตัวตนแล้วทั้งหมด {count} คน")


def run_bot():
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    run_bot()
