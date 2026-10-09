import os
import io
import hashlib
import re
import json
import ssl
import math
import time
import copy
import shutil
import base64
import string
import random
import secrets
import logging
import uuid
import asyncio
import aiohttp
import requests
import qrcode
import datetime
import threading

from io import BytesIO
from types import SimpleNamespace
from typing import Optional, Literal
from collections import defaultdict, deque

from email.message import EmailMessage
import smtplib

from discord.ui import View, Button, Select

# مكتبات الصور
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageColor

# الترجمة
from deep_translator import GoogleTranslator

from dotenv import load_dotenv

# مكتبات Discord
import discord
from discord import (
    File, Embed, utils, Interaction, app_commands,
    ButtonStyle, FFmpegPCMAudio, Color, User,
    PartialEmoji, Colour
)
from discord.ext import commands, tasks
from discord.ext.commands import Bot
from discord.utils import get
from discord.ui import View, Button, button, Modal, TextInput
from discord import ui

from collections import defaultdict

from telegram_backup import send_backup_to_telegram, start_backup_task

import aiosqlite



# ==================== 🔄 تحميل متغيرات البيئة ====================
load_dotenv()

# ============================================================
# 🧩 إعدادات أساسية / ثوابت
# ============================================================

# 👑 المالك الأساسي للبوت
OWNER_IDS = {1118943027067633756}

# 📁 مسارات الملفات والبيانات
DB_PATH = "data.db"

# 📂 مجلدات
BACKGROUNDS_PATH = "backgrounds"
IMPORTANT_BACKUPS_DIR = "important_backups"

# 🔤 الخطوط
font_path = "Roboto-Regular.ttf"

# ============================================================
# 🧠 الكاشات العامة (Caches)
# ============================================================

# -------------------------------
# كاش الدعوات وأدوات التزامن
# -------------------------------
invite_cache = {}
last_invite_check = {}
invite_lock = asyncio.Lock()

# -------------------------------
# نظام الرسائل الخاصة (DM)
# -------------------------------
DM_COOLDOWN = 5  # ثواني بين كل رسالة
dm_queues: dict[int, asyncio.Queue] = {}
dm_tasks: dict[int, asyncio.Task] = {}

# -------------------------------
# كاشات عامة
# -------------------------------
server_settings_cache = {}
server_aliases_cache = {}

last_xp_time = {}              # تتبع وقت آخر XP
deleted_messages_cache = {}    # حفظ الرسائل المحذوفة مؤقتًا
voice_join_times = {}          # تتبع دخول الصوتي

# 🎨 الخلفيات
الخلفيات_النشطة = {}

# 🤖 الرسائل التلقائية
auto_messages_config = {}

# ============================================================
# ⚙️ إعدادات السيرفر (Configuration)
# ============================================================

# 🏠 السيرفر الرئيسي
MAIN_GUILD_ID = 1398281305417973921 

# 📋 روم مراجعة التوثيق
VERIFICATION_REVIEW_CHANNEL_ID = 1427578851239661609

# ============================================================
# 📝 اللوجات (Logging)
# ============================================================

logging.basicConfig(level=logging.INFO)

# ============================================================
# ⚙️ صلاحيات البوت (Intents)
# ============================================================

intents = discord.Intents.default()

intents.message_content = True  # قراءة محتوى الرسائل
intents.guilds = True           # التعامل مع السيرفرات
intents.members = True          # التعامل مع الأعضاء
# ⚠️ لا تفعّل presence بدون إذن Discord



# ==============================
#  نظام تبريد فائق السرعة مع تنظيف تلقائي للذاكرة
# ==============================

_user_cooldowns = defaultdict(dict)
_COOLDOWN_MSG_TEMPLATE = "**ـ {name}**, يرجى الانتظار (تبقى **{remain} ثانية**)"

async def check_cooldown(interaction_or_ctx, command_name: str, cooldown_seconds: int) -> bool:
    """
    نظام تبريد عالي الأداء يدعم كل من الأوامر العادية والسلاش.
    - بدون I/O ثقيل
    - يخزن مؤقتًا بالذاكرة فقط
    - يحذف البيانات تلقائيًا بعد انتهاء مدة التبريد
    """

    now = time.monotonic()
    user = getattr(interaction_or_ctx, "user", getattr(interaction_or_ctx, "author", None))
    if not user:
        return True

    uid = user.id
    user_data = _user_cooldowns[uid]
    last = user_data.get(command_name, 0)
    remaining = cooldown_seconds - (now - last)

    if remaining > 0:
        msg = _COOLDOWN_MSG_TEMPLATE.format(name=user.display_name, remain=int(remaining))
        try:
            if isinstance(interaction_or_ctx, discord.Interaction):
                if interaction_or_ctx.response.is_done():
                    await interaction_or_ctx.followup.send(msg, ephemeral=True)
                else:
                    await interaction_or_ctx.response.send_message(msg, ephemeral=True)
            else:
                await interaction_or_ctx.reply(msg, mention_author=False, delete_after=5)
        except discord.HTTPException:
            pass
        return False

    # ⚡ تحديث آخر استخدام
    user_data[command_name] = now

    # 🔹 تنظيف تلقائي بعد انتهاء التبريد
    async def remove_after_cooldown():
        await asyncio.sleep(cooldown_seconds)
        # احذف الأمر إذا ما حدش استخدمه مرة تانية
        if user_data.get(command_name, 0) == now:
            del user_data[command_name]
        # احذف المستخدم بالكامل إذا خالي من أي أوامر
        if not user_data:
            del _user_cooldowns[uid]

    asyncio.create_task(remove_after_cooldown())
    return True
    
# 🚀 الكلاس الأساسي للبوت
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):

        # ✅ تحميل جميع الـ Cogs
        extensions = [
            "cogs.help_menu",
            "cogs.setup_ticket",
            "cogs.giveaways_system",
            "cogs.register_system",
            "cogs.gxhup",
            "cogs.suggestions_and_ratings",
            "cogs.role_system",
            "cogs.block_commands",
            "cogs.emoji_system",
            "cogs.auto_replyes",
            "cogs.block_links",
            "cogs.advanced_logger",
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ Loaded {ext}")
            except Exception as e:
                print(f"⚠️ فشل تحميل {ext}: {e}")

        # ✅ مزامنة أوامر السلاش
        await self.sync_slash_commands()

    async def sync_slash_commands(self):
        try:
            # ✅ السطر ده اتحذف — كان بيكسر الـ sync
            # self.tree.interaction_check = منع_اوامر_سلاش

            synced = await self.tree.sync()
            print(f"✅ تمت مزامنة {len(synced)} أمر سلاش.")

        except discord.HTTPException as e:
            print(f"❌ فشل مزامنة أوامر السلاش (HTTP {e.status}): {e.text}")

        except Exception as e:
            print(f"❌ فشل مزامنة أوامر السلاش:\n{e}")


# ✅ إنشاء نسخة البوت
bot = MyBot()


# ============================================================
# 🗄️ CONNECTION POOL — connection مشترك لكل العمليات
# ============================================================

_db_conn: aiosqlite.Connection | None = None
_db_write_lock: asyncio.Lock | None = None  # ✅ مش global scope


def get_write_lock() -> asyncio.Lock:
    """يرجع الـ lock أو ينشئه لو مش موجود (آمن مع event loop)."""
    global _db_write_lock
    if _db_write_lock is None:
        _db_write_lock = asyncio.Lock()
    return _db_write_lock


async def get_db() -> aiosqlite.Connection:
    """
    يرجع connection مشترك واحد للبوت كله.
    - يفحص إذا الـ connection حي فعلاً قبل ما يرجعه
    - لو مات أو مش موجود، يفتح واحد جديد تلقائياً
    """
    global _db_conn

    # ✅ فحص إذا الـ connection موجود وشغال
    needs_reconnect = (
        _db_conn is None
        or not getattr(_db_conn, "_running", False)
    )

    if needs_reconnect:
        # أقفل القديم لو موجود
        if _db_conn is not None:
            try:
                await _db_conn.close()
            except Exception:
                pass
            _db_conn = None

        # افتح connection جديد
        _db_conn = await aiosqlite.connect(DB_PATH, timeout=30)
        _db_conn.row_factory = aiosqlite.Row
        await _db_conn.execute("PRAGMA journal_mode=WAL;")
        await _db_conn.execute("PRAGMA synchronous=NORMAL;")
        await _db_conn.execute("PRAGMA busy_timeout=5000;")
        await _db_conn.execute("PRAGMA cache_size=-20000;")
        await _db_conn.execute("PRAGMA foreign_keys=ON;")

    return _db_conn
    

# ============================================================
# 👤 ensure_user — ضمان وجود المستخدم في جدول users (per guild)
# ============================================================

async def ensure_user(uid: str, gid: str) -> dict:
    """
    يضمن وجود المستخدم في جدول users الخاص بالسيرفر.
    يرجع dict بيانات المستخدم دايماً (مش فاضي أبداً).
    """
    async with get_write_lock():
        db = await get_db()

        await db.execute("""
            INSERT OR IGNORE INTO users (
                user_id, guild_id,
                xp, msg_xp, voice_xp,
                invites, last_mine, last_vote
            )
            VALUES (?, ?, 0, 0, 0, 0, NULL, 0)
        """, (uid, gid))

        await db.commit()

        # ✅ القراءة داخل نفس الـ lock — connection واحد، أمان أكثر
        async with db.execute("""
            SELECT * FROM users
            WHERE user_id = ? AND guild_id = ?
        """, (uid, gid)) as cursor:
            row = await cursor.fetchone()

    return dict(row) if row else {
        "user_id": uid, "guild_id": gid,
        "xp": 0, "msg_xp": 0, "voice_xp": 0,
        "invites": 0, "last_mine": None, "last_vote": 0
    }


# ============================================================
# 📊 update_user_stats — تحديث XP أو Invites في users
# ============================================================

_SERVER_FIELDS = {"xp", "msg_xp", "voice_xp", "invites"}

async def update_user_stats(uid: str, gid: str, **kwargs) -> None:
    """
    يحدّث فقط الحقول الخاصة بالسيرفر (xp, msg_xp, voice_xp, invites).
    أي حقل تاني (kento, level, ...) يتجاهله — ده شغل global_users.
    """
    if not kwargs:
        return

    # فلتر الحقول الصح بس
    valid = {k: v for k, v in kwargs.items() if k in _SERVER_FIELDS and isinstance(v, (int, float))}
    if not valid:
        return

    set_clause = ", ".join(f"{k} = {k} + ?" for k in valid)
    values     = list(valid.values()) + [uid, gid]

    try:
        async with get_write_lock():
            db = await get_db()
            await db.execute(f"""
                UPDATE users
                SET {set_clause}
                WHERE user_id = ? AND guild_id = ?
            """, values)
            await db.commit()

    except Exception as e:
        logging.error(f"[update_user_stats ERROR] uid={uid} gid={gid} | {e}")


# ============================================================
# 🌍 ensure_global_user — ضمان وجود المستخدم في global_users
# ============================================================

_GLOBAL_USER_DEFAULTS = {
    "total_xp": 0, "level": 1,
    "kento": 0,    "deposit": 0,
    "trust": 0,    "verified_level": 0,
    "background": "default.png",
    "email": None, "full_name": None,
    "country": None, "pin": None,
    "birthday": None, "verify_token": None,
}

async def ensure_global_user(uid: str) -> dict:
    """
    يضمن وجود المستخدم في global_users.
    يرجع dict بيانات المستخدم دايماً (مش فاضي أبداً).
    """
    async with get_write_lock():
        db = await get_db()

        await db.execute("""
            INSERT OR IGNORE INTO global_users (
                user_id, total_xp, level,
                kento, deposit, trust,
                verified_level, background
            )
            VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
        """, (uid,))

        await db.commit()

        # ✅ القراءة داخل نفس الـ lock — connection واحد، أمان أكثر
        async with db.execute("""
            SELECT * FROM global_users
            WHERE user_id = ?
        """, (uid,)) as cursor:
            row = await cursor.fetchone()

    # fallback لو حصل خطأ غريب
    return dict(row) if row else {"user_id": uid, **_GLOBAL_USER_DEFAULTS}

                  
async def init_db():
    """Clean Hybrid Economy System (Global + Server Split)"""

    # ✅ نستخدم get_db() بدل فتح connection جديد
    db = await get_db()

    # ====================================================
    # 🏢 1️⃣ SERVER DATA
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   TEXT NOT NULL,
            guild_id  TEXT NOT NULL,

            xp        INTEGER NOT NULL DEFAULT 0,
            msg_xp    INTEGER NOT NULL DEFAULT 0,
            voice_xp  INTEGER NOT NULL DEFAULT 0,
            invites   INTEGER NOT NULL DEFAULT 0,

            last_mine TEXT,
            last_vote REAL NOT NULL DEFAULT 0,

            PRIMARY KEY (user_id, guild_id)
        )
    """)

    # ====================================================
    # 🌍 2️⃣ GLOBAL ECONOMY
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS global_users (
            user_id        TEXT PRIMARY KEY NOT NULL,

            total_xp       INTEGER NOT NULL DEFAULT 0,
            level          INTEGER NOT NULL DEFAULT 1,

            kento          INTEGER NOT NULL DEFAULT 0,
            deposit        INTEGER NOT NULL DEFAULT 0,

            trust          INTEGER NOT NULL DEFAULT 0,
            verified_level INTEGER NOT NULL DEFAULT 0,

            background     TEXT NOT NULL DEFAULT 'default.png',

            email          TEXT,
            full_name      TEXT,
            country        TEXT,
            pin            TEXT,
            birthday       TEXT,
            verify_token   TEXT,

            -- ⭐ TRUST SYSTEM FIX
            last_trust     TEXT
        )
    """)

# ====================================================
    # ⚙️ 3️⃣ SERVER SETTINGS
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS server_settings (
            guild_id             TEXT PRIMARY KEY NOT NULL,

            welcome_enabled      INTEGER NOT NULL DEFAULT 1,
            welcome_channel      TEXT,
            welcome_role         TEXT,
            welcome_message      TEXT    NOT NULL DEFAULT 'أهلاً بك!',
            image_url            TEXT,
            followups_json       TEXT    NOT NULL DEFAULT '[]',

            invite_logs_enabled  INTEGER NOT NULL DEFAULT 0,
            invite_logs_channel  TEXT,

            autorole_enabled     INTEGER NOT NULL DEFAULT 0,
            autorole_roles       TEXT    NOT NULL DEFAULT '[]',

            dm_welcome_enabled   INTEGER NOT NULL DEFAULT 0,
            dm_message           TEXT,
            dm_use_embed         INTEGER NOT NULL DEFAULT 0,

            adhkar_enabled       INTEGER NOT NULL DEFAULT 0,
            adhkar_channel       TEXT,
            adhkar_interval      INTEGER NOT NULL DEFAULT 60,
            adhkar_last_sent     INTEGER NOT NULL DEFAULT 0,
            
            custom_aliases       TEXT    NOT NULL DEFAULT '{}',

            settings             TEXT    NOT NULL DEFAULT '{}'
        )
    """)
    
    
     # ====================================================
    # 🧾 4️⃣ JOIN TRACKING
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS joined_members (
            guild_id   TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            inviter_id TEXT,
            PRIMARY KEY (guild_id, user_id)
        )
    """)

    # ====================================================
    # 🚫 5️⃣ BLOCKED SERVERS
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS blocked_servers (
            guild_id TEXT PRIMARY KEY NOT NULL
        )
    """)

    # ====================================================
    # 🔗 6️⃣ INVITES CACHE
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS invite_cache (
            guild_id    TEXT NOT NULL,
            invite_code TEXT NOT NULL,
            uses        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, invite_code)
        )
    """)

    # ====================================================
    # 🎟️ 7️⃣ COUPONS
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            code       TEXT PRIMARY KEY NOT NULL,
            creator_id TEXT NOT NULL,
            amount     INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0
        )
    """)

    # ====================================================
    # 📅 8️⃣ DAILY TRANSFERS
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS daily_transfers (
            user_id TEXT NOT NULL,
            date    TEXT NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    """)

    # ====================================================
    # ⚠️ 9️⃣ WARNINGS
    # ====================================================
    await db.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id   TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            mod_id     TEXT NOT NULL,
            reason     TEXT NOT NULL DEFAULT 'بدون سبب',
            created_at TEXT NOT NULL
        )
    """)

    # ====================================================
    # 🗂️ Indexes للأداء
    # ====================================================
    await db.execute("CREATE INDEX IF NOT EXISTS idx_users_guild     ON users (guild_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_users_xp        ON users (guild_id, msg_xp DESC);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_users_voice     ON users (guild_id, voice_xp DESC);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_users_invites   ON users (guild_id, invites DESC);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_global_kento    ON global_users (kento DESC);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_warnings_guild  ON warnings (guild_id, user_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_daily_transfers ON daily_transfers (user_id, date);")

    # ✅ commit واحد في الآخر بس
    await db.commit()

    print("✅ HYBRID ECONOMY READY (GLOBAL + SERVER SPLIT)")
    logging.info("🗄️ Clean Architecture Database Initialized")
        
    
        
# ============================================================
# 🔄 db_update_user — تحديث users و global_users في نفس الوقت
# ============================================================

_SERVER_WRITE_FIELDS = {"xp", "msg_xp", "voice_xp", "invites"}
_GLOBAL_WRITE_FIELDS = {"kento", "deposit", "level", "trust", "verified_level", "background",
                        "email", "full_name", "country", "pin", "birthday", "verify_token", "total_xp"}

# الحقول دي بتتضاف (+=) مش بتتبدل (=)
_INCREMENTAL_SERVER = {"xp", "msg_xp", "voice_xp", "invites"}
_INCREMENTAL_GLOBAL = {"kento", "deposit", "total_xp", "trust"}


async def db_update_user(uid: str, gid: str, **kwargs) -> None:
    """
    يحدّث بيانات المستخدم في الجدولين الصح:
    - users       ← xp, msg_xp, voice_xp, invites, last_mine, last_vote
    - global_users ← kento, deposit, level, trust, verified_level, background, ...

    الحقول الرقمية في _INCREMENTAL تتضاف (+=).
    باقي الحقول بتتبدل (=).
    أي حقل مش معروف يتجاهل تلقائياً.
    """
    if not kwargs:
        return

    # =========================================
    # فصل الحقول على الجدولين
    # =========================================
    server_updates: dict = {}
    global_updates: dict = {}

    for key, value in kwargs.items():
        if key in _SERVER_WRITE_FIELDS:
            server_updates[key] = value
        elif key in _GLOBAL_WRITE_FIELDS:
            global_updates[key] = value
        else:
            logging.warning(f"[db_update_user] حقل غير معروف تم تجاهله: '{key}'")

    if not server_updates and not global_updates:
        return

    try:
        async with get_write_lock():
            db = await get_db()

            # =========================================
            # 🏢 ضمان وجود المستخدم في users
            # =========================================
            await db.execute("""
                INSERT OR IGNORE INTO users (
                    user_id, guild_id,
                    xp, msg_xp, voice_xp,
                    invites, last_mine, last_vote
                )
                VALUES (?, ?, 0, 0, 0, 0, NULL, 0)
            """, (uid, gid))

            # =========================================
            # 🌍 ضمان وجود المستخدم في global_users
            # =========================================
            if global_updates:
                await db.execute("""
                    INSERT OR IGNORE INTO global_users (
                        user_id, total_xp, level,
                        kento, deposit, trust,
                        verified_level, background
                    )
                    VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
                """, (uid,))

            # =========================================
            # 🏢 UPDATE users
            # =========================================
            if server_updates:
                set_parts  = []
                set_values = []

                for k, v in server_updates.items():
                    if k in _INCREMENTAL_SERVER:
                        set_parts.append(f"{k} = {k} + ?")
                    else:
                        set_parts.append(f"{k} = ?")
                    set_values.append(v)

                await db.execute(f"""
                    UPDATE users
                    SET {', '.join(set_parts)}
                    WHERE user_id = ? AND guild_id = ?
                """, set_values + [uid, gid])

            # =========================================
            # 🌍 UPDATE global_users
            # =========================================
            if global_updates:
                set_parts  = []
                set_values = []

                for k, v in global_updates.items():
                    if k in _INCREMENTAL_GLOBAL:
                        set_parts.append(f"{k} = {k} + ?")
                    else:
                        set_parts.append(f"{k} = ?")
                    set_values.append(v)

                await db.execute(f"""
                    UPDATE global_users
                    SET {', '.join(set_parts)}
                    WHERE user_id = ?
                """, set_values + [uid])

            await db.commit()

    except Exception as e:
        logging.error(f"[db_update_user ERROR] uid={uid} gid={gid} kwargs={list(kwargs.keys())} | {e}")
        
                
                       
# ============================================================
# 💾 create_backup — نسخة احتياطية فورية
# ============================================================

async def create_backup() -> str | None:
    """
    إنشاء نسخة احتياطية فورية من قاعدة البيانات.
    - بيستخدم الـ connection المشترك (get_db) لعمل checkpoint أولاً
    - بيفتح src منفصل للـ backup عشان aiosqlite.backup تشتغل صح
    - يرجع مسار الملف لو نجح، أو None لو فشل
    """

    if not os.path.exists(DB_PATH):
        logging.warning("[⚠️] ملف قاعدة البيانات غير موجود.")
        return None

    os.makedirs(IMPORTANT_BACKUPS_DIR, exist_ok=True)

    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(IMPORTANT_BACKUPS_DIR, f"backup_{timestamp}.db")

    src = None
    dst = None

    try:
        # ✅ checkpoint على الـ connection المشترك أولاً
        db = await get_db()
        await db.execute("PRAGMA wal_checkpoint(FULL);")

        # ✅ src منفصل عشان .backup() محتاج connection خاص بيه
        src = await aiosqlite.connect(DB_PATH, timeout=15)
        dst = await aiosqlite.connect(backup_file)

        await src.backup(dst)

        logging.info(f"[💾] Backup created: {backup_file}")
        return backup_file

    except Exception as e:
        logging.error(f"[❌] Backup failed: {e}")
        # احذف الملف الناقص لو اتعمل
        if os.path.exists(backup_file):
            try:
                os.remove(backup_file)
            except Exception:
                pass
        return None

    finally:
        # ✅ اقفل src و dst دايماً حتى لو حصل خطأ
        if dst:
            try:
                await dst.close()
            except Exception:
                pass
        if src:
            try:
                await src.close()
            except Exception:
                pass


# ============================================================
# 🔄 periodic_sqlite_backup — نسخ احتياطي كل ساعة
# ============================================================

_BACKUP_KEEP    = 24       # عدد النسخ المحتفظ بيها
_BACKUP_INTERVAL = 3600    # ثانية (ساعة)


async def periodic_sqlite_backup() -> None:
    """
    Loop يشتغل في الخلفية:
    - بينشئ نسخة احتياطية كل ساعة عبر create_backup()
    - بيحتفظ بآخر 24 نسخة بس ويحذف الأقدم
    """

    os.makedirs(IMPORTANT_BACKUPS_DIR, exist_ok=True)

    while True:
        await asyncio.sleep(_BACKUP_INTERVAL)  # ✅ ننتظر أول ساعة قبل أول نسخة

        try:
            backup_file = await create_backup()

            if not backup_file:
                continue

            # =========================
            # 🧹 تنظيف النسخ القديمة
            # =========================
            try:
                all_backups = sorted(
                    [
                        os.path.join(IMPORTANT_BACKUPS_DIR, f)
                        for f in os.listdir(IMPORTANT_BACKUPS_DIR)
                        if f.endswith(".db")
                    ],
                    key=os.path.getmtime
                )

                to_delete = all_backups[:-_BACKUP_KEEP] if len(all_backups) > _BACKUP_KEEP else []

                for old in to_delete:
                    try:
                        os.remove(old)
                        logging.info(f"[🧹] Deleted old backup: {old}")
                    except Exception as e:
                        logging.error(f"[⚠️] Delete failed: {old} | {e}")

            except Exception as e:
                logging.error(f"[⚠️] Backup cleanup error: {e}")

        except Exception as e:
            logging.error(f"[❌] periodic_sqlite_backup error: {e}")
            
                    

# ============================================================
# 📊 calculate_level_and_progress — حساب المستوى والتقدم
# ============================================================

def calculate_level_and_progress(total_xp: int) -> tuple[int, int, int, int]:
    """
    يحسب المستوى الحالي والتقدم بناءً على إجمالي الـ XP.

    المعادلة: xp_needed للمستوى N = 100 + (N² × 20)
    يرجع: (level, xp_current, xp_needed, progress_percent)
    """

    total_xp = max(0, total_xp)  # ✅ منع قيم سالبة

    level    = 0
    temp_xp  = total_xp

    while True:
        needed = 100 + (level ** 2 * 20)
        if temp_xp >= needed:
            temp_xp -= needed
            level   += 1
        else:
            break

    xp_current = temp_xp
    xp_needed  = 100 + (level ** 2 * 20)
    progress   = int((xp_current / xp_needed) * 100) if xp_needed else 0

    return level, xp_current, xp_needed, progress


# ============================================================
# ⭐ add_xp — إضافة XP للسيرفر والعالمي + تحديث المستوى
# ============================================================

_VALID_XP_TYPES = {"msg", "voice"}

async def add_xp(user_id: int, guild_id: int, xp_amount: int, type: str = "msg") -> int:
    """
    يضيف XP للمستخدم في:
    - users       ← xp + msg_xp أو voice_xp (خاص بالسيرفر)
    - global_users ← total_xp + level       (عالمي)

    يرجع المستوى الجديد (int).
    """

    if xp_amount <= 0:
        return 0

    if type not in _VALID_XP_TYPES:
        logging.warning(f"[add_xp] نوع XP غير معروف: '{type}' — تم استخدام 'msg'")
        type = "msg"

    uid    = str(user_id)
    gid    = str(guild_id)
    column = "msg_xp" if type == "msg" else "voice_xp"

    try:
        async with get_write_lock():
            db = await get_db()

            # ✅ ضمان وجود المستخدم في السيرفر
            await db.execute("""
                INSERT OR IGNORE INTO users (
                    user_id, guild_id,
                    xp, msg_xp, voice_xp,
                    invites, last_mine, last_vote
                )
                VALUES (?, ?, 0, 0, 0, 0, NULL, 0)
            """, (uid, gid))

            # ✅ ضمان وجود المستخدم عالمياً
            await db.execute("""
                INSERT OR IGNORE INTO global_users (
                    user_id, total_xp, level,
                    kento, deposit, trust,
                    verified_level, background
                )
                VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
            """, (uid,))

            # ✅ إضافة XP للسيرفر (xp الكلي + العمود الخاص)
            await db.execute(f"""
                UPDATE users
                SET xp = xp + ?,
                    {column} = {column} + ?
                WHERE user_id = ? AND guild_id = ?
            """, (xp_amount, xp_amount, uid, gid))

            # ✅ إضافة XP العالمي
            await db.execute("""
                UPDATE global_users
                SET total_xp = total_xp + ?
                WHERE user_id = ?
            """, (xp_amount, uid))

            # ✅ جلب total_xp الجديد
            async with db.execute("""
                SELECT total_xp FROM global_users
                WHERE user_id = ?
            """, (uid,)) as cursor:
                row = await cursor.fetchone()

            total_xp = row["total_xp"] if row else 0

            # ✅ حساب المستوى الجديد
            new_level, _, _, _ = calculate_level_and_progress(total_xp)

            # ✅ تحديث المستوى في global_users
            await db.execute("""
                UPDATE global_users
                SET level = ?
                WHERE user_id = ?
            """, (new_level, uid))

            await db.commit()

        return new_level

    except Exception as e:
        logging.error(f"[add_xp ERROR] uid={uid} gid={gid} amount={xp_amount} | {e}")
        return 0
        
                        
PREFIX = "!"

@bot.event
async def on_message(message: discord.Message):

    # ============================================================
    # 1️⃣ التجاهل الأساسي — أول حاجة دايماً
    # ============================================================
    if not message.guild or message.author.bot:
        return

    guild_id = str(message.guild.id)
    uid      = str(message.author.id)
    text     = message.content.strip()

    # رسالة فاضية بدون ملفات
    if not text and not message.attachments:
        await bot.process_commands(message)
        return

    # ============================================================
    # 2️⃣ حفظ الرسالة في الكاش (للحذف لاحقاً)
    # tuple: (author_id, content, channel_id, timestamp, attachments)
    # ============================================================
    if not hasattr(bot, "deleted_messages_cache"):
        bot.deleted_messages_cache = {}

    bot.deleted_messages_cache[message.id] = (
        message.author.id,
        message.content or "",
        message.channel.id,
        message.created_at.timestamp(),
        tuple(a.url for a in message.attachments)
    )

    # تنظيف الكاش لو كبر (احتفظ بآخر 500 رسالة بس)
    if len(bot.deleted_messages_cache) > 500:
        oldest_keys = list(bot.deleted_messages_cache.keys())[:100]
        for k in oldest_keys:
            bot.deleted_messages_cache.pop(k, None)



    # ============================================================
    # 2️⃣ نظام الاختصارات (Aliases) — من الكاش مباشرة
    # ============================================================
    base_aliases = {
        "k": "تحويل", "w": "توب", "p": "ملف",
        "رصيد": "رصيد", "تحويل": "تحويل", "توب": "توب", "ملف": "ملف",
        "تحذير": "تحذير", "warn": "تحذير", "فتح": "فتح", "unlock": "فتح",
        "قفل": "قفل", "lock": "قفل", "تايم": "تايم", "timeout": "تايم",
        "ميوت": "ميوت", "mute": "ميوت", "مسح": "مسح", "clear": "مسح",
        "تعدين": "minecoins", "باند": "باند", "ban": "باند", "bnd": "باند",
        "طرد": "طرد", "kick": "طرد", "kck": "طرد",
        "top": "top_xp", "t": "top_xp", "top_xp": "top_xp",
        
        # 🏢 أمر سيرفر واختصاراته
        "سيرفر": "سيرفر", "server": "سيرفر", "s": "سيرفر",
        
        # 🆔 أمر iid واختصاراته
        "iid": "iid", "id": "iid", "id": "iid"
    }

    # ✅ من الكاش مباشرة — مفيش DB call هنا خالص
    raw_aliases = server_settings_cache.get(guild_id, {}).get("custom_aliases", {})
    if isinstance(raw_aliases, str):
        try:
            raw_aliases = json.loads(raw_aliases)
        except Exception:
            raw_aliases = {}

    aliases = {**base_aliases, **raw_aliases}

    # ============================================================
    # 3️⃣ تحويل النص حسب الاختصارات
    # ============================================================
    parts = text.split()
    if not parts:
        await bot.process_commands(message)
        return

    first_word  = parts[0].lower().strip()
    rest_text   = " ".join(parts[1:]) if len(parts) > 1 else ""
    transformed = None

    # منطق k الذكي
    if first_word == "k":
        if len(parts) == 1:
            transformed = f"{PREFIX}رصيد"
        elif message.mentions and len(parts) == 2:
            transformed = f"{PREFIX}رصيد {message.mentions[0].mention}"
        elif any(ch.isdigit() for ch in rest_text):
            transformed = f"{PREFIX}تحويل {rest_text}".strip()
        else:
            transformed = f"{PREFIX}رصيد"

    # aliases بدون prefix
    elif first_word in aliases:
        transformed = f"{PREFIX}{aliases[first_word]} {rest_text}".strip()

    # aliases مع prefix
    elif first_word.startswith(PREFIX):
        raw = first_word[len(PREFIX):]
        if raw in aliases:
            transformed = f"{PREFIX}{aliases[raw]} {rest_text}".strip()

    if transformed:
        message.content = transformed
        text = transformed

    # ============================================================
    # 4️⃣ نظام XP — مرة كل 10 ثواني لكل مستخدم
    # ============================================================
    now       = time.time()
    last_time = last_xp_time.setdefault(guild_id, {}).get(uid, 0)

    if now - last_time >= 10:
        try:
            await add_xp(int(uid), int(guild_id), 1, type="msg")
            last_xp_time[guild_id][uid] = now

            # تنظيف الكاش لو كبر
            if len(last_xp_time[guild_id]) > 1000:
                last_xp_time[guild_id].clear()

        except Exception as e:
            logging.error(f"[on_message XP ERROR] uid={uid} gid={guild_id} | {e}")

    # ============================================================
    # 5️⃣ روم مراجعة التوثيق
    # ============================================================
    if message.channel.id == VERIFICATION_REVIEW_CHANNEL_ID:

        content_clean = message.content.strip()
        is_id_digits  = content_clean.isdigit()
        is_mention    = bool(message.mentions)

        if is_id_digits or is_mention:
            uid_lookup = str(message.mentions[0].id) if is_mention else content_clean

            try:
                db = await get_db()
                async with db.execute(
                    "SELECT * FROM global_users WHERE user_id = ?",
                    (uid_lookup,)
                ) as cursor:
                    row = await cursor.fetchone()

                if not row or row["verified_level"] == 0:
                    await message.channel.send(
                        f"⚠️ العضو <@{uid_lookup}> غير موثّق أو غير موجود.",
                        delete_after=7
                    )
                else:
                    v_level = row["verified_level"]

                    emb = discord.Embed(
                        title="📑 ملف تحقق عضو (GLOBAL SYSTEM)",
                        colour=discord.Colour.green() if v_level >= 2 else discord.Colour.orange(),
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    emb.add_field(name="👤 العضو",        value=f"<@{uid_lookup}> (`{uid_lookup}`)", inline=False)
                    emb.add_field(name="🪪 الاسم الرباعي", value=row["full_name"] or "غير محدد",     inline=False)
                    emb.add_field(name="🌍 الدولة",        value=row["country"]   or "غير محدد",     inline=True)
                    emb.add_field(name="📧 البريد",         value=row["email"]     or "غير محدد",     inline=True)
                    emb.add_field(name="🎂 تاريخ الميلاد", value=row["birthday"]  or "غير محدد",     inline=True)
                    emb.add_field(
                        name="📌 الحالة",
                        value="🟢 Email Verified" if v_level >= 2 else "🟡 PIN Verified",
                        inline=False
                    )
                    emb.add_field(name="🔑 PIN", value=f"`{row['pin'] or '---'}`", inline=False)

                    try:
                        target_user = await bot.fetch_user(int(uid_lookup))
                        emb.set_thumbnail(url=target_user.display_avatar.url)
                    except Exception:
                        pass

                    await message.channel.send(embed=emb)

            except Exception as e:
                logging.error(f"[on_message VERIFY ERROR] uid={uid_lookup} | {e}")

    # ============================================================
    # 6️⃣ معالجة الأوامر — دايماً آخر حاجة
    # ============================================================
    await bot.process_commands(message)
    

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):

    # ============================================================
    # 1️⃣ التجاهل الأساسي
    # ============================================================
    if member.bot or not member.guild:
        return

    uid = str(member.id)
    gid = str(member.guild.id)
    now = time.time()

    # ============================================================
    # 2️⃣ تحديد AFK
    # ============================================================
    is_afk = (
        after.channel
        and member.guild.afk_channel
        and after.channel.id == member.guild.afk_channel.id
    )

    try:
        # ============================================================
        # 3️⃣ JOIN VOICE — تسجيل وقت الدخول
        # ============================================================
        if not before.channel and after.channel and not is_afk:
            voice_join_times[uid] = now

        # ============================================================
        # 4️⃣ LEAVE / AFK — حساب الوقت وإضافة XP
        # ============================================================
        elif before.channel and (not after.channel or is_afk):

            join_time = voice_join_times.pop(uid, None)

            if join_time:
                elapsed = now - join_time
                minutes = int(elapsed / 60)

                if minutes >= 1:
                    xp_gain = max(1, minutes // 4)

                    # ✅ add_xp بيعمل ensure_user و ensure_global_user جوّاه
                    new_level = await add_xp(int(uid), int(gid), xp_gain, type="voice")

                    # ✅ إشعار Level Up — تم إيقاف إرسال الرسالة في الخاص
                    if new_level and new_level > 0:
                        try:
                            # ✅ get_db بدل aiosqlite.connect
                            db = await get_db()
                            async with db.execute(
                                "SELECT level FROM global_users WHERE user_id = ?",
                                (uid,)
                            ) as cursor:
                                row = await cursor.fetchone()

                            new_lvl = row["level"] if row else new_level

                            # 🛑 تم تعطيل إرسال الرسالة في الخاص لراحة الأعضاء
                            pass
                        except Exception:
                            pass

                    logging.info(
                        f"[🎙️ Voice XP] {member.name} +{xp_gain} XP in {member.guild.name}"
                    )


        # ============================================================
        # 5️⃣ MOVE — انتقل بين رومات صوتية
        # ============================================================
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            if not is_afk:
                voice_join_times[uid] = now

        # ============================================================
        # 6️⃣ COG HANDLER
        # ============================================================
        cog = bot.get_cog("TasksSystem")
        if cog and hasattr(cog, "on_voice_state_update"):
            asyncio.create_task(
                cog.on_voice_state_update(member, before, after)
            )

    except Exception as e:
        logging.error(f"[on_voice_state_update ERROR] uid={uid} gid={gid} | {e}")
        

# ============================================================
# 🗑️ on_message_delete — تسجيل الرسائل المحذوفة
# ============================================================

@bot.event
async def on_message_delete(message: discord.Message):

    # ============================================================
    # 1️⃣ التجاهل الأساسي
    # ============================================================
    if not message.guild or message.author.bot:
        return

    gid = str(message.guild.id)

    # ============================================================
    # 2️⃣ جلب إعدادات اللوج من الكاش
    # ============================================================
    settings = server_settings_cache.get(gid)

    if settings is None:
        # حاول تحمّل الكاش من DB لو مش موجود
        try:
            db = await get_db()
            async with db.execute(
                "SELECT settings FROM server_settings WHERE guild_id = ?",
                (gid,)
            ) as cursor:
                row = await cursor.fetchone()

            if row and row["settings"]:
                try:
                    settings = json.loads(row["settings"])
                    server_settings_cache[gid] = settings
                except Exception:
                    settings = {}
            else:
                settings = {}

        except Exception as e:
            logging.error(f"[on_message_delete CACHE ERROR] gid={gid} | {e}")
            settings = {}

    # ============================================================
    # 3️⃣ التحقق من تفعيل لوج الحذف
    # ============================================================
    deleted_log = settings.get("deleted_log")

    if not deleted_log or not deleted_log.get("enabled"):
        return

    log_channel_id = deleted_log.get("channel_id")
    if not log_channel_id:
        return

    # ============================================================
    # 4️⃣ جلب قناة اللوج
    # ============================================================
    log_channel = bot.get_channel(int(log_channel_id))
    if log_channel is None:
        try:
            log_channel = await bot.fetch_channel(int(log_channel_id))
        except Exception:
            return

    # ============================================================
    # 5️⃣ جلب بيانات الرسالة
    # ✅ الكاش هنا tuple: (author_id, content, channel_id, timestamp, attachments)
    # ============================================================
    cache = getattr(bot, "deleted_messages_cache", None)
    saved = cache.pop(message.id, None) if cache else None

    if saved and isinstance(saved, tuple) and len(saved) == 5:
        author_id, content, channel_id, timestamp, attachments = saved

        author           = message.guild.get_member(author_id) or message.author
        original_channel = message.guild.get_channel(channel_id) or message.channel
        time_str         = datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    else:
        # fallback لو الرسالة مش في الكاش
        author           = message.author
        content          = message.content or "*محتوى غير معروف*"
        original_channel = message.channel
        time_str         = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        attachments      = tuple(a.url for a in message.attachments)

    # ============================================================
    # 6️⃣ Audit Log — مين اللي حذف الرسالة
    # ============================================================
    deleter = "غير معروف ❓"

    try:
        async for entry in message.guild.audit_logs(
            limit=1,
            action=discord.AuditLogAction.message_delete
        ):
            if entry.target and entry.target.id == author.id:
                deleter = entry.user.mention
                break
    except Exception:
        pass

    # ============================================================
    # 7️⃣ بناء الـ Embed
    # ============================================================
    embed = discord.Embed(
        title="🗑️ Message Deleted",
        color=discord.Color.red(),
        timestamp=datetime.datetime.utcnow()
    )

    embed.description = (
        f"**User:** {author.mention}\n"
        f"**Deleted by:** {deleter}\n"
        f"**Channel:** {original_channel.mention}\n"
        f"**Time:** `{time_str}`"
    )

    # محتوى الرسالة
    if content and content != "*محتوى غير معروف*":
        embed.add_field(
            name="Content",
            value=f"```{content[:1000]}```",
            inline=False
        )

    # المرفقات
    if attachments:
        embed.add_field(
            name="Attachments",
            value=f"{len(attachments)} file(s)",
            inline=False
        )

        first = attachments[0]
        if isinstance(first, str) and first.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
            embed.set_image(url=first)

    # ============================================================
    # 8️⃣ إرسال اللوج
    # ============================================================
    try:
        await log_channel.send(embed=embed)
    except discord.Forbidden:
        logging.warning(f"[on_message_delete] لا توجد صلاحية للإرسال في القناة {log_channel_id}")
    except Exception as e:
        logging.error(f"[on_message_delete SEND ERROR] gid={gid} | {e}")
                                                                     


async def update_invite_cache(guild: discord.Guild):
    """تحديث الكاش لتقليل الضغط على API ديسكورد"""
    now = datetime.datetime.utcnow()
    gid = guild.id

    if gid in last_invite_check and (now - last_invite_check[gid]).total_seconds() < 30:
        return invite_cache.get(gid)

    async with invite_lock:
        try:
            invites = await guild.invites()
            invites_map = {i.code: i.uses for i in invites}
            invite_cache[gid] = invites_map
            last_invite_check[gid] = now
            return invites_map
        except Exception as e:
            logging.warning(f"[⚠️] فشل تحديث الدعوات لـ {guild.name}: {e}")
            return invite_cache.get(gid, {})

# -------------------------------
# نظام إرسال الرسائل الخاصة (DM Worker)
# -------------------------------
async def dm_worker(guild_id: int):
    """عامل إرسال رسائل الترويج من الطابور"""
    if guild_id not in dm_queues:
        return
        
    queue = dm_queues[guild_id]
    while True:
        member: discord.Member = await queue.get()
        try:
            # التأكد من وجود دوال الرسائل والأزرار
            await member.send(get_promo_message(member), view=PromoButtons())
            await asyncio.sleep(DM_COOLDOWN)
        except Exception as e:
            print(f"[⚠️ DM Promo Error] {e}")
        finally:
            queue.task_done()

# -------------------------------
# ملاحظة: استبدلنا save_invites_data بـ SQL 
# سيتم تنفيذ الحفظ فوراً في الأحداث القادمة (Join/Leave)
# -------------------------------

                        
# -------------------------------
# حفظ البيانات بشكل آمن (SQLite Version)
# -------------------------------
async def safe_save_invites():
    """
    في نظام SQLite، الحفظ يتم تلقائياً عند تنفيذ await db.commit()
    لذا نترك هذه الدالة لضمان توافق الأكواد القديمة التي تستدعيها.
    """
    pass 


def get_promo_message(user: discord.User) -> str:
    return """**# GxBot — الجيل الجديد من أنظمة ديسكورد
بوت متكامل لإدارة السيرفر يجمع بين الأمان، الإدارة، الاقتصاد، والتفاعل الذكي داخل شبكة موحدة.
من تطوير فريق برمجيات Global X **

### المميزات الرئيسية:
-# - 
**1 الأمان والتوثيق: PIN وبريد إلكتروني لحماية الحسابات والمعاملات.

2 العملة Kentos: تحويلات داخلية وبنكية، كوبونات، وحماية تلقائية للرصيد.

3 المهام والتوب: نقاط يومية، ترتيب الأعضاء والسيرفرات، توب عالمي.

4 التذاكر والدعم: نظام ذكي لإدارة الشكاوى مع تقييمات وتوب فريق الدعم.

5 شبكة GxHip الاجتماعية: منشورات، تعليقات، بروفايلات، وحماية محتوى تلقائية.

6 الإدارة واللوغ: حظر، كتم، دعوات، وتتبع كل الأحداث تلقائيًا.

7 البروفايلات والخلفيات: أكثر من 140 خلفية مع عرض الرصيد والإنجازات.

8 الترفيه والتفاعل: ألعاب، نقاط XP، اقتراحات، وأنظمة تفاعلية متنوعة.

9 الحماية: مضاد سبام وروابط، تحذيرات تلقائية، وتكامل كامل مع التوثيق.

10 دعوات والترحيب: نظام خروج ودخول الأعضاء ترحيب في خاص وفي رومات 

11 رقابه: تسجيل دخول الأداره يوميا ومتابعه التسجيلات

12 ردود الإيموجي : ردود تلقائي وا ردود على كلمات رد خط وا ردود الإيموجي على رسايل وتحويل صور ل ايموجي 

13 اخري: انظمه اخذ رولات او ازاله اميبد نظام اقتراحات في روم وا تقييمات في روم افتار عضو اذكار دينيه في روم 
تغير ايقون رتبه رول
-# - 
### الخلاصة: GxBot
هو نظام متكامل لإدارة مجتمعك باحتراف داخل شبكة عالمية واغلب مزايا برايم في أغلب البوتات موجوده بشكل مجاني.**
-# > Trust Above All 
-# > الثقة قبل كل شيء
-# https://cdn.discordapp.com/attachments/1427578850094874795/1475070761021603892/6ad2a11635410e0d.png 
-# https://discord.gg/N4f4rsfSkR
"""

class PromoButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        # زر دعوة البوت
        self.add_item(discord.ui.Button(
            label="دعوة البوت ➕",
            style=discord.ButtonStyle.link,
            url="https://discord.com/oauth2/authorize?client_id=1411571554025865236&permissions=8&scope=bot%20applications.commands"
        ))

        # زر موقع البوت
        self.add_item(discord.ui.Button(
            label="موقع البوت 🌐",
            style=discord.ButtonStyle.link,
            url="https://gxbot.is-best.net"
        ))
        
                
## -------------------------------
# حدث دخول العضو مع نظام الرتب التلقائي (SQLite Version)
# -------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    guild_id = str(member.guild.id)
    user_id = str(member.id)

    # 1. ضمان وجود العضو في قاعدة البيانات الأساسية (Kentos/XP)
    try:
        await ensure_user(user_id, str(guild.id))
    except NameError:
        pass

    # 2. جلب إعدادات السيرفر من SQLite
    async with aiosqlite.connect(DB_PATH, timeout=20) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM server_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            settings = await cursor.fetchone()
    
    # تحويل الصف لقاموس لتسهيل التعامل مع الكود القديم
    settings = dict(settings) if settings else {}

    # 3. نظام تحديث الدعوات وتحديد الداعي
    inviter_id = None
    try:
        invites_now = await member.guild.invites()
        # نستخدم الكاش لسرعة المقارنة
        previous_invites = invite_cache.get(member.guild.id) or {}

        for invite in invites_now:
            old_uses = previous_invites.get(invite.code, 0)
            if invite.uses > old_uses:
                inviter_id = str(invite.inviter.id) if invite.inviter else None
                break

        # تحديث الكاش فوراً
        invites_map = {invite.code: invite.uses for invite in invites_now}
        invite_cache[member.guild.id] = invites_map

        # تسجيل الدعوة في قاعدة البيانات
        if inviter_id:
            async with aiosqlite.connect(DB_PATH) as db:
                # التحقق إذا كان العضو دخل قبل كدة (عشان ميزودش دعوات وهمية)
                async with db.execute("SELECT user_id FROM joined_members WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cur:
                    already_joined = await cur.fetchone()
                
                if not already_joined:
                    # تسجيل العضو الجديد مع الداعي له
                    await db.execute("INSERT INTO joined_members (guild_id, user_id, inviter_id) VALUES (?, ?, ?)", 
                                     (guild_id, user_id, inviter_id))
                    # زيادة عدد دعوات الداعي في جدول المستخدمين الرئيسي
                    await db.execute("UPDATE users SET invites = invites + 1 WHERE user_id = ?", (inviter_id,))
                    await db.commit()
    except Exception as e:
        print(f"[⚠️] فشل معالجة الدعوات: {e}")
    # 4. إرسال رسالة الترحيب (Welcome Embed)
    if settings.get("welcome_enabled", 1):
        channel_id = settings.get("welcome_channel")
        if channel_id:
            channel = member.guild.get_channel(int(channel_id))
            if channel:
                try:
                    # 💡 تم تعديل العنوان والوصف ليعتمد فقط على كلام الإعدادات ومنشن العضو
                    embed = discord.Embed(
                        title=f"{member.display_name}",
                        description=f"{settings.get('welcome_message', 'أهلاً بك!')}\n{member.mention}",
                        color=discord.Color.gold()
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)

                    # معالجة الـ followups (إذا كنت مخزنها كـ JSON في القاعدة)
                    import json
                    try:
                        followups = json.loads(settings.get("followups_json", "[]"))
                        for i, item in enumerate(followups[:3], start=1):
                            ch = member.guild.get_channel(int(item.get("channel_id")))
                            msg = item.get("message")
                            if ch and msg:
                                embed.add_field(name=f"📌 Section {i}", value=f"**{msg}**\n➡️ {ch.mention}", inline=False)
                    except: pass

                    if settings.get("image_url"):
                        embed.set_image(url=settings.get("image_url"))

                    embed.set_footer(text=f"Member #{len(member.guild.members)} in the server 🎊")
                    embed.timestamp = discord.utils.utcnow()
                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"[⚠️] خطأ ترحيب: {e}")

    # 5. إعطاء رتبة الترحيب والرتب التلقائية
    try:
        roles_to_add = []
        # رتبة الترحيب الأساسية
        if settings.get("welcome_role"):
            r = member.guild.get_role(int(settings["welcome_role"]))
            if r: roles_to_add.append(r)
        
        # رتب AutoRoles
        if settings.get("autorole_enabled"):
            try:
                autorole_ids = json.loads(settings.get("autorole_roles", "[]"))
                for rid in autorole_ids:
                    r = member.guild.get_role(int(rid))
                    if r: roles_to_add.append(r)
            except: pass
            
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason="GxBot: نظام الرتب التلقائي")
    except Exception as e:
        print(f"[⚠️] فشل إعطاء الرتب: {e}")

#=====
    # 6. نظام DM Welcome
    # 6. نظام DM Welcome
    try:
        dm_enabled = settings.get("dm_welcome_enabled", 0)
        if dm_enabled:
            dm_use_embed = settings.get("dm_use_embed", 0)

            # افتراضياً بنستخدم الرسالة المخزنة
            dm_msg = settings.get("dm_message") or "مرحباً بك في السيرفر!"

            if dm_use_embed:
                dm_embed = discord.Embed(
                    title=f"أهلاً وسهلاً {member.display_name}!",
                    description=dm_msg or "مرحباً بك في السيرفر!",
                    color=discord.Color.gold()
                )
                # 🛑 تم إزالة سطر إضافة صورة العضو (set_thumbnail) من هنا
                dm_embed.timestamp = discord.utils.utcnow()
                try:
                    await member.send(embed=dm_embed)
                except:
                    pass
            else:
                dm_msg = dm_msg or "مرحباً بك في السيرفر!"
                try:
                    await member.send(dm_msg)
                except:
                    pass
    except Exception as e:
        print(f"[⚠️] خطأ DM Welcome: {e}")
        
#==/==        
    # 7. تسجيل الدخول في قناة لوج الدعوات
    if settings.get("invite_logs_enabled", 0):
        log_channel_id = settings.get("invite_logs_channel")
        if log_channel_id:
            log_channel = member.guild.get_channel(int(log_channel_id))
            if log_channel:
                inviter_name = "❓ غير معروف"
                inviter_invites_count = 0
                if inviter_id:
                    try:
                        inviter = await bot.fetch_user(int(inviter_id))
                        inviter_name = inviter.name
                    except: pass
                    try:
                        async with aiosqlite.connect(DB_PATH) as db:
                            async with db.execute("SELECT invites FROM users WHERE user_id = ?", (inviter_id,)) as cur:
                                row = await cur.fetchone()
                                inviter_invites_count = row[0] if row else 0
                    except: pass
                
                await log_channel.send(
                    f"📥 **{member.mention}** انضم إلى السيرفر.\n"
                    f"تمت دعوته بواسطة: **{inviter_name}**"
                    f"  دعواته: {inviter_invites_count}"
                )
    # 8. 📣 Smart DM Promotion (Anti-Spam)
    # التعديل: لا يرسل الترويج إذا كان نظام DM Welcome الخاص بالسيرفر مفعلاً
    try:
        # فحص: هل صاحب السيرفر مفعل رسالة ترحيب خاصة به في الخاص؟
        # settings جلبناها مسبقاً من SQLite في بداية حدث on_member_join
        is_custom_dm_enabled = settings.get("dm_welcome_enabled", 0)

        if not is_custom_dm_enabled:
            # إذا لم يكن هناك ترحيب خاص، نضع العضو في طابور الترويج المعتاد
            gid = member.guild.id
            if gid not in dm_queues: 
                dm_queues[gid] = asyncio.Queue()
            
            await dm_queues[gid].put(member)
            
            if gid not in dm_tasks or dm_tasks[gid].done():
                dm_tasks[gid] = asyncio.create_task(dm_worker(gid))
        else:
            # إذا كان مفعلاً، نكتفي برسالة السيرفر ولا نرسل ترويج البوت
            print(f"[ℹ️] تخطي الترويج لـ {member.name} (بسبب تفعيل DM Welcome الخاص بالسيرفر)")

    except Exception as e:
        print(f"[⚠️ DM Promo Error] {e}")
        
@bot.event
async def on_member_remove(member):
    if member.bot: return

    guild_id, user_id = str(member.guild.id), str(member.id)
    inviter_id, settings = None, {}

    # 1. فتح اتصال واحد لتنفيذ كل العمليات (أداء أسرع)
    async with aiosqlite.connect(DB_PATH, timeout=20) as db:
        db.row_factory = aiosqlite.Row
        
        # جلب الإعدادات والداعي في بلوك واحد
        async with db.execute("SELECT * FROM server_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            settings = dict(row) if row else {}
        
        async with db.execute("SELECT inviter_id FROM joined_members WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
            joined_row = await cursor.fetchone()
            if joined_row:
                inviter_id = joined_row["inviter_id"]

        # 2. معالجة البيانات إذا وجد الداعي
        if inviter_id:
            await db.execute("DELETE FROM joined_members WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            await db.execute("UPDATE users SET invites = MAX(0, invites - 1) WHERE user_id = ?", (inviter_id,))
            await db.commit()

    # 3. تحديث كاش الدعوات لضمان الدقة (مهم جداً لـ GxBot)
    try:
        invites_now = await member.guild.invites()
        invite_cache[member.guild.id] = {i.code: i.uses for i in invites_now}
    except: pass
####
    # 4. نظام اللوج (Logs)
    if settings.get("invite_logs_enabled") and settings.get("invite_logs_channel"):
        log_ch = member.guild.get_channel(int(settings["invite_logs_channel"]))
        if log_ch:
            inviter_name = "❓ غير معروف"
            inviter_invites_count = 0
            if inviter_id:
                inviter = member.guild.get_member(int(inviter_id)) or await bot.fetch_user(int(inviter_id))
                inviter_name = inviter.name if inviter else inviter_id
                try:
                    async with aiosqlite.connect(DB_PATH) as db:
                        async with db.execute("SELECT invites FROM users WHERE user_id = ?", (inviter_id,)) as cur:
                            row = await cur.fetchone()
                            inviter_invites_count = row[0] if row else 0
                except: pass
            
            await log_ch.send(f"📤 **{member.name}** خرج من السيرفر.\n**بواسطة:** {inviter_name}\n دعواته: {inviter_invites_count}")
            # ============================================================
# 🔄 sync_guild_members_fast — مزامنة أعضاء السيرفر مع DB
# ============================================================

async def sync_guild_members_fast(guild: discord.Guild) -> None:
    """
    يضمن وجود كل أعضاء السيرفر في users و global_users.
    بيشتغل في الخلفية عند دخول سيرفر جديد.
    """
    gid     = str(guild.id)
    members = [m for m in guild.members if not m.bot]
    count   = 0

    for member in members:
        uid = str(member.id)
        try:
            await ensure_user(uid, gid)
            await ensure_global_user(uid)
            count += 1
        except Exception as e:
            logging.error(f"[sync_guild_members_fast ERROR] uid={uid} gid={gid} | {e}")

    logging.info(f"[✅] تمت مزامنة {count}/{len(members)} عضو في {guild.name}")


# ============================================================
# 🏠 on_guild_join — دخول سيرفر جديد
# ============================================================

SUPPORT_LOG_CHANNEL_ID = 1433032605531377829

@bot.event
async def on_guild_join(guild: discord.Guild):

    gid = str(guild.id)

    try:
        # ============================================================
        # 1️⃣ التحقق من الحظر
        # ✅ get_db بدل aiosqlite.connect
        # ============================================================
        db = await get_db()
        async with db.execute(
            "SELECT guild_id FROM blocked_servers WHERE guild_id = ?",
            (gid,)
        ) as cursor:
            if await cursor.fetchone():
                await guild.leave()
                logging.warning(f"[🚫] غادر سيرفر محظور: {guild.name} ({guild.id})")
                return

        # ============================================================
        # 2️⃣ إنشاء إعدادات السيرفر الافتراضية
        # ✅ lock + get_db
        # ============================================================
        async with get_write_lock():
            db = await get_db()
            await db.execute("""
                INSERT OR IGNORE INTO server_settings (
                    guild_id,
                    welcome_enabled,
                    invite_logs_enabled
                )
                VALUES (?, 1, 0)
            """, (gid,))
            await db.commit()

        # تحديث الكاش
        server_settings_cache.setdefault(gid, {})
        logging.info(f"[✅] تم تسجيل السيرفر في DB: {guild.name}")

        # ============================================================
        # 3️⃣ تحديث كاش الدعوات
        # ✅ update_invite_cache بدل تكرار نفس الكود
        # ============================================================
        try:
            invites_map = await asyncio.wait_for(
                update_invite_cache(guild),
                timeout=10
            )
            logging.info(f"[📜] تم تحميل {len(invites_map)} دعوة من {guild.name}")
        except asyncio.TimeoutError:
            invite_cache[guild.id] = {}
            logging.warning(f"[⚠️] timeout في تحميل الدعوات: {guild.name}")
        except Exception as e:
            invite_cache[guild.id] = {}
            logging.warning(f"[⚠️] فشل تحميل الدعوات: {guild.name} | {e}")

        # ============================================================
        # 4️⃣ مزامنة الأعضاء في الخلفية
        # ============================================================
        asyncio.create_task(sync_guild_members_fast(guild))

        # ============================================================
        # 5️⃣ تقرير دخول السيرفر لقناة الدعم
        # ============================================================
        log_channel = bot.get_channel(SUPPORT_LOG_CHANNEL_ID)
        if not log_channel:
            try:
                log_channel = await bot.fetch_channel(SUPPORT_LOG_CHANNEL_ID)
            except Exception:
                log_channel = None

        if log_channel:
            # محاولة إنشاء دعوة
            invite_url = "❌ لا توجد صلاحية إنشاء دعوة"
            try:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).create_instant_invite:
                        invite     = await channel.create_invite(max_age=0, max_uses=0)
                        invite_url = invite.url
                        break
            except Exception:
                invite_url = "❌ خطأ أثناء إنشاء الدعوة"

            try:
                await log_channel.send(
                    f"🟢 **دخلت سيرفر جديد!**\n\n"
                    f"🏠 **اسم السيرفر:** `{guild.name}`\n"
                    f"🆔 **أيدي السيرفر:** `{guild.id}`\n"
                    f"👥 **عدد الأعضاء:** `{guild.member_count}`\n"
                    f"🔗 **رابط دعوة:** {invite_url}\n"
                    f"📅 **التاريخ:** <t:{int(discord.utils.utcnow().timestamp())}:F>"
                )
            except Exception as e:
                logging.error(f"[on_guild_join LOG ERROR] | {e}")

    except Exception as e:
        logging.error(f"[on_guild_join ERROR] gid={gid} | {e}")
                                                                                                                                                                                                                      
@bot.tree.command(name="invites", description="عرض عدد الدعوات أو التوب 10")
@app_commands.describe(member="(اختياري) اختر عضو لعرض عدد دعواته فقط")
async def invites(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer(thinking=True)

    guild_id = str(interaction.guild.id)

    async with aiosqlite.connect(DB_PATH, timeout=20) as db:
        db.row_factory = aiosqlite.Row

        # =========================
        # عضو معين
        # =========================
        if member:
            async with db.execute("""
                SELECT invites 
                FROM users 
                WHERE user_id = ? AND guild_id = ?
            """, (str(member.id), guild_id)) as cursor:
                row = await cursor.fetchone()

            count = row["invites"] if row else 0

            embed = discord.Embed(
                title="📨 عدد الدعوات",
                description=f"**{member.mention}** لديه **{count}** دعوة في هذا السيرفر.",
                color=discord.Color.blue()
            )
            return await interaction.followup.send(embed=embed)

        # =========================
        # Leaderboard (Top 10)
        # =========================
        async with db.execute("""
            SELECT user_id, invites
            FROM users
            WHERE guild_id = ? AND invites > 0
            ORDER BY invites DESC
            LIMIT 10
        """, (guild_id,)) as cursor:
            top_inviters = await cursor.fetchall()

    # =========================
    # لو مفيش بيانات
    # =========================
    if not top_inviters:
        return await interaction.followup.send("❌ لا توجد بيانات دعوات.")

    # =========================
    # بناء القائمة
    # =========================
    invite_list = []

    for i, row in enumerate(top_inviters, start=1):
        uid = row["user_id"]
        uses = row["invites"]

        try:
            user = await bot.fetch_user(int(uid))
            name = user.name
        except:
            name = f"User {uid}"

        invite_list.append(f"**{i}** - {name} » `{uses}` دعوة")

    embed = discord.Embed(
        title=f"🏆 أفضل الداعين في {interaction.guild.name}",
        description="\n".join(invite_list),
        color=discord.Color.gold()
    )

    await interaction.followup.send(embed=embed)
    
# ============================================================
# 📌 autorole_setup — إعداد الرتب التلقائية
# ============================================================

@bot.tree.command(
    name="autorole_setup",
    description="تفعيل أو إلغاء نظام AutoRoles وتحديد الرتب"
)
@app_commands.describe(
    action="اختر تفعيل أو إلغاء النظام",
    role1="اختر الرتبة الأولى (اختياري)",
    role2="اختر الرتبة الثانية (اختياري)",
    role3="اختر الرتبة الثالثة (اختياري)",
    role4="اختر الرتبة الرابعة (اختياري)",
    role5="اختر الرتبة الخامسة (اختياري)",
    role6="اختر الرتبة السادسة (اختياري)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="تفعيل النظام",  value="enable"),
    app_commands.Choice(name="إلغاء النظام", value="disable")
])
async def autorole_setup(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    role1: discord.Role = None,
    role2: discord.Role = None,
    role3: discord.Role = None,
    role4: discord.Role = None,
    role5: discord.Role = None,
    role6: discord.Role = None
):
    # ============================================================
    # 1️⃣ صلاحيات
    # ============================================================
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(
            "❌ ليس لديك صلاحية استخدام هذا الأمر.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    guild_id = str(interaction.guild.id)
    enabled  = 1 if action.value == "enable" else 0

    # ============================================================
    # 2️⃣ تجميع الرتب وفلترة None
    # ============================================================
    roles     = [r for r in [role1, role2, role3, role4, role5, role6] if r is not None]
    roles_ids = [r.id for r in roles]
    roles_json = json.dumps(roles_ids)

    # ============================================================
    # 3️⃣ DB UPDATE
    # ✅ get_db + lock بدل aiosqlite.connect
    # ============================================================
    try:
        async with get_write_lock():
            db = await get_db()

            await db.execute("""
                INSERT OR IGNORE INTO server_settings (guild_id)
                VALUES (?)
            """, (guild_id,))

            await db.execute("""
                UPDATE server_settings
                SET autorole_enabled = ?,
                    autorole_roles   = ?
                WHERE guild_id = ?
            """, (enabled, roles_json, guild_id))

            await db.commit()

        # ✅ تحديث الكاش مباشرة بدون إعادة قراءة من DB
        server_settings_cache.setdefault(guild_id, {})
        server_settings_cache[guild_id]["autorole_enabled"] = enabled
        server_settings_cache[guild_id]["autorole_roles"]   = roles_ids

    except Exception as e:
        logging.error(f"[autorole_setup ERROR] gid={guild_id} | {e}")
        return await interaction.followup.send(
            "❌ حدث خطأ أثناء حفظ الإعدادات.",
            ephemeral=True
        )

    # ============================================================
    # 4️⃣ الرد
    # ============================================================
    roles_names = ", ".join(r.mention for r in roles) if roles else "لا توجد رتب محددة"

    await interaction.followup.send(
        f"✅ تم **{'تفعيل' if enabled else 'إلغاء'}** نظام AutoRoles.\n"
        f"🔹 **الرتب:** {roles_names}",
        ephemeral=True
    )
    
# ===============================
# 📌 أمر إعداد الترحيب في الخاص (SQLite Version)
# ===============================

@bot.tree.command(
    name="dm_welcome",
    description="إعداد نظام الترحيب في الخاص"
)
@app_commands.describe(
    enabled="تشغيل أو إيقاف الترحيب في الخاص",
    use_embed="هل تريد استخدام Embed؟",
    message="نص رسالة الترحيب (اكتب None لعدم التعديل)"
)
async def dm_welcome_command(
    interaction: discord.Interaction,
    enabled: bool,
    use_embed: bool,
    message: str = None
):
    # ================= CHECK GUILD =================
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message(
            "❌ هذا الأمر يعمل داخل السيرفر فقط.",
            ephemeral=True
        )

# ================= ADMIN ONLY CHECK =================
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ هذا الأمر للأدمن فقط.",
            ephemeral=True
        )

    import json  # حماية مستقبلية لو احتجته لاحقًا

    gid = str(guild.id)

    is_enabled = 1 if enabled else 0
    is_embed = 1 if use_embed else 0

    # ================= DATABASE UPDATE =================
    async with aiosqlite.connect(DB_PATH, timeout=20) as db:

        # تأكيد وجود السيرفر
        await db.execute("""
            INSERT OR IGNORE INTO server_settings (guild_id)
            VALUES (?)
        """, (gid,))

        # ================= SMART UPDATE =================
        if message is not None and message.lower() != "none":
            await db.execute("""
                UPDATE server_settings 
                SET dm_welcome_enabled = ?, 
                    dm_use_embed = ?, 
                    dm_message = ?
                WHERE guild_id = ?
            """, (is_enabled, is_embed, message, gid))
        else:
            await db.execute("""
                UPDATE server_settings 
                SET dm_welcome_enabled = ?, 
                    dm_use_embed = ?
                WHERE guild_id = ?
            """, (is_enabled, is_embed, gid))

        await db.commit()

    # ================= RESPONSE =================
    await interaction.response.send_message(
        f"✅ تم تحديث إعدادات الترحيب في الخاص بنجاح.\n"
        f"🔹 الحالة: **{'مفعل' if enabled else 'معطل'}**\n"
        f"🔹 النوع: **{'Embed' if use_embed else 'نص عادي'}**",
        ephemeral=True
    )
                                                                                
# ===============================
# 📌 أمر إعداد نظام الترحيب (SQLite Version - FINAL)
# ===============================


@bot.tree.command(
    name="setup_welcome",
    description="إعداد وتشغيل نظام الترحيب الكامل"
)
@app_commands.describe(
    toggle="تشغيل أو إيقاف النظام (True/False)",
    channel="القناة التي تُرسل فيها رسالة الترحيب",
    role="الرتبة التي تُعطى تلقائيًا (اختياري)",
    msg_welcome="نص الترحيب الرئيسي",
    msg1="نص القسم 1",
    channel1="القناة 1",
    msg2="نص القسم 2",
    channel2="القناة 2",
    msg3="نص القسم 3",
    channel3="القناة 3",
    image_url="رابط الصورة (اختياري)"
)
@commands.has_permissions(administrator=True)
async def setup_welcome(
    interaction: discord.Interaction, 
    toggle: Optional[bool] = None, 
    channel: Optional[discord.TextChannel] = None, 
    role: Optional[discord.Role] = None, 
    msg_welcome: Optional[str] = None, 
    msg1: Optional[str] = None, 
    channel1: Optional[discord.TextChannel] = None, 
    msg2: Optional[str] = None, 
    channel2: Optional[discord.TextChannel] = None, 
    msg3: Optional[str] = None, 
    channel3: Optional[discord.TextChannel] = None,
    image_url: Optional[str] = None
):
    guild_id = str(interaction.guild.id)

    # ===============================
    # 1️⃣ Toggle Only Mode
    # ===============================
    if toggle is not None and not any([channel, msg_welcome]):
        async with aiosqlite.connect(DB_PATH, timeout=20) as db:

            await db.execute("""
                INSERT OR IGNORE INTO server_settings (guild_id)
                VALUES (?)
            """, (guild_id,))

            await db.execute("""
                UPDATE server_settings 
                SET welcome_enabled = ?
                WHERE guild_id = ?
            """, (1 if toggle else 0, guild_id))

            await db.commit()

        msg = "✅ تم تشغيل نظام الترحيب." if toggle else "❌ تم إيقاف نظام الترحيب."
        return await interaction.response.send_message(msg, ephemeral=True)

    # ===============================
    # 2️⃣ Validation
    # ===============================
    if not msg_welcome or not channel:
        return await interaction.response.send_message(
            "⚠️ يجب تحديد نص الترحيب وقناة الترحيب على الأقل.",
            ephemeral=True
        )

    # ===============================
    # 3️⃣ Followups JSON Build
    # ===============================
    followups = []

    if msg1 and channel1:
        followups.append({
            "message": msg1,
            "channel_id": str(channel1.id)
        })

    if msg2 and channel2:
        followups.append({
            "message": msg2,
            "channel_id": str(channel2.id)
        })

    if msg3 and channel3:
        followups.append({
            "message": msg3,
            "channel_id": str(channel3.id)
        })

    followups_json = json.dumps(followups)

    # ===============================
    # 4️⃣ DB SAVE
    # ===============================
    async with aiosqlite.connect(DB_PATH, timeout=20) as db:

        await db.execute("""
            INSERT OR IGNORE INTO server_settings (guild_id)
            VALUES (?)
        """, (guild_id,))

        await db.execute("""
            UPDATE server_settings 
            SET welcome_channel = ?,
                welcome_message = ?,
                welcome_role = ?,
                welcome_enabled = 1,
                image_url = ?,
                followups_json = ?
            WHERE guild_id = ?
        """, (
            str(channel.id),
            msg_welcome,
            str(role.id) if role else None,
            image_url,
            followups_json,
            guild_id
        ))

        await db.commit()

    # ===============================
    # 5️⃣ PREVIEW EMBED
    # ===============================
    embed = discord.Embed(
        title="🎉 Preview Welcome System",
        description=f"{msg_welcome}\n\n> {interaction.user.mention}",
        color=discord.Color.gold()
    )

    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    for i, item in enumerate(followups, start=1):
        embed.add_field(
            name=f"📌 Section {i}",
            value=f"**{item['message']}**\n➡️ <#{item['channel_id']}>",
            inline=False
        )

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text=f"{interaction.guild.name} - Welcome Preview")

    await interaction.response.send_message(embed=embed, ephemeral=True)
    
@bot.tree.command(
    name="remove_invites",
    description="تصفير عدد الدعوات لعضو محدد أو لجميع الأعضاء"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    العضو="اختياري: العضو المراد تصفير دعواته"
)
async def remove_invites(interaction: discord.Interaction, العضو: discord.Member | None = None):
    await interaction.response.defer(ephemeral=True)

    guild_id = str(interaction.guild.id)

    async with aiosqlite.connect(DB_PATH, timeout=20) as db:

        # ================================
        # عضو واحد
        # ================================
        if العضو:
            uid = str(العضو.id)

            # تصفير invites داخل هذا السيرفر فقط
            await db.execute("""
                UPDATE users 
                SET invites = 0 
                WHERE user_id = ? AND guild_id = ?
            """, (uid, guild_id))

            # حذف سجل الدعوات في هذا السيرفر فقط
            await db.execute("""
                DELETE FROM joined_members 
                WHERE guild_id = ? AND inviter_id = ?
            """, (guild_id, uid))

            await db.commit()

            embed = discord.Embed(
                title="📨 Reset Done",
                description=(
                    f"**Member:** {العضو.mention}\n"
                    f"**Status:** تم تصفير الدعوات في هذا السيرفر فقط"
                ),
                color=discord.Color.orange()
            )

            return await interaction.followup.send(embed=embed)

        # ================================
        # تصفير الكل في السيرفر
        # ================================

        # حذف كل سجلات الدعوات في هذا السيرفر
        await db.execute("""
            DELETE FROM joined_members 
            WHERE guild_id = ?
        """, (guild_id,))

        # تصفير invites لكل مستخدم في هذا السيرفر فقط
        await db.execute("""
            UPDATE users 
            SET invites = 0 
            WHERE guild_id = ?
        """)

        await db.commit()

    embed = discord.Embed(
        title="🧹 Global Invites Reset",
        description=(
            f"**Server:** {interaction.guild.name}\n"
            f"**Status:** تم تصفير جميع الدعوات بنجاح"
        ),
        color=discord.Color.red()
    )

    await interaction.followup.send(embed=embed)
    
               
            
from typing import Optional, Literal

@bot.tree.command(
    name="invite_logs",
    description="تشغيل أو إيقاف نظام تتبع الدعوات"
)
async def invite_logs(
    interaction: discord.Interaction,
    حالة: Literal["تشغيل", "إيقاف"],
    قناة: Optional[discord.TextChannel] = None
):

    # =========================
    # صلاحيات
    # =========================
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ هذا الأمر للإدارة فقط.",
            ephemeral=True
        )

    # =========================
    # منطق التشغيل
    # =========================
    enabled = 1 if حالة == "تشغيل" else 0
    channel_id = str(قناة.id) if قناة else None

    if حالة == "تشغيل" and قناة is None:
        return await interaction.response.send_message(
            "⚠️ لازم تحدد قناة عند التشغيل.",
            ephemeral=True
        )

    guild_id = str(interaction.guild.id)

    # =========================
    # قاعدة البيانات
    # =========================
    async with aiosqlite.connect(DB_PATH, timeout=20) as db:

        # ضمان وجود الصف
        await db.execute("""
            INSERT OR IGNORE INTO server_settings (guild_id)
            VALUES (?)
        """, (guild_id,))

        # تحديث الإعدادات
        if enabled:
            await db.execute("""
                UPDATE server_settings
                SET invite_logs_enabled = 1,
                    invite_logs_channel = ?
                WHERE guild_id = ?
            """, (channel_id, guild_id))
        else:
            await db.execute("""
                UPDATE server_settings
                SET invite_logs_enabled = 0,
                    invite_logs_channel = NULL
                WHERE guild_id = ?
            """, (guild_id,))

        await db.commit()

    # =========================
    # الرد
    # =========================
    if enabled:
        msg = f"✅ تم تفعيل نظام الدعوات\n📍 القناة: {قناة.mention}"
    else:
        msg = "🛑 تم إيقاف نظام الدعوات"

    await interaction.response.send_message(msg, ephemeral=True)
    

@bot.tree.command(name="top_xp", description="عرض قائمة متصدرين XP في السيرفر")
async def top_xp(interaction: discord.Interaction):
    if not await check_cooldown(interaction, "top_xp", 10):
        return

    await interaction.response.defer()
    
    guild = interaction.guild
    guild_id = str(guild.id)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            # جلب جميع المستخدمين (حتى لو XP صفر)
            async with db.execute(
                "SELECT user_id, msg_xp FROM users WHERE guild_id = ? ORDER BY msg_xp DESC LIMIT 5",
                (guild_id,)
            ) as cursor:
                top_chat_rows = await cursor.fetchall()
                
            async with db.execute(
                "SELECT user_id, voice_xp FROM users WHERE guild_id = ? ORDER BY voice_xp DESC LIMIT 5",
                (guild_id,)
            ) as cursor:
                top_voice_rows = await cursor.fetchall()

    except sqlite3.OperationalError as e:
        print(f"⚠️ [Top XP Error] Missing Column: {e}")
        return await interaction.followup.send("⚠️ قاعدة البيانات قيد التحديث، برجاء المحاولة لاحقاً.")

    if not top_chat_rows and not top_voice_rows:
        return await interaction.followup.send("❌ لا توجد بيانات تفاعل مسجلة لهذا السيرفر حتى الآن.")

    # بناء نص المتصدرين
    chat_lines = [f"**#{i+1}** | <@{r['user_id']}> — `xp {r['msg_xp']}`" for i, r in enumerate(top_chat_rows)]
    voice_lines = [f"**#{i+1}** | <@{r['user_id']}> — `xp {r['voice_xp']}`" for i, r in enumerate(top_voice_rows)]

    embed = discord.Embed(title=f"📋 متصدرين XP - {guild.name}", color=discord.Color.gold())
    embed.add_field(name="💬 الشات (Top 5)", value="\n".join(chat_lines) if chat_lines else "لا يوجد", inline=False)
    embed.add_field(name="🎤 الصوت (Top 5)", value="\n".join(voice_lines) if voice_lines else "لا يوجد", inline=False)
    
    await interaction.followup.send(embed=embed)

# ==============================
# أمر كلاسيكي بالـ prefix: top_xp
# ==============================
@bot.command(aliases=["topxp", "توبxp"])
async def top_xp(ctx):
    # تحقق من التبريد (Cooldown)
    if not await check_cooldown(ctx, "top_xp", 10):
        return

    async with ctx.typing():  # ✅ بدل trigger_typing

        guild = ctx.guild
        guild_id = str(guild.id)

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row

                # جلب جميع المستخدمين (حتى لو XP صفر)
                async with db.execute(
                    "SELECT user_id, msg_xp FROM users WHERE guild_id = ? ORDER BY msg_xp DESC LIMIT 5",
                    (guild_id,)
                ) as cursor:
                    top_chat_rows = await cursor.fetchall()

                async with db.execute(
                    "SELECT user_id, voice_xp FROM users WHERE guild_id = ? ORDER BY voice_xp DESC LIMIT 5",
                    (guild_id,)
                ) as cursor:
                    top_voice_rows = await cursor.fetchall()

        except sqlite3.OperationalError as e:
            print(f"⚠️ [Top XP Error] Missing Column: {e}")
            return await ctx.reply("⚠️ قاعدة البيانات قيد التحديث، برجاء المحاولة لاحقاً.", mention_author=False)

        if not top_chat_rows and not top_voice_rows:
            return await ctx.reply("❌ لا توجد بيانات تفاعل مسجلة لهذا السيرفر حتى الآن.", mention_author=False)

        # بناء نص المتصدرين
        chat_lines = [f"**#{i+1}** | <@{r['user_id']}> — `xp {r['msg_xp']}`" for i, r in enumerate(top_chat_rows)]
        voice_lines = [f"**#{i+1}** | <@{r['user_id']}> — `xp {r['voice_xp']}`" for i, r in enumerate(top_voice_rows)]

        embed = discord.Embed(title=f"📋 متصدرين XP - {guild.name}", color=discord.Color.gold())
        embed.add_field(name="💬 الشات (Top 5)", value="\n".join(chat_lines) if chat_lines else "لا يوجد", inline=False)
        embed.add_field(name="🎤 الصوت (Top 5)", value="\n".join(voice_lines) if voice_lines else "لا يوجد", inline=False)

        await ctx.reply(embed=embed, mention_author=False)

                                                                                                                                                                                                                
@bot.tree.command(name="slowmode", description="تعيين سلو مود للروم الحالي")
@app_commands.describe(duration="مدة السلو مود (مثال: 10s, 5m, 1h, 1d)")
async def slowmode(interaction: discord.Interaction, duration: str):
    # تحويل المدة لثواني
    seconds = None
    try:
        unit = duration[-1].lower()
        value = int(duration[:-1])
        if unit == "s":
            seconds = value
        elif unit == "m":
            seconds = value * 60
        elif unit == "h":
            seconds = value * 3600
        elif unit == "d":
            seconds = value * 86400
    except:
        pass

    if seconds is None:
        return await interaction.response.send_message(
            "❌ صيغة المدة غير صحيحة! استخدم s/m/h/d (مثال: 10s, 5m, 1h, 1d).",
            ephemeral=True
        )

    # تحديد الحد الأقصى (Discord يسمح حتى 6 ساعات = 21600 ثانية)
    max_slowmode = 21600
    applied_seconds = min(seconds, max_slowmode)

    try:
        await interaction.channel.edit(slowmode_delay=applied_seconds)
        await interaction.response.send_message(
            f"✅ تم تفعيل السلو مود على هذا الروم لمدة `{duration}` "
            f"(تم تطبيق الحد الأقصى المسموح `{applied_seconds}s` إذا كانت أكبر من الحد المسموح)",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ حدث خطأ: {e}", ephemeral=True)

@bot.tree.command(name="server_block", description="حظر أو فك حظر سيرفر من استخدام البوت (OWNER فقط)")
@app_commands.describe(
    guild_id="أيدي السيرفر",
    action="اختيار حظر أو فك الحظر"
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="🚫 حظر السيرفر", value="block"),
        app_commands.Choice(name="✅ فك الحظر", value="unblock")
    ]
)
async def server_block(
    interaction: discord.Interaction,
    guild_id: str,
    action: app_commands.Choice[str]
):

    # التحقق من المالك
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message(
            "❌ هذا الأمر مخصص فقط لمالك البوت.",
            ephemeral=True
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:

        if action.value == "block":

            await db.execute(
                "INSERT OR IGNORE INTO blocked_servers (guild_id) VALUES (?)",
                (guild_id,)
            )
            await db.commit()

            await interaction.response.send_message(
                f"🚫 تم حظر السيرفر `{guild_id}` من استخدام البوت."
            )

        elif action.value == "unblock":

            await db.execute(
                "DELETE FROM blocked_servers WHERE guild_id = ?",
                (guild_id,)
            )
            await db.commit()

            await interaction.response.send_message(
                f"✅ تم فك الحظر عن السيرفر `{guild_id}`."
            )

@bot.command()
async def رصيد(ctx, عضو: discord.Member = None):

    if not await check_cooldown(ctx, "رصيد", 5):
        return

    try:
        عضو = عضو or ctx.author

        if عضو.bot:
            return await ctx.reply("🤨 البوتات لا تملك أرصدة.", mention_author=False, delete_after=5)

        uid = str(عضو.id)

        # 🌍 GLOBAL SYSTEM (صح)
        user_data = await ensure_global_user(uid)

        wallet = user_data.get("kento", 0)
        bank = user_data.get("deposit", 0)

        msg = (
            f"**رصيد {عضو.display_name} هو `{wallet:,} ¥` كينتو** 💰\n"
            f"**رصيده البنكي `{bank:,} ¥`** 🏦"
        )

        await ctx.reply(msg, mention_author=False)

    except Exception as e:
        logging.error(f"[❌ رصيد] {e}")
        await ctx.reply("⚠️ حدث خطأ أثناء الاتصال بقاعدة البيانات.", mention_author=False)
                
@bot.tree.command(name="kentos", description="عرض رصيدك أو رصيد أي عضو")
@app_commands.describe(عضو="اختر العضو لعرض رصيده (اختياري)")
async def kentos_slash(interaction: discord.Interaction, عضو: Optional[discord.Member] = None):

    if not await check_cooldown(interaction, "kentos", 5):
        return

    try:
        عضو = عضو or interaction.user

        if عضو.bot:
            return await interaction.response.send_message(
                "🤨 البوتات لا تملك أرصدة.", ephemeral=True
            )

        uid = str(عضو.id)

        # 🌍 GLOBAL ECONOMY
        user_data = await ensure_global_user(uid)

        wallet = user_data.get("kento", 0)
        bank = user_data.get("deposit", 0)

        msg = (
            f"**رصيد {عضو.display_name} هو `{wallet:,} ¥` كينتو** 💰\n"
            f"**رصيده البنكي `{bank:,} ¥`** 🏦"
        )

        await interaction.response.send_message(msg)

    except Exception as e:
        logging.error(f"[❌ kentos slash] {e}")

        if not interaction.response.is_done():
            await interaction.response.send_message(
                "⚠️ حدث خطأ أثناء جلب البيانات.",
                ephemeral=True
            )
                                                        
# ========================================================
# 📧 نظام إرسال كود التحقق (نسخة التوافق مع SQLite)
# ========================================================
def send_transfer_email(to_email: str, code: str, subject: str = "🔑 كود تأكيد التحويل",
                        sender_name: str = None, receiver_name: str = None,
                        amount: int = None, net_amount: int = None):
    try:
        msg = EmailMessage()
        msg["From"] = f"GxBot <{EMAIL_USER}>"
        msg["To"] = to_email
        msg["Subject"] = f"⚡ {subject}"

        text_content = f"كود تأكيد التحويل الخاص بك هو: {code}\nصالح لمدة 3 دقائق فقط."
        if sender_name and receiver_name and amount is not None:
            text_content = (
                f"🛡️ تفاصيل عملية التحويل:\n"
                f"👤 من: {sender_name}\n"
                f"👤 إلى: {receiver_name}\n"
                f"💰 المبلغ: {amount}\n"
                f"💵 الصافي: {net_amount}\n"
                f"🔑 الكود: {code}\n"
                f"⏰ تنبيه: الكود ينتهي بعد 3 دقائق."
            )
        msg.set_content(text_content)

        html_content = f"""
        <html>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f9; padding: 20px;">
                <div style="max-width: 500px; margin: auto; background: white; border-radius: 15px; overflow: hidden; border: 1px solid #e1e8ed; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                    <div style="background: #007bff; color: white; padding: 20px; text-align: center;">
                        <h2 style="margin: 0;">🔐 تأكيد عملية التحويل</h2>
                    </div>
                    <div style="padding: 30px; text-align: center; color: #333;">
                        <p style="font-size: 16px;">أنت على وشك إجراء عملية تحويل أموال (Kento)</p>
                        <div style="background: #f8f9fa; border-radius: 10px; padding: 15px; margin: 20px 0; border: 1px dashed #007bff;">
                            <span style="font-size: 32px; font-weight: bold; color: #007bff; letter-spacing: 5px;">{code}</span>
                        </div>
                        <p style="color: #666; font-size: 14px;">⏰ هذا الكود صالح لمدة <b>3 دقائق</b> فقط.</p>
                        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                        <div style="text-align: right; font-size: 13px; color: #555;">
                            <b>👤 المرسل إليه:</b> {receiver_name}<br>
                            <b>💰 المبلغ الإجمالي:</b> {amount}<br>
                            <b>💵 المبلغ الصافي:</b> {net_amount}
                        </div>
                    </div>
                    <div style="background: #f1f1f1; padding: 10px; text-align: center; font-size: 12px; color: #999;">
                        GxBot Security System • لا تشارك هذا الكود مع أي شخص
                    </div>
                </div>
            </body>
        </html>
        """
        msg.add_alternative(html_content, subtype="html")

        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


# ==============================
# 🚨 أمر التحويل المطور (SQLite + Security Layers)
# ==============================

@bot.command(name="تحويل")
async def تحويل(ctx, عضو: discord.Member, المبلغ: int):

    if not await check_cooldown(ctx, "تحويل", 15):
        return

    try:
        المرسل = ctx.author
        uid_مرسل = str(المرسل.id)
        uid_عضو = str(عضو.id)

        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 🌍 GLOBAL SYSTEM
        sender_data = await ensure_global_user(uid_مرسل)
        receiver_data = await ensure_global_user(uid_عضو)

        verified_level = sender_data.get("verified_level", 0)
        user_pin = sender_data.get("pin")
        email = sender_data.get("email")

        if verified_level == 0:
            return await ctx.send(
                "❌ يجب توثيق حسابك أولاً. استخدم `/verify` (تحقق أساسي أو كامل).",
                delete_after=8
            )

        if المرسل.id == عضو.id:
            return await ctx.reply(
    f"💳 | رصيدك الحالي هو `{sender_data['kento']:,}` كنتو.",
    mention_author=False
)

        if عضو.bot:
            return await ctx.send("🙂 لا يمكنك تحويل الكنتو إلى بوتات.", delete_after=5)

        if المبلغ <= 0:
            return await ctx.send("🤨 المبلغ يجب أن يكون أكبر من صفر.", delete_after=5)

        if sender_data["kento"] < المبلغ:
            return await ctx.send("🥲 ليس لديك كنتو كافٍ.", delete_after=5)

        # =========================
        # ✅ فحص daily_transfers عبر get_db()
        # =========================
        db = await get_db()
        async with db.execute(
            "SELECT count FROM daily_transfers WHERE user_id = ? AND date = ?",
            (uid_مرسل, today)
        ) as cursor:
            row = await cursor.fetchone()

        transfer_count = row[0] if row else 0

        LIMIT_AMOUNT = 5000
        DAILY_TRANSFER_LIMIT = 5

        يحتاج_كود = (المبلغ >= LIMIT_AMOUNT) or (transfer_count >= DAILY_TRANSFER_LIMIT)

        # =========================
        # UI CONFIRM
        # =========================
        class ConfirmTransferView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.confirmed = None

            @discord.ui.button(label="تأكيد ✅", style=discord.ButtonStyle.green)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id == ctx.author.id:
                    self.confirmed = True
                    self.stop()
                    await interaction.response.edit_message(
                        content="✅ تم التأكيد، جاري المتابعة...",
                        view=None
                    )

            @discord.ui.button(label="إلغاء ❌", style=discord.ButtonStyle.red)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id == ctx.author.id:
                    self.confirmed = False
                    self.stop()
                    await interaction.response.edit_message(
                        content="❌ تم إلغاء العملية.",
                        view=None
                    )

        view = ConfirmTransferView()
        await ctx.send(f"هل تريد تحويل `{المبلغ:,}` كنتو إلى {عضو.mention}؟", view=view)
        await view.wait()

        if view.confirmed is not True:
            return

        # =========================
        # ✅ execute_transfer — آمن بالكامل مع lock + فحص مزدوج
        # =========================
        async def execute_transfer():
            try:
                async with _db_write_lock:
                    db = await get_db()

                    async with db.execute(
                        "SELECT kento FROM global_users WHERE user_id = ?",
                        (uid_مرسل,)
                    ) as cursor:
                        row = await cursor.fetchone()

                    if not row or row[0] < المبلغ:
                        return False

                    await db.execute(
                        "UPDATE global_users SET kento = kento - ? WHERE user_id = ?",
                        (المبلغ, uid_مرسل)
                    )

                    await db.execute(
                        "UPDATE global_users SET kento = kento + ? WHERE user_id = ?",
                        (المبلغ, uid_عضو)
                    )

                    await db.execute("""
                        INSERT INTO daily_transfers (user_id, date, count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(user_id, date)
                        DO UPDATE SET count = count + 1
                    """, (uid_مرسل, today))

                    await db.commit()
                    return True

            except Exception as e:
                logging.error(f"[execute_transfer ERROR] {e}")
                return False

        # =========================
        # SEND RECEIPTS
        # =========================
        async def send_receipt():
            for target, msg_txt in [
                (عضو, f":atm: | إيصال التحويل\n```لقد استلمت {المبلغ:,} كنتو من {المرسل.name}```"),
                (المرسل, f":atm: | إيصال التحويل\n```لقد قمت بتحويل {المبلغ:,} كنتو إلى {عضو.name}```")
            ]:
                try:
                    await target.send(msg_txt)
                except Exception:
                    pass

        # =========================
        # EXECUTE NORMAL (بدون كود)
        # =========================
        if not يحتاج_كود:
            if await execute_transfer():
                await ctx.send(
                    f"**ـ {المرسل.mention} قام بتحويل `{المبلغ:,}` كنتو إلى {عضو.name}** | :moneybag:"
                )
                await send_receipt()
                return
            else:
                return await ctx.send("❌ حدث خطأ في الرصيد أثناء المعالجة.")

        fallback_to_email = False

        # =========================
        # ✅ PIN CHECK مع حماية Brute Force + حذف الرسالة فوراً
        # =========================
        if user_pin:
            pin_deadline = time.time() + 10
            await ctx.send("🔐 ادخل PIN خلال 10 ثواني...", delete_after=10)
            pin_attempts = 0

            while pin_attempts < 3:
                try:
                    remaining_pin_time = max(1, int(pin_deadline - time.time()))

                    msg = await bot.wait_for(
                        "message",
                        timeout=remaining_pin_time,
                        check=lambda m: m.author.id == ctx.author.id and m.channel == ctx.channel
                    )

                    entered_pin = msg.content.strip()

                    # ✅ حذف رسالة الـ PIN فوراً (سري وأمان)
                    try:
                        await msg.delete()
                    except Exception:
                        pass

                    if entered_pin == str(user_pin):
                        if await execute_transfer():
                            await ctx.send(
                                f"**ـ {المرسل.mention} قام بتحويل `{المبلغ:,}` كنتو إلى {عضو.name}** | :moneybag:"
                            )
                            await send_receipt()
                            return
                        else:
                            return await ctx.send("❌ حدث خطأ في الرصيد أثناء المعالجة.")
                    else:
                        pin_attempts += 1
                        remaining = 3 - pin_attempts
                        if remaining > 0:
                            await ctx.send(f"❌ PIN خطأ — تبقى {remaining} محاولة")
                        else:
                            if verified_level >= 2 and email:
                                fallback_to_email = True
                                break
                            else:
                                return await ctx.send("🚫 تم إلغاء التحويل بسبب محاولات خاطئة متكررة.")

                except asyncio.TimeoutError:
                    if verified_level >= 2 and email:
                        fallback_to_email = True
                        break
                    else:
                        return await ctx.send("⌛ انتهى الوقت.")

            if not fallback_to_email:
                return

        # =========================
        # ✅ EMAIL CHECK مع حماية Brute Force + حذف الرسالة فوراً
        # =========================
        if not email:
            return await ctx.send("❌ لا يوجد بريد إلكتروني مرتبط بحسابك.")

        email_deadline = time.time() + 180
        code = str(random.randint(100000, 999999))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: send_transfer_email(
                email,
                code,
                sender_name=المرسل.name,
                receiver_name=عضو.name,
                amount=المبلغ,
                net_amount=المبلغ
            )
        )

        await ctx.send("📧 تم إرسال كود التحقق لبريدك الإلكتروني (صالح 3 دقائق)")

        email_attempts = 0

        while email_attempts < 3:
            try:
                remaining_time = max(1, int(email_deadline - time.time()))

                msg = await bot.wait_for(
                    "message",
                    timeout=remaining_time,
                    check=lambda m: m.author.id == ctx.author.id and m.channel == ctx.channel
                )

                entered_code = msg.content.strip()

                # ✅ حذف رسالة الكود فوراً (سري وأمان)
                try:
                    await msg.delete()
                except Exception:
                    pass

                if time.time() > email_deadline:
                    return await ctx.send("⌛ انتهت صلاحية الكود. أعد المحاولة.")

                if entered_code == code:
                    if await execute_transfer():
                        await ctx.send(
                            f"**ـ {المرسل.mention} قام بتحويل `{المبلغ:,}` كنتو إلى {عضو.name}** | :moneybag:"
                        )
                        await send_receipt()
                        return
                    else:
                        return await ctx.send("❌ حدث خطأ في الرصيد أثناء المعالجة.")
                else:
                    email_attempts += 1
                    remaining = 3 - email_attempts
                    if remaining > 0:
                        await ctx.send(f"❌ كود خطأ — تبقى {remaining} محاولة")
                    else:
                        return await ctx.send("🚫 تم إلغاء التحويل بسبب محاولات خاطئة متكررة.")

            except asyncio.TimeoutError:
                return await ctx.send("⌛ انتهى الوقت.")

        return

    except Exception as e:
        logging.error(f"[تحويل ERROR] {e}")
        await ctx.send("⚠️ حدث خطأ غير متوقع.")
                
# ==============================
# ⛏️ إعدادات نظام التعدين والتصويت (SQLite)
# ==============================

MAX_TOTAL_SUPPLY = 50_000_000
MINING_SUPPLY_CAP = 30_000_000
VOTING_SUPPLY_CAP = 20_000_000

MINING_COOLDOWN_HOURS = 1
MIN_REWARD = 100
MAX_REWARD = 400

VOTE_COOLDOWN_HOURS = 12
VOTE_MIN_REWARD = 200
VOTE_MAX_REWARD = 500

active_mining_sessions = {}
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")  # ✅ من .env

# ==================== 🧮 أدوات الحساب السريعة (SQL Based) ====================

async def get_total_kento():
    """حساب إجمالي الكنتو من global_users فقط"""
    db = await get_db()  # ✅ connection مشترك
    async with db.execute("SELECT SUM(kento + deposit) FROM global_users") as cursor:
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 0


async def get_used_mining_supply():
    total = await get_total_kento()
    return min(total, MINING_SUPPLY_CAP)


async def supply_percent():
    total = await get_total_kento()
    return (total / MAX_TOTAL_SUPPLY) * 100


def generate_math_problem():
    a, b = random.randint(5, 25), random.randint(5, 25)
    op = random.choice(["+", "-", "*"])
    if op == "+": return f"{a} + {b}", a + b
    if op == "-": return f"{a} - {b}", a - b
    return f"{a} × {b}", a * b


# ==================== ⛏️ Mining — Slash ====================

@bot.tree.command(name="mine", description="⛏️ تعدين Kentos بحل مسألة رياضية")
async def mine(interaction: discord.Interaction):

    if not await check_cooldown(interaction, "mine", 60):
        return

    await interaction.response.defer(ephemeral=True)

    uid = str(interaction.user.id)
    guild_id = str(interaction.guild.id)

    user_data = await ensure_user(uid, guild_id)

    now = datetime.datetime.now(datetime.timezone.utc)

    last_mine_str = user_data.get("last_mine")
    if last_mine_str:
        last_mine = datetime.datetime.fromisoformat(last_mine_str)
        if now < last_mine + datetime.timedelta(hours=MINING_COOLDOWN_HOURS):
            remaining = (last_mine + datetime.timedelta(hours=MINING_COOLDOWN_HOURS)) - now
            return await interaction.followup.send(
                f"⏳ يمكنك التعدين بعد `{int(remaining.total_seconds()//60)}` دقيقة",
                ephemeral=True
            )

    if await get_used_mining_supply() >= MINING_SUPPLY_CAP:
        return await interaction.followup.send(
            "❌ تم إغلاق التعدين (وصلنا للحد الأقصى)",
            ephemeral=True
        )

    q, ans = generate_math_problem()
    active_mining_sessions[uid] = ans

    embed = discord.Embed(
        title="⛏️ GX Mining Process",
        description=f"🧮 **حل المسألة:**\n`{q}`\n\n✍️ اكتب الإجابة خلال **30 ثانية**",
        color=discord.Color.blurple()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

    try:
        msg = await bot.wait_for(
            "message",
            timeout=30,
            check=lambda m: m.author.id == interaction.user.id and m.channel == interaction.channel
        )

        if int(msg.content.strip()) == ans:
            reward = random.randint(MIN_REWARD, MAX_REWARD)

            # ✅ get_db() بدل aiosqlite.connect منفصل
            async with get_write_lock():
                db = await get_db()

                await db.execute("""
                    INSERT OR IGNORE INTO global_users (
                        user_id, total_xp, level,
                        kento, deposit, trust,
                        verified_level, background
                    )
                    VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
                """, (uid,))

                await db.execute(
                    "UPDATE global_users SET kento = kento + ? WHERE user_id = ?",
                    (reward, uid)
                )

                await db.execute(
                    "UPDATE users SET last_mine = ? WHERE user_id = ? AND guild_id = ?",
                    (now.isoformat(), uid, guild_id)
                )

                await db.commit()

            used = await get_used_mining_supply()
            total = await get_total_kento()

            res_embed = discord.Embed(
                title="✅ Mining Successful",
                color=discord.Color.green()
            )
            res_embed.description = (
                f"💰 **Reward:** `{reward:,}` Kentos\n"
                f"📦 **Mined:** `{used:,}/{MINING_SUPPLY_CAP:,}`\n"
                f"🌍 **Economy:** `{total:,}/{MAX_TOTAL_SUPPLY:,}`"
            )

            await interaction.followup.send(embed=res_embed, ephemeral=True)

        else:
            await interaction.followup.send("❌ إجابة غير صحيحة", ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("❌ انتهى الوقت", ephemeral=True)

    finally:
        active_mining_sessions.pop(uid, None)


# ==================== Prefix Mining ====================

@bot.command(name="minecoins", help="⛏️ تعدين Kentos")
async def mine_prefix(ctx):

    uid = str(ctx.author.id)
    guild_id = str(ctx.guild.id)

    user_data = await ensure_user(uid, guild_id)
    now = datetime.datetime.now(datetime.timezone.utc)

    last_mine_str = user_data.get("last_mine")
    if last_mine_str:
        try:
            last_mine = datetime.datetime.fromisoformat(last_mine_str)
            cooldown_time = datetime.timedelta(hours=MINING_COOLDOWN_HOURS)
            if now < last_mine + cooldown_time:
                remaining = (last_mine + cooldown_time) - now
                minutes = int(remaining.total_seconds() // 60)
                return await ctx.reply(f"⏳ يمكنك التعدين بعد `{minutes}` دقيقة")
        except ValueError:
            pass

    if await get_used_mining_supply() >= MINING_SUPPLY_CAP:
        return await ctx.reply("❌ التعدين مغلق")

    q, ans = generate_math_problem()
    active_mining_sessions[uid] = ans

    embed = discord.Embed(
        title="⛏️ GX Mining Process",
        description=f"🧮 `{q}`",
        color=discord.Color.blurple()
    )

    await ctx.reply(embed=embed)

    def check(m):
        return m.author.id == ctx.author.id and m.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", timeout=30.0, check=check)

        if msg.content.strip().isdigit() and int(msg.content.strip()) == ans:
            reward = random.randint(MIN_REWARD, MAX_REWARD)

            # ✅ get_db() بدل aiosqlite.connect منفصل
            async with get_write_lock():
                db = await get_db()

                await db.execute("""
                    INSERT OR IGNORE INTO global_users (
                        user_id, total_xp, level,
                        kento, deposit, trust,
                        verified_level, background
                    )
                    VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
                """, (uid,))

                await db.execute(
                    "UPDATE global_users SET kento = kento + ? WHERE user_id = ?",
                    (reward, uid)
                )

                await db.execute(
                    "UPDATE users SET last_mine = ? WHERE user_id = ? AND guild_id = ?",
                    (now.isoformat(), uid, guild_id)
                )

                await db.commit()

            await ctx.reply(f"✅ حصلت على `{reward:,}` كنتو")

        else:
            await ctx.reply("❌ خطأ")

    except asyncio.TimeoutError:
        await ctx.reply("⏱️ انتهى الوقت")

    finally:
        active_mining_sessions.pop(uid, None)


# ==================== 🗳️ Vote — SQLite ====================

async def check_vote(user_id: int):
    url = f"https://top.gg/api/bots/1411571554025865236/check?userId={user_id}"
    headers = {"Authorization": TOPGG_TOKEN}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("voted") == 1
    return False


@bot.tree.command(name="vote", description="🗳️ صوّت للبوت واحصل على مكافأة")
async def vote(interaction: discord.Interaction):

    uid = str(interaction.user.id)
    gid = str(interaction.guild.id)

    user_data = await ensure_user(uid, gid)

    now = time.time()

    last_vote = user_data.get("last_vote", 0)

    if now - last_vote < VOTE_COOLDOWN_HOURS * 3600:
        rem = int((VOTE_COOLDOWN_HOURS * 3600 - (now - last_vote)) / 3600)
        return await interaction.response.send_message(
            f"⏳ يمكنك التصويت بعد {rem} ساعة.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🗳️ دعم بوت GX",
        description="صوتك يساعدنا نطور أكثر ❤️\nاضغط الزر بالأسفل للتصويت",
        color=discord.Color.green()
    )

    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            label="🔗 التصويت الآن",
            style=discord.ButtonStyle.link,
            url="https://top.gg/bot/1411571554025865236"
        )
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    voted = False

    # ⏱️ 5 دقائق فحص (30 × 10 ثواني)
    for _ in range(30):
        if await check_vote(interaction.user.id):
            voted = True
            break
        await asyncio.sleep(10)

    if voted:
        total_kento = await get_total_kento()

        reward = int(
            random.randint(VOTE_MIN_REWARD, VOTE_MAX_REWARD)
            * max(0.05, (MAX_TOTAL_SUPPLY - total_kento) / MAX_TOTAL_SUPPLY)
        )

        # ✅ كنتو في global_users + last_vote في users (الجدولين الصح)
        async with get_write_lock():
            db = await get_db()

            await db.execute("""
                INSERT OR IGNORE INTO global_users (
                    user_id, total_xp, level,
                    kento, deposit, trust,
                    verified_level, background
                )
                VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
            """, (uid,))

            await db.execute(
                "UPDATE global_users SET kento = kento + ? WHERE user_id = ?",
                (reward, uid)
            )

            await db.execute(
                "UPDATE users SET last_vote = ? WHERE user_id = ? AND guild_id = ?",
                (now, uid, gid)
            )

            await db.commit()

        await interaction.followup.send(
            f"🎉 تم التصويت! حصلت على `{reward:,}` كنتو ❤️",
            ephemeral=True
        )

    else:
        await interaction.followup.send(
            "⚠️ لم نكتشف تصويتك، حاول لاحقاً.",
            ephemeral=True
        )
                            
# ==============================
# 📊 أمر إحصائيات الاقتصاد العالمي (SQLite Version)
# ==============================

def format_number(n: int | float) -> str:
    """تنسيق الأرقام الكبيرة (K, M, B, T)"""
    n = int(max(0, n))

    if n < 1_000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1_000:.1f}K"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n < 1_000_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    return f"{n / 1_000_000_000_000:.1f}T"


FAKE_USERS = 100  # تحسين بصري فقط


@bot.tree.command(name="used_for", description="عرض إحصائيات الاقتصاد العالمي للبوت")
async def bot_stats(interaction: discord.Interaction):

    if not await check_cooldown(interaction, "used_for", 20):
        return

    await interaction.response.defer()

    try:
        db = await get_db()

        async with db.execute("""
            SELECT 
                COUNT(user_id),
                COALESCE(SUM(kento), 0),
                COALESCE(SUM(deposit), 0)
            FROM global_users
        """) as cursor:
            row = await cursor.fetchone()

        # ==============================
        # 🧠 SAFE PARSING
        # ==============================
        if not row:
            db_users = 0
            total_kento = 0
            total_deposit = 0
        else:
            db_users = row[0] or 0
            total_kento = row[1] or 0
            total_deposit = row[2] or 0

        total_users = db_users

        total_currency = total_kento + total_deposit
        avg_currency = total_currency / total_users if total_users else 0

        # لو مش معرف عندك
        try:
            supply_percent = (
                (total_currency / MAX_TOTAL_SUPPLY) * 100
                if MAX_TOTAL_SUPPLY else 0
            )
            max_supply_text = format_number(MAX_TOTAL_SUPPLY)
        except:
            supply_percent = 0
            max_supply_text = "N/A"

        embed = discord.Embed(
            title="📊 GX Bot — Global Economy Statistics",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        embed.description = (
            f"**🌍 نظرة عامة:**\n"
            f"• Servers: `{format_number(len(bot.guilds))}`\n"
            f"• Users: `{format_number(total_users + FAKE_USERS)}`\n\n"

            f"**💰 السيولة المالية:**\n"
            f"• Total Currency: `{format_number(total_currency)} ¥`\n"
            f"• In Bank: `{format_number(total_deposit)} ¥` 🏦\n"
            f"• In Wallets: `{format_number(total_kento)} ¥` 💳\n\n"

            f"**📈 مؤشرات الاقتصاد:**\n"
            f"• Average / User: `{format_number(avg_currency)}`\n"
            f"• Supply Used: `{supply_percent:.2f}%` 📦\n"
            f"• Max Supply: `{max_supply_text}`"
        )

        if bot.user:
            embed.set_thumbnail(url=bot.user.display_avatar.url)

        embed.set_footer(text="GX Bot • Real-time Economy Data")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        logging.error(f"[❌ used_for] {e}")
        await interaction.followup.send(
            "⚠️ حدث خطأ أثناء قراءة بيانات الاقتصاد العالمي."
        )
        
                                                                                                        
# ==================== ➕ إضافة كينتوس (Owner Only - GLOBAL) ====================
@bot.command(name="اضافه")
async def add_kento(ctx, member: discord.Member, amount: int):

    if ctx.author.id not in OWNER_IDS:
        return

    if amount <= 0:
        return

    uid = str(member.id)

    # 🔥 ضمان وجود المستخدم في global_users
    await ensure_global_user(uid)

    # 🔥 تحديث مباشر في global
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE global_users
            SET kento = kento + ?
            WHERE user_id = ?
        """, (amount, uid))
        await db.commit()

        # 🔥 جلب الرصيد الجديد
        async with db.execute("""
            SELECT kento FROM global_users WHERE user_id = ?
        """, (uid,)) as cursor:
            row = await cursor.fetchone()

    current_kento = row[0] if row else 0

    await ctx.send(
        f"✅ تم إضافة `{amount:,}` كينتوس لـ {member.mention}\n"
        f"💰 الرصيد الحالي: `{current_kento:,}`"
    )
    
# ==================== ➖ خصم كينتوس (Owner Only - GLOBAL) ====================
@bot.command(name="خصم")
async def remove_kento(ctx, member: discord.Member, amount: int):

    if ctx.author.id not in OWNER_IDS:
        return

    if amount <= 0:
        return

    uid = str(member.id)

    # 🔥 ضمان وجود المستخدم في global_users
    await ensure_global_user(uid)

    async with aiosqlite.connect(DB_PATH) as db:

        # 🔥 جلب الرصيد الحالي
        async with db.execute("""
            SELECT kento FROM global_users WHERE user_id = ?
        """, (uid,)) as cursor:
            row = await cursor.fetchone()

        current_bal = row[0] if row else 0

        actual_remove = min(amount, current_bal)

        if actual_remove <= 0:
            return await ctx.send(f"❌ لا يمكن الخصم لأن رصيد {member.mention} صفر.")

        # 🔥 الخصم
        await db.execute("""
            UPDATE global_users
            SET kento = kento - ?
            WHERE user_id = ?
        """, (actual_remove, uid))

        await db.commit()

    await ctx.send(
        f"⚠️ تم خصم `{actual_remove:,}` كينتوس من {member.mention}\n"
        f"💰 الرصيد المتبقي: `{current_bal - actual_remove:,}`"
    )
              
@bot.tree.command(name="create_coupon", description="أنشئ كوبون من رصيدك بعد التحقق الأمني")
@app_commands.describe(amount="قيمة الكنتو", pin="رمز الـPIN الخاص بك")
async def create_coupon(interaction: discord.Interaction, amount: int, pin: str = None):

    if not await check_cooldown(interaction, "create_coupon", 90):
        return

    await interaction.response.defer(ephemeral=True)

    uid = str(interaction.user.id)

    # ✅ GLOBAL SYSTEM فقط — الكنتو في global_users
    user_data = await ensure_global_user(uid)

    # ✅ فحص الرصيد من global_users
    if amount <= 0:
        return await interaction.followup.send("🤨 المبلغ يجب أن يكون أكبر من صفر.", ephemeral=True)

    if user_data.get("kento", 0) < amount:
        return await interaction.followup.send(
            f"💰 رصيدك غير كافٍ. رصيدك الحالي: `{user_data.get('kento', 0):,}`",
            ephemeral=True
        )

    verified_level = user_data.get("verified_level", 0)
    saved_pin      = user_data.get("pin")
    email          = user_data.get("email")

    if verified_level == 0:
        return await interaction.followup.send(
            "❌ يجب توثيق حسابك أولًا عبر `/verify`.",
            ephemeral=True
        )

    # =========================
    # 📧 Email verification
    # =========================
    if email:
        code = str(random.randint(100000, 999999))
        code_expiry = time.time() + 180  # ✅ 3 دقائق

        loop = asyncio.get_event_loop()
        sent = await loop.run_in_executor(
            None,
            lambda: send_transfer_email(
                email, code,
                interaction.user.name,
                "إنشاء كوبون",
                amount, amount
            )
        )

        if not sent:
            return await interaction.followup.send(
                "⚠️ فشل إرسال بريد التحقق.",
                ephemeral=True
            )

        await interaction.followup.send(
            f"📧 أرسلنا كود لبريدك. اكتبه هنا (صالح 3 دقائق):",
            ephemeral=True
        )

        email_attempts = 0
        while email_attempts < 3:  # ✅ حماية Brute Force
            try:
                remaining_time = max(1, int(code_expiry - time.time()))
                msg = await bot.wait_for(
                    "message",
                    timeout=min(60, remaining_time),
                    check=lambda m: m.author.id == interaction.user.id
                )

                if time.time() > code_expiry:
                    return await interaction.followup.send("⌛ انتهت صلاحية الكود.", ephemeral=True)

                if msg.content.strip() == code:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    break  # ✅ كود صح — كمّل
                else:
                    email_attempts += 1
                    remaining = 3 - email_attempts
                    if remaining > 0:
                        await interaction.followup.send(
                            f"❌ كود خاطئ — تبقى {remaining} محاولة", ephemeral=True
                        )
                    else:
                        return await interaction.followup.send(
                            "🚫 تم الإلغاء بسبب محاولات خاطئة متكررة.", ephemeral=True
                        )
            except asyncio.TimeoutError:
                return await interaction.followup.send("⌛ انتهى الوقت.", ephemeral=True)

    else:
        # =========================
        # 🔐 PIN verification
        # =========================
        if not saved_pin or str(pin) != str(saved_pin):
            return await interaction.followup.send(
                "🔒 الـ PIN غير صحيح أو غير متوفر.",
                ephemeral=True
            )

    # =========================
    # 🎟️ إنشاء الكوبون — مع lock + فحص رصيد مزدوج
    # =========================
    coupon_code = "GX-" + "".join(
        random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=10)
    )

    expire_dt  = datetime.datetime.now() + datetime.timedelta(days=3)
    expire_str = expire_dt.strftime("%Y-%m-%d %H:%M:%S")

    try:
        async with get_write_lock():
            db = await get_db()

            # ✅ فحص الرصيد مرة تانية جوا الـ lock (منع race condition)
            async with db.execute(
                "SELECT kento FROM global_users WHERE user_id = ?",
                (uid,)
            ) as cursor:
                row = await cursor.fetchone()

            if not row or row[0] < amount:
                return await interaction.followup.send(
                    f"💰 رصيدك غير كافٍ.",
                    ephemeral=True
                )

            # ✅ خصم الكنتو من global_users
            await db.execute(
                "UPDATE global_users SET kento = kento - ? WHERE user_id = ?",
                (amount, uid)
            )

            # ✅ إنشاء الكوبون
            await db.execute("""
                INSERT INTO coupons (code, creator_id, amount, expires_at, used)
                VALUES (?, ?, ?, ?, 0)
            """, (coupon_code, uid, amount, expire_str))

            await db.commit()

    except Exception as e:
        logging.error(f"[coupon error] {e}")
        return await interaction.followup.send(
            "❌ حدث خطأ أثناء إنشاء الكوبون.",
            ephemeral=True
        )

    await interaction.followup.send(
        f"**🎟️ تم إنشاء كوبون بنجاح!**\n"
        f"**الكود:** `{coupon_code}`\n"
        f"**القيمة:** `{amount:,}` 🪙\n"
        f"**ينتهي في:** `{expire_str}`",
        ephemeral=True
    )

    try:
        await interaction.user.send(f"🎟️ كودك:\n`{coupon_code}`")
    except Exception:
        pass


@bot.tree.command(name="use_coupon", description="استخدم كوبون للحصول على كنتو")
@app_commands.describe(code="كود الكوبون الذي تريد استخدامه")
async def use_coupon(interaction: discord.Interaction, code: str):

    if not await check_cooldown(interaction, "use_coupon", 20):
        return

    await interaction.response.defer(ephemeral=True)

    uid   = str(interaction.user.id)
    now   = datetime.datetime.now()

    try:
        async with get_write_lock():
            db = await get_db()

            # 🔍 البحث عن الكوبون
            async with db.execute(
                "SELECT creator_id, amount, expires_at, used FROM coupons WHERE code = ?",
                (code,)
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                return await interaction.followup.send("❌ الكوبون غير موجود.", ephemeral=True)

            creator_id, amount, expires_at_str, used = row

            if used == 1:
                return await interaction.followup.send("⚠️ تم استخدام الكوبون مسبقًا.", ephemeral=True)

            # ⌛ التحقق من الانتهاء
            try:
                expires_at = datetime.datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                expires_at = datetime.datetime.fromisoformat(expires_at_str)

            # ❗ لو منتهي → يرجع لصاحبه في global_users ✅
            if now > expires_at:
                await db.execute(
                    "UPDATE global_users SET kento = kento + ? WHERE user_id = ?",
                    (amount, creator_id)
                )
                await db.execute(
                    "UPDATE coupons SET used = 1 WHERE code = ?",
                    (code,)
                )
                await db.commit()

                return await interaction.followup.send(
                    "⌛ الكوبون انتهى وتم استرجاعه لصاحبه.",
                    ephemeral=True
                )

            # 🚫 منع صاحب الكوبون من استخدامه
            if creator_id == uid:
                return await interaction.followup.send(
                    "😅 لا يمكنك استخدام كوبونك.",
                    ephemeral=True
                )

            # ✅ ضمان وجود المستخدم في global_users
            await db.execute("""
                INSERT OR IGNORE INTO global_users (
                    user_id, total_xp, level,
                    kento, deposit, trust,
                    verified_level, background
                )
                VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
            """, (uid,))

            # ✅ إضافة الكنتو في global_users
            await db.execute(
                "UPDATE global_users SET kento = kento + ? WHERE user_id = ?",
                (amount, uid)
            )

            await db.execute(
                "UPDATE coupons SET used = 1 WHERE code = ?",
                (code,)
            )

            await db.commit()

    except Exception as e:
        logging.error(f"[use_coupon ERROR] {e}")
        return await interaction.followup.send("❌ حدث خطأ أثناء استخدام الكوبون.", ephemeral=True)

    await interaction.followup.send(
        f"🎉 تم الاستخدام +{amount:,} 🪙",
        ephemeral=True
    )

    try:
        owner = bot.get_user(int(creator_id))
        if owner:
            await owner.send(f"🎟️ تم استخدام كوبونك `{code}`")
    except Exception:
        pass
        
                                                                                                                                                            
@bot.tree.command(name="clear", description="حذف عدد من الرسائل")
@app_commands.describe(
    number="عدد الرسائل المراد حذفها (1 - 100)"
)
async def clear(interaction: discord.Interaction, number: int):

    # ⏱️ Cooldown
    if not await check_cooldown(interaction, "clear", 10):
        return

    # 🔐 صلاحيات العضو
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message(
            "ليس لديك صلاحية حذف الرسائل.",
            ephemeral=True
        )

    # 🔐 صلاحيات البوت
    if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
        return await interaction.response.send_message(
            "لا أمتلك صلاحية حذف الرسائل في هذه القناة.",
            ephemeral=True
        )

    # 🔢 تحقق من الرقم
    if number < 1:
        return await interaction.response.send_message(
            "يرجى إدخال رقم أكبر من 0.",
            ephemeral=True
        )

    if number > 100:
        return await interaction.response.send_message(
            "الحد الأقصى للحذف هو 100 رسالة.",
            ephemeral=True
        )

    # 🧹 بدء الحذف
    await interaction.response.send_message(
        f"جارٍ حذف `{number}` رسالة...",
        ephemeral=True
    )

    try:
        two_weeks_ago = discord.utils.utcnow() - datetime.timedelta(days=14)
        deleted = await interaction.channel.purge(
            limit=number,
            after=two_weeks_ago,
            bulk=True
        )

        await interaction.edit_original_response(
            content=f"تم حذف `{len(deleted)}` رسالة بنجاح."
        )

        # 🕒 حذف رسالة التأكيد
        await asyncio.sleep(2)
        await interaction.delete_original_response()

    except discord.Forbidden:
        await interaction.edit_original_response(
            content="ليس لدي صلاحية كافية لتنفيذ العملية."
        )

    except discord.HTTPException as e:
        print(f"[Clear Error] {e}")
        await interaction.edit_original_response(
            content="⚠️ حدث تقييد من Discord أثناء الحذف، حاول مرة أخرى بعد لحظات."
        )

    except Exception as e:
        print(f"[Clear Error] {e}")
        await interaction.edit_original_response(
            content="حدث خطأ أثناء حذف الرسائل."
        )
        

# ================= Confirmation View =================

class ConfirmResetXP(discord.ui.View):

    def __init__(self, gid: str):
        super().__init__(timeout=60)
        self.gid = gid
        self.message = None

        self.confirm_button = discord.ui.Button(
            label="🗑️ تأكيد الحذف (10)",
            style=discord.ButtonStyle.danger,
            disabled=True
        )
        self.confirm_button.callback = self.confirm

        self.cancel_button = discord.ui.Button(
            label="❌ إلغاء",
            style=discord.ButtonStyle.secondary,
            disabled=False
        )
        self.cancel_button.callback = self.cancel

        self.add_item(self.confirm_button)
        self.add_item(self.cancel_button)

    async def start_countdown(self):
        for remaining in range(9, -1, -1):
            await asyncio.sleep(1)
            if self.is_finished():
                return
            if remaining > 0:
                self.confirm_button.label    = f"🗑️ تأكيد الحذف ({remaining})"
                self.confirm_button.disabled = True
            else:
                self.confirm_button.label    = "🗑️ تأكيد الحذف"
                self.confirm_button.disabled = False
            try:
                # ✅ الصح للـ ephemeral
                await self.message.edit(view=self)
            except Exception:
                return

    # ================= زر التأكيد =================
    async def confirm(self, interaction: discord.Interaction):
        self.confirm_button.disabled = True
        self.cancel_button.disabled  = True

        # ✅ بدل interaction.message.edit → هذا هو الحل
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

        try:
            async with get_write_lock():
                db = await get_db()
                await db.execute("""
                    UPDATE users
                    SET xp = 0, msg_xp = 0, voice_xp = 0
                    WHERE guild_id = ?
                """, (self.gid,))
                await db.commit()

            await interaction.followup.send(
                "✅ تم إعادة تعيين XP جميع الأعضاء بنجاح.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"[reset_xp CONFIRM ERROR] {e}")
            await interaction.followup.send(
                "❌ حدث خطأ أثناء إعادة التعيين.",
                ephemeral=True
            )

        self.stop()

    # ================= زر الإلغاء =================
    async def cancel(self, interaction: discord.Interaction):
        self.confirm_button.disabled = True
        self.cancel_button.disabled  = True

        # ✅ نفس الحل
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

        await interaction.followup.send(
            "↩️ تم إلغاء العملية.",
            ephemeral=True
        )

        self.stop()


# ================= RESET XP COMMAND =================

@bot.tree.command(name="reset_xp", description="🗑️ إعادة تعيين XP جميع أعضاء السيرفر")
@app_commands.default_permissions(administrator=True)
async def reset_xp(interaction: discord.Interaction):

    if not interaction.guild or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "❌ هذا الأمر لمالك السيرفر فقط.",
            ephemeral=True
        )

    gid  = str(interaction.guild.id)
    view = ConfirmResetXP(gid)

    embed = discord.Embed(
        title="⚠️ تحذير — إعادة تعيين XP",
        description=(
            "🚨 **هذا الإجراء لا يمكن التراجع عنه!**\n\n"
            "سيتم حذف جميع نقاط XP لكل أعضاء السيرفر.\n\n"
            "⏳ **انتظر 10 ثواني قبل التأكيد**"
        ),
        color=discord.Color.red()
    )
    embed.set_footer(text=f"طلب من: {interaction.user.display_name}")

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )

    view.message = await interaction.original_response()
    asyncio.create_task(view.start_countdown())
    

@bot.tree.command(name="owner_bot", description="معلومات عن مالك ومطور البوت")
async def مالك_البوت(interaction: discord.Interaction):

    # ==============================
    # 🔘 Buttons
    # ==============================
    class OwnerLinks(discord.ui.View):
        def __init__(self):
            super().__init__()

            self.add_item(discord.ui.Button(
                label="ملفي الشخصي",
                url="https://website7-sandy.vercel.app/",
                style=discord.ButtonStyle.link,
                emoji="🌐"
            ))

            self.add_item(discord.ui.Button(
                label="موقع الشركة",
                url="https://global-x-red.vercel.app/",
                style=discord.ButtonStyle.link,
                emoji="🏢"
            ))

    # ==============================
    # 💎 Embed
    # ==============================
    embed = discord.Embed(
        title="👑 مالك ومطور البوت",
        description=(
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💎 **AmrAyman | Founder of Global X**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "> 🚀 مطور متخصص في بناء أنظمة Discord الاحترافية\n"
            "> 🐍 خبير في Python و discord.py وتطوير الحلول الذكية\n"
            "> ⚡ مؤسس شركة Global X وصاحب عدة مشاريع تقنية متقدمة\n"
            "> 🌍 أسعى لتقديم أنظمة سريعة، مستقرة، وعالية الجودة للمجتمعات العربية والعالمية\n"
            "> 🤝 **Trust Above All — الثقة قبل كل شيء**"
        ),
        color=discord.Color.from_rgb(88, 101, 242)
    )

    # ==============================
    # 📌 Developer Info
    # ==============================
    embed.add_field(
        name="╔══ 👤 Developer",
        value=(
            "```yaml\n"
            "Name   : AmrAyman\n"
            "Handle : or6n\n"
            "ID     : 1118943027067633756\n"
            "```"
        ),
        inline=True
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="╠══ 🛠️ Tech Stack",
        value=(
            "```ini\n"
            "[Language] Python 3.x 🐍\n"
            "[Library]  discord.py\n"
            "[Origin]   Egypt 🇪🇬\n"
            "```"
        ),
        inline=True
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="╚══ 🔗 Links",
        value=(
            "> 🌐 [ملفي الشخصي](https://website7-sandy.vercel.app/)\n"
            "> 🏢 [موقع الشركة](https://global-x-red.vercel.app/)"
        ),
        inline=False
    )

    # ==============================
    # 🖼️ Images
    # ==============================
    try:
        owner = await bot.fetch_user(1118943027067633756)
        embed.set_thumbnail(url=owner.display_avatar.url)
        embed.set_footer(
            text="⚡ Developed with 💙 by AmrAyman • or6n",
            icon_url=owner.display_avatar.url
        )
    except Exception:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_footer(
            text="⚡ Developed with 💙 by AmrAyman • or6n",
            icon_url=bot.user.display_avatar.url
        )

    banner_file = discord.File("banner.gif", filename="banner.gif")
    embed.set_image(url="attachment://banner.gif")

    embed.timestamp = discord.utils.utcnow()

    await interaction.response.send_message(
        embed=embed,
        file=banner_file,
        view=OwnerLinks()
    )            
    
# ================== قفل ==================
@bot.command(name="قفل", aliases=["lock"])
@commands.has_permissions(manage_channels=True)
async def lock_text(ctx):
    channel = ctx.channel
    role = ctx.guild.default_role

    overwrites = channel.overwrites_for(role)
    overwrites.send_messages = False

    await channel.set_permissions(role, overwrite=overwrites)
    await ctx.send(f"🔒 تم قفل الإرسال في {channel.mention}")


# ================== فتح ==================
@bot.command(name="فتح", aliases=["unlock"])
@commands.has_permissions(manage_channels=True)
async def unlock_text(ctx):
    channel = ctx.channel
    role = ctx.guild.default_role

    overwrites = channel.overwrites_for(role)
    overwrites.send_messages = None  # يرجّعها للوضع الطبيعي

    await channel.set_permissions(role, overwrite=overwrites)
    await ctx.send(f"🔓 تم فتح الإرسال في {channel.mention}")
    

# ================== ميوت ==================
@bot.command(name="ميوت", aliases=["mute"])
@commands.has_permissions(manage_roles=True)
async def mute_text(ctx, member: discord.Member):

    # منع المستخدم من ميوت نفسه
    if member == ctx.author:
        return await ctx.send("❌ لا يمكنك ميوت نفسك")

    # مقارنة رتبة العضو مع رتبة كاتب الأمر
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send(
            f"❌ لا يمكنك ميوت {member.mention}، رتبته مساوية أو أعلى من رتبتك."
        )

    # مقارنة رتبة العضو مع رتبة البوت
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            f"❌ لا أستطيع ميوت {member.mention}، رتبته أعلى من رتبة البوت."
        )

    guild = ctx.guild
    server_data = points_data.setdefault("servers", {}).setdefault(str(guild.id), {})

    # الحصول على رتبة الميوت من بيانات السيرفر أو إنشاء واحدة إذا لم تكن موجودة
    role_id = server_data.get("mute_role")
    role = guild.get_role(role_id) if role_id else None

    if not role:
        role = discord.utils.get(guild.roles, name="Muted")
        if not role:
            try:
                role = await guild.create_role(
                    name="Muted",
                    permissions=discord.Permissions.none(),
                    reason="Mute system"
                )
                for channel in guild.text_channels:
                    await channel.set_permissions(role, send_messages=False)
            except Exception as e:
                return await ctx.send(f"⚠️ حدث خطأ أثناء إنشاء رتبة الميوت: {e}")

        server_data["mute_role"] = role.id

    # تطبيق الميوت أو فك الميوت
    try:
        if role in member.roles:
            await member.remove_roles(role, reason=f"Unmuted by {ctx.author}")
            await ctx.send(f"🔊 تم فك الميوت عن {member.mention}")
        else:
            await member.add_roles(role, reason=f"Muted by {ctx.author}")
            await ctx.send(f"🔇 تم ميوت {member.mention}")
    except Exception as e:
        await ctx.send(f"⚠️ حدث خطأ أثناء تعديل الرتب: {e}")
                
# ================== تايم ==================
@bot.command(name="تايم", aliases=["timeout"])
@commands.has_permissions(moderate_members=True)
async def timeout_text(ctx, member: discord.Member, time: str = None, *, reason: str = None):

    # منع المستخدم من إعطاء تايم لنفسه
    if member == ctx.author:
        return await ctx.send("❌ لا يمكنك إعطاء تايم لنفسك.")

    # مقارنة رتبة العضو مع رتبة كاتب الأمر
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send(
            f"❌ لا يمكنك إعطاء تايم ل{member.mention}، رتبته مساوية أو أعلى من رتبتك."
        )

    # مقارنة رتبة العضو مع رتبة البوت
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            f"❌ لا أستطيع إعطاء تايم ل{member.mention}، رتبته أعلى من رتبة البوت."
        )

    # التأكد من تحديد الوقت
    if not time:
        return await ctx.send("❌ مثال: `تايم @عضو 10m` أو `تايم @عضو 0` لإلغاء التايم أوت")

    # إزالة التايم أوت إذا كان الوقت 0
    if time == "0":
        try:
            await member.edit(timed_out_until=None)
            return await ctx.send(f"✅ تم إزالة التايم أوت من {member.mention}")
        except Exception as e:
            return await ctx.send(f"⚠️ حدث خطأ أثناء إزالة التايم أوت: {e}")

    # التحقق من صيغة الوقت
    match = re.match(r"(\d+)([smhd])", time)
    if not match:
        return await ctx.send("❌ صيغة خاطئة: استخدم `10m` / `2h` / `1d`")

    value, unit = int(match[1]), match[2]
    seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    until = datetime.utcnow() + timedelta(seconds=value * seconds)

    # محاولة تطبيق التايم أوت
    try:
        await member.edit(
            timed_out_until=until,
            reason=f"{reason or 'بدون سبب'} | {ctx.author}"
        )
        await ctx.send(f"⏳ تم إعطاء {member.mention} تايم أوت لمدة `{time}`")
    except Exception as e:
        await ctx.send(f"⚠️ حدث خطأ أثناء إعطاء التايم أوت: {e}")
        
@bot.command(name="مسح", aliases=["clear", "delete"])
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.channel)
async def clear_text(ctx, amount: int = 100):

    # 🧮 تحقق من الرقم
    if amount < 1:
        msg = await ctx.send("يرجى إدخال رقم أكبر من 0.")
        return await msg.delete(delay=3)

    if amount > 100:
        msg = await ctx.send("الحد الأقصى للحذف هو 100 رسالة في المرة الواحدة.")
        return await msg.delete(delay=3)

    # 🧹 حذف رسالة الأمر نفسها
    try:
        await ctx.message.delete()
    except:
        pass

    # 🧹 تنفيذ الحذف (فقط للرسائل الأحدث من 14 يوم لتجنب bulk delete fallback البطيء)
    try:
        two_weeks_ago = discord.utils.utcnow() - datetime.timedelta(days=14)
        deleted = await ctx.channel.purge(
            limit=amount,
            after=two_weeks_ago,
            bulk=True
        )
    except discord.HTTPException as e:
        deleted = []
        err_msg = await ctx.send(f"⚠️ حدث خطأ أثناء الحذف: {e}")
        return await err_msg.delete(delay=5)

    # 📢 رسالة تأكيد
    confirm = await ctx.send(
        f"تم حذف `{len(deleted)}` رسالة."
    )

    await confirm.delete(delay=5)
    
# ================== باند ==================
@bot.command(name="باند", aliases=["ban"])
@commands.has_permissions(ban_members=True)
async def ban_text(ctx, member: discord.Member, *, reason: str = None):

    # محاولة حظر نفسه
    if member == ctx.author:
        return await ctx.send("❌ لا يمكنك حظر نفسك.")

    # رتبة العضو مقابل رتبة كاتب الأمر
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send(
            f"❌ لا يمكنك حظر {member.mention}، رتبته مساوية أو أعلى من رتبتك."
        )

    # رتبة العضو مقابل رتبة البوت
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            f"❌ لا أستطيع حظر {member.mention}، رتبته أعلى من رتبة البوت."
        )

    # تنفيذ الباند
    try:
        await member.ban(reason=f"{reason or 'بدون سبب'} | {ctx.author}")
        await ctx.send(f"⛔ تم حظر {member.mention} بنجاح")
    except Exception as e:
        await ctx.send(f"⚠️ حدث خطأ أثناء محاولة الحظر: {e}")
            
# ================== طرد ==================
@bot.command(name="طرد", aliases=["kick"])
@commands.has_permissions(kick_members=True)
async def kick_text(ctx, member: discord.Member, *, reason: str = None):

    # محاولة الطرد لنفسه
    if member == ctx.author:
        return await ctx.send("❌ لا يمكنك طرد نفسك.")

    # رتبة العضو مقابل رتبة كاتب الأمر
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send(
            f"❌ لا يمكنك طرد {member.mention}، رتبته مساوية أو أعلى من رتبتك."
        )

    # رتبة العضو مقابل رتبة البوت
    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send(
            f"❌ لا أستطيع طرد {member.mention}، رتبته أعلى من رتبة البوت."
        )

    try:
        await member.kick(reason=f"{reason or 'بدون سبب'} | {ctx.author}")
        await ctx.send(f"👢 تم طرد {member.mention} بنجاح")
    except Exception as e:
        await ctx.send(f"⚠️ حدث خطأ أثناء محاولة الطرد: {e}")
            
# ✅ أمر إظهار الرومات
@bot.tree.command(name="show_rooms", description="إظهار الرومات التي تم إخفاؤها فقط")
async def عرض_رومات(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ هذا الأمر مخصص فقط للإدارة.", ephemeral=True)

    # ⚡ تحقق من التبريد (60 ثانية)
    if not await check_cooldown(interaction, "show_rooms", 60):
        return

    # باقي كود إظهار الرومات يظل كما هو...
    await interaction.response.defer(ephemeral=True)

    role = interaction.guild.default_role
    count = 0
    restored = []

    # نرجع بس الرومات اللي إحنا أخفيناها
    hidden_list = hidden_channels_cache.get(interaction.guild.id, [])
    for channel_id in hidden_list:
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            continue
        try:
            overwrites = channel.overwrites_for(role)
            if overwrites.view_channel is False:
                overwrites.view_channel = True
                await channel.set_permissions(role, overwrite=overwrites)
                restored.append(channel_id)
                count += 1
        except Exception as e:
            print(f"[⚠️] فشل عرض {channel.name}: {e}")

    # نفضي الكاش بعد ما خلصنا
    hidden_channels_cache[interaction.guild.id] = [
        cid for cid in hidden_list if cid not in restored
    ]

    if count == 0:
        msg = "⚠️ مفيش أي رومات متخزنة للإظهار."
    else:
        msg = f"✅ تم إظهار `{count}` من الرومات."

    await interaction.followup.send(msg, ephemeral=True)
                            

@bot.tree.command(
    name="set_role_icon",
    description="تغيير أيقونة رتبة باستخدام إيموجي من السيرفر (إدارة فقط)"
)
@app_commands.describe(
    role="الرتبة التي تريد تعديل أيقونتها",
    emoji="إيموجي من السيرفر"
)
async def set_role_icon(
    interaction: discord.Interaction,
    role: discord.Role,
    emoji: str
):
    await interaction.response.defer(ephemeral=True)

    # ===== صلاحيات المستخدم =====
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("هذا الأمر مخصص للإدارة فقط.")

    # ===== صلاحيات البوت =====
    bot_member = interaction.guild.me or interaction.guild.get_member(bot.user.id)

    if not bot_member.guild_permissions.manage_roles:
        return await interaction.followup.send("لا أمتلك صلاحية Manage Roles.")

    if role >= bot_member.top_role:
        return await interaction.followup.send(
            "لا يمكنني تعديل هذه الرتبة لأنها أعلى أو مساوية لرتبتي."
        )

    # ===== قراءة الإيموجي =====
    try:
        emoji_obj = discord.PartialEmoji.from_str(emoji)
    except Exception:
        emoji_obj = None

    if not emoji_obj or not emoji_obj.id:
        return await interaction.followup.send(
            "يرجى استخدام إيموجي مخصص من نفس السيرفر."
        )

    # ===== رابط الإيموجي =====
    emoji_url = emoji_obj.url

    # ===== تحميل الصورة =====
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(emoji_url)) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("فشل تحميل صورة الإيموجي.")
                icon_bytes = await resp.read()
    except Exception:
        return await interaction.followup.send("حدث خطأ أثناء تحميل الإيموجي.")

    # ===== تعديل الرتبة =====
    try:
        await role.edit(icon=icon_bytes)
        await interaction.followup.send(
            f"تم تغيير أيقونة رتبة **{role.name}** بنجاح."
        )

    except discord.Forbidden:
        await interaction.followup.send("لا أمتلك صلاحية تعديل هذه الرتبة.")

    except TypeError:
        # fallback للإصدارات القديمة
        try:
            b64_icon = f"data:image/png;base64,{base64.b64encode(icon_bytes).decode()}"
            await interaction.guild._state.http.edit_role(
                interaction.guild.id,
                role.id,
                icon=b64_icon
            )
            await interaction.followup.send(
                f"تم تغيير أيقونة رتبة **{role.name}** بنجاح."
            )
        except Exception:
            await interaction.followup.send("فشل تعديل أيقونة الرتبة.")

    except Exception as e:
        print(f"[set_role_icon error] {e}")
        await interaction.followup.send("حدث خطأ غير متوقع.")
                        
@bot.tree.command(
    name="rename_channel",
    description="تغيير اسم أي روم بسرعة وبشكل آمن."
)
@app_commands.describe(
    channel="القناة التي تريد تغيير اسمها",
    new_name="الاسم الجديد للقناة"
)
async def rename_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    new_name: str
):
    await interaction.response.defer(ephemeral=True)

    # ===== صلاحيات المستخدم =====
    if not interaction.user.guild_permissions.manage_channels:
        return await interaction.followup.send(
            "ليس لديك صلاحية تعديل القنوات."
        )

    # ===== صلاحيات البوت =====
    bot_member = interaction.guild.me or interaction.guild.get_member(bot.user.id)
    if not bot_member.guild_permissions.manage_channels:
        return await interaction.followup.send(
            "لا أمتلك صلاحية تعديل القنوات."
        )

    old_name = channel.name

    # ===== تحقق من الاسم =====
    if new_name == old_name:
        return await interaction.followup.send(
            "الاسم الجديد مطابق للاسم الحالي."
        )

    if len(new_name) < 1 or len(new_name) > 100:
        return await interaction.followup.send(
            "اسم القناة يجب أن يكون بين 1 و 100 حرف."
        )

    # ===== تعديل الاسم =====
    try:
        await channel.edit(
            name=new_name,
            reason=f"Renamed by {interaction.user} ({interaction.user.id})"
        )

        embed = discord.Embed(
            title="تم تغيير اسم القناة",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="القناة", value=channel.mention, inline=False)
        embed.add_field(name="الاسم السابق", value=f"`{old_name}`", inline=True)
        embed.add_field(name="الاسم الجديد", value=f"`{new_name}`", inline=True)
        embed.add_field(
            name="بواسطة",
            value=interaction.user.mention,
            inline=False
        )

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        embed.set_footer(text="GX Bot • Channel Management")

        await interaction.followup.send(embed=embed)

    except discord.Forbidden:
        await interaction.followup.send(
            "لا يمكنني تعديل هذه القناة (تحقق من الترتيب والصلاحيات)."
        )

    except Exception as e:
        print(f"[rename_channel error] {e}")
        await interaction.followup.send(
            "حدث خطأ غير متوقع أثناء تعديل اسم القناة."
        )

@bot.tree.command(name="warn", description="تحذير عضو بسبب معين")
@app_commands.describe(
    العضو="العضو الذي تريد تحذيره",
    السبب="سبب التحذير"
)
async def تحذير(interaction: discord.Interaction, العضو: discord.Member, السبب: str):

    if not interaction.user.guild_permissions.kick_members:
        return await interaction.response.send_message(
            "❌ تحتاج صلاحية طرد لتحذير الأعضاء.",
            ephemeral=True
        )

    if العضو == interaction.user:
        return await interaction.response.send_message(
            "❌ لا يمكنك تحذير نفسك.",
            ephemeral=True
        )

    if العضو.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(
            "❌ لا يمكنك تحذير عضو رتبته أعلى أو مساوية لرتبتك.",
            ephemeral=True
        )

    if العضو.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "❌ لا أستطيع تحذير هذا العضو لأن رتبته أعلى من رتبة البوت.",
            ephemeral=True
        )

    guild_id = str(interaction.guild.id)
    user_id = str(العضو.id)
    mod_id = str(interaction.user.id)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    async with get_write_lock():
        db = await get_db()

        await db.execute("""
            INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, mod_id, السبب, now))

        await db.commit()

    await interaction.response.send_message(
        f"⚠️ تم تحذير {العضو.mention} بسبب: **{السبب}**"
    )
    
@bot.command(name="تحذير", aliases=["warn"])
@commands.has_permissions(kick_members=True)
async def warn_text(ctx, member: discord.Member, *, reason: str = "بدون سبب"):

    if member == ctx.author:
        return await ctx.send("❌ لا يمكنك تحذير نفسك")

    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send("❌ لا يمكنك تحذير عضو أعلى منك")

    if member.top_role >= ctx.guild.me.top_role:
        return await ctx.send("❌ لا أستطيع تحذيره بسبب الرتب")

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    mod_id = str(ctx.author.id)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    async with get_write_lock():
        db = await get_db()

        await db.execute("""
            INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, mod_id, reason, now))

        await db.commit()

    await ctx.reply(
    f"⚠️ تم تحذير {member.mention} بنجاح",
    mention_author=False
)
        
@bot.tree.command(name="warnings", description="عرض تحذيرات عضو")
async def warnings(interaction: discord.Interaction, member: discord.Member):

    await interaction.response.defer(ephemeral=True)

    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.followup.send("❌ لا تملك صلاحية")

    guild_id = str(interaction.guild.id)
    user_id = str(member.id)

    db = await get_db()

    async with db.execute("""
        SELECT mod_id, reason, created_at
        FROM warnings
        WHERE guild_id = ? AND user_id = ?
        ORDER BY id DESC
        LIMIT 15
    """, (guild_id, user_id)) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return await interaction.followup.send(f"لا توجد تحذيرات لـ {member.mention}")

    lines = []
    for i, w in enumerate(rows, 1):
        lines.append(
            f"**#{i}** | {w['reason']}\n↳ <@{w['mod_id']}> — {w['created_at']}"
        )

    embed = discord.Embed(
        title="⚠️ تحذيرات العضو",
        description="\n\n".join(lines),
        color=discord.Color.orange()
    )

    embed.set_author(
        name=member.display_name,
        icon_url=member.display_avatar.url
    )

    await interaction.followup.send(embed=embed)
    
@bot.tree.command(name="remove_warnings", description="حذف تحذير أو كل التحذيرات")
async def remove_warnings(interaction: discord.Interaction, member: discord.Member, index: Optional[int] = None):

    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message("❌ لا تملك صلاحية", ephemeral=True)

    guild_id = str(interaction.guild.id)
    user_id = str(member.id)

    async with get_write_lock():
        db = await get_db()

        if index is None:
            await db.execute("""
                DELETE FROM warnings
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id))

            await db.commit()
            return await interaction.response.send_message("تم حذف كل التحذيرات", ephemeral=True)

        async with db.execute("""
            SELECT id FROM warnings
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT 1 OFFSET ?
        """, (guild_id, user_id, index - 1)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return await interaction.response.send_message("رقم غير صحيح", ephemeral=True)

        await db.execute("""
            DELETE FROM warnings WHERE id = ?
        """, (row["id"],))

        await db.commit()

    await interaction.response.send_message(f"تم حذف التحذير #{index}", ephemeral=True)
                                                                                                                                                                
@bot.tree.command(
    name="invites_bot",
    description="عرض معلومات وروابط البوت"
)
async def invites_bot(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    bot_user = bot.user
    bot_avatar = bot_user.display_avatar.url if bot_user else None

    embed = discord.Embed(
        title="GX Bot — Information & Links",
        description=(
            "GX Bot مصمم لتقديم نظام متكامل واحترافي لإدارة السيرفرات.\n\n"
            "**ما يمكنك فعله:**\n"
            "• دعوة البوت إلى سيرفرك\n"
            "• الانضمام إلى سيرفر الدعم\n"
            "• التواصل في حال وجود أي مشكلة\n\n"
            "**ملاحظة:** في حال تعطل السيرفر الأساسي، يمكنك استخدام رابط الدعم الاحتياطي."
        ),
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )

    if bot_avatar:
        embed.set_thumbnail(url=bot_avatar)

    embed.set_footer(text="GX Bot • Official Links")

    # ===== Buttons =====
    view = discord.ui.View()

    view.add_item(
        discord.ui.Button(
            label="Invite Bot",
            style=discord.ButtonStyle.link,
            url=(
                "https://discord.com/oauth2/authorize"
                "?client_id=1411571554025865236"
                "&permissions=8"
                "&scope=bot%20applications.commands"
            )
        )
    )

    view.add_item(
        discord.ui.Button(
            label="Support Server",
            style=discord.ButtonStyle.link,
            url="https://discord.gg/N4f4rsfSkR"
        )
    )

    view.add_item(
        discord.ui.Button(
            label="Backup Support",
            style=discord.ButtonStyle.link,
            url="https://discord.gg/cZ9hFrjJnn"
        )
    )

    await interaction.followup.send(embed=embed, view=view)
          
    
import time

@bot.tree.command(name="ping", description="عرض زمن استجابة البوت وقاعدة البيانات بالتفصيل")
async def ping(interaction: discord.Interaction):
    # 1. تسجيل وقت بداية العملية بدقة عالية
    start_time = time.perf_counter()
    
    # تأجيل الرد عشان نحسب الـ Latency الفعلي للـ API
    await interaction.response.defer(thinking=True)
    
    # 2. حساب زمن استجابة قاعدة البيانات (SQLite)
    db_start = time.perf_counter()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("SELECT 1")
    db_end = time.perf_counter()
    db_latency = round((db_end - db_start) * 1000)

    # 3. حساب سرعة اتصال البوت (Gateway Latency)
    gateway_latency = round(bot.latency * 1000)

    # 4. حساب زمن الرد الكامل (REST API Latency)
    end_time = time.perf_counter()
    api_latency = round((end_time - start_time) * 1000)

    # تحديد اللون بناءً على السرعة
    if api_latency < 150:
        color = discord.Color.green()
        status = "🟢 ممتاز"
    elif api_latency < 300:
        color = discord.Color.gold()
        status = "🟡 جيد"
    else:
        color = discord.Color.red()
        status = "🔴 متأخر"

    embed = discord.Embed(
        title="🏓 Pong! - حالة اتصال GxBot",
        color=color,
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(name="🌐 Gateway", value=f"`{gateway_latency}ms`", inline=True)
    embed.add_field(name="⚡ API Rest", value=f"`{api_latency}ms`", inline=True)
    embed.add_field(name="🗄️ Database", value=f"`{db_latency}ms`", inline=True)
    
    embed.add_field(name="📊 حالة النظام", value=f"**{status}**", inline=False)
    
    # إضافة صورة رمزية صغيرة (Thumbnail)
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    
    embed.set_footer(
        text=f"Requested by {interaction.user.name}", 
        icon_url=interaction.user.display_avatar.url
    )

    await interaction.followup.send(embed=embed)


                                                        
@bot.tree.command(
    name="give_role",
    description="إعطاء رتبة للأعضاء أو البوتات أو الجميع"
)
@app_commands.describe(
    role="الرتبة التي تريد إعطائها",
    target="الفئة المستهدفة"
)
@app_commands.choices(
    target=[
        app_commands.Choice(name="الأعضاء فقط", value="members"),
        app_commands.Choice(name="البوتات فقط", value="bots"),
        app_commands.Choice(name="الجميع", value="all")
    ]
)
async def give_role(
    interaction: discord.Interaction,
    role: discord.Role,
    target: str
):
    await interaction.response.defer(ephemeral=True)

    # ===== صلاحيات المستخدم =====
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send(
            "ليس لديك صلاحية استخدام هذا الأمر."
        )

    bot_member = interaction.guild.me

    # ===== صلاحيات البوت =====
    if not bot_member.guild_permissions.manage_roles:
        return await interaction.followup.send(
            "لا أمتلك صلاحية Manage Roles."
        )

    if role >= bot_member.top_role:
        return await interaction.followup.send(
            "لا يمكنني إعطاء رتبة أعلى أو مساوية لرتبتي."
        )

    # ===== تحديد الهدف =====
    if target == "members":
        targets = [m for m in interaction.guild.members if not m.bot]
    elif target == "bots":
        targets = [m for m in interaction.guild.members if m.bot]
    else:
        targets = interaction.guild.members

    success = 0
    failed = 0

    for member in targets:
        if role in member.roles:
            continue

        try:
            await member.add_roles(
                role,
                reason=f"Give role command by {interaction.user}"
            )
            success += 1
            await asyncio.sleep(0.15)  # أسرع وآمن
        except discord.Forbidden:
            failed += 1
        except discord.HTTPException:
            failed += 1

    embed = discord.Embed(
        title="Give Role Result",
        description=(
            f"**Role:** {role.mention}\n"
            f"**Target:** `{target}`\n\n"
            f"**Success:** `{success}`\n"
            f"**Failed:** `{failed}`"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )

    await interaction.followup.send(embed=embed)
    

@bot.tree.command(
    name="remove_role",
    description="إزالة رتبة من الأعضاء أو البوتات أو الجميع"
)
@app_commands.describe(
    role="الرتبة المراد إزالتها",
    target="الفئة المستهدفة"
)
@app_commands.choices(
    target=[
        app_commands.Choice(name="الأعضاء فقط", value="members"),
        app_commands.Choice(name="البوتات فقط", value="bots"),
        app_commands.Choice(name="الجميع", value="all")
    ]
)
async def remove_role(
    interaction: discord.Interaction,
    role: discord.Role,
    target: str
):
    await interaction.response.defer(ephemeral=True)

    # ===== صلاحيات المستخدم =====
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send(
            "ليس لديك صلاحية استخدام هذا الأمر."
        )

    bot_member = interaction.guild.me

    # ===== صلاحيات البوت =====
    if not bot_member.guild_permissions.manage_roles:
        return await interaction.followup.send(
            "لا أمتلك صلاحية Manage Roles."
        )

    if role >= bot_member.top_role:
        return await interaction.followup.send(
            "لا يمكنني إزالة رتبة أعلى أو مساوية لرتبتي."
        )

    # ===== تحديد الهدف =====
    if target == "members":
        targets = [m for m in interaction.guild.members if not m.bot]
    elif target == "bots":
        targets = [m for m in interaction.guild.members if m.bot]
    else:
        targets = interaction.guild.members

    removed = 0
    failed = 0

    for member in targets:
        if role not in member.roles:
            continue

        try:
            await member.remove_roles(
                role,
                reason=f"Remove role command by {interaction.user}"
            )
            removed += 1
            await asyncio.sleep(0.15)
        except discord.Forbidden:
            failed += 1
        except discord.HTTPException:
            failed += 1

    embed = discord.Embed(
        title="Remove Role Result",
        description=(
            f"**Role:** {role.mention}\n"
            f"**Target:** `{target}`\n\n"
            f"**Removed:** `{removed}`\n"
            f"**Failed:** `{failed}`"
        ),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )

    await interaction.followup.send(embed=embed)
        
        
@bot.tree.command(name="roles", description=" عرض جميع رتب السيرفر")
async def عرض_الرولات(interaction: discord.Interaction):
    guild = interaction.guild
    roles = [role for role in guild.roles if role.name != "@everyone"]
    roles.sort(reverse=True)  # من الأعلى للأدنى

    if not roles:
        return await interaction.response.send_message(
            "⚠️ لا توجد رتب متاحة في هذا السيرفر.",
            ephemeral=True
        )

    # ✅ نعمل defer الأول عشان التفاعل ميفصلش
    await interaction.response.defer()

    description = ""
    for role in roles:
        member_count = sum(1 for member in guild.members if role in member.roles)
        description += f"{role.mention} — `{member_count}` عضو\n"

    embed = discord.Embed(
        title=f"📋 قائمة الرتب في السيرفر: {guild.name}",
        description=description[:4000],  # حد الوصف 4000 حرف
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"🔢 عدد الرتب: {len(roles)}")
    embed.timestamp = discord.utils.utcnow()

    # ✨ بعد defer نستخدم followup.send
    await interaction.followup.send(embed=embed)                                                                                                                
                                 
@bot.tree.command(name="server", description="عرض خصائص وإحصائيات السيرفر")
async def احصائيات(interaction: discord.Interaction):
    # 🕒 تبريد 5 ثواني لتقليل الضغط ومنع السبام
    if not await check_cooldown(interaction, "server", 5):
        return

    guild = interaction.guild
    
    # عدد الأعضاء
    humans = len([m for m in guild.members if not m.bot])
    bots = len([m for m in guild.members if m.bot])
    online = len([m for m in guild.members if m.status != discord.Status.offline])

    # عدد الرومات الفعلية فقط (بدون الثريدات أو التصنيفات)
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    threads = sum([len(c.threads) for c in guild.text_channels if hasattr(c, "threads")])

    # تنسيق تاريخ الإنشاء
    created_at = discord.utils.format_dt(guild.created_at, style="F")

    embed = discord.Embed(
        title=f"  {guild.name}",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

    embed.add_field(name="👑 مالك السيرفر", value=guild.owner.mention, inline=True)
    embed.add_field(name="🗓️ تاريخ الإنشاء", value=created_at, inline=True)
    embed.add_field(name="🎖️ عدد التعزيزات", value=guild.premium_subscription_count, inline=True)

    embed.add_field(name="📁 الرومات النصية", value=str(text_channels), inline=True)
    embed.add_field(name="🔊 الرومات الصوتية", value=str(voice_channels), inline=True)
    embed.add_field(name="📂 التصنيفات", value=str(categories), inline=True)

    embed.add_field(name="🧵 الثريدات النشطة", value=str(threads), inline=True)
    embed.add_field(name="👤 الأعضاء العاديين", value=str(humans), inline=True)
    embed.add_field(name="🤖 عدد البوتات", value=str(bots), inline=True)

    embed.set_footer(text=f"🆔 ID: {guild.id}")

    await interaction.response.send_message(embed=embed)                
@bot.command(name="سيرفر")
async def server(ctx: commands.Context):
    if not await check_cooldown(ctx, "server", 5):
        return

    guild = ctx.guild

    humans = len([m for m in guild.members if not m.bot])
    bots = len([m for m in guild.members if m.bot])
    online = len([m for m in guild.members if m.status != discord.Status.offline])

    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    threads = sum([len(c.threads) for c in guild.text_channels if hasattr(c, "threads")])

    created_at = discord.utils.format_dt(guild.created_at, style="F")

    embed = discord.Embed(
        title=f"📊 {guild.name}",
        color=discord.Color.blurple()
    )

    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

    embed.add_field(name="👑 مالك السيرفر", value=guild.owner.mention, inline=True)
    embed.add_field(name="🆔 ID", value=str(guild.id), inline=True)
    embed.add_field(name="🗓️ تاريخ الإنشاء", value=created_at, inline=True)

    embed.add_field(name="🎖️ البوستات", value=str(guild.premium_subscription_count), inline=True)

    embed.add_field(name="📁 الرومات النصية", value=str(text_channels), inline=True)
    embed.add_field(name="🔊 الرومات الصوتية", value=str(voice_channels), inline=True)
    embed.add_field(name="📂 التصنيفات", value=str(categories), inline=True)

    embed.add_field(name="🧵 الثريدات", value=str(threads), inline=True)
    embed.add_field(name="👤 الأعضاء", value=str(humans), inline=True)
    embed.add_field(name="🤖 البوتات", value=str(bots), inline=True)

    embed.set_footer(text=f"Server ID: {guild.id}")

    await ctx.reply(
    embed=embed,
    mention_author=False
)
                                                        
@bot.tree.command(name="embed", description="إنشاء رسالة إيمبد احترافية عن طريق كتابتها")
@app_commands.describe(
    title="عنوان الإيمبد",
    image="صورة مرفقة تظهر كبيرة (اختياري)",
    thumbnail="صورة صغيرة تظهر في الزاوية (اختياري)",
    channel="القناة (اختياري، الافتراضي هذه القناة)",
    color="لون جانب الإيمبد"
)
@app_commands.choices(color=[
    app_commands.Choice(name="🔴 أحمر", value="red"),
    app_commands.Choice(name="🔵 أزرق", value="blue"),
    app_commands.Choice(name="🟢 أخضر", value="green"),
    app_commands.Choice(name="🟡 أصفر", value="yellow"),
    app_commands.Choice(name="🟠 برتقالي", value="orange"),
    app_commands.Choice(name="⚪ أبيض", value="white"),
    app_commands.Choice(name="⚫ أسود", value="black"),
    app_commands.Choice(name="✨ ذهبي", value="gold"),
    app_commands.Choice(name="🎲 عشوائي", value="random"),
])
async def embed(
    interaction: discord.Interaction,
    title: str,
    image: Optional[discord.Attachment] = None,
    thumbnail: Optional[discord.Attachment] = None,
    channel: Optional[discord.TextChannel] = None,
    color: Optional[app_commands.Choice[str]] = None
):
    # 1. التحقق من الصلاحيات
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("❌ تحتاج صلاحية `إدارة الرسائل` لاستخدام هذا الأمر.", ephemeral=True)

    # 2. طلب المحتوى من المستخدم
    await interaction.response.send_message(
        f"📝 **يا {interaction.user.display_name}، اكتب الآن محتوى الإيمبد (الوصف) في هذه القناة.**\n"
        f"⏳ لديك 60 ثانية...", 
        ephemeral=True
    )

    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id

    try:
        msg = await bot.wait_for("message", timeout=60, check=check)
    except asyncio.TimeoutError:
        return await interaction.followup.send("⌛ انتهى الوقت! أعد كتابة الأمر مرة أخرى.", ephemeral=True)

    # 3. إعداد الألوان
    COLOR_MAP = {
        "red": discord.Color.red(),
        "blue": discord.Color.blue(),
        "green": discord.Color.green(),
        "yellow": discord.Color.yellow(),
        "orange": discord.Color.orange(),
        "white": discord.Color.from_rgb(254, 254, 254),
        "black": discord.Color.from_rgb(1, 1, 1),
        "gold": discord.Color.gold(),
        "random": discord.Color.random()
    }
    
    selected_color = COLOR_MAP.get(color.value if color else "random", discord.Color.random())

    # 4. بناء الإيمبد الاحترافي
    final_embed = discord.Embed(
        title=title,
        description=msg.content,
        color=selected_color,
        timestamp=discord.utils.utcnow()
    )

    # إذا كان العضو أرفق صورة مع رسالته النصية، نستخدمها كصورة للإيمبد لو مفيش صورة اختيارية
    if image:
        final_embed.set_image(url=image.url)
    elif msg.attachments:
        final_embed.set_image(url=msg.attachments[0].url)

    if thumbnail:
        final_embed.set_thumbnail(url=thumbnail.url)

    # إضافة معلومات كاتب الإيمبد (اختياري لزيادة الفخامة)
    final_embed.set_footer(text=f"بواسطة: {interaction.user.name}", icon_url=interaction.user.display_avatar.url)

    # 5. التنظيف والإرسال
    try:
        await msg.delete() # حذف رسالة المحتوى عشان الشات يفضل نظيف
    except:
        pass

    target_channel = channel or interaction.channel
    try:
        await target_channel.send(embed=final_embed)
        await interaction.followup.send(f"✅ تم إرسال الإيمبد في {target_channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ حدث خطأ أثناء الإرسال: {e}", ephemeral=True)

                                          
@bot.tree.command(name="ban", description=" حظر عضو من السيرفر")
@app_commands.describe(
    member="العضو الذي تريد حظره",
    reason="سبب الحظر (اختياري)"
)
async def ban_command(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: Optional[str] = "لا يوجد سبب محدد"
):
    # تحقق من صلاحية المستخدم
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("❌ لا تمتلك صلاحية لحظر الأعضاء.", ephemeral=True)

    # تحقق من صلاحية البوت
    if not interaction.guild.me.guild_permissions.ban_members:
        return await interaction.response.send_message("⚠️ لا أمتلك صلاحية حظر الأعضاء.", ephemeral=True)

    if member.id == interaction.user.id:
        return await interaction.response.send_message("⚠️ لا يمكنك حظر نفسك.", ephemeral=True)
    if member.id == interaction.guild.owner_id:
        return await interaction.response.send_message("⚠️ لا يمكن حظر مالك السيرفر.", ephemeral=True)

    if member.bot and member.id == bot.user.id:
        return await interaction.response.send_message("🤖 لا يمكنك حظر البوت!", ephemeral=True)

    # محاولة إرسال رسالة خاصة للعضو قبل الحظر
    try:
        await member.send(f"🚫 تم حظرك من السيرفر `{interaction.guild.name}`.\n📝 السبب: {reason}")
    except:
        pass  # تجاهل لو ما قدر يرسل له خاص

    # تنفيذ الحظر
    try:
        await member.ban(reason=f"{reason} - بواسطة {interaction.user}")
        await interaction.response.send_message(
            f"✅ تم حظر {member.mention} من السيرفر.\n📝 السبب: {reason}",
            ephemeral=False
        )
    except Exception as e:
        print(f"[❌] خطأ أثناء الحظر: {e}")
        await interaction.response.send_message("❌ فشل تنفيذ الحظر. تأكد من أن رتبتك أعلى من العضو.", ephemeral=True)
                                                                            
@bot.tree.command(name="kick", description="اعطاء طرد لشخص أو ازالته من السيرفر")
@app_commands.describe(
    member="الشخص الذي تريد طرده",
    reason="السبب (اختياري)"
)
async def kick_command(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: Optional[str] = None
):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("❌ لا تمتلك صلاحية لطرد الأعضاء.", ephemeral=True)
        return

    # ✅ تحقق من أن البوت لديه الصلاحية
    if not interaction.guild.me.guild_permissions.kick_members:
        await interaction.response.send_message("⚠️ لا أمتلك صلاحية طرد الأعضاء.", ephemeral=True)
        return

    # ✅ صياغة السبب
    final_reason = f"{reason or 'لا يوجد سبب محدد'} - بواسطة {interaction.user}"

    try:
        await member.kick(reason=final_reason)
        await interaction.response.send_message(f"✅ تم طرد {member.mention} من السيرفر.", ephemeral=False)
    except Exception as e:
        print(f"[⚠️] خطأ أثناء الطرد: {e}")
        await interaction.response.send_message("⚠️ حدث خطأ أثناء محاولة الطرد. تأكد من أن رتبتي أعلى من العضو.", ephemeral=True)

                      
@bot.tree.command(name="lock", description=" قفل الروم الحالي (يمنع الجميع من الكتابة)")
async def lock(interaction: discord.Interaction):
    # ✅ تحقق من صلاحية إدارة القنوات
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ لا تمتلك صلاحية لقفل الروم.", ephemeral=True)
        return

    await interaction.response.defer()  # إظهار أن البوت يعالج الطلب

    try:
        # ✅ منع everyone من إرسال الرسائل
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            send_messages=False
        )

        await interaction.followup.send(f"🔒 تم قفل {interaction.channel.mention} بنجاح.")
    except Exception as e:
        print(f"[❌ خطأ في أمر lock]: {e}")
        await interaction.followup.send("⚠️ حدث خطأ أثناء محاولة قفل الروم. تأكد من صلاحياتي.", ephemeral=True)
        
@bot.tree.command(name="mute", description="اعطاء ميوت لشخص أو إزالته")
@app_commands.describe(
    member="الشخص الذي تريد إعطاءه أو إزالة الميوت",
    give_or_remove="اختر: إعطاء أو إزالة"
)
@app_commands.choices(give_or_remove=[
    app_commands.Choice(name="Give", value="Give"),
    app_commands.Choice(name="Remove", value="Remove"),
])
async def mute_command(
    interaction: discord.Interaction,
    member: discord.Member,
    give_or_remove: app_commands.Choice[str]
):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ لا تمتلك صلاحية إدارة الرتب.", ephemeral=True)

    await interaction.response.defer(ephemeral=False)

    guild = interaction.guild
    role = discord.utils.get(guild.roles, name="Muted")

    # ✅ إنشاء رتبة Muted إذا لم تكن موجودة
    if not role:
        try:
            role = await guild.create_role(name="Muted", permissions=discord.Permissions.none(), reason="لأغراض الميوت")
            # منع إرسال الرسائل في كل الرومات النصية
            for channel in guild.text_channels:
                try:
                    await channel.set_permissions(role, send_messages=False)
                except Exception as e:
                    print(f"[⚠️] لم أتمكن من ضبط الصلاحيات في {channel.name}: {e}")
        except Exception as e:
            return await interaction.followup.send("❌ فشل إنشاء رتبة Muted. تحقق من صلاحيات البوت.", ephemeral=True)

    # ✅ تنفيذ الإجراء المطلوب
    if give_or_remove.value == "Give":
        try:
            await member.add_roles(role, reason=f"Muted by {interaction.user}")
            return await interaction.followup.send(f"🔇 تم إعطاء الميوت لـ {member.mention}")
        except:
            return await interaction.followup.send("❌ فشل إعطاء الرتبة. تحقق من صلاحيات البوت والرتب.", ephemeral=True)

    elif give_or_remove.value == "Remove":
        if role not in member.roles:
            return await interaction.followup.send("⚠️ هذا الشخص لا يمتلك ميوت.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Unmuted by {interaction.user}")
            return await interaction.followup.send(f"🔊 تم إزالة الميوت من {member.mention}")
        except:
            return await interaction.followup.send("❌ فشل إزالة الرتبة. تحقق من صلاحيات البوت والرتب.", ephemeral=True)                                                                                                                                                                                      
@bot.tree.command(name="role", description="إعطاء رتبة لشخص أو إزالتها")
@app_commands.describe(
    member="الشخص الذي تريد إعطاءه أو إزالة الرتبة",
    role="الرتبة المستهدفة",
    give_or_remove="هل تريد الإعطاء أم الإزالة؟"
)
@app_commands.choices(give_or_remove=[
    app_commands.Choice(name="Give", value="Give"),
    app_commands.Choice(name="Remove", value="Remove"),
])
async def role_command(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role,
    give_or_remove: app_commands.Choice[str]
):
    # ✅ تحقق من صلاحيات المستخدم
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ لا تمتلك صلاحية إدارة الرتب.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    # ✅ تحقق من أن البوت لديه صلاحية التحكم في الرتبة
    bot_member = interaction.guild.me
    if role >= bot_member.top_role:
        return await interaction.followup.send("⚠️ لا يمكنني التحكم بهذه الرتبة. تأكد من أن رتبة البوت أعلى منها.", ephemeral=True)

    try:
        if give_or_remove.value == "Give":
            await member.add_roles(role, reason=f"By {interaction.user}")
            return await interaction.followup.send(f"✅ تم إعطاء الرتبة {role.mention} إلى {member.mention}")

        elif give_or_remove.value == "Remove":
            if role not in member.roles:
                return await interaction.followup.send("⚠️ هذا الشخص لا يمتلك هذه الرتبة.", ephemeral=True)

            await member.remove_roles(role, reason=f"By {interaction.user}")
            return await interaction.followup.send(f"✅ تم إزالة الرتبة {role.mention} من {member.mention}")

    except Exception as e:
        print(f"[❌ خطأ أثناء تعديل الرتب]: {e}")
        return await interaction.followup.send("⚠️ حدث خطأ أثناء تعديل الرتبة. تحقق من الصلاحيات.", ephemeral=True)
        
@bot.tree.command(name="unlock", description=" فتح الروم الحالي (السماح للجميع بالكتابة)")
async def unlock(interaction: discord.Interaction):
    # ✅ التحقق من صلاحيات العضو
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ لا تمتلك صلاحية لفتح الروم.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        # ✅ تعديل صلاحيات everyone للسماح بالكتابة
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            send_messages=True
        )

        await interaction.followup.send(f"🔓 تم فتح {interaction.channel.mention} بنجاح.")
    except Exception as e:
        print(f"[⚠️ خطأ أثناء فتح الروم]: {e}")
        await interaction.followup.send("⚠️ حدث خطأ أثناء محاولة فتح الروم. تأكد من صلاحياتي.", ephemeral=True)
        
@bot.tree.command(name="timeout", description=" إعطاء تايم أوت لعضو أو إزالته")
@app_commands.describe(
    member="الشخص الذي تريد إعطاؤه التايم أوت",
    time="المدة بالدقائق (ضع 0 لإزالة التايم أوت)",
    reason="السبب (اختياري)"
)
async def timeout(
    interaction: discord.Interaction,
    member: discord.Member,
    time: int,
    reason: Optional[str] = "No reason"
):
    # ✅ التحقق من صلاحيات المستخدم
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("❌ لا تمتلك صلاحية لإدارة السيرفر.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    try:
        if time == 0:
            await member.edit(timed_out_until=None, reason=f"Timeout removed by {interaction.user} | {reason}")
            return await interaction.followup.send(f"✅ تم إزالة التايم أوت من {member.mention}")
        else:
            timeout_duration = datetime.utcnow() + timedelta(minutes=time)
            await member.edit(timed_out_until=timeout_duration, reason=f"By {interaction.user} | {reason}")
            return await interaction.followup.send(f"⏳ تم إعطاء {member.mention} تايم أوت لمدة `{time}` دقيقة.")
    except Exception as e:
        print(f"[❌ Timeout Error] {e}")
        return await interaction.followup.send("⚠️ حدث خطأ أثناء إعطاء التايم أوت. تأكد من صلاحياتي وترتيب الرتب.", ephemeral=True)
                                                                                                    
# ==================================
# 🕌 نظام الأذكار الاحترافي (SQLite & Fast Caching)
# ==================================

# كاش لتخزين الأذكار في الرام لسرعة الوصول
ADHKAR_CACHE = []

def load_adhkar():
    """تحميل الأذكار من الملف مرة واحدة فقط لتسريع الأداء"""
    global ADHKAR_CACHE
    if ADHKAR_CACHE: return ADHKAR_CACHE
    try:
        with open("adhkar.txt", "r", encoding="utf-8") as f:
            ADHKAR_CACHE = [line.strip() for line in f if line.strip()]
            return ADHKAR_CACHE
    except Exception as e:
        print(f"⚠️ فشل تحميل الأذكار: {e}")
        return []

adhkar_emojis = [
    "📿", "🌸", "💫", "🌿", "🌙", "🕋", "🌼", "🌺", 
    "🌹", "⭐", "☘️", "🌻", "🍃", "🌷", "🌟", "🕌", "🕊️"
]

# ----------------------------------
# ✅ أمر الأذكار المدمج (تشغيل / إيقاف)
# ----------------------------------
@bot.tree.command(name="adhkar", description="إعداد وتشغيل أو إيقاف الأذكار التلقائية")
@app_commands.describe(
    action="اختر تشغيل أو إيقاف نظام الأذكار",
    channel="القناة (مطلوبة عند التشغيل فقط)",
    interval="المدة الزمنية بين كل ذكر والتاني"
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="✅ تشغيل / تحديث", value="enable"),
        app_commands.Choice(name="🛑 إيقاف النظام", value="disable")
    ],
    interval=[
        app_commands.Choice(name="🕐 نصف ساعة", value=30),
        app_commands.Choice(name="🕒 ساعة", value=60),
        app_commands.Choice(name="📅 24 ساعة", value=1440),
    ]
)
async def adhkar_command(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    channel: Optional[discord.TextChannel] = None,
    interval: Optional[app_commands.Choice[int]] = None
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ هذا الأمر مخصص للإدارة فقط.", ephemeral=True)

    gid = str(interaction.guild.id)

    # --- حالة الإيقاف ---
    if action.value == "disable":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO server_settings (guild_id) VALUES (?)", (gid,))
            await db.execute("UPDATE server_settings SET adhkar_enabled = 0 WHERE guild_id = ?", (gid,))
            await db.commit()
        return await interaction.response.send_message("🛑 تم إيقاف نظام الأذكار في السيرفر.", ephemeral=True)

    # --- حالة التشغيل ---
    if not channel:
        return await interaction.response.send_message("⚠️ يجب تحديد القناة لتفعيل النظام.", ephemeral=True)

    minutes = interval.value if interval else 60
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO server_settings (guild_id) VALUES (?)", (gid,))
        await db.execute("""
            UPDATE server_settings 
            SET adhkar_enabled = 1, adhkar_channel = ?, adhkar_interval = ? 
            WHERE guild_id = ?
        """, (str(channel.id), minutes, gid))
        await db.commit()

    label = {30: "نصف ساعة", 60: "ساعة", 1440: "24 ساعة"}.get(minutes, f"{minutes} دقيقة")
    await interaction.response.send_message(
        f"✅ تم تفعيل الأذكار في {channel.mention} كل **{label}**.",
        ephemeral=True
    )

# ----------------------------------
# 🔄 التاسك التلقائي (نسخة خفيفة على الموارد)
# ----------------------------------
@tasks.loop(minutes=10)  # ✅ فحص كل 10 دقائق بدل 5 لتقليل عدد عمليات القراءة من القاعدة
async def auto_adhkar_loop():
    now_ts = int(time.time())
    adhkar_list = load_adhkar()
    if not adhkar_list:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM server_settings WHERE adhkar_enabled = 1") as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return

    updates = []  # ✅ تجميع التحديثات لعمل commit واحد بس في الآخر بدل اتصال لكل سيرفر

    for row in rows:
        gid = row["guild_id"]
        interval_sec = (row["adhkar_interval"] or 60) * 60
        last_sent = row["adhkar_last_sent"] or 0

        if now_ts - last_sent < interval_sec:
            continue

        if not row["adhkar_channel"]:
            continue

        channel = bot.get_channel(int(row["adhkar_channel"]))
        if not channel:
            continue

        try:
            text = random.choice(adhkar_list)
            emoji = random.choice(adhkar_emojis)
            await channel.send(f"{emoji} **{{ {text} }}**")
            updates.append((now_ts, gid))
            await asyncio.sleep(0.5)  # ✅ تجنب ضرب rate limit عند وجود عدد كبير من السيرفرات في نفس اللحظة
        except discord.HTTPException:
            continue
        except Exception:
            continue

    # ✅ اتصال واحد فقط لتحديث كل السيرفرات التي تم الإرسال لها
    if updates:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executemany(
                "UPDATE server_settings SET adhkar_last_sent = ? WHERE guild_id = ?",
                updates
            )
            await db.commit()
                                                                            
                                        
         
@bot.tree.command(name="id", description="اعرف معلوماتك أو معلومات عضو آخر داخل السيرفر")
@app_commands.describe(member="اختر العضو لمعرفة ملفه (اختياري)")
async def id(interaction: discord.Interaction, member: discord.Member = None):
    # ⚡ تبريد 5 ثواني لتقليل الضغط
    if not await check_cooldown(interaction, "id", 5):
        return

    member = member or interaction.user

    if not member.joined_at:
        return await interaction.response.send_message(
            "❌ لا يمكن تحديد تاريخ دخول هذا العضو.",
            ephemeral=True
        )

    joined_at = member.joined_at.strftime("%Y-%m-%d")
    created_at = member.created_at.strftime("%Y-%m-%d")

    # 🎭 الرتب (مرتبة من الأعلى للأسفل)
    roles = [
        role.mention
        for role in reversed(member.roles)
        if role != interaction.guild.default_role
    ]

    # ⚠️ جلب عدد التحذيرات من قاعدة البيانات الجديدة
    db = await get_db()
    async with db.execute("""
        SELECT COUNT(*)
        FROM warnings
        WHERE guild_id = ? AND user_id = ?
    """, (
        str(interaction.guild.id),
        str(member.id)
    )) as cursor:
        row = await cursor.fetchone()

    warnings_count = row[0] if row else 0

    # 📅 مدة البقاء في السيرفر
    delta = discord.utils.utcnow() - member.joined_at
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60

    embed = discord.Embed(
        title=f"🪪 ملف العضو — {member.display_name}",
        color=discord.Color.blue()
    )

    embed.add_field(name="👤 العضو", value=member.mention, inline=True)
    embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
    embed.add_field(name="🤖 بوت", value="نعم" if member.bot else "لا", inline=True)

    embed.add_field(name="📅 تاريخ إنشاء الحساب", value=created_at, inline=True)
    embed.add_field(name="📥 تاريخ الدخول للسيرفر", value=joined_at, inline=True)
    embed.add_field(
        name="⏳ مدة البقاء في السيرفر",
        value=f"**{days} يوم، {hours} ساعة، و {minutes} دقيقة**",
        inline=False
    )

    embed.add_field(name="⚠️ التحذيرات", value=str(warnings_count), inline=True)

    # 🎭 الرتب
    if roles:
        roles_text = ", ".join(roles)
        if len(roles_text) <= 1024:
            embed.add_field(name="🎭 الرتب", value=roles_text, inline=False)
        else:
            chunks = [roles_text[i:i + 1024] for i in range(0, len(roles_text), 1024)]
            for idx, chunk in enumerate(chunks, start=1):
                embed.add_field(name=f"🎭 الرتب (جزء {idx})", value=chunk, inline=False)
    else:
        embed.add_field(name="🎭 الرتب", value="لا توجد", inline=False)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)
    
@bot.command(name="iid")
async def id(ctx: commands.Context, member: discord.Member = None):
    if not await check_cooldown(ctx, "id", 5):
        return

    member = member or ctx.author

    if not member.joined_at:
        return await ctx.send("❌ لا يمكن تحديد تاريخ دخول هذا العضو.")

    joined_at = member.joined_at.strftime("%Y-%m-%d")
    created_at = member.created_at.strftime("%Y-%m-%d")

    roles = [
        role.mention
        for role in reversed(member.roles)
        if role != ctx.guild.default_role
    ]

    db = await get_db()
    async with db.execute("""
        SELECT COUNT(*)
        FROM warnings
        WHERE guild_id = ? AND user_id = ?
    """, (
        str(ctx.guild.id),
        str(member.id)
    )) as cursor:
        row = await cursor.fetchone()

    warnings_count = row[0] if row else 0

    delta = discord.utils.utcnow() - member.joined_at
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60

    embed = discord.Embed(
        title=f"🪪 ملف العضو — {member.display_name}",
        color=discord.Color.blue()
    )

    embed.add_field(name="👤 العضو", value=member.mention, inline=True)
    embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
    embed.add_field(name="🤖 بوت", value="نعم" if member.bot else "لا", inline=True)

    embed.add_field(name="📅 تاريخ إنشاء الحساب", value=created_at, inline=True)
    embed.add_field(name="📥 تاريخ الدخول للسيرفر", value=joined_at, inline=True)
    embed.add_field(
        name="⏳ مدة البقاء في السيرفر",
        value=f"**{days} يوم، {hours} ساعة، و {minutes} دقيقة**",
        inline=False
    )

    embed.add_field(name="⚠️ التحذيرات", value=str(warnings_count), inline=True)

    if roles:
        roles_text = ", ".join(roles)
        if len(roles_text) <= 1024:
            embed.add_field(name="🎭 الرتب", value=roles_text, inline=False)
        else:
            chunks = [roles_text[i:i + 1024] for i in range(0, len(roles_text), 1024)]
            for idx, chunk in enumerate(chunks, start=1):
                embed.add_field(name=f"🎭 الرتب (جزء {idx})", value=chunk, inline=False)
    else:
        embed.add_field(name="🎭 الرتب", value="لا توجد", inline=False)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")

    await ctx.reply(
    embed=embed,
    mention_author=False
)
                            
@bot.tree.command(
    name="avatar_member",
    description="عرض الصورة الشخصية بالحجم الكامل"
)
@app_commands.describe(العضو="العضو الذي تريد صورته")
async def صورة_عضو(interaction: discord.Interaction, العضو: discord.Member):

    # حماية DM
    if not interaction.guild:
        return await interaction.response.send_message("❌ هذا الأمر يعمل داخل السيرفر فقط.", ephemeral=True)

    # cooldown
    if not await check_cooldown(interaction, "avatar_member", 4):
        return

    # defer لمنع not responding
    await interaction.response.defer()

    embed = discord.Embed(
        title=f"صورة {العضو.display_name}",
        color=discord.Color.random()
    )
    embed.set_image(url=العضو.display_avatar.url)

    await interaction.followup.send(embed=embed)
                    

@bot.tree.command(
    name="opinion",
    description="اعطي حكم عشوائي على العضو"
)
@app_commands.describe(العضو="العضو الذي تريد الحكم عليه")
async def احكم_عليه(interaction: discord.Interaction, العضو: discord.Member):
    # ⚡ التحقق من التبريد (3 ثواني)
    if not await check_cooldown(interaction, "opinion", 3):
        return

    judgments = [
        "شخص دايم نايم 😴",
        "دايم أول واحد يكتب في القيف أواي 🎁",
        "يحب المشاكل بس طيب ❤️",
        "لو في مشكلة أكيد هو داخل فيها 😂",
        "فخم بس ما يتكلم 🗿",
        "أسطورة ما تحتاج تعريف 🔥",
        "ينسى الرومات اللي يدخلها 🤦",
        "يضحك بدون سبب 😂",
        "ملك الإيموجيات 👑",
        "دايم ينسى الميوت شغال 🎙️",
        "كلمه السر دايم عنده 🍪",
        "يدخل الروم ويطلع بدون سبب 🚪",
        "يجمع الكوينز كأنه بنك 💰",
        "يسرق الميمز وينشرها كأنها له 📸",
        "دايم يكتب 'هههه' بدون ما يضحك 😐",
        "المتحدث الرسمي للسيرفر 🎤",
        "يدخل يتفرج وما يشارك 👀",
        "كل شوي يغير صورته 🖼️",
        "أكثر واحد يسوي رياكشن غلط 😂",
        "عنده ألف لقب بس ولا واحد رسمي 🏷️",
        "يكتب جمل طويلة ما حد يقراها 📜",
        "دايم في الميوت وكأنه شخصية سرية 🕵️",
        "لو كان في لعبة دايم يخسر أول واحد 🎮",
        "دايم يدخل وقت النوم ⏳",
        "أفضل شخص في توزيع النكات البايخة 😅",
        "لو في جائزة أكثر شخص يرسل 'ههه' يفوز 🏆",
        "دايم يكتب نفس الكلمة مرتين ✌️",
        "يدخل الروم الصوتي ويكتم الكل 🔇",
        "أكثر شخص يسوي سبام 😂",
        "ملك الفواصل والنقاط ... ..."
    ]

    حكم = random.choice(judgments)

    embed = discord.Embed(
        title="😂 حكم عشوائي",
        description=f"**{العضو.mention}** — {حكم}",
        color=discord.Color.random()
    )
    embed.set_thumbnail(url=العضو.display_avatar.url)
    embed.set_footer(text=f"طلب بواسطة {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)
        
# ===============================
# 🏦 GLOBAL BANK SYSTEM
# ===============================

def draw_arabic_text(draw, position, text, font, fill="white"):
    x, y = position
    draw.text((x, y), text, font=font, fill=fill)


def shorten_number(num):
    num = float(num)

    if num >= 1_000_000_000:
        return f"{num/1_000_000_000:.2f}B".rstrip("0").rstrip(".")

    elif num >= 1_000_000:
        return f"{num/1_000_000:.2f}M".rstrip("0").rstrip(".")

    elif num >= 1_000:
        return f"{num/1_000:.2f}K".rstrip("0").rstrip(".")

    return str(int(num)) if num.is_integer() else str(num)


def flip_english_name(name):
    return " ".join(reversed(name.split())) if all(ord(c) < 128 for c in name) else name


# ===============================
# 🏦 GLOBAL BANK SYSTEM
# ===============================

async def generate_bank_card(interaction: discord.Interaction, uid: str):

    user = interaction.user

    # ✅ GLOBAL USER — ensure_global_user بدل ensure_user
    user_data = await ensure_global_user(uid)

    balance = user_data.get("kento", 0)
    deposit = user_data.get("deposit", 0)

    # ✅ استخدام get_db() بدل connection جديد
    db = await get_db()
    async with db.execute("SELECT SUM(deposit) FROM global_users") as cursor:
        row = await cursor.fetchone()
        total_deposits = row[0] or 0

    # =========================================
    # BACKGROUND
    # =========================================
    try:
        bg = Image.open("amroi/bank_bg.png").convert("RGBA")
    except Exception:
        bg = Image.new("RGBA", (1000, 600), (20, 20, 25, 255))

    draw = ImageDraw.Draw(bg)
    W, H = bg.size

    font_main = ImageFont.truetype("Roboto-Regular.ttf", 48)
    font_small = ImageFont.truetype("Roboto-Regular.ttf", 38)
    font_large = ImageFont.truetype("Roboto-Regular.ttf", 58)

    display_name = flip_english_name(user.name)

    # =========================================
    # AVATAR
    # =========================================
    avatar_url = user.avatar.url if user.avatar else user.default_avatar.url

    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as response:
            avatar_bytes = await response.read()

    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    avatar = ImageOps.fit(avatar, (100, 100), method=Image.LANCZOS)

    mask = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 100, 100), fill=255)
    avatar.putalpha(mask)
    bg.paste(avatar, (30, 30), avatar)

    # =========================================
    # TEXT
    # =========================================
    data_x = 160
    data_y = int(H * 0.05)
    spacing = 70

    draw_arabic_text(draw, (data_x, data_y), f"Name: {display_name}", font_main, "#00ffff")
    data_y += spacing

    draw_arabic_text(draw, (data_x, data_y), f"User ID: {uid}", font_small, "#ffcc00")
    data_y += spacing

    # Account Number
    reversed_uid = uid[::-1]
    acc_num = " ".join([reversed_uid[i:i + 4] for i in range(0, len(reversed_uid), 4)])
    acc_x = (W - font_large.getlength(acc_num)) // 2
    draw.text((acc_x, data_y), acc_num, font=font_large, fill="#00ff66")
    data_y += spacing + 20

    draw_arabic_text(
        draw,
        (data_x - 130, data_y),
        f"Balance: {shorten_number(balance)}",
        font_main,
        "#FFD700"
    )
    data_y += spacing

    draw_arabic_text(
        draw,
        (data_x - 130, data_y),
        f"Deposit: {shorten_number(deposit)}",
        font_main,
        "#FF69B4"
    )
    data_y += spacing

    draw_arabic_text(
        draw,
        (data_x - 130, data_y),
        f"GLOBAL BANK SYSTEM",
        font_main,
        "#00BFFF"
    )

    # =========================================
    # QR CODE
    # =========================================
    qr = qrcode.QRCode(border=1, box_size=3)
    qr.add_data(f"https://discord.com/users/{uid}")
    qr.make(fit=True)

    qr_img = qr.make_image(fill="black", back="white").convert("RGBA")
    bg.paste(qr_img, (W - qr_img.width - 30, H - qr_img.height - 30), qr_img)

    buffer = io.BytesIO()
    bg.save(buffer, "PNG")
    buffer.seek(0)

    return discord.File(buffer, filename="bank_card.png")


# --------------------------------------------------------
# 💰 Modal لعمليات الإيداع والسحب (SQLite GLOBAL)
# --------------------------------------------------------

class InputAmountModal(discord.ui.Modal):
    def __init__(self, mode: str, uid: str):
        super().__init__(title="💰 Deposit" if mode == "deposit" else "🏧 Withdraw")
        self.mode = mode
        self.uid = uid

        self.amount = discord.ui.TextInput(
            label="Amount",
            placeholder="Enter amount",
            required=True
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value)
        except:
            return await interaction.response.send_message(
                "❌ رقم غير صحيح",
                ephemeral=True
            )

        if amount <= 0:
            return await interaction.response.send_message(
                "❌ المبلغ لازم يكون أكبر من 0",
                ephemeral=True
            )

        # ==============================
        # ✅ GLOBAL USER SAFE FETCH
        # ==============================
        user = await ensure_global_user(self.uid)

        # حماية من None أو ناقص keys
        if not user:
            return await interaction.response.send_message(
                "❌ لم يتم العثور على الحساب",
                ephemeral=True
            )

        kento = user.get("kento", 0)
        deposit = user.get("deposit", 0)

        async with aiosqlite.connect(DB_PATH) as db:

            if self.mode == "deposit":

                if kento < amount:
                    return await interaction.response.send_message(
                        "❌ رصيد غير كافي",
                        ephemeral=True
                    )

                await db.execute("""
                    UPDATE global_users
                    SET kento = kento - ?,
                        deposit = deposit + ?
                    WHERE user_id = ?
                """, (amount, amount, self.uid))

                msg = f"✅ Deposit {amount}"

            else:

                if deposit < amount:
                    return await interaction.response.send_message(
                        "❌ لا يوجد رصيد",
                        ephemeral=True
                    )

                await db.execute("""
                    UPDATE global_users
                    SET deposit = deposit - ?,
                        kento = kento + ?
                    WHERE user_id = ?
                """, (amount, amount, self.uid))

                msg = f"✅ Withdraw {amount}"

            await db.commit()

        await interaction.response.send_message(msg, ephemeral=True)
        
class BankButtons(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=None)
        self.uid = uid

    async def interaction_check(self, interaction: discord.Interaction):
        return str(interaction.user.id) == self.uid

    @discord.ui.button(label="Deposit", style=discord.ButtonStyle.green)
    async def deposit(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(
            InputAmountModal("deposit", self.uid)
        )

    @discord.ui.button(label="Withdraw", style=discord.ButtonStyle.red)
    async def withdraw(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(
            InputAmountModal("withdraw", self.uid)
        )

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.blurple)
    async def refresh(self, interaction: discord.Interaction, _):
        await interaction.response.defer()

        file = await generate_bank_card(interaction, self.uid)

        await interaction.message.edit(
            attachments=[file],
            view=BankButtons(self.uid)
        )

    @discord.ui.button(label="Wallet ID", style=discord.ButtonStyle.gray)
    async def wallet(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            f"`{self.uid[::-1]}`",
            ephemeral=True
        )


# ========================================================
# 📲 Show Bank Command (SQLite GLOBAL Version)
# ========================================================

@bot.tree.command(
    name="bank",
    description="🏦 عرض بطاقتك البنكية العالمية وإدارة الإيداع والسحب"
)
async def bank(interaction: discord.Interaction):

    if not await check_cooldown(interaction, "bank", 20):
        return

    await interaction.response.defer()

    uid = str(interaction.user.id)

    # ✅ إنشاء / جلب المستخدم بشكل GLOBAL
    await ensure_user(uid, "global")

    file = await generate_bank_card(interaction, uid)

    await interaction.followup.send(
        file=file,
        view=BankButtons(uid)
    )
                                               
@bot.command(name="توب")
async def top_kentos(ctx):

    if not await check_cooldown(ctx, "top_kentos", 20):
        return

    async with ctx.typing():

        def format_kento(kento):
            kento = int(kento or 0)
            if kento >= 1_000_000_000: return f"{kento / 1_000_000_000:.2f}b"
            if kento >= 1_000_000:     return f"{kento / 1_000_000:.2f}m"
            if kento >= 1_000:         return f"{kento / 1_000:.2f}k"
            return str(kento)

        top_users        = []
        user_id          = str(ctx.author.id)
        user_rank        = None
        user_kento_total = 0

        db = await get_db()

        async with db.execute("""
            SELECT user_id, kento
            FROM global_users
            ORDER BY kento DESC
            LIMIT 10
        """) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                top_users.append((str(row[0]), int(row[1] or 0)))

        async with db.execute("""
            SELECT kento FROM global_users WHERE user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                user_kento_total = int(row[0] or 0)

                async with db.execute("""
                    SELECT COUNT(*) + 1
                    FROM global_users
                    WHERE kento > (
                        SELECT kento FROM global_users WHERE user_id = ?
                    )
                """, (user_id,)) as rc:
                    r = await rc.fetchone()
                    user_rank = r[0] if r is not None else None

        top_ids     = [uid for uid, _ in top_users]
        user_in_top = user_id in top_ids

        scale   = 2
        base_w  = 720
        spacing = 90 * scale
        y_start = 110 * scale
        base_h  = 1080
        w, h    = base_w * scale, base_h * scale

        try:
            bg_path = os.path.join(os.path.dirname(__file__), "amroi", "background.png")
            bg = Image.open(bg_path).convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        except Exception as e:
            return await ctx.send(f"❌ الخلفية غير موجودة: {e}")

        draw = ImageDraw.Draw(bg)

        font_title   = ImageFont.truetype("arabic.ttf",         52 * scale)
        font_english = ImageFont.truetype("Roboto-Regular.ttf", 30 * scale)
        font_number  = ImageFont.truetype("Roboto-Regular.ttf", 26 * scale)

        draw.text((w // 2, 40 * scale), "RICH KHENTOS", font=font_title, fill="gold", anchor="mm")

        box_colors = {0: "#FFD700", 1: "#C0C0C0", 2: "#CD7F32"}

        async with aiohttp.ClientSession() as session:

            for i, (uid, kento_val) in enumerate(top_users):

                try:
                    user  = bot.get_user(int(uid)) or await bot.fetch_user(int(uid))
                    name  = user.name

                    y           = y_start + i * spacing
                    x_offset    = 30 * scale
                    rect_width  = 700 * scale - x_offset
                    rect_height = 70 * scale

                    if i >= 3:
                        gradient = Image.new("RGBA", (rect_width, rect_height), (0, 0, 0, 0))
                        gd = ImageDraw.Draw(gradient)
                        for x in range(rect_width):
                            gray = int(60 + (x / rect_width) * 80)
                            gd.line([(x, 0), (x, rect_height)], fill=(gray, gray, gray, 255))
                        mask = Image.new("L", (rect_width, rect_height), 0)
                        ImageDraw.Draw(mask).rounded_rectangle(
                            [0, 0, rect_width, rect_height], radius=25 * scale, fill=255
                        )
                        bg.paste(gradient, (x_offset, y), mask)
                    else:
                        base_color = ImageColor.getrgb(box_colors.get(i, "#1e1e1e"))
                        darkened   = tuple(int(c * 0.8) for c in base_color)
                        draw.rounded_rectangle(
                            [(x_offset, y), (700 * scale, y + rect_height)],
                            radius=25 * scale,
                            fill=darkened + (255,)
                        )

                    circle_radius = 22 * scale
                    circle_x      = x_offset + 10 * scale
                    circle_y      = y + 12 * scale
                    draw.ellipse(
                        [(circle_x, circle_y),
                         (circle_x + 2 * circle_radius, circle_y + 2 * circle_radius)],
                        fill=box_colors.get(i, "white"),
                        outline="black",
                        width=2 * scale
                    )
                    draw.text(
                        (circle_x + circle_radius, circle_y + circle_radius),
                        str(i + 1),
                        font=font_number, fill="black", anchor="mm"
                    )

                    avatar_x = circle_x + 2 * circle_radius + 10 * scale
                    avatar_y = y + 10 * scale
                    async with session.get(user.display_avatar.replace(format="png", size=512).url) as resp:
                        avatar_bytes = await resp.read()
                    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
                    avatar = avatar.resize((50 * scale, 50 * scale), Image.Resampling.LANCZOS)
                    av_mask = Image.new("L", avatar.size, 0)
                    ImageDraw.Draw(av_mask).ellipse((0, 0) + avatar.size, fill=255)
                    avatar.putalpha(av_mask)
                    bg.paste(avatar, (int(avatar_x), int(avatar_y)), avatar)

                    name_x = avatar_x + 60 * scale
                    name_y = y + 25 * scale
                    draw.text((name_x, name_y), name,
                              font=font_english, fill="white",  anchor="lm")
                    draw.text((680 * scale, name_y), format_kento(kento_val),
                              font=font_english, fill="yellow", anchor="rm")

                except Exception as e:
                    print(f"[TOP ERROR] {e}")
                    continue

            # ===== USER RANK =====
            if user_rank is not None and not user_in_top:

                y_base = y_start + len(top_users) * spacing
                y      = int(y_base * 0.99)

                draw.rounded_rectangle(
                    [(20 * scale, y), (700 * scale, y + 70 * scale)],
                    radius=25 * scale,
                    fill=(80, 0, 0, 220)
                )

                self_user = bot.get_user(int(user_id)) or await ctx.bot.fetch_user(int(user_id))

                # ✅ حساب عرض الرقم عشان الصورة والاسم يتزحزحوا معاه
                rank_text  = f"#{user_rank}"
                rank_bbox  = font_english.getbbox(rank_text)
                rank_width = rank_bbox[2] - rank_bbox[0]

                rank_x         = 40 * scale
                avatar_start_x = rank_x + rank_width + 15 * scale
                name_start_x   = avatar_start_x + 55 * scale + 10 * scale

                # ===== AVATAR للعضو =====
                try:
                    async with session.get(self_user.display_avatar.replace(format="png", size=512).url) as resp:
                        av_bytes = await resp.read()
                    av = Image.open(BytesIO(av_bytes)).convert("RGBA")
                    av = av.resize((50 * scale, 50 * scale), Image.Resampling.LANCZOS)
                    av_m = Image.new("L", av.size, 0)
                    ImageDraw.Draw(av_m).ellipse((0, 0) + av.size, fill=255)
                    av.putalpha(av_m)
                    bg.paste(av, (int(avatar_start_x), int(y + 10 * scale)), av)
                except Exception:
                    pass

                draw.text(
                    (rank_x, y + 35 * scale),
                    rank_text,
                    font=font_english, fill="white", anchor="lm"
                )
                draw.text(
                    (name_start_x, y + 35 * scale),
                    self_user.name,
                    font=font_english, fill="white", anchor="lm"
                )
                draw.text(
                    (680 * scale, y + 35 * scale),
                    format_kento(user_kento_total),
                    font=font_english, fill="yellow", anchor="rm"
                )

        with BytesIO() as image_binary:
            bg.save(image_binary, "PNG")
            image_binary.seek(0)
            await ctx.reply(
    file=discord.File(fp=image_binary, filename="top_kento.png"),
    mention_author=False
)
            
                                                                                                                                    
@bot.tree.command(name="log_deleted", description="إرسال الرسائل المحذوفة إلى روم لوج (إعدادات SQLite)")
@app_commands.describe(
    الروم="الروم الذي سترسل فيه رسائل الحذف",
    تفعيل="هل تريد تشغيل أو إيقاف الميزة؟"
)
@app_commands.choices(
    تفعيل=[
        app_commands.Choice(name="✅ تشغيل", value="on"),
        app_commands.Choice(name="🛑 إيقاف", value="off")
    ]
)
async def سجل_الحذف(
    interaction: discord.Interaction,
    الروم: discord.TextChannel = None,
    تفعيل: app_commands.Choice[str] = None
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ هذا الأمر مخصص فقط للإدارة.", ephemeral=True)
        return

    if not تفعيل:
        await interaction.response.send_message("⚠️ يجب اختيار تشغيل أو إيقاف.", ephemeral=True)
        return

    gid = str(interaction.guild.id)
    
    # 1. جلب الإعدادات الحالية من SQLite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT settings FROM server_settings WHERE guild_id = ?", (gid,)) as cursor:
            row = await cursor.fetchone()
            if row and row["settings"]:
                current_settings = json.loads(row["settings"])
            else:
                current_settings = {}

    # 2. تحديث الإعدادات
    if تفعيل.value == "on":
        if not الروم:
            await interaction.response.send_message("⚠️ يجب تحديد الروم عند التشغيل!", ephemeral=True)
            return
            
        current_settings["deleted_log"] = {
            "enabled": True,
            "channel_id": str(الروم.id)
        }
        msg = f"✅ تم تفعيل سجل الحذف في {الروم.mention}"
    else:
        current_settings.pop("deleted_log", None)
        msg = "🛑 تم إيقاف سجل الحذف بنجاح."

    # 3. حفظ التغييرات
    async with aiosqlite.connect(DB_PATH) as db:
        settings_json = json.dumps(current_settings)
        await db.execute(
            "INSERT INTO server_settings (guild_id, settings) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET settings = ?",
            (gid, settings_json, settings_json)
        )
        await db.commit()

    # 4. تحديث الكاش
    server_settings_cache[gid] = current_settings

    await interaction.response.send_message(msg, ephemeral=True)
                                                                                                                                                                                                                                            
# 🗑️ أمر حذف قناة أو رتبة مع تأكيد
@bot.tree.command(
    name="remove_one",
    description="حذف قناة أو رتبة واحدة مع تأكيد"
)
@app_commands.describe(
    النوع="اختار هل تريد حذف قناة أو رتبة",
    القناة="اختر القناة المراد حذفها (إذا اخترت قناة)",
    الرتبة="اختر الرتبة المراد حذفها (إذا اخترت رتبة)"
)
@app_commands.choices(النوع=[
    app_commands.Choice(name="قناة واحدة", value="channel"),
    app_commands.Choice(name="رتبة واحدة", value="role"),
])
async def remove_one(
    interaction: discord.Interaction,
    النوع: app_commands.Choice[str],
    القناة: discord.TextChannel = None,
    الرتبة: discord.Role = None
):

    # حماية DM
    if not interaction.guild:
        return await interaction.response.send_message("❌ هذا الأمر يعمل داخل السيرفر فقط.", ephemeral=True)

    # cooldown
    if not await check_cooldown(interaction, "remove_one", 3):
        return

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ هذا الأمر مخصص للإدارة فقط.", ephemeral=True
        )

    guild = interaction.guild
    bot_member = guild.me

    target = القناة if النوع.value == "channel" else الرتبة
    if not target:
        return await interaction.response.send_message(
            f"⚠️ يجب تحديد {'القناة' if النوع.value == 'channel' else 'الرتبة'}.", ephemeral=True
        )

    # hierarchy + default role
    if النوع.value == "role":
        if target == guild.default_role or target >= bot_member.top_role or target >= interaction.user.top_role:
            return await interaction.response.send_message("⚠️ لا يمكن حذف هذه الرتبة.", ephemeral=True)

    # صلاحيات البوت
    if النوع.value == "channel" and not guild.me.guild_permissions.manage_channels:
        return await interaction.response.send_message("❌ البوت لا يملك صلاحية حذف القنوات.", ephemeral=True)

    if النوع.value == "role" and not guild.me.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ البوت لا يملك صلاحية حذف الرتب.", ephemeral=True)

    class ConfirmView(View):
        def __init__(self):
            super().__init__(timeout=30)

        async def on_timeout(self):
            for item in self.children:
                item.disabled = True

        @discord.ui.button(label="تأكيد الحذف", style=discord.ButtonStyle.danger)
        async def confirm(self, i: discord.Interaction, button: Button):
            if i.user.id != interaction.user.id:
                return await i.response.send_message("❌ هذا الزر ليس لك.", ephemeral=True)

            try:
                await target.delete()
                await i.response.send_message(
                    f"✅ تم حذف {'القناة' if النوع.value == 'channel' else 'الرتبة'} **{target.name}** بنجاح.",
                    ephemeral=True
                )
            except Exception as e:
                await i.response.send_message(f"❌ فشل الحذف: {e}", ephemeral=True)

            self.stop()

        @discord.ui.button(label="إلغاء العملية", style=discord.ButtonStyle.secondary)
        async def cancel(self, i: discord.Interaction, button: Button):
            if i.user.id != interaction.user.id:
                return await i.response.send_message("❌ هذا الزر ليس لك.", ephemeral=True)

            await i.response.send_message("تم إلغاء العملية.", ephemeral=True)
            self.stop()

    view = ConfirmView()

    await interaction.response.send_message(
        f"⚠️ هل أنت متأكد أنك تريد حذف {'القناة' if النوع.value == 'channel' else 'الرتبة'} **{target.name}**؟",
        view=view,
        ephemeral=True
    )
    
# ================================
# 🎨 نظام الخلفيات (FINAL CLEAN)
# ================================

@bot.tree.command(name="backgrounds", description="🎨 تصفح الخلفيات المجانية وتعيين ما تريد")
async def backgrounds(interaction: discord.Interaction):

    if not interaction.guild:
        return await interaction.response.send_message("❌ الأمر داخل السيرفر فقط", ephemeral=True)

    if not await check_cooldown(interaction, "backgrounds", 10):
        return

    await interaction.response.defer()

    uid = str(interaction.user.id)
    guild_id = str(interaction.guild.id)

    # ✅ النظام الجديد
    await ensure_user(uid, guild_id)

    try:
        الصور = sorted([
            f for f in os.listdir(BACKGROUNDS_PATH)
            if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        ])

        if not الصور:
            return await interaction.followup.send("⚠️ لا توجد خلفيات حالياً.", ephemeral=True)

    except Exception as e:
        return await interaction.followup.send(f"⚠️ خطأ أثناء تحميل الخلفيات: {e}", ephemeral=True)

    await send_background_embed(interaction, 0, الصور, uid, guild_id)


# ================================
async def send_background_embed(interaction, index, الصور, uid, guild_id):

    اسم_الخلفية = الصور[index]
    رقم = os.path.splitext(اسم_الخلفية)[0]
    path = os.path.join(BACKGROUNDS_PATH, اسم_الخلفية)

    if not os.path.exists(path):
        return await interaction.followup.send("⚠️ الخلفية غير موجودة.", ephemeral=True)

    embed = discord.Embed(
        title=f"🎨 الخلفية رقم {رقم}",
        description="🖼️ يمكنك تعيين هذه الخلفية مجاناً عبر الزر بالأسفل.",
        color=discord.Color.blurple()
    )

    embed.set_footer(text=f"{index + 1} من {len(الصور)}")

    file = discord.File(path, filename="bg.png")
    embed.set_image(url="attachment://bg.png")

    view = discord.ui.View(timeout=None)

    view.add_item(discord.ui.Button(
        label="🎯 تعيين",
        style=discord.ButtonStyle.blurple,
        custom_id=f"set:{index}"
    ))

    if index > 0:
        view.add_item(discord.ui.Button(
            label="⬅️ السابق",
            style=discord.ButtonStyle.gray,
            custom_id=f"prev:{index - 1}"
        ))

    if index + 1 < len(الصور):
        view.add_item(discord.ui.Button(
            label="➡️ التالي",
            style=discord.ButtonStyle.gray,
            custom_id=f"next:{index + 1}"
        ))

    if index + 10 < len(الصور):
        view.add_item(discord.ui.Button(
            label="⏭️ تخطي 10",
            style=discord.ButtonStyle.gray,
            custom_id=f"jump:{index + 10}"
        ))

    if index >= 10:
        view.add_item(discord.ui.Button(
            label="⏮️ رجوع 10",
            style=discord.ButtonStyle.gray,
            custom_id=f"jump:{index - 10}"
        ))

    view.add_item(discord.ui.Button(
        label="❌ إغلاق",
        style=discord.ButtonStyle.red,
        custom_id="close"
    ))

    msg = await interaction.followup.send(embed=embed, file=file, view=view)

    الخلفيات_النشطة[msg.id] = {
        "user_id": uid,
        "guild_id": guild_id,
        "images": الصور,
        "index": index,
        "message": msg
    }

    asyncio.create_task(auto_delete_background(msg.id))


# ================================
async def auto_delete_background(msg_id):
    await asyncio.sleep(900)
    data = الخلفيات_النشطة.pop(msg_id, None)
    if data:
        try:
            await data["message"].delete()
        except:
            pass


# ================================
# 🧩 التفاعل مع الأزرار (FIXED GLOBAL SYSTEM)
# ================================
@bot.event
async def on_interaction(interaction: discord.Interaction):

    data = interaction.data or {}
    custom_id = data.get("custom_id")

    if not custom_id or (":" not in custom_id and custom_id != "close"):
        return

    msg_id = interaction.message.id if interaction.message else None
    if msg_id not in الخلفيات_النشطة:
        return

    bg_data = الخلفيات_النشطة[msg_id]

    if bg_data["user_id"] != str(interaction.user.id):
        return await interaction.response.send_message(
            "❌ لا يمكنك التحكم في رسالة غيرك.",
            ephemeral=True
        )

    الصور = bg_data["images"]
    uid = str(interaction.user.id)
    guild_id = bg_data["guild_id"]

    # ====================
    # 🎯 تعيين الخلفية (GLOBAL FIXED)
    # ====================
    if custom_id.startswith("set:"):

        index = int(custom_id.split(":")[1])

        if index < 0 or index >= len(الصور):
            return await interaction.response.send_message(
                "⚠️ الخلفية غير صالحة.",
                ephemeral=True
            )

        اسم_الخلفية = الصور[index]

        async with aiosqlite.connect(DB_PATH) as db:

            # 🔥 مهم: ضمان وجود user في global_users
            await db.execute("""
                INSERT OR IGNORE INTO global_users (user_id)
                VALUES (?)
            """, (uid,))

            # 🔥 تحديث الخلفية GLOBAL بشكل صحيح
            await db.execute("""
                UPDATE global_users
                SET background = ?
                WHERE user_id = ?
            """, (اسم_الخلفية, uid))

            await db.commit()

        return await interaction.response.send_message(
            f"✅ تم تعيين الخلفية رقم `{os.path.splitext(اسم_الخلفية)[0]}` على حسابك العالمي!",
            ephemeral=True
        )

    # ====================
    # 🔄 التنقل
    # ====================
    elif custom_id.startswith(("next:", "prev:", "jump:")):

        try:

            index = int(custom_id.split(":")[1])

            if index < 0:
                index = 0
            elif index >= len(الصور):
                index = len(الصور) - 1

            الخلفيات_النشطة[msg_id]["index"] = index

            path = os.path.join(BACKGROUNDS_PATH, الصور[index])

            embed = discord.Embed(
                title=f"🎨 الخلفية رقم {os.path.splitext(الصور[index])[0]}",
                description="🖼️ يمكنك تعيين هذه الخلفية مجاناً عبر الزر بالأسفل.",
                color=discord.Color.blurple()
            )

            embed.set_footer(text=f"{index + 1} من {len(الصور)}")

            file = discord.File(path, filename="bg.png")
            embed.set_image(url="attachment://bg.png")

            view = discord.ui.View(timeout=None)

            view.add_item(discord.ui.Button(
                label="🎯 تعيين",
                style=discord.ButtonStyle.blurple,
                custom_id=f"set:{index}"
            ))

            if index > 0:
                view.add_item(discord.ui.Button(
                    label="⬅️ السابق",
                    style=discord.ButtonStyle.gray,
                    custom_id=f"prev:{index - 1}"
                ))

            if index + 1 < len(الصور):
                view.add_item(discord.ui.Button(
                    label="➡️ التالي",
                    style=discord.ButtonStyle.gray,
                    custom_id=f"next:{index + 1}"
                ))

            if index + 10 < len(الصور):
                view.add_item(discord.ui.Button(
                    label="⏭️ تخطي 10",
                    style=discord.ButtonStyle.gray,
                    custom_id=f"jump:{index + 10}"
                ))

            if index >= 10:
                view.add_item(discord.ui.Button(
                    label="⏮️ رجوع 10",
                    style=discord.ButtonStyle.gray,
                    custom_id=f"jump:{index - 10}"
                ))

            view.add_item(discord.ui.Button(
                label="❌ إغلاق",
                style=discord.ButtonStyle.red,
                custom_id="close"
            ))

            await interaction.response.edit_message(
                embed=embed,
                attachments=[file],
                view=view
            )

        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ خطأ: {e}",
                ephemeral=True
            )

    # ====================
    # ❌ إغلاق
    # ====================
    elif custom_id == "close":

        الخلفيات_النشطة.pop(msg_id, None)

        try:
            await interaction.message.delete()
        except:
            pass
            
            
       
@bot.tree.command(name="trust", description="🤝 امنح نقطة ثقة لعضو مرة كل 24 ساعة")
@app_commands.describe(member="اختر العضو الذي تثق به")
async def give_trust(interaction: discord.Interaction, member: discord.Member):

    if not await check_cooldown(interaction, "trust", 60):
        return

    await interaction.response.defer()

    giver_id = str(interaction.user.id)
    receiver_id = str(member.id)

    if giver_id == receiver_id:
        return await interaction.followup.send(
            "❌ لا يمكنك منح نقطة ثقة لنفسك!",
            ephemeral=True
        )

    if member.bot:
        return await interaction.followup.send(
            "⚠️ لا يمكنك منح نقطة ثقة لبوت!",
            ephemeral=True
        )

    now = datetime.datetime.utcnow()
    now_iso = now.isoformat()

    try:

        async with get_write_lock():

            db = await get_db()

            # ضمان وجود المستخدمين
            await db.execute("""
                INSERT OR IGNORE INTO global_users (
                    user_id, total_xp, level,
                    kento, deposit, trust,
                    verified_level, background
                )
                VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
            """, (giver_id,))

            await db.execute("""
                INSERT OR IGNORE INTO global_users (
                    user_id, total_xp, level,
                    kento, deposit, trust,
                    verified_level, background
                )
                VALUES (?, 0, 1, 0, 0, 0, 0, 'default.png')
            """, (receiver_id,))

            # آخر وقت منح ثقة
            async with db.execute("""
                SELECT last_trust
                FROM global_users
                WHERE user_id = ?
            """, (giver_id,)) as cursor:
                row = await cursor.fetchone()

            if row and row["last_trust"]:
                try:
                    last_time = datetime.datetime.fromisoformat(
                        row["last_trust"]
                    )

                    elapsed = (now - last_time).total_seconds()

                    if elapsed < 86400:
                        remaining = int(86400 - elapsed)

                        h = remaining // 3600
                        m = (remaining % 3600) // 60

                        return await interaction.followup.send(
                            f"⏳ يمكنك منح نقطة ثقة بعد `{h}h {m}m`.",
                            ephemeral=True
                        )

                except Exception:
                    pass

            # زيادة الثقة
            await db.execute("""
                UPDATE global_users
                SET trust = trust + 1
                WHERE user_id = ?
            """, (receiver_id,))

            # تحديث آخر وقت
            await db.execute("""
                UPDATE global_users
                SET last_trust = ?
                WHERE user_id = ?
            """, (now_iso, giver_id))

            # جلب العدد الجديد
            async with db.execute("""
                SELECT trust
                FROM global_users
                WHERE user_id = ?
            """, (receiver_id,)) as cursor:
                row = await cursor.fetchone()

            total = row["trust"] if row else 0

            await db.commit()

    except Exception as e:
        logging.exception(f"[TRUST ERROR] {e}")

        return await interaction.followup.send(
            "❌ حدث خطأ أثناء منح الثقة.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🤝 TRUST EARNED",
        description=(
            f"**{interaction.user.mention}** منح نقطة ثقة لـ "
            f"**{member.mention}**\n\n"
            f"🔰 إجمالي نقاط الثقة: `{total}`"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="GX • Trust System")

    await interaction.followup.send(embed=embed)
    
    
# ================= Gmail Settings =================
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USER = "gxbotar7@gmail.com"
EMAIL_PASS = "gwgy royo jopk mttb"

# ================= Verification Tools =================

def generate_verify_token(length=6):
    return ''.join(secrets.choice("0123456789") for _ in range(length))


def send_verification_email(to_email: str, code: str):
    msg = EmailMessage()
    msg["From"] = f"GxBot <{EMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = "⚡ GxBot | Email Verification Code"
    msg.set_content(f"""
🛡️ GxBot Total Security System 🛡️

Your verification code: {code}

⏰ Valid for 15 minutes.
""")
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        logging.error(f"[SMTP ERROR] {e}")


# ================= EMAIL MODAL =================

class EmailCodeModal(discord.ui.Modal, title="Email Verification"):

    code = discord.ui.TextInput(label="Enter the 6-digit code", required=True, max_length=6)

    def __init__(self, uid, email, correct_token, pin, birthday, full_name, country):
        super().__init__()
        self.uid = uid
        self.email = email
        self.correct_token = correct_token
        self.pin = pin
        self.birthday = birthday
        self.full_name = full_name
        self.country = country

    async def on_submit(self, interaction: discord.Interaction):

        if self.code.value.strip() != self.correct_token:
            return await interaction.response.send_message("❌ Invalid code", ephemeral=True)

        async with get_write_lock():
            db = await get_db()

            await db.execute(
                "INSERT OR IGNORE INTO global_users (user_id) VALUES (?)",
                (self.uid,)
            )
            await db.execute("""
                UPDATE global_users
                SET verified_level = 2,
                    email          = ?,
                    pin            = ?,
                    birthday       = ?,
                    full_name      = ?,
                    country        = ?,
                    verify_token   = NULL
                WHERE user_id = ?
            """, (self.email, self.pin, self.birthday, self.full_name, self.country, self.uid))

            await db.commit()

        await interaction.response.send_message("✅ Fully Verified (GLOBAL)", ephemeral=True)


# ================= VERIFY COMMAND =================

@bot.tree.command(name="verify", description="Verify your GxBot account (Global System)")
async def verify(
    interaction: discord.Interaction,
    full_name: str,
    country: str,
    pin: str,
    birthday: str,
    email: str = None
):
    uid = str(interaction.user.id)

    async with get_write_lock():
        db = await get_db()
        await db.execute(
            "INSERT OR IGNORE INTO global_users (user_id) VALUES (?)",
            (uid,)
        )
        await db.commit()

    db = await get_db()
    async with db.execute(
        "SELECT verified_level FROM global_users WHERE user_id = ?",
        (uid,)
    ) as cursor:
        row = await cursor.fetchone()

    if row and row[0] == 2:
        return await interaction.response.send_message("✅ Already Verified", ephemeral=True)

    # ================= VALIDATION =================
    if len(full_name.split()) < 2:
        return await interaction.response.send_message("❌ Enter first & last name", ephemeral=True)

    if not pin.isdigit() or len(pin) != 4:
        return await interaction.response.send_message("❌ PIN must be 4 digits", ephemeral=True)

    # ================= BASIC (بدون إيميل) =================
    if not email:
        async with get_write_lock():
            db = await get_db()
            await db.execute("""
                UPDATE global_users
                SET full_name      = ?,
                    country        = ?,
                    pin            = ?,
                    birthday       = ?,
                    verified_level = 1
                WHERE user_id = ?
            """, (full_name, country, pin, birthday, uid))
            await db.commit()

        return await interaction.response.send_message("✅ Basic Verified", ephemeral=True)

    # ================= EMAIL =================
    token = generate_verify_token()

    async with get_write_lock():
        db = await get_db()
        await db.execute(
            "UPDATE global_users SET verify_token = ? WHERE user_id = ?",
            (token, uid)
        )
        await db.commit()

    await interaction.response.send_modal(
        EmailCodeModal(uid, email.lower().strip(), token, pin, birthday, full_name, country)
    )

    asyncio.create_task(asyncio.to_thread(send_verification_email, email.lower().strip(), token))
    
# كاش بسيط للصور في الذاكرة {url: (timestamp, bytes)}
image_cache = {}
CACHE_MAX_AGE = 60 * 60  # 1 ساعة افتراضياً

async def fetch_image_cached(url: str, session: aiohttp.ClientSession, max_age: int = CACHE_MAX_AGE):
    """جلب صورة مع كاش بسيط بالذاكرة. يعيد PIL.Image."""
    now = time.time()
    entry = image_cache.get(url)

    if entry:
        ts, data = entry
        if now - ts < max_age:
            try:
                return Image.open(io.BytesIO(data)).convert("RGBA")
            except Exception:
                image_cache.pop(url, None)

    async with session.get(url) as resp:
        data = await resp.read()
        image_cache[url] = (now, data)
        return Image.open(io.BytesIO(data)).convert("RGBA")
        

# ======= الكوماند: ملف (Profile) =======
@bot.command(name="ملف")
async def ملف(ctx, member: discord.Member = None):

    if not await check_cooldown(ctx, "ملف", 15):
        return

    member = member or ctx.author

    if member.bot:
        return await ctx.send("🧐 البوتات لا تمتلك ملف", delete_after=5)

    async with ctx.typing():

        uid = str(member.id)
        guild_id = str(ctx.guild.id)

        # =========================================
        # ✅ ضمان وجود المستخدم في DB
        # =========================================
        await ensure_user(uid, guild_id)
        await ensure_global_user(uid)

        # =========================================
        # 🌍 GLOBAL DATA — عبر get_db()
        # =========================================
        db = await get_db()

        async with db.execute("""
            SELECT kento, trust, background, verified_level, level
            FROM global_users
            WHERE user_id = ?
        """, (uid,)) as cursor:
            g_row = await cursor.fetchone()

        kento = g_row["kento"] if g_row else 0
        trust = g_row["trust"] if g_row else 0
        background_file = g_row["background"] if g_row else "default.png"
        verified_level = g_row["verified_level"] if g_row else 0

        # =========================================
        # 🏢 SERVER XP (SUM ALL SERVERS)
        # =========================================
        async with db.execute("""
            SELECT SUM(xp)
            FROM users
            WHERE user_id = ?
        """, (uid,)) as cursor:
            row = await cursor.fetchone()

        xp = row[0] or 0

        # =========================================
        # 📊 حساب المستوى
        # =========================================
        level_int, current_xp, total_xp, progress_raw = calculate_level_and_progress(xp)

        progress = float(current_xp) / float(total_xp) if total_xp > 0 else 0.0
        xp_percentage = progress * 100
        total_real_xp = int(xp)

        # =========================================
        # 🌍 تحديث المستوى العالمي
        # =========================================
        async with get_write_lock():
            db = await get_db()
            await db.execute(
                "UPDATE global_users SET level = ? WHERE user_id = ?",
                (level_int, uid)
            )
            await db.commit()

        # =========================================
        # 🔢 RANK (عالمي عبر كل السيرفرات)
        # =========================================
        db = await get_db()
        async with db.execute("""
            SELECT COUNT(*) FROM (
                SELECT user_id, SUM(xp) AS total
                FROM users
                GROUP BY user_id
                HAVING total > ?
            )
        """, (xp,)) as cursor:
            row = await cursor.fetchone()

        rank = (row[0] or 0) + 1

        # =========================================
        # 🎨 دوال مساعدة
        # =========================================
        def format_kento(val):
            def clean(n):
                return str(int(n)) if n == int(n) else f"{n:.2f}"

            if val >= 1_000_000_000:
                return f"{clean(val / 1_000_000_000)}B"
            if val >= 1_000_000:
                return f"{clean(val / 1_000_000)}M"
            if val >= 1_000:
                return f"{clean(val / 1_000)}K"
            return clean(val)

        # =========================================
        # 🖼️ BACKGROUND
        # =========================================
        background_path = os.path.join("backgrounds", background_file)
        if not os.path.exists(background_path):
            background_path = "backgrounds/default.png"

        background = Image.open(background_path).convert("RGBA").resize((512, 512), Image.LANCZOS)

        overlay = Image.new("RGBA", background.size, (0, 0, 0, 120))
        background = Image.alpha_composite(background, overlay)
        draw = ImageDraw.Draw(background)

        # =========================================
        # 🔤 الخطوط
        # =========================================
        font_path = "Roboto-Regular.ttf"
        font_bold_path = "Roboto-Bold.ttf"

        try:
            font_label = ImageFont.truetype(font_path, 18)
            font_xxp = ImageFont.truetype(font_path, 15)
            font_value_bold = ImageFont.truetype(font_bold_path, 36)
            font_value_small_bold = ImageFont.truetype(font_bold_path, 20)
        except Exception:
            font_label = ImageFont.load_default()
            font_xxp = ImageFont.load_default()
            font_value_bold = ImageFont.load_default()
            font_value_small_bold = ImageFont.load_default()

        # =========================================
        # 📋 البيانات النصية
        # =========================================
        data_x, data_y, space = 40, 170, 80

        def shadow_text(x, y, text, font, fill="white", shadow_offset=(1, 1)):
            draw.text((x + shadow_offset[0], y + shadow_offset[1]), text, font=font, fill="black")
            draw.text((x, y), text, font=font, fill=fill)

        def draw_data(label, value, y_offset):
            label_upper = label.upper()

            if label_upper in ["RANK", "LVL", "KENTOS", "TRUST"]:
                value_font = font_value_bold if label_upper == "LVL" else font_value_small_bold
            else:
                value_font = font_value_small_bold

            shadow_text(data_x, data_y + y_offset, label_upper, font_label)
            shadow_text(data_x, data_y + y_offset + 25, str(value), value_font)

        draw_data("LVL", level_int, 0)
        draw_data("TRUST", f"+{trust}", space)
        draw_data("KENTOS", format_kento(kento), space * 2)
        draw_data("RANK", f"#{rank}", space * 3)

# =========================================
        # 📊 XP BAR
        # =========================================
        percent_text = f"{current_xp} / {total_xp} XP"
        total_text = f"Total XP: {total_real_xp}"

        scale = 1.15
        bar_total_w = int(240 * scale)
        bar_h = int(22 * scale)
        bar_x = int((background.width - bar_total_w) // 2 + 40 * scale)
        bar_y = int(background.height - 78 * scale)
        radius = bar_h // 2
        border_width = int(2 * scale)
        pad = border_width + 1

        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + bar_total_w, bar_y + bar_h],
            radius=radius,
            fill=(34, 34, 40, 220),
            outline=(255, 255, 255, 70),
            width=border_width
        )

        inner_w_total = bar_total_w - (pad * 2)
        inner_h = bar_h - (pad * 2)
        progress_w = int(inner_w_total * max(0.0, min(1.0, progress)))

        if progress_w > 0:
            if xp_percentage < 33:
                start_color, end_color = (255, 80, 80), (255, 160, 60)
            elif xp_percentage < 66:
                start_color, end_color = (255, 160, 60), (255, 220, 60)
            else:
                start_color, end_color = (70, 180, 255), (60, 240, 140)

            grad = Image.new("RGBA", (progress_w, inner_h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(grad)

            for xi in range(progress_w):
                t = xi / max(1, progress_w - 1)
                r = int(start_color[0] * (1 - t) + end_color[0] * t)
                g = int(start_color[1] * (1 - t) + end_color[1] * t)
                b = int(start_color[2] * (1 - t) + end_color[2] * t)
                gd.line([(xi, 0), (xi, inner_h)], fill=(r, g, b, 255))

            mask_crop = Image.new("L", (progress_w, inner_h), 0)
            mdraw = ImageDraw.Draw(mask_crop)
            mdraw.rounded_rectangle([0, 0, progress_w, inner_h], radius=inner_h // 2, fill=255)

            background.paste(grad, (bar_x + pad, bar_y + pad), mask_crop)

        pct_w = draw.textlength(percent_text, font=font_xxp)
        shadow_text(bar_x + (bar_total_w - pct_w) // 2, bar_y + 2, percent_text, font_xxp)

        total_w = draw.textlength(total_text, font=font_xxp)
        shadow_text(bar_x + (bar_total_w - total_w) // 2, bar_y + bar_h + 10, total_text, font_xxp)
        
                        # =========================================
        # 🎨 Avatar + Border + Username + Guild Icon
        # =========================================
        async with aiohttp.ClientSession() as session:
            try:
                avatar_url = member.display_avatar.replace(
                    static_format="png",
                    size=512
                ).url

                avatar_img = await fetch_image_cached(
                    avatar_url,
                    session
                )

                avatar = avatar_img.resize(
                    (135, 135),
                    Image.LANCZOS
                )

            except Exception as e:
                print(f"[avatar error] {e}")
                avatar = Image.new(
                    "RGBA",
                    (135, 135),
                    (120, 120, 120, 255)
                )

            mask = Image.new("L", avatar.size, 0)

            ImageDraw.Draw(mask).ellipse(
                (0, 0, 135, 135),
                fill=255
            )

            avatar.putalpha(mask)

            avatar_x, avatar_y = 25, 12

            shadow = Image.new(
                "RGBA",
                (135, 135),
                (0, 0, 0, 0)
            )

            ImageDraw.Draw(shadow).ellipse(
                (0, 0, 135, 135),
                fill=(0, 0, 0, 90)
            )

            shadow = shadow.filter(
                ImageFilter.GaussianBlur(radius=3)
            )

            background.paste(
                shadow,
                (avatar_x, avatar_y),
                shadow
            )

            border_color = (
                (255, 255, 255, 230)
                if kento < 400_000 else
                (255, 80, 80, 230)
                if kento < 800_000 else
                (255, 215, 0, 255)
            )

            border_size = 143
            aa_scale = 3

            big_size = border_size * aa_scale

            big_border = Image.new(
                "RGBA",
                (big_size, big_size),
                (0, 0, 0, 0)
            )

            ImageDraw.Draw(big_border).ellipse(
                (0, 0, big_size - 1, big_size - 1),
                outline=border_color,
                width=4 * aa_scale
            )

            border = big_border.resize(
                (border_size, border_size),
                Image.LANCZOS
            )

            if kento >= 800_000:
                glow = Image.new(
                    "RGBA",
                    (border_size + 10, border_size + 10),
                    (0, 0, 0, 0)
                )

                ImageDraw.Draw(glow).ellipse(
                    (5, 5, border_size + 5, border_size + 5),
                    outline=(255, 215, 0, 80),
                    width=8
                )

                glow = glow.filter(
                    ImageFilter.GaussianBlur(radius=4)
                )

                background.paste(
                    glow,
                    (avatar_x - 4, avatar_y - 4),
                    glow
                )

            background.paste(
                border,
                (avatar_x - 4, avatar_y - 4),
                border
            )

            background.paste(
                avatar,
                (avatar_x, avatar_y),
                avatar
            )

            name_str = member.name

            max_w = 300

            while draw.textlength(
                name_str,
                font=font_value_bold
            ) > max_w:

                name_str = name_str[:-1]

                if len(name_str) <= 2:
                    break

            shadow_text(
                175,
                25,
                name_str,
                font=font_value_bold
            )

            if ctx.guild and ctx.guild.icon:
                try:
                    icon_url = ctx.guild.icon.replace(
                        static_format="png",
                        size=512
                    ).url

                    icon_img = await fetch_image_cached(
                        icon_url,
                        session
                    )

                    icon = icon_img.resize(
                        (42, 42),
                        Image.LANCZOS
                    )

                    ic_mask = Image.new(
                        "L",
                        icon.size,
                        0
                    )

                    ImageDraw.Draw(ic_mask).ellipse(
                        [0, 0, 42, 42],
                        fill=255
                    )

                    icon.putalpha(ic_mask)

                    background.paste(
                        icon,
                        (background.width - 52, 10),
                        icon
                    )

                except:
                    pass

                    
        # =========================================
        # ✅ VERIFIED BADGE
        # =========================================
        if verified_level > 0:

            badge_size = 38
            badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
            bdraw = ImageDraw.Draw(badge)

            color = (46, 204, 113, 240) if verified_level >= 2 else (231, 76, 60, 240)

            bdraw.ellipse(
                [0, 0, badge_size - 1, badge_size - 1],
                fill=color,
                outline=(255, 255, 255, 240),
                width=3
            )
            bdraw.line([(10, 20), (16, 26), (28, 12)], width=4, fill=(255, 255, 255, 255))

            background.paste(
                badge,
                (background.width - 50, background.height - 50),
                badge
            )

        # =========================================
        # 📤 OUTPUT
        # =========================================
        with io.BytesIO() as image_binary:
            background.save(image_binary, "PNG")
            image_binary.seek(0)

            await ctx.reply(
                file=discord.File(fp=image_binary, filename="profile.png"),
                mention_author=False
            )
                        


# ======= سلاش: ملف (Profile) =======
@bot.tree.command(name="profile", description="عرض ملف العضو")
async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):

    if not await check_cooldown(interaction, "ملف", 15):
        return

    member = member or interaction.user

    if getattr(member, "bot", False):
        return await interaction.response.send_message("🧐 البوتات لا تمتلك ملف", ephemeral=True)

    await interaction.response.defer()

    uid = str(member.id)
    gid = str(interaction.guild.id)

    # =========================================
    # ✅ ضمان وجود المستخدم في DB
    # =========================================
    await ensure_user(uid, gid)
    await ensure_global_user(uid)

    # =========================================
    # 🌍 GLOBAL DATA — عبر get_db()
    # =========================================
    db = await get_db()

    async with db.execute("""
        SELECT kento, trust, background, verified_level, level
        FROM global_users
        WHERE user_id = ?
    """, (uid,)) as cursor:
        g_row = await cursor.fetchone()

    kento = g_row["kento"] if g_row else 0
    trust = g_row["trust"] if g_row else 0
    background_file = g_row["background"] if g_row else "default.png"
    verified_level = g_row["verified_level"] if g_row else 0

    # =========================================
    # 🏢 SERVER XP (GLOBAL SUM)
    # =========================================
    async with db.execute("""
        SELECT SUM(xp)
        FROM users
        WHERE user_id = ?
    """, (uid,)) as cursor:
        row = await cursor.fetchone()

    xp = row[0] or 0

    # =========================================
    # 📊 حساب المستوى
    # =========================================
    level_int, current_xp, total_xp, progress_raw = calculate_level_and_progress(xp)

    progress = float(current_xp) / float(total_xp) if total_xp > 0 else 0.0
    xp_percentage = progress * 100
    total_real_xp = int(xp)

    # =========================================
    # 🌍 تحديث المستوى العالمي
    # =========================================
    async with get_write_lock():
        db = await get_db()
        await db.execute(
            "UPDATE global_users SET level = ? WHERE user_id = ?",
            (level_int, uid)
        )
        await db.commit()

    # =========================================
    # 🔢 RANK (عالمي عبر كل السيرفرات)
    # =========================================
    db = await get_db()
    async with db.execute("""
        SELECT COUNT(*) FROM (
            SELECT user_id, SUM(xp) AS total
            FROM users
            GROUP BY user_id
            HAVING total > ?
        )
    """, (xp,)) as cursor:
        row = await cursor.fetchone()

    rank = (row[0] or 0) + 1

    # =========================================
    # 🎨 دوال مساعدة
    # =========================================
    def format_kento(val):
        def clean(n):
            return str(int(n)) if n == int(n) else f"{n:.2f}"
        if val >= 1_000_000_000:
            return f"{clean(val/1_000_000_000)}B"
        if val >= 1_000_000:
            return f"{clean(val/1_000_000)}M"
        if val >= 1_000:
            return f"{clean(val/1_000)}K"
        return clean(val)

    # =========================================
    # 🖼️ BACKGROUND
    # =========================================
    background_path = os.path.join("backgrounds", background_file)
    if not os.path.exists(background_path):
        background_path = "backgrounds/default.png"

    background = Image.open(background_path).convert("RGBA").resize((512, 512), Image.LANCZOS)

    overlay = Image.new("RGBA", background.size, (0, 0, 0, 120))
    background = Image.alpha_composite(background, overlay)
    draw = ImageDraw.Draw(background)

    # =========================================
    # 🔤 الخطوط
    # =========================================
    font_path = "Roboto-Regular.ttf"
    font_bold_path = "Roboto-Bold.ttf"

    try:
        font_label = ImageFont.truetype(font_path, 18)
        font_xxp = ImageFont.truetype(font_path, 15)
        font_value_bold = ImageFont.truetype(font_bold_path, 36)
        font_value_small_bold = ImageFont.truetype(font_bold_path, 20)
    except Exception:
        font_label = ImageFont.load_default()
        font_xxp = ImageFont.load_default()
        font_value_bold = ImageFont.load_default()
        font_value_small_bold = ImageFont.load_default()

    # =========================================
    # 📋 البيانات النصية
    # =========================================
    data_x, data_y, space = 40, 170, 80

    def shadow_text(x, y, text, font, fill="white", shadow_offset=(1, 1)):
        draw.text((x + shadow_offset[0], y + shadow_offset[1]), text, font=font, fill="black")
        draw.text((x, y), text, font=font, fill=fill)

    def draw_data(label, value, y_offset):
        label_upper = label.upper()

        if label_upper in ["RANK", "LVL", "KENTOS", "TRUST"]:
            value_font = font_value_bold if label_upper == "LVL" else font_value_small_bold
        else:
            value_font = font_value_small_bold

        shadow_text(data_x, data_y + y_offset, label_upper, font_label)
        shadow_text(data_x, data_y + y_offset + 25, str(value), value_font)

    draw_data("LVL", level_int, 0)
    draw_data("TRUST", f"+{trust}", space)
    draw_data("KENTOS", format_kento(kento), space * 2)
    draw_data("RANK", f"#{rank}", space * 3)

# =========================================
    # 📊 XP BAR
    # =========================================
    percent_text = f"{current_xp} / {total_xp} XP"
    total_text = f"Total XP: {total_real_xp}"

    scale = 1.15
    bar_total_w = int(240 * scale)
    bar_h = int(22 * scale)
    bar_x = int((background.width - bar_total_w) // 2 + 40 * scale)
    bar_y = int(background.height - 78 * scale)
    radius = bar_h // 2
    border_width = int(2 * scale)
    pad = border_width + 1

    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_total_w, bar_y + bar_h],
        radius=radius,
        fill=(34, 34, 40, 220),
        outline=(255, 255, 255, 70),
        width=border_width
    )

    inner_w_total = bar_total_w - (pad * 2)
    inner_h = bar_h - (pad * 2)
    progress_w = int(inner_w_total * max(0.0, min(1.0, progress)))

    if progress_w > 0:
        if xp_percentage < 33:
            start_color, end_color = (255, 80, 80), (255, 160, 60)
        elif xp_percentage < 66:
            start_color, end_color = (255, 160, 60), (255, 220, 60)
        else:
            start_color, end_color = (70, 180, 255), (60, 240, 140)

        grad = Image.new("RGBA", (progress_w, inner_h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)

        for xi in range(progress_w):
            t = xi / max(1, progress_w - 1)
            r = int(start_color[0] * (1 - t) + end_color[0] * t)
            g = int(start_color[1] * (1 - t) + end_color[1] * t)
            b = int(start_color[2] * (1 - t) + end_color[2] * t)
            gd.line([(xi, 0), (xi, inner_h)], fill=(r, g, b, 255))

        mask_crop = Image.new("L", (progress_w, inner_h), 0)
        mdraw = ImageDraw.Draw(mask_crop)
        mdraw.rounded_rectangle([0, 0, progress_w, inner_h], radius=inner_h // 2, fill=255)
        background.paste(grad, (bar_x + pad, bar_y + pad), mask_crop)

    # =========================================
    # 📊 CENTER XP TEXT INSIDE BAR
    # =========================================
    center_x = bar_x + bar_total_w // 2
    center_y = bar_y + bar_h // 2

    pct_w = draw.textlength(percent_text, font=font_xxp)
    pct_h = font_xxp.size

    shadow_text(
        center_x - pct_w // 2,
        center_y - pct_h // 2,
        percent_text,
        font_xxp
    )

    total_w = draw.textlength(total_text, font=font_xxp)
    shadow_text(
        bar_x + (bar_total_w - total_w) // 2,
        bar_y + bar_h + 10,
        total_text,
        font_xxp
    )
    
    # =========================================
    # 🎨 Avatar + Border + Username + Guild Icon
    # =========================================
    async with aiohttp.ClientSession() as session:
        try:
            avatar_url = member.display_avatar.replace(static_format="png", size=512).url
            avatar_img = await fetch_image_cached(avatar_url, session)
            avatar = avatar_img.resize((135, 135), Image.LANCZOS)
        except Exception as e:
            print(f"[avatar error] {e}")
            avatar = Image.new("RGBA", (135, 135), (120, 120, 120, 255))

        mask = Image.new("L", avatar.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 135, 135), fill=255)
        avatar.putalpha(mask)

        avatar_x, avatar_y = 25, 12

        shadow = Image.new("RGBA", (135, 135), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse((0, 0, 135, 135), fill=(0, 0, 0, 90))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=3))
        background.paste(shadow, (avatar_x, avatar_y), shadow)

        border_color = (
            (255, 255, 255, 230)
            if kento < 400_000 else
            (255, 80, 80, 230)
            if kento < 800_000 else
            (255, 215, 0, 255)
        )

        border_size = 143
        aa_scale = 3
        big_size = border_size * aa_scale

        big_border = Image.new("RGBA", (big_size, big_size), (0, 0, 0, 0))
        ImageDraw.Draw(big_border).ellipse(
            (0, 0, big_size - 1, big_size - 1),
            outline=border_color,
            width=4 * aa_scale
        )
        border = big_border.resize((border_size, border_size), Image.LANCZOS)

        if kento >= 800_000:
            glow = Image.new("RGBA", (border_size + 10, border_size + 10), (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse(
                (5, 5, border_size + 5, border_size + 5),
                outline=(255, 215, 0, 80),
                width=8
            )
            glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
            background.paste(glow, (avatar_x - 4, avatar_y - 4), glow)

        background.paste(border, (avatar_x - 4, avatar_y - 4), border)
        background.paste(avatar, (avatar_x, avatar_y), avatar)

        name_str = member.name
        max_w = 300

        while draw.textlength(name_str, font=font_value_bold) > max_w:
            name_str = name_str[:-1]
            if len(name_str) <= 2:
                break

        shadow_text(175, 25, name_str, font=font_value_bold)

        if interaction.guild and interaction.guild.icon:
            try:
                icon_url = interaction.guild.icon.replace(static_format="png", size=512).url
                icon_img = await fetch_image_cached(icon_url, session)
                icon = icon_img.resize((42, 42), Image.LANCZOS)

                ic_mask = Image.new("L", icon.size, 0)
                ImageDraw.Draw(ic_mask).ellipse([0, 0, 42, 42], fill=255)
                icon.putalpha(ic_mask)

                background.paste(icon, (background.width - 52, 10), icon)
            except:
                pass

    # =========================================
    # ✅ VERIFIED BADGE
    # =========================================
    if verified_level > 0:
        badge_size = 38
        badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(badge)

        color = (46, 204, 113, 240) if verified_level >= 2 else (231, 76, 60, 240)

        bdraw.ellipse(
            [0, 0, badge_size - 1, badge_size - 1],
            fill=color,
            outline=(255, 255, 255, 240),
            width=3
        )
        bdraw.line([(10, 20), (16, 26), (28, 12)], width=4, fill=(255, 255, 255, 255))

        background.paste(
            badge,
            (background.width - 50, background.height - 50),
            badge
        )

    # =========================================
    # 📤 OUTPUT
    # =========================================
    with io.BytesIO() as image_binary:
        background.save(image_binary, "PNG", optimize=True)
        image_binary.seek(0)

        await interaction.followup.send(
            file=discord.File(fp=image_binary, filename="profile.png")
        )
                                                                                      
@bot.tree.command(name="top_kentos", description="عرض قائمة الأغنياء بالكينتو")
async def top_kentos(interaction: discord.Interaction):

    if not await check_cooldown(interaction, "top_kentos", 20):
        return

    await interaction.response.defer()

    def format_kento(kento):
        kento = int(kento or 0)
        if kento >= 1_000_000_000:
            return f"{kento / 1_000_000_000:.2f}b"
        if kento >= 1_000_000:
            return f"{kento / 1_000_000:.2f}m"
        if kento >= 1_000:
            return f"{kento / 1_000:.2f}k"
        return str(kento)

    top_users = []
    user_id = str(interaction.user.id)
    user_rank = None
    user_kento_total = 0

    db = await get_db()

    async with db.execute("""
        SELECT user_id, kento
        FROM global_users
        ORDER BY kento DESC
        LIMIT 10
    """) as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            top_users.append((str(row[0]), int(row[1] or 0)))

    async with db.execute("""
        SELECT kento FROM global_users WHERE user_id = ?
    """, (user_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            user_kento_total = int(row[0] or 0)

            async with db.execute("""
                SELECT COUNT(*) + 1
                FROM global_users
                WHERE kento > (
                    SELECT kento FROM global_users WHERE user_id = ?
                )
            """, (user_id,)) as rc:
                r = await rc.fetchone()
                user_rank = r[0] if r is not None else None

    top_ids = [uid for uid, _ in top_users]
    user_in_top = user_id in top_ids

    scale = 2
    base_w = 720
    spacing = 90 * scale
    y_start = 110 * scale
    base_h = 1080
    w, h = base_w * scale, base_h * scale

    try:
        bg_path = os.path.join(os.path.dirname(__file__), "amroi", "background.png")
        bg = Image.open(bg_path).convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
    except Exception as e:
        return await interaction.followup.send(f"❌ الخلفية غير موجودة: {e}", ephemeral=True)

    draw = ImageDraw.Draw(bg)

    font_title = ImageFont.truetype("arabic.ttf", 52 * scale)
    font_english = ImageFont.truetype("Roboto-Regular.ttf", 30 * scale)
    font_number = ImageFont.truetype("Roboto-Regular.ttf", 26 * scale)

    draw.text((w // 2, 40 * scale), "RICH KHENTOS", font=font_title, fill="gold", anchor="mm")

    box_colors = {0: "#FFD700", 1: "#C0C0C0", 2: "#CD7F32"}

    async with aiohttp.ClientSession() as session:
        for i, (uid, kento_val) in enumerate(top_users):
            try:
                user = interaction.client.get_user(int(uid)) or await interaction.client.fetch_user(int(uid))
                name = user.name

                y = y_start + i * spacing
                x_offset = 30 * scale
                rect_width = 700 * scale - x_offset
                rect_height = 70 * scale

                if i >= 3:
                    gradient = Image.new("RGBA", (rect_width, rect_height), (0, 0, 0, 0))
                    gd = ImageDraw.Draw(gradient)
                    for x in range(rect_width):
                        gray = int(60 + (x / rect_width) * 80)
                        gd.line([(x, 0), (x, rect_height)], fill=(gray, gray, gray, 255))
                    mask = Image.new("L", (rect_width, rect_height), 0)
                    ImageDraw.Draw(mask).rounded_rectangle(
                        [0, 0, rect_width, rect_height], radius=25 * scale, fill=255
                    )
                    bg.paste(gradient, (x_offset, y), mask)
                else:
                    base_color = ImageColor.getrgb(box_colors.get(i, "#1e1e1e"))
                    darkened = tuple(int(c * 0.8) for c in base_color)
                    draw.rounded_rectangle(
                        [(x_offset, y), (700 * scale, y + rect_height)],
                        radius=25 * scale,
                        fill=darkened + (255,)
                    )

                circle_radius = 22 * scale
                circle_x = x_offset + 10 * scale
                circle_y = y + 12 * scale
                draw.ellipse(
                    [(circle_x, circle_y),
                     (circle_x + 2 * circle_radius, circle_y + 2 * circle_radius)],
                    fill=box_colors.get(i, "white"),
                    outline="black",
                    width=2 * scale
                )
                draw.text(
                    (circle_x + circle_radius, circle_y + circle_radius),
                    str(i + 1),
                    font=font_number, fill="black", anchor="mm"
                )

                avatar_x = circle_x + 2 * circle_radius + 10 * scale
                avatar_y = y + 10 * scale
                async with session.get(user.display_avatar.replace(format="png", size=512).url) as resp:
                    avatar_bytes = await resp.read()
                avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
                avatar = avatar.resize((50 * scale, 50 * scale), Image.Resampling.LANCZOS)
                av_mask = Image.new("L", avatar.size, 0)
                ImageDraw.Draw(av_mask).ellipse((0, 0) + avatar.size, fill=255)
                avatar.putalpha(av_mask)
                bg.paste(avatar, (int(avatar_x), int(avatar_y)), avatar)

                name_x = avatar_x + 60 * scale
                name_y = y + 25 * scale
                draw.text((name_x, name_y), name, font=font_english, fill="white", anchor="lm")
                draw.text((680 * scale, name_y), format_kento(kento_val), font=font_english, fill="yellow", anchor="rm")

            except Exception as e:
                print(f"[TOP ERROR] {e}")
                continue

        if user_rank is not None and not user_in_top:
            y_base = y_start + len(top_users) * spacing
            y = int(y_base * 0.99)

            draw.rounded_rectangle(
                [(20 * scale, y), (700 * scale, y + 70 * scale)],
                radius=25 * scale,
                fill=(80, 0, 0, 220)
            )

            self_user = interaction.client.get_user(int(user_id)) or await interaction.client.fetch_user(int(user_id))

            rank_text = f"#{user_rank}"
            rank_bbox = font_english.getbbox(rank_text)
            rank_width = rank_bbox[2] - rank_bbox[0]

            rank_x = 40 * scale
            avatar_start_x = rank_x + rank_width + 15 * scale
            name_start_x = avatar_start_x + 55 * scale + 10 * scale

            try:
                async with session.get(self_user.display_avatar.replace(format="png", size=512).url) as resp:
                    av_bytes = await resp.read()
                av = Image.open(BytesIO(av_bytes)).convert("RGBA")
                av = av.resize((50 * scale, 50 * scale), Image.Resampling.LANCZOS)
                av_m = Image.new("L", av.size, 0)
                ImageDraw.Draw(av_m).ellipse((0, 0) + av.size, fill=255)
                av.putalpha(av_m)
                bg.paste(av, (int(avatar_start_x), int(y + 10 * scale)), av)
            except Exception:
                pass

            draw.text(
                (rank_x, y + 35 * scale),
                rank_text,
                font=font_english, fill="white", anchor="lm"
            )
            draw.text(
                (name_start_x, y + 35 * scale),
                self_user.name,
                font=font_english, fill="white", anchor="lm"
            )
            draw.text(
                (680 * scale, y + 35 * scale),
                format_kento(user_kento_total),
                font=font_english, fill="yellow", anchor="rm"
            )

    with BytesIO() as image_binary:
        bg.save(image_binary, "PNG")
        image_binary.seek(0)
        await interaction.followup.send(file=discord.File(fp=image_binary, filename="top_kento.png"))        
        
VOICE_GUILD_ID = 1398281305417973921   # ايدي السيرفر
VOICE_CHANNEL_ID = 1427578831702589522 # ايدي الروم الصوتي

@bot.event
async def on_ready():

    # =========================
    # منع التكرار
    # =========================
    if getattr(bot, "startup_done", False):
        return
    bot.startup_done = True

    print(f"🚀 [STARTUP] Logged in as {bot.user}")

    # ============================================
    # 1️⃣ قاعدة البيانات والكاش
    # ============================================
    try:
        await init_db()

        # Migration (اختياري)
        if os.path.exists("data.json") and "migrate_json_to_sqlite" in globals():
            print("🚛 Migrating JSON → SQLite...")
            await migrate_json_to_sqlite()

        # ✅ تحميل كاش السيرفرات — بدون connection جديد
        server_settings_cache.clear()
        db = await get_db()

        async with db.execute("SELECT guild_id, settings FROM server_settings") as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            gid = str(row["guild_id"])
            try:
                server_settings_cache[gid] = json.loads(row["settings"]) if row["settings"] else {}
            except Exception:
                server_settings_cache[gid] = {}

        print(f"⚡ Loaded {len(server_settings_cache)} servers into cache")

    except Exception as e:
        print(f"❌ Startup Error: {e}")

    # ============================================
    # 2️⃣ الدعوات والسيرفرات
    # ============================================
    print("📨 [SYNC] Updating Invites and Server Data...")

    try:
        for guild in bot.guilds:
            gid = str(guild.id)

            # أ- تحديث كاش الدعوات
            try:
                invs = await guild.invites()
                invite_cache[guild.id] = {inv.code: inv.uses for inv in invs}
            except Exception:
                invite_cache[guild.id] = {}

            # ب- Legacy support
            if "points_data" in globals():
                if gid not in points_data.get("servers", {}):
                    points_data.setdefault("servers", {})[gid] = {
                        "settings": {},
                        "custom_aliases": {},
                        "autoreplies": [],
                        "blocked_channels": [],
                    }

            # ج- ✅ مزامنة الأعضاء بـ BULK بدل query لكل عضو
            try:
                members_to_insert = [
                    (str(m.id), gid, 0, 0, 0, 0, None, 0)
                    for m in guild.members
                    if not m.bot
                ]
                if members_to_insert:
                    async with get_write_lock():
                        db = await get_db()
                        await db.executemany("""
                            INSERT OR IGNORE INTO users (
                                user_id, guild_id,
                                xp, msg_xp, voice_xp,
                                invites, last_mine, last_vote
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, members_to_insert)
                        await db.commit()
                    print(f"👥 [{guild.name}] Synced {len(members_to_insert)} members")
            except Exception as e:
                print(f"⚠️ Member sync error [{guild.name}]: {e}")

        # Legacy save
        if "save_data" in globals():
            save_data()
        if "save_invites_data" in globals():
            save_invites_data()

        print(f"✅ [SYNC] Processed {len(bot.guilds)} guilds successfully.")

    except Exception as e:
        print(f"⚠️ [Sync Error] {e}")

    # ============================================
    # 3️⃣ الخدمات الخلفية
    # ============================================
    try:
        await start_backup_task()
        await start_save_queue()

        if not auto_adhkar_loop.is_running():
            auto_adhkar_loop.start()

        print("✅ [TASKS] Backup, SaveQueue, and Adhkar loop are running.")

    except Exception as e:
        print(f"⚠️ [Task Error] {e}")

    # ============================================
    # 4️⃣ استعادة الـ Views الدائمة
    # ============================================
    if not getattr(bot, "persistent_views_added", False):
        bot.persistent_views_added = True

        # أ- Role Menus
        try:
            from cogs.role_system import restore_role_menus
            await restore_role_menus(bot)
        except Exception as e:
            print(f"⚠️ View Error (Roles): {e}")

        # ب- RegisterView
        try:
            if "message_data" in globals() and isinstance(message_data, dict):
                for guild_id in message_data.keys():
                    bot.add_view(RegisterView(bot, guild_id))
        except Exception as e:
            print(f"⚠️ View Error (Register): {e}")

        # ج- TicketView
        try:
            load_ticket_configs()
            load_ticket_points()
            load_active_tickets()

            for guild_id, cfg in ticket_configs.items():
                guild = bot.get_guild(int(guild_id))
                if not guild:
                    continue
                channel = guild.get_channel(cfg.get("channel_id"))
                if not channel:
                    continue
                admin_role = guild.get_role(cfg["admin_role"]) if cfg.get("admin_role") else None
                view = TicketView(
                    admin_role,
                    cfg["buttons"],
                    cfg.get("image_url"),
                    cfg.get("use_menu", False)
                )
                bot.add_view(view)

            await setup_ticket_commands(bot)
            print("✅ [VIEWS] All persistent views restored.")

        except Exception as e:
            print(f"❌ [View Error] Ticket system: {e}")

    # ============================================
    # 5️⃣ الصوت — بدون slash sync (صار في setup_hook)
    # ============================================
    try:
        guild = bot.get_guild(VOICE_GUILD_ID)
        if guild:
            channel = guild.get_channel(VOICE_CHANNEL_ID)
            if channel and not guild.voice_client:
                await channel.connect()
                print("🔊 [VOICE] Connected to voice channel.")
    except Exception as e:
        print(f"⚠️ Voice Error: {e}")

    print(f"""
    ==========================================
    ✅ GxBot is fully operational!
    🆔 User : {bot.user}
    📊 DB   : SQLite (Shared Connection)
    👥 Guilds: {len(bot.guilds)}
    ==========================================
    """)
                        
bot.run(os.getenv("DISCORD_TOKEN"))