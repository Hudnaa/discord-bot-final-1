import os
import time
import asyncio
import threading
import sqlite3
import secrets
import urllib.parse

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

BACKGROUND_IMAGE_URL = "https://i.ibb.co/PzGWTPDX/file-0000000038447209a7fe0ab84d413e2a.png"
BOT_BRAND_NAME = "remouse.pmt"

SOCIAL_LINKS = {
    "discord": "https://discord.gg/3UgwZhKsp3",
    "instagram": "https://www.instagram.com/remousepmt",
    "youtube": "https://www.youtube.com/@JoDobig",
    "website": "https://discord-bot-final-1-pzlz.onrender.com/",
}

OWNER_GUILD_IDS = []

AUTHORIZED_USER_IDS = [1526937904423764030, 1526503693690601592]

def is_authorized():
    async def predicate(ctx):
        return ctx.author.id in AUTHORIZED_USER_IDS
    return commands.check(predicate)


# ---------- ฐานข้อมูล ----------
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

    debug_msg = f"[ขั้น1 เพิ่มเข้าเซิร์ฟ] status={res.status_code} body={res.text[:200]}"

    if res.status_code not in (201, 204):
        return False, debug_msg

    if role_id:
        role_res = requests.put(
            f"https://discord.com/api/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
        )
        debug_msg += f" | [ขั้น2 ใส่ยศ] status={role_res.status_code} body={role_res.text[:200]}"

        if role_res.status_code != 204:
            return False, debug_msg

    return True, debug_msg


def get_all_verified_users():
    rows = conn.execute("SELECT user_id FROM user_tokens").fetchall()
    return [row[0] for row in rows]


# ---------- หน้าเว็บผลลัพธ์ (ตกแต่งสวยงาม) ----------
def render_result_page(guild_name, success=True, error_message=None):
    guild_display = guild_name if guild_name else "Discord Server"

    if success:
        theme_color = "50,255,120"
        accent = "#7dffb0"
        title = "FINISH"
        desc = "รับยศสำเร็จแล้ว"
        sub = "กลับไปที่ Discord ได้เลย"
        status_box = '<div class="statusbox">ROLE GRANTED ✓</div>'
        logo_icon = "✅"
    else:
        theme_color = "255,70,70"
        accent = "#ff8a8a"
        title = "Verify Failed"
        desc = error_message or "เกิดข้อผิดพลาดบางอย่าง"
        sub = "กรุณาลองใหม่อีกครั้ง"
        status_box = '<div class="statusbox">UNKNOWN_ERROR</div>'
        logo_icon = "❌"

    return f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            * {{ box-sizing: border-box; }}
            html, body {{ margin: 0; height: 100%; overflow: hidden; }}
            body {{
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                font-family: 'Segoe UI', sans-serif;
                background-image: url("{BACKGROUND_IMAGE_URL}");
                background-size: cover;
                background-position: center;
                padding: 20px;
                position: relative;
            }}
            body::before {{
                content: "";
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.55);
                z-index: 0;
            }}
            .card {{
                background: rgba(8, 15, 12, 0.88);
                border: 1px solid rgba({theme_color},0.25);
                border-radius: 20px;
                padding: 36px 28px;
                text-align: center;
                max-width: 360px;
                width: 100%;
                box-shadow: 0 0 50px rgba({theme_color},0.15), 0 8px 24px rgba(0,0,0,0.6);
                position: relative;
                z-index: 10;
            }}
            .logo {{
                width: 90px; height: 90px; border-radius: 50%;
                margin: 0 auto 16px;
                background: radial-gradient(circle, rgba({theme_color},0.15), #041505);
                border: 2px solid rgba({theme_color},0.5);
                box-shadow: 0 0 25px rgba({theme_color},0.4);
                display: flex; align-items: center; justify-content: center;
                font-size: 30px;
            }}
            .label {{ color: {accent}; font-size: 12px; letter-spacing: 2px; margin-bottom: 6px; opacity: 0.85; }}
            h1 {{ color: #fff; font-size: 28px; margin: 0 0 14px; letter-spacing: 1px; }}
            .desc {{ color: {accent}; font-weight: 600; font-size: 15px; margin-bottom: 4px; }}
            .sub {{ color: #999; font-size: 13px; margin-bottom: 20px; }}
            .statusbox {{
                background: rgba({theme_color},0.08);
                border: 1px solid rgba({theme_color},0.35);
                color: {accent}; font-weight: bold; letter-spacing: 1px;
                border-radius: 10px; padding: 12px; margin-bottom: 22px; font-size: 14px;
            }}
            .socials {{ display: flex; justify-content: center; gap: 14px; margin-bottom: 18px; }}
            .socials a {{
                width: 40px; height: 40px; border-radius: 50%;
                background: rgba(255,255,255,0.07);
                display: flex; align-items: center; justify-content: center;
                text-decoration: none;
            }}
            .socials svg {{ width: 18px; height: 18px; fill: #e5e5e5; }}
            .footer {{ color: #aaa; font-size: 11px; line-height: 1.6; }}

            .snow {{
                position: fixed; top: -10px; color: white;
                user-select: none; pointer-events: none; z-index: 1;
                animation-name: fall, sway;
                animation-timing-function: linear, ease-in-out;
                animation-iteration-count: infinite;
            }}
            @keyframes fall {{ to {{ transform: translateY(110vh); }} }}
            @keyframes sway {{ 0%, 100% {{ margin-left: 0; }} 50% {{ margin-left: 40px; }} }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="logo">{logo_icon}</div>
            <div class="label">SERVER VERIFY</div>
            <h1>{title}</h1>
            <div class="desc">{desc}</div>
            <div class="sub">{sub}</div>
            {status_box}

            <div class="socials">
                <a href="{SOCIAL_LINKS['discord']}" target="_blank" title="Discord">
                    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12c0 3.54 1.84 6.65 4.62 8.44-.15-.71-.28-1.8.06-2.58.31-.71 2-8.5 2-8.5s-.51-1.02-.51-2.53c0-2.37 1.37-4.14 3.08-4.14 1.45 0 2.15 1.09 2.15 2.39 0 1.46-.93 3.64-1.41 5.66-.4 1.7.85 3.08 2.52 3.08 3.02 0 5.06-3.88 5.06-8.46 0-3.49-2.35-6.1-6.62-6.1-4.82 0-7.83 3.6-7.83 7.62 0 1.39.41 2.37 1.05 3.13.29.35.33.49.23.89-.08.31-.26 1.02-.33 1.3-.11.42-.44.57-.81.42-2.26-.92-3.31-3.4-3.31-6.19C6 8.16 9.36 4.9 15.24 4.9c5 0 8.36 3.62 8.36 7.5 0 5.13-2.85 8.96-7.08 8.96-1.42 0-2.75-.77-3.21-1.63l-.87 3.32c-.26 1-.77 2-1.22 2.68.92.28 1.9.43 2.91.43 5.52 0 10-4.48 10-10S17.52 2 12 2z"/></svg>
                </a>
                <a href="{SOCIAL_LINKS['instagram']}" target="_blank" title="Instagram">
                    <svg viewBox="0 0 24 24"><path d="M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41-.56-.22-.96-.48-1.38-.9-.42-.42-.68-.82-.9-1.38-.16-.42-.36-1.06-.41-2.23-.06-1.27-.07-1.65-.07-4.85s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41 1.27-.06 1.65-.07 4.85-.07M12 0C8.74 0 8.33.01 7.05.07 5.78.13 4.9.33 4.14.63c-.79.31-1.46.72-2.13 1.38C1.35 2.68.94 3.35.63 4.14c-.3.76-.5 1.64-.56 2.91C.01 8.33 0 8.74 0 12s.01 3.67.07 4.95c.06 1.27.26 2.15.56 2.91.31.79.72 1.46 1.38 2.13.67.66 1.34 1.07 2.13 1.38.76.3 1.64.5 2.91.56C8.33 23.99 8.74 24 12 24s3.67-.01 4.95-.07c1.27-.06 2.15-.26 2.91-.56.79-.31 1.46-.72 2.13-1.38.66-.67 1.07-1.34 1.38-2.13.3-.76.5-1.64.56-2.91.06-1.28.07-1.69.07-4.95s-.01-3.67-.07-4.95c-.06-1.27-.26-2.15-.56-2.91-.31-.79-.72-1.46-1.38-2.13C21.32 1.35 20.65.94 19.86.63c-.76-.3-1.64-.5-2.91-.56C15.67.01 15.26 0 12 0zm0 5.84A6.16 6.16 0 1 0 18.16 12 6.16 6.16 0 0 0 12 5.84zm0 10.16A4 4 0 1 1 16 12a4 4 0 0 1-4 4zm6.41-10.4a1.44 1.44 0 1 1-1.44-1.44 1.44 1.44 0 0 1 1.44 1.44z"/></svg>
                </a>
                <a href="{SOCIAL_LINKS['youtube']}" target="_blank" title="YouTube">
                    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l7 4.5-7 4.5z"/></svg>
                </a>
                <a href="{SOCIAL_LINKS['website']}" target="_blank" title="Website">
                    <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm7.94 9h-3.05a15.6 15.6 0 0 0-1.14-5.32A8 8 0 0 1 19.94 11zM12 4.06c.94 1.24 1.99 3.33 2.28 6.94H9.72c.29-3.61 1.34-5.7 2.28-6.94zM9.72 13h4.56c-.29 3.61-1.34 5.7-2.28 6.94-.94-1.24-1.99-3.33-2.28-6.94zM8.25 5.68A15.6 15.6 0 0 0 7.11 11H4.06a8 8 0 0 1 4.19-5.32zM4.06 13h3.05a15.6 15.6 0 0 0 1.14 5.32A8 8 0 0 1 4.06 13zm11.69 5.32A15.6 15.6 0 0 0 16.89 13h3.05a8 8 0 0 1-4.19 5.32z"/></svg>
                </a>
            </div>

            <div class="footer">
                © 2026 {guild_display}<br>
                Powered by {BOT_BRAND_NAME}
            </div>
        </div>

        <script>
            const snowflakeCount = 35;
            const body = document.body;
            for (let i = 0; i < snowflakeCount; i++) {{
                const flake = document.createElement('div');
                flake.className = 'snow';
                flake.textContent = '❄';
                flake.style.left = Math.random() * 100 + 'vw';
                flake.style.fontSize = (Math.random() * 14 + 10) + 'px';
                flake.style.opacity = Math.random() * 0.6 + 0.4;
                const fallDuration = Math.random() * 6 + 5;
                const swayDuration = Math.random() * 3 + 2;
                const delay = Math.random() * 5;
                flake.style.animationDuration = fallDuration + 's, ' + swayDuration + 's';
                flake.style.animationDelay = delay + 's, ' + delay + 's';
                body.appendChild(flake);
            }}
        </script>
    </body>
    </html>
    """


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
        return render_result_page(None, success=False, error_message="ไม่ได้รับอนุญาต"), 400

    guild_id = None
    role_id = None
    guild_name = None
    if state:
        parts = state.split(":", 2)
        if len(parts) >= 1:
            guild_id = parts[0]
        if len(parts) >= 2:
            role_id = parts[1]
        if len(parts) >= 3:
            guild_name = urllib.parse.unquote(parts[2])

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
        return render_result_page(guild_name, success=False, error_message="แลก token ไม่สำเร็จ"), 400

    user_res = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_id = user_res.json()["id"]

    save_user_token(user_id, access_token, refresh_token, expires_in)

    if guild_id:
        success, message = join_user_to_guild(user_id, guild_id, role_id)
        if success:
            return render_result_page(guild_name, success=True)
        else:
            return render_result_page(guild_name, success=False, error_message="ไม่สามารถแจกยศได้")

    return render_result_page(guild_name, success=True)


@app.errorhandler(429)
def ratelimit_handler(e):
    return render_result_page(None, success=False, error_message="คำขอถี่เกินไป กรุณาลองใหม่ภายหลัง"), 429


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# ---------- ส่วนบอท Discord ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


class VerifyView(discord.ui.View):
    def __init__(self, guild_id, role_id, guild_name, emoji="✅"):
        super().__init__(timeout=None)

        encoded_name = urllib.parse.quote(guild_name)
        state_value = f"{guild_id}:{role_id}:{encoded_name}"

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
            emoji=emoji,
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
async def setup_verify(ctx, role: discord.Role, emoji: str = "✅", banner_url: str = None, *, description: str = None):
    final_banner = banner_url if banner_url else BACKGROUND_IMAGE_URL
    final_description = description if description else f"กดปุ่มด้านล่างเลยKub กดรับยศจะได้ยศ {role.mention}"

    embed = discord.Embed(
        title="🔐 รับยศ",
        description=final_description,
        color=discord.Color.blurple()
    )

    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)

    embed.set_image(url=final_banner)
    embed.set_footer(
        text=f"{ctx.guild.name} • ระบบยืนยันตัวตน",
        icon_url=ctx.guild.icon.url if ctx.guild.icon else None
    )
    embed.timestamp = discord.utils.utcnow()

    view = VerifyView(ctx.guild.id, role.id, ctx.guild.name, emoji=emoji)

    await ctx.send(embed=embed, view=view)


@bot.command()
@is_authorized()
async def pull(ctx, member: discord.Member, guild_id: str, role_id: str = None):
    success, message = join_user_to_guild(str(member.id), guild_id, role_id)
    if success:
        await ctx.send(f"✅ ดึง {member.mention} เข้าเซิร์ฟ `{guild_id}` สำเร็จแล้ว\n`{message}`")
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
        chunk = "\n".join(fail_list[:5])
        await ctx.send(f"รายละเอียด:\n```{chunk}```")


@bot.command()
@is_authorized()
async def countverified(ctx):
    count = len(get_all_verified_users())
    await ctx.send(f"มีผู้ยืนยันตัวตนแล้วทั้งหมด {count} คน")


@bot.command()
@is_authorized()
async def removerole(ctx, role: discord.Role):
    members_with_role = [m for m in ctx.guild.members if role in m.roles]
    total = len(members_with_role)

    if total == 0:
        await ctx.send(f"ไม่มีใครมียศ {role.mention} เลยตอนนี้")
        return

    await ctx.send(f"กำลังลบยศ {role.mention} ออกจาก {total} คน...")

    success_count = 0
    fail_count = 0

    for member in members_with_role:
        try:
            await member.
