# data_manager_compatible.py
import asyncio
import json
import shutil
import datetime
import logging
import os

# =======================================
# ✅ استخدام المتغيرات والدوال من الكود الأساسي
# =======================================
from bot import points_data, save_data, _data_lock  # موجود في bot.py

# =======================================
# الحقول الافتراضية للمستخدم
# =======================================
USER_DEFAULTS = {
    "kento": 0,
    "trust": 0,
    "xp": 0,
    "level": 0,
    "premium": False,
    "last_daily": None,
    "last_trust": None,
    "background": "default.png",
    "owned_backgrounds": []
}

# =======================================
# ✅ ضمان بيانات المستخدم
# =======================================
def ensure_user(uid: str) -> dict:
    """
    التأكد من وجود بيانات المستخدم وإرجاعها.
    يقوم بتعبئة القيم الافتراضية إذا لم تكن موجودة.
    """
    user = points_data.setdefault("global_users", {}).setdefault(uid, {})
    for k, v in USER_DEFAULTS.items():
        user.setdefault(k, v)
    return user

# =======================================
# ✅ إصلاح يدوي للبيانات
# =======================================
def manual_repair(data: dict) -> dict:
    """
    إصلاح أي تلف في البنية الأساسية للبيانات.
    يضيف القيم الافتراضية للمستخدمين ويضمن وجود الأقسام الأساسية.
    """
    try:
        data.setdefault("global_users", {})
        data.setdefault("servers", {})
        data.setdefault("activity", {})
        data.setdefault("warnings", {})

        for uid, user in list(data["global_users"].items()):
            if not isinstance(user, dict):
                logging.warning(f"إصلاح بيانات المستخدم {uid}: كانت {type(user).__name__}")
                data["global_users"][uid] = {}
                user = data["global_users"][uid]

            for key, value in USER_DEFAULTS.items():
                user.setdefault(key, value)

        logging.info("✅ تم إصلاح البيانات يدويًا.")
    except Exception as e:
        logging.exception(f"❌ خطأ في manual_repair: {e}")
    return data

# =======================================
# ✅ حفظ دوري آمن
# =======================================
async def periodic_save(interval: int = 60):
    """
    حلقة حفظ تلقائية لكل interval ثانية.
    يعتمد على save_data من الكود الأساسي لضمان الأمان.
    """
    while True:
        try:
            save_data()
        except Exception as e:
            logging.exception(f"❌ خطأ أثناء periodic_save: {e}")
        await asyncio.sleep(interval)

# =======================================
# ✅ واجهة استدعاء النسخ الاحتياطي المبسط
# =======================================
def generate_simple_backup(backup_file="data_backup.json"):
    """
    إنشاء نسخة احتياطية سريعة من بيانات المستخدمين والسيرفرات.
    آمن، ولا يغير أي بيانات موجودة في الكود الأساسي.
    """
    try:
        backup = {
            "global_users": {},
            "servers": {},
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        # نسخ بيانات المستخدمين الأساسية فقط
        for uid, user_data in points_data.get("global_users", {}).items():
            backup["global_users"][uid] = {
                "kento": user_data.get("kento", 0),
                "background": user_data.get("background", "default.png"),
                "owned_backgrounds": user_data.get("owned_backgrounds", [])
            }

        # نسخ بيانات السيرفرات الأساسية فقط
        for gid, server in points_data.get("servers", {}).items():
            backup["servers"][gid] = {
                "settings": server.get("settings", {}),
                "users": server.get("users", {})
            }

        tmp_file = backup_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, separators=(",", ":"))

        os.replace(tmp_file, backup_file)
        logging.info(f"💾 نسخة احتياطية تم إنشاؤها -> {backup_file}")
    except Exception as e:
        logging.exception(f"❌ خطأ أثناء إنشاء النسخة الاحتياطية: {e}")