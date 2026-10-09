import discord
from discord.ext import commands
from discord import app_commands
import os


# ============= ⚙️ زر فتح القائمة ============= #

class ExtraMenuButton(discord.ui.Button):
    def __init__(self, author_id):
        super().__init__(label="📚 القائمة الإضافية", style=discord.ButtonStyle.blurple)
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ لا يمكنك استخدام هذه القائمة.", ephemeral=True)

        view = ExtraDropdownView(self.author_id)
        embed = discord.Embed(
            title="📚 القائمة الإضافية",
            description="🧭 اختر من القائمة أدناه لعرض النظام أو الميزة التي تريد شرحها.\n> **سيظهر الشرح لك فقط برسالة خاصة.**",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=view)


# ============= 📜 المنيو العريضة ============= #

class ExtraDropdown(discord.ui.Select):
    def __init__(self, author_id):
        self.author_id = author_id

        options = [
            discord.SelectOption(label="💰 نظام العملة", description="شرح نظام العملة والرصيد", value="1"),
            discord.SelectOption(label="🏦 نظام الاقتصاد", description="شرح الاقتصاد والتعاملات", value="2"),
            discord.SelectOption(label=" نظام التوثيق", description="شرح التوثيق والتحقق", value="3"),
            discord.SelectOption(label="🎯 نظام المهام", description="شرح المهام اليومية والتحديات", value="4"),
            discord.SelectOption(label="⚙️ نظام الإدارة", description="شرح أدوات الإدارة والتحكم", value="5"),
            discord.SelectOption(label="🛡️ نظام الحماية", description="شرح الحماية والتحقق الأمني", value="6"),
            discord.SelectOption(label="🎮 نظام الترفيه", description="شرح الأوامر الترفيهية الممتعة", value="7"),
            discord.SelectOption(label="🎫 نظام التذاكر", description="شرح الدعم الفني والتذاكر", value="8"),
            discord.SelectOption(label="📊 نظام التوب", description="شرح لوحات التوب والترتيب", value="9"),
            discord.SelectOption(label="💌 نظام الدعوات", description="شرح نظام الدعوات والمكافآت", value="10"),
            discord.SelectOption(label="🧩 باقي الأنظمة", description="أنظمة إضافية ومعلومات عامة", value="11"),
        ]

        super().__init__(
            placeholder="اختر نظام لعرض شرحه...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="extra_dropdown"
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ لا يمكنك استخدام هذه القائمة.", ephemeral=True)

        page_num = self.values[0]
        file_path = f"pages/info_{page_num}.txt"

        if not os.path.exists(file_path):
            text = f"⚠️ لم يتم العثور على الملف `{file_path}`."
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

        embed = discord.Embed(
            title=f"📘 شرح النظام رقم {page_num}",
            description=text or "❌ الملف فارغ.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="💡 يمكنك اختيار نظام آخر من القائمة بالأسفل.")
        await interaction.response.edit_message(embed=embed, view=self.view)
        

# ============= 🎛️ واجهة القائمة الكاملة ============= #

class ExtraDropdownView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=None)
        self.add_item(ExtraDropdown(author_id))
        self.add_item(BackToHelpButton(author_id))


class BackToHelpButton(discord.ui.Button):
    def __init__(self, author_id):
        super().__init__(label="🔙 العودة للقائمة الأساسية", style=discord.ButtonStyle.success)
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ لا يمكنك الرجوع.", ephemeral=True)

        view = HelpView(self.author_id)
        embed = discord.Embed(
            title="📘 دليل أوامر GxBot",
            description="⚙️ عدت إلى القائمة الرئيسية للأوامر. استخدم القائمة أدناه لاختيار قسم.",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=embed, view=view)
        

# ============= 📚 القائمة الأساسية الأصلية ============= #

class SectionSelect(discord.ui.Select):
    def __init__(self, sections, author_id):
        options = [
            discord.SelectOption(
                label=sec["title"],
                emoji=sec["emoji"],
                description=sec["short"]
            )
            for sec in sections.values()
        ]
        super().__init__(
            placeholder="📂 اختر قسمًا لعرض أوامره...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.sections = sections
        self.author_id = author_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ هذا التفاعل مخصص فقط لمن طلب الأمر.", ephemeral=True)

        selected = self.values[0]
        section = next((sec for sec in self.sections.values() if sec["title"] == selected), None)
        if not section:
            return await interaction.response.send_message("❌ لم يتم العثور على القسم.", ephemeral=True)

        embed = discord.Embed(
            title=f"{section['emoji']} {section['title']}",
            description=section["description"],
            color=discord.Color.blue()
        )
        view = HelpView(self.author_id)
        await interaction.response.edit_message(embed=embed, view=view)


class HelpView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=None)
        self.author_id = author_id

        self.sections = {
            "general": {
                "emoji": "📋",
                "title": "الأوامر العامة",
                "short": "أوامر معلوماتية وخدمات عامة",
                "description": (
                    "**__/vote__** — التصويت للبوت على Top.gg.\n"
                    "**__/server__** — عرض إحصائيات وخصائص السيرفر.\n"
                    "**__/verify__** — قدّم طلب توثيق حسابك في البوت .\n"
                    "**__/invites_bot__** — معلومات وروابط البوت.\n"
                    "**__/gxhup__** — الشبكة  العالميه عبر السيرفرات .\n" 
                    "**__/owner_bot__** — معلومات مالك البوت.\n"
                    "**__/lnformation__** — عرض معلوماتك داخل السيرفر."
                )
            },
            "moderation": {
                "emoji": "🛠️",
                "title": "إدارة الأعضاء",
                "short": "أوامر الإشراف والتحكم",
                "description": (
                    "**__/warn__** — تحذير عضو.\n"
                    "**__/warnings__** — عرض تحذيرات عضو.\n"
                    "**__/remove_warnings__** — حذف تحذير.\n"
                    "**__/ban__** — حظر عضو.\n"
                    "**__/kick__** — طرد عضو.\n"
                    "**__/mute__** — ميوت عضو.\n"
                    "**__/timeout__** — تايم أوت.\n"
                    "**__/role__** — إعطاء أو إزالة رتبة.\n"
                    "**__/give_role__** — إعطاء رتبة للجميع.\n"
                    "**__/remove_role__** — إزالة رتبة من الجميع."
                )
            },
            "rooms": {
                "emoji": "🔐",
                "title": "التحكم في الرومات",
                "short": "قفل، فتح وتنظيم القنوات",
                "description": (
                    "**__/lock__** — قفل الروم الحالي.\n"
                    "**__/unlock__** — فتح الروم.\n"
                    "**__/clear__** — مسح رسائل.\n"
                    "**__/remove_one__** —  حذف روم أو رول واحد.\n"
                    "**__/block_room__** — منع أوامر البوت.\n"
                    "**__/Hide_rooms__** — إخفاء كل الرومات.\n"
                    "**__/Show_rooms__** — عرض رومات.\n"
                    "**__/allow_links__** — السماح بالروابط.\n"
                    "**__/block_links__** — منع الروابط."
                )
            },
            "advanced": {
                "emoji": "⚙️",
                "title": "إعدادات متقدمة",
                "short": "تحكم شامل في إعدادات البوت",
                "description": (
                    "**__/log__** — تفعيل اللوج.\n"
                    "**__/registration_panel__** —  لوحة تسجيل الإدارة .\n"
                    "**__/stop_log__** — إيقاف اللوج.\n"
                    "**__/log_deleted__** — لوج الرسائل المحذوفة.\n"
                    "**__/invite_logs__** — تتبع الدعوات.\n"
                    "**__/general_reply__** — إعداد الرد التلقائي في روم \n"
                    "**__/remove_invites__** — تصفير الدعوات.\n"
                    "**__/setup_welcome__** — نظام الترحيب.\n"
                    "**__/setup_suggestions__** — تعيين روم الاقتراحات.\n"
                    "**__/suggest__** — إرسال اقتراح.\n"
                    "**__/aliases__** — تعيين اختصار.\n"
                    "**__/show_aliases__** — عرض الاختصارات.\n"
                    "**__/remove_aliases__** — حذف اختصار مخصص .\n"
                    "**__/auto_reply__** — إضافة رد تلقائي.\n" 
                    "**__/list_replys__** — قائمه الردود التلقائية المفعلة.\n"           
                    "**__/ticket_points__** — عرض نقاط تجميع التذاكر.\n"
                    "**__/setup_ticket__** — إعداد وإرسال رسالة التذاكر.\n"
                    "**__/ticket_feedback__** —   تقيمات التذاكر المجمعه .\n"
                    "**__/auto_reply_remove__** — حذف رد تلقائي."
                    "**__/setup_ratings__** — تفعيل/تعطيل نظام التقييم."
                )
            },
            "economy": {
                "emoji": "💰",
                "title": "الاقتصاد",
                "short": "أوامر العملات والشراء",
                "description": (
                    "**__/bank__** — عرض بطاقة البنك.\n"
                    "**__/profile__** —   عرض ملفك أو ملف عضو آخر.\n"
                    "**__/top_kentos__** —  عرض قائمة الأغنياء بالكينتو.\n"
                    "**__/create_coupon__** — إنشاء كوبون من رصيدك.\n"
                    "**__/use_coupon__** — استخدام كوبون كنتو.\n"
                    "**__/trust__** — منح TRUST كل 24 ساعة.\n"
                    "**__/background** — تصفح الخلفيات.\n"
                    "**__/top_servers__** — عرض توب سيرفرات .\n"
                    "**__/top_tasks__** — عرض توب مهام .\n"
                    "**__/mine__** — ابدأ التعدين   Kentos كل ساعة .\n"
                )
            },
            "fun": {
                "emoji": "🎮",
                "title": "التسلية والألعاب",
                "short": "أوامر ترفيهية",
                "description": (
                    "**__/gx_wheel__** — عجلة الحظ GX.\n"
                    "**__/gx_wheel_channel__** — تحديد قنوات عجلة.\n" 
                    "**__/opinion__** — حكم أو وصف عشوائي.\n"
                    "**__/avatar_member__** — صورة عضو.\n"
                    "**__/film_suggestions__** — ترشيحات أفلام.\n"
                    "**__/anime_suggestions__** — ترشيحات أنمي."
                )
            },
            "extras": {
                "emoji": "🌀",
                "title": "أوامر إضافية",
                "short": "أنظمة وأوامر أخرى",
                "description": (
                    "**__/adhkar__** — تشغيل الأذكار.\n"
                    "**__/stop_adhkar__** — إيقاف الأذكار.\n"
                    "**__/used_for__** — عرض عدد مستخدمي البوت.\n"
                    "**__/embed__** — إرسال كلام بإيمبد.\n"
                    "**__/stop_room_emoji__** — إيقاف تحويل الصور إلى إيموجيات .\n"
                    "**__/room_emojis__** — تحديد الروم لتحويل الصور إلى إيموجيات .\n"
                    "**__/stopped_reply_emoji__** — إلغاء التفاعل  بالإيموجيات.\n"
                    "**__/auto_reply_emoji__** — اختيار روم والإيموجيات التي يرد بها  .\n"
                    "**__/tax__** — تعيين روم حساب الضريبه .\n"
                 )
            },
            "shortcuts": {
                "emoji": "⌨️",
                "title": "الاختصارات",
                "short": "أوامر الكتابة المختصرة",
                "description": (
                    "**__تحويل (K)__** — تحويل الكينتو بين الأعضاء.\n"
                    "**__رصيد (K)__** — عرض رصيدك أو  رصيد لعضو آخر.\n"
                    "**__ملف (P)__** — عرض ملفك الشخصي.\n"
                    "**__خلفيات (B)__** — عرض الخلفيات المتاحة.\n"
                    "**__توب__** — عرض أغنى 10 أعضاء."
                    "**__تعدين (minecoins)__** — ابدأ التعدين   الكينتوس كل ساعة.\n"
                )
            },
            # يمكنك إضافة باقي الأقسام هنا كما في النسخة السابقة...
        }

        self.add_item(SectionSelect(self.sections, author_id))
        self.add_item(ExtraMenuButton(author_id))  # ← زر القائمة الجديدة


# ============= ⚡ أمر /help الرئيسي ============= #

class HelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="عرض قائمة الأوامر")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        embed = discord.Embed(
            title="📘 دليل أوامر GxBot",
            description=(
                "🤖 **مرحبًا بك في GxBot!**\n\n"
                "يقدّم لك البوت تجربة متكاملة تجمع بين **الأوامر الإدارية** لإدارة السيرفر، "
                "و**أوامر التسلية والألعاب** لقضاء وقت ممتع مع أصدقائك، "
                "وكذلك أنظمة **الاقتصاد الشخصي**، والعديد من الأدوات والخدمات الذكية.\n\n"
                "📂 استخدم القائمة بالأسفل للاطّلاع على جميع الأقسام المتوفّرة واختر ما يناسبك.\n\n"
                "⚡ الإصدار الحالي: **1.5.0** — جاهز دائمًا لتقديم الأفضل!"
            ),
            color=discord.Color.blurple()
        )
        embed.set_image(url="attachment://help.png")

        view = HelpView(interaction.user.id)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(HelpCommand(bot))