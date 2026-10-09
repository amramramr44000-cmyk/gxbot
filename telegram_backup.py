import os
import aiohttp
import asyncio
import logging
import aiosqlite
import datetime

TELEGRAM_TOKEN = "8349100596:AAHZRZhhEMPk1ceORPPHMQmxb17gk8LQPas"
TELEGRAM_CHAT_ID = "-1002624931196"

DB_PATH = "data.db"

BACKUP_INTERVAL = 1800  # كل 30 دقيقة


# -----------------------------
# إنشاء نسخة احتياطية SQLite
# -----------------------------
async def create_backup():
    if not os.path.exists(DB_PATH):
        return None

    backup_name = f"backup_{int(datetime.datetime.now().timestamp())}.db"

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f"VACUUM INTO '{backup_name}'")

        return backup_name

    except Exception as e:
        logging.error(f"Backup error: {e}")
        return None


# -----------------------------
# إرسال النسخة إلى تليجرام
# -----------------------------
async def send_backup_to_telegram():
    backup_file = await create_backup()

    if not backup_file:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"

    try:
        async with aiohttp.ClientSession() as session:
            with open(backup_file, "rb") as f:

                form = aiohttp.FormData()
                form.add_field("chat_id", TELEGRAM_CHAT_ID)
                form.add_field("document", f, filename=backup_file)
                form.add_field(
                    "caption",
                    f"🗄️ Database Backup\n⏰ {datetime.datetime.now()}"
                )

                await session.post(url, data=form)

        logging.info("✅ Backup sent to Telegram")

    except Exception as e:
        logging.error(f"Telegram error: {e}")

    finally:
        # حذف النسخة بعد الإرسال
        try:
            os.remove(backup_file)
        except Exception:
            pass


# -----------------------------
# حلقة النسخ الاحتياطي
# -----------------------------
async def backup_loop():

    logging.info("📦 Backup system started")

    while True:
        try:
            await send_backup_to_telegram()
        except Exception as e:
            logging.error(f"Backup loop error: {e}")

        await asyncio.sleep(BACKUP_INTERVAL)


# -----------------------------
# تشغيل نظام النسخ الاحتياطي
# -----------------------------
def start_backup_task():
    asyncio.create_task(backup_loop())