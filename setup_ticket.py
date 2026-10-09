# cogs/setup_ticket.py
# -*- coding: utf-8 -*-
"""
Ticket system cog implementing requested behavior.

Features:
- /setup_ticket sets panel_title, panel_desc and ask_on_open (ask user on open).
- Ticket embed includes Opened by, Collected by, Rating summary.
- Collect/Transfer/Close/Rating flows:
    * Collect: staff only (or allowed by admin role) - records collector and awards point.
    * Transfer: choose target from a select menu (eligible members), increments their points.
    * Close: requester posts a public confirm message (visible to channel). Confirm shows rating UI to opener; staff may close immediately.
    * Rating: only the opener's rating is accepted when rating UI shown; updates embed with avg/count and awards rater a point.
- Persistent JSON storage (async-locked).
- Persistent views re-registered on startup.
"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
import json, os, io, asyncio, datetime
from typing import Optional, Dict, Any, List, Tuple

BASE_DIR = os.path.dirname(__file__) or "."
TICKET_FILE = os.path.join(BASE_DIR, "ticket_data.json")
TICKET_POINTS_FILE = os.path.join(BASE_DIR, "ticket_points.json")
ACTIVE_TICKETS_FILE = os.path.join(BASE_DIR, "active_tickets.json")
TICKET_LOGS_FILE = os.path.join(BASE_DIR, "ticket_logs.json")
FEEDBACK_FILE = os.path.join(BASE_DIR, "ticket_feedback.json")

# In-memory stores (mirrors the files)
ticket_points: Dict[str, Dict[str, int]] = {}     # guild_id -> {user_id: points}
active_tickets: Dict[str, int] = {}               # key_str -> channel_id
ticket_logs: Dict[str, int] = {}                  # guild_id -> log_channel_id
ticket_configs: Dict[str, Dict[str, Any]] = {}    # guild_id -> config dict
ticket_feedback: Dict[str, Dict[str, Any]] = {}   # guild_id -> {ticket_key: {...}}

_FILE_LOCK = asyncio.Lock()

# -------------------------
# Key helpers (safe)
# -------------------------
def make_key(guild_id: int, user_id: int, ticket_type: str) -> str:
    token = "".join(ch for ch in str(ticket_type) if ch.isalnum() or ch in "_-")[:32]
    return f"{guild_id}:{user_id}:{token}"

def parse_key(key: str) -> Optional[Tuple[int,int,str]]:
    try:
        gid, uid, ttype = key.split(":", 2)
        return int(gid), int(uid), ttype
    except Exception:
        return None

# -------------------------
# Safe JSON read/write helpers
# -------------------------
def _read_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def _write_json(path: str, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[ticket] write error {path}: {e}")

async def load_all_files():
    global ticket_configs, ticket_points, active_tickets, ticket_logs, ticket_feedback
    async with _FILE_LOCK:
        ticket_configs = _read_json(TICKET_FILE, {})
        ticket_points = _read_json(TICKET_POINTS_FILE, {})
        active_tickets = _read_json(ACTIVE_TICKETS_FILE, {})
        ticket_logs = _read_json(TICKET_LOGS_FILE, {})
        ticket_feedback = _read_json(FEEDBACK_FILE, {})

async def save_ticket_configs():
    async with _FILE_LOCK:
        _write_json(TICKET_FILE, ticket_configs)

async def save_ticket_points():
    async with _FILE_LOCK:
        _write_json(TICKET_POINTS_FILE, ticket_points)

async def save_active_tickets():
    async with _FILE_LOCK:
        _write_json(ACTIVE_TICKETS_FILE, active_tickets)

async def save_ticket_logs():
    async with _FILE_LOCK:
        _write_json(TICKET_LOGS_FILE, ticket_logs)

async def save_ticket_feedback():
    async with _FILE_LOCK:
        _write_json(FEEDBACK_FILE, ticket_feedback)

# -------------------------
# Modal for ticket creation (ask_on_open=True)
# -------------------------
class TicketCreateModal(Modal):
    def __init__(self, label: str, value: str, desc_default: str, admin_role_id: Optional[int], image_url: Optional[str]):
        super().__init__(title="Reason for opening the ticket")  # ✅ عنوان المودال الجديد
        self._label = label
        self._value = value
        self._desc_default = desc_default
        self._admin_role_id = admin_role_id
        self._image_url = image_url

        # ✅ خانة واحدة فقط: السبب
        self.reason_input = TextInput(
            label="Reason for opening the ticket",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
            placeholder="Write your reason here..."
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        reason = str(self.reason_input.value).strip() or "No reason provided."
        await _create_ticket_channel(
            interaction,
            self._label,
            self._value,
            reason,  # ✅ السبب يستخدم كوصف التذكرة
            self._admin_role_id,
            self._image_url,
            custom_title=self._label  # ✅ العنوان هو نوع التذكرة
        )
        
# -------------------------
# Panel view (menu or buttons)
# -------------------------
class TicketPanelView(View):
    def __init__(self, admin_role_id: Optional[int], buttons: List[Dict[str, str]], image_url: Optional[str], use_menu: bool, ask_on_open: bool, panel_title: Optional[str], panel_desc: Optional[str]):
        super().__init__(timeout=None)
        self.admin_role_id = admin_role_id
        self.image_url = image_url
        self.use_menu = use_menu
        self.buttons_data = buttons or []
        self.ask_on_open = ask_on_open
        self.panel_title = panel_title
        self.panel_desc = panel_desc

        if self.use_menu:
            # 🟦 إنشاء القائمة المنسدلة
            opts = [
                discord.SelectOption(label=b["label"], description=b.get("desc", ""), value=b["value"])
                for b in self.buttons_data
            ]

            # ✅ نضيف خيار "تحديث القائمة" كخيار خاص داخل المنيو
            opts.append(
                discord.SelectOption(
                    label=" Refresh panel",
                    value="__refresh__"
                )
            )

            sel = Select(
                placeholder="🎟️ Choose ticket type",
                min_values=1,
                max_values=1,
                options=opts,
                custom_id="ticket:panel:select"
            )

            async def sel_cb(interaction: discord.Interaction):
                chosen_value = sel.values[0]

                # ✅ إذا تم اختيار "Refresh" (مفتوح للجميع)
                if chosen_value == "__refresh__":
                    embed = discord.Embed(
                        title=self.panel_title or "🎫 Ticket Panel",
                        description=self.panel_desc or "Choose ticket type from the menu below.",
                        color=discord.Color.blurple()
                    )
                    if self.image_url:
                        embed.set_image(url=self.image_url)

                    try:
                        await interaction.message.edit(
                            embed=embed,
                            view=TicketPanelView(
                                self.admin_role_id,
                                self.buttons_data,
                                self.image_url,
                                self.use_menu,
                                self.ask_on_open,
                                self.panel_title,
                                self.panel_desc
                            )
                        )
                        return await interaction.response.send_message("✅ تم تحديث اللوحة بنجاح.", ephemeral=True)
                    except Exception:
                        return await interaction.response.send_message("❌ فشل في تحديث اللوحة.", ephemeral=True)

                # ⚙️ باقي اختيارات المنيو (أنواع التيكت)
                chosen = next((o for o in sel.options if o.value == chosen_value), None)
                if not chosen:
                    return await interaction.response.send_message("❌ اختيار غير صالح.", ephemeral=True)

                if self.ask_on_open:
                    await interaction.response.send_modal(
                        TicketCreateModal(
                            chosen.label,
                            chosen.value,
                            chosen.description or self.panel_desc or "",
                            self.admin_role_id,
                            self.image_url
                        )
                    )
                else:
                    title = self.panel_title or chosen.label
                    desc = self.panel_desc or (chosen.description or "")
                    await _create_ticket_channel(
                        interaction,
                        chosen.label,
                        chosen.value,
                        desc,
                        self.admin_role_id,
                        self.image_url,
                        custom_title=title
                    )

            sel.callback = sel_cb
            self.add_item(sel)

        else:
            # 🟥 وضع الأزرار فقط
            for b in self.buttons_data:
                btn = Button(
                    label=b["label"],
                    style=discord.ButtonStyle.success,
                    custom_id=f"ticket:panel:btn:{b['value']}"
                )

                async def btn_cb(interaction: discord.Interaction, label=b["label"], value=b["value"], desc=b.get("desc", "")):
                    if self.ask_on_open:
                        await interaction.response.send_modal(
                            TicketCreateModal(
                                label,
                                value,
                                desc or self.panel_desc or "",
                                self.admin_role_id,
                                self.image_url
                            )
                        )
                    else:
                        title = self.panel_title or label
                        desc_use = self.panel_desc or desc or ""
                        await _create_ticket_channel(
                            interaction,
                            label,
                            value,
                            desc_use,
                            self.admin_role_id,
                            self.image_url,
                            custom_title=title
                        )

                btn.callback = btn_cb
                self.add_item(btn)
                                                
# -------------------------
# Close view placed inside ticket channel
# -------------------------
class CloseTicketView(View):
    def __init__(self, admin_role_id: Optional[int], key: str):
        super().__init__(timeout=None)
        self.admin_role_id = admin_role_id
        self.key = key
        collect_btn = Button(label="✅ Collect Ticket", style=discord.ButtonStyle.blurple, custom_id=f"ticket:collect:{key}")
        transfer_btn = Button(label="🔁 Transfer Collect", style=discord.ButtonStyle.primary, custom_id=f"ticket:transfer:{key}")
        close_btn = Button(label="🔒 Request Close", style=discord.ButtonStyle.danger, custom_id=f"ticket:close_req:{key}")
        collect_btn.callback = self._on_collect
        transfer_btn.callback = self._on_transfer
        close_btn.callback = self._on_request_close
        self.add_item(collect_btn)
        self.add_item(transfer_btn)
        self.add_item(close_btn)

    async def _is_staff(self, guild: discord.Guild, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        if self.admin_role_id:
            role = guild.get_role(self.admin_role_id)
            if role and role in member.roles:
                return True
        return False

    async def _on_collect(self, interaction: discord.Interaction):
        if not await self._is_staff(interaction.guild, interaction.user):
            return await interaction.response.send_message("This action is for staff only.", ephemeral=True)
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        ticket_points.setdefault(gid, {})
        ticket_points[gid][uid] = ticket_points[gid].get(uid, 0) + 1
        await save_ticket_points()
        # store collected_by in feedback
        ticket_feedback.setdefault(gid, {}).setdefault(self.key, {})
        ticket_feedback[gid][self.key]["collected_by"] = uid
        ticket_feedback[gid][self.key]["collected_at"] = datetime.datetime.utcnow().isoformat()
        await save_ticket_feedback()
        # disable collect button in view
        for ch in self.children:
            if getattr(ch, "custom_id", "").startswith("ticket:collect:"):
                ch.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass
        # update embed to show collector
        await _update_ticket_embed_collected(interaction.channel, gid, self.key, uid)
        await interaction.response.send_message(f"Collected. Your points: {ticket_points[gid][uid]}", ephemeral=True)

    async def _on_transfer(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        fb = ticket_feedback.get(gid, {}).get(self.key, {})
        collected_by = fb.get("collected_by")

        # ✅ السماح فقط للجامع الأصلي باستخدام الزر
        if not collected_by or str(interaction.user.id) != collected_by:
            return await interaction.response.send_message(
                "Only the member who collected this ticket can transfer it.",
                ephemeral=True
            )

        # build candidate list: staff-like members only (limit 25)
        candidates = []
        admin_role = interaction.guild.get_role(self.admin_role_id) if self.admin_role_id else None
        count = 0
        for mem in interaction.guild.members:
            if count >= 25:
                break
            if mem.bot:
                continue
            if (
                mem.guild_permissions.administrator
                or mem.guild_permissions.manage_guild
                or (admin_role and admin_role in mem.roles)
            ):
                candidates.append(discord.SelectOption(label=mem.display_name[:100], value=str(mem.id)))
                count += 1

        if not candidates:
            return await interaction.response.send_message("No eligible staff members found to transfer to.", ephemeral=True)

        sel = Select(
            placeholder="Select target to transfer collect to",
            min_values=1,
            max_values=1,
            options=candidates,
            custom_id=f"ticket:transfer_sel:{self.key}"
        )

        async def sel_cb(sel_inter: discord.Interaction):
            # ✅ التحقق مرة ثانية داخل القائمة (أمان إضافي)
            if str(sel_inter.user.id) != collected_by:
                return await sel_inter.response.send_message(
                    "You are not the collector of this ticket.",
                    ephemeral=True
                )

            target_id = sel.values[0]
            ticket_points.setdefault(gid, {})
            ticket_points[gid][target_id] = ticket_points[gid].get(target_id, 0) + 1
            ticket_feedback.setdefault(gid, {}).setdefault(self.key, {})["collected_by"] = str(target_id)
            ticket_feedback[gid][self.key]["collected_at"] = datetime.datetime.utcnow().isoformat()
            await save_ticket_points()
            await save_ticket_feedback()

            # ✅ تحديث الـ embed لعرض الجامع الجديد
            await _update_ticket_embed_collected(sel_inter.channel, gid, self.key, target_id)

            await sel_inter.response.send_message(f"✅ Collect transferred to <@{target_id}>.", ephemeral=True)

        sel.callback = sel_cb
        view = View(timeout=60)
        view.add_item(sel)
        await interaction.response.send_message("Choose target to transfer to:", view=view, ephemeral=True)

    async def _on_request_close(self, interaction: discord.Interaction):
        # Post a public confirm/cancel message in the ticket channel (visible to all)
        confirm_view = ConfirmClosePublicView(self.key, self.admin_role_id)
        try:
            await interaction.channel.send(
                content="⚠️ A close has been requested — confirm below to proceed (Confirm will show rating options if opener).",
                view=confirm_view
            )
            await interaction.response.send_message("Close request posted publicly in the channel.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Failed to post close confirmation in channel.", ephemeral=True)

# -------------------------
# Public confirm view (visible to all)
# -------------------------
class ConfirmClosePublicView(View):
    def __init__(self, key: str, admin_role_id: Optional[int]):
        super().__init__(timeout=None)
        self.key = key
        self.admin_role_id = admin_role_id

    @discord.ui.button(label="✅ Confirm Close", style=discord.ButtonStyle.green, custom_id="ticket:public_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        parsed = parse_key(self.key)
        if not parsed:
            return await interaction.response.send_message("Invalid ticket key.", ephemeral=True)
        gid, opener_id, ttype = parsed
        opener_allowed = (interaction.user.id == opener_id)
        staff_allowed = interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild
        if not (opener_allowed or staff_allowed):
            if self.admin_role_id:
                role = interaction.guild.get_role(self.admin_role_id)
                if role and role in interaction.user.roles:
                    staff_allowed = True
        if not (opener_allowed or staff_allowed):
            return await interaction.response.send_message("You don't have permission to confirm close.", ephemeral=True)

        if opener_allowed:
            try:
                await interaction.channel.send(content="⭐ Rating: the opener may rate 1-5 below. Others will see the rating but only opener's input will be accepted.", view=RatingPublicView(self.key))
                await interaction.response.send_message("Rating UI posted publicly.", ephemeral=True)
            except Exception:
                await interaction.response.send_message("Failed to post rating UI.", ephemeral=True)
        else:
            # staff closes immediately without rating
            ch = interaction.channel
            await interaction.response.send_message("Ticket will be closed by staff (no rating required).", ephemeral=True)
            await _final_close_ticket_and_cleanup(ch, interaction.user, self.key)

        # disable buttons in this public confirm message
        try:
            for ch in self.children:
                ch.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.gray, custom_id="ticket:public_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            for ch in self.children:
                ch.disabled = True
            await interaction.message.edit(view=self)
        except Exception:
            pass
        await interaction.response.send_message("Close canceled.", ephemeral=True)

# -------------------------
# Public rating UI (visible to all) — only opener's rating accepted
# -------------------------
class RatingPublicView(View):
    def __init__(self, key: str):
        super().__init__(timeout=None)
        self.key = key
        for i in range(1,6):
            btn = Button(label=str(i), style=discord.ButtonStyle.secondary, custom_id=f"ticket:public_rate:{key}:{i}")
            async def make_cb(interaction: discord.Interaction, rating=i):
                await _handle_public_rating(interaction, self.key, rating)
            btn.callback = make_cb
            self.add_item(btn)
        skip = Button(label="Skip rating", style=discord.ButtonStyle.gray, custom_id=f"ticket:public_rate:skip:{key}")
        async def skip_cb(interaction: discord.Interaction):
            await _handle_public_rating(interaction, self.key, None)
        skip.callback = skip_cb
        self.add_item(skip)

# -------------------------
# Core ticket functions
# -------------------------
async def _create_ticket_channel(interaction: discord.Interaction, label: str, value: str, desc: str, admin_role_id: Optional[int], image_url: Optional[str], custom_title: Optional[str]=None):
    guild = interaction.guild
    if not guild:
        return await interaction.response.send_message("This command only works in a guild.", ephemeral=True)
    ticket_type = value
    key = make_key(guild.id, interaction.user.id, ticket_type)

    # prevent duplicate
    if key in active_tickets:
        ch_id = active_tickets.get(key)
        ch = guild.get_channel(ch_id)
        if ch:
            return await interaction.response.send_message(f"You already have an open ticket: {ch.mention}", ephemeral=True)
        else:
            try:
                del active_tickets[key]; await save_active_tickets()
            except Exception:
                pass

    # create/find category
    category = discord.utils.get(guild.categories, name="🎫 tickets")
    if not category:
        try:
            category = await guild.create_category("🎫 tickets")
        except Exception:
            category = None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    if admin_role_id:
        role = guild.get_role(admin_role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

    safe_name = f"{value}-{interaction.user.name}".lower().replace(" ", "-")[:90]
    try:
        channel = await guild.create_text_channel(name=safe_name, category=category, overwrites=overwrites)
    except Exception as e:
        return await interaction.response.send_message(f"Failed to create ticket: {e}", ephemeral=True)

    active_tickets[key] = channel.id
    await save_active_tickets()

    await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

    # prepare embed
    title = custom_title or label
    em = discord.Embed(title=f"🎫 {title}", description=desc or "Please describe your issue.", color=discord.Color.green())
    em.add_field(name="Opened by", value=f"{interaction.user.mention}", inline=False)
    em.add_field(name="Collected by", value="—", inline=False)
    em.set_footer(text=f"Type: {value} • Opened at {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    if image_url:
        try:
            em.set_image(url=image_url)
        except Exception:
            pass

    view = CloseTicketView(admin_role_id, key)
    try:
        interaction.client.add_view(view)
    except Exception:
        pass

    try:
        msg = await channel.send(content=f"{interaction.user.mention} {guild.get_role(admin_role_id).mention if admin_role_id and guild.get_role(admin_role_id) else ''}".strip() or None, embed=em, view=view)
        # store embed message id in feedback for later updates
        gid = str(guild.id)
        ticket_feedback.setdefault(gid, {}).setdefault(key, {})["embed_id"] = msg.id
        await save_ticket_feedback()
    except Exception:
        try:
            msg = await channel.send(embed=em)
            gid = str(guild.id)
            ticket_feedback.setdefault(gid, {}).setdefault(key, {})["embed_id"] = msg.id
            await save_ticket_feedback()
        except Exception:
            pass

async def _update_ticket_embed_collected(channel: discord.TextChannel, gid: str, key: str, collector_uid: str):
    fb = ticket_feedback.setdefault(gid, {}).setdefault(key, {})
    embed_id = fb.get("embed_id")
    if not embed_id:
        return
    try:
        msg = await channel.fetch_message(embed_id)
        if not msg or not msg.embeds:
            return
        em = discord.Embed.from_dict(msg.embeds[0].to_dict())
        # update or add "Collected by" field
        found = False
        for idx, f in enumerate(em.fields):
            if f.name.lower().startswith("collected"):
                em.set_field_at(idx, name="Collected by", value=f"<@{collector_uid}>", inline=False)
                found = True
                break
        if not found:
            em.add_field(name="Collected by", value=f"<@{collector_uid}>", inline=False)
        # update footer to include collected_by
        footer_text = em.footer.text or ""
        new_footer = f"Collected by: {collector_uid} • {footer_text}"
        em.set_footer(text=new_footer)
        try:
            await msg.edit(embed=em)
        except Exception:
            pass
    except Exception:
        pass

async def _handle_public_rating(interaction: discord.Interaction, key: str, rating: Optional[int]):
    parsed = parse_key(key)
    if not parsed:
        return await interaction.response.send_message("Invalid ticket key.", ephemeral=True)
    gid, opener_id, ttype = parsed
    gid_s = str(gid)
    # Only opener allowed to submit rating (per requirement)
    if interaction.user.id != opener_id:
        return await interaction.response.send_message("Only the ticket opener can submit the rating.", ephemeral=True)
    if rating is not None:
        rec = ticket_feedback.setdefault(gid_s, {}).setdefault(key, {})
        rec.setdefault("ratings", []).append({"by": str(interaction.user.id), "rating": int(rating), "at": datetime.datetime.utcnow().isoformat()})
        vals = [r["rating"] for r in rec.get("ratings", []) if isinstance(r.get("rating"), int)]
        rec["average"] = (sum(vals)/len(vals)) if vals else 0.0
        rec["count"] = len(vals)
        await save_ticket_feedback()
        # award small point to rater
        ticket_points.setdefault(gid_s, {})
        ticket_points[gid_s][str(interaction.user.id)] = ticket_points[gid_s].get(str(interaction.user.id), 0) + 1
        await save_ticket_points()
        # update embed rating summary
        await _update_ticket_embed_rating(interaction.channel, gid_s, key)
        await interaction.response.send_message(f"Thanks — you rated {rating} star(s). Ticket will be closed now.", ephemeral=True)
    else:
        await interaction.response.send_message("Rating skipped. Ticket will be closed now.", ephemeral=True)
    # final close
    ch = interaction.channel
    await _final_close_ticket_and_cleanup(ch, interaction.user, key)

async def _update_ticket_embed_rating(channel: discord.TextChannel, gid: str, key: str):
    fb = ticket_feedback.get(gid, {}).get(key, {})
    embed_id = fb.get("embed_id")
    if not embed_id:
        return
    try:
        msg = await channel.fetch_message(embed_id)
        if not msg or not msg.embeds:
            return
        em = discord.Embed.from_dict(msg.embeds[0].to_dict())
        avg = fb.get("average", 0.0)
        cnt = fb.get("count", 0)
        summary = f"Average rating: {avg:.2f} ({cnt} ratings)"
        # replace or add field "Rating"
        found = False
        for idx, f in enumerate(em.fields):
            if f.name.lower().startswith("avg") or f.name.lower().startswith("rating"):
                em.set_field_at(idx, name="Rating", value=summary, inline=False)
                found = True
                break
        if not found:
            em.add_field(name="Rating", value=summary, inline=False)
        try:
            await msg.edit(embed=em)
        except Exception:
            pass
    except Exception:
        pass

async def _final_close_ticket_and_cleanup(channel: discord.TextChannel, closer: discord.Member, key: str):
    try:
        await save_transcript_for_channel(channel)
    except Exception:
        pass
    try:
        if key in active_tickets:
            del active_tickets[key]
            await save_active_tickets()
    except Exception:
        pass
    try:
        await channel.delete()
    except Exception:
        pass

async def save_transcript_for_channel(channel: discord.TextChannel):
    gid = str(channel.guild.id)
    log_ch_id = ticket_logs.get(gid)
    if not log_ch_id:
        return
    log_ch = channel.guild.get_channel(log_ch_id)
    if not log_ch:
        return
    messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
    lines = []
    for m in messages:
        atts = " ".join(a.url for a in m.attachments) if m.attachments else ""
        content = (m.content or "").replace("\n", " ")
        lines.append(f"[{m.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {m.author}: {content} {atts}\n")
    transcript = "".join(lines) or "(no messages)"
    b = io.BytesIO(transcript.encode("utf-8"))
    file = discord.File(b, filename=f"transcript-{channel.name}.txt")
    embed = discord.Embed(title="📑 Ticket Closed - Transcript", description=f"Channel: {channel.name}\nClosed at: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}", color=discord.Color.red())
    try:
        await log_ch.send(embed=embed, file=file)
    except Exception:
        pass

# -------------------------
# Cog: commands & startup
# -------------------------
class TicketManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await load_all_files()

    @commands.Cog.listener()
    async def on_ready(self):
        await load_all_files()
        # restore panel views by message_id
        for gid_str, cfg in list(ticket_configs.items()):
            try:
                msg_id = cfg.get("message_id")
                buttons = cfg.get("buttons", [])
                use_menu = cfg.get("use_menu", False)
                image_url = cfg.get("image_url")
                admin_role_id = cfg.get("admin_role")
                ask_on_open = cfg.get("ask_on_open", False)
                panel_title = cfg.get("panel_title")
                panel_desc = cfg.get("panel_desc")
                if msg_id:
                    try:
                        self.bot.add_view(TicketPanelView(admin_role_id, buttons, image_url, use_menu, ask_on_open, panel_title, panel_desc), message_id=msg_id)
                    except Exception:
                        pass
            except Exception:
                continue
        # restore CloseTicketView for active tickets
        for key_str, ch_id in list(active_tickets.items()):
            parsed = parse_key(key_str)
            if not parsed:
                try:
                    del active_tickets[key_str]; await save_active_tickets()
                except Exception:
                    pass
                continue
            gid, uid, ttype = parsed
            admin_role_id = ticket_configs.get(str(gid), {}).get("admin_role")
            try:
                self.bot.add_view(CloseTicketView(admin_role_id, key_str))
            except Exception:
                pass

    @app_commands.command(name="setup_ticket", description="Configure and post a ticket panel")
    @app_commands.describe(
        channel="Text channel to post the ticket panel",
        admin_role="Support/admin role (optional)",
        image_url="Image/GIF URL to show on the panel (optional)",
        use_menu="Use a select menu instead of buttons?",
        log_channel="Log channel to receive transcripts (optional)",
        panel_title="Default ticket embed title (used if ask_on_open=False)",
        panel_desc="Default ticket embed description (used if ask_on_open=False)",
        ask_on_open="Ask user for title & description when opening a ticket?"
    )
    async def setup_ticket(self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        admin_role: Optional[discord.Role] = None,
        image_url: Optional[str] = None,
        use_menu: bool = False,
        log_channel: Optional[discord.TextChannel] = None,
        panel_title: Optional[str] = None,
        panel_desc: Optional[str] = None,
        ask_on_open: bool = False,
        button1: Optional[str] = None, desc1: Optional[str] = None,
        button2: Optional[str] = None, desc2: Optional[str] = None,
        button3: Optional[str] = None, desc3: Optional[str] = None,
        button4: Optional[str] = None, desc4: Optional[str] = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)

        buttons = []
        if button1: buttons.append({"label": button1, "desc": desc1 or "", "value": "opt1"})
        if button2: buttons.append({"label": button2, "desc": desc2 or "", "value": "opt2"})
        if button3: buttons.append({"label": button3, "desc": desc3 or "", "value": "opt3"})
        if button4: buttons.append({"label": button4, "desc": desc4 or "", "value": "opt4"})
        if not buttons:
            return await interaction.response.send_message("You must provide at least one button (button1..4).", ephemeral=True)

        gid = str(interaction.guild.id)
        if log_channel:
            ticket_logs[gid] = log_channel.id
            await save_ticket_logs()

        cfg = {
            "buttons": buttons,
            "use_menu": use_menu,
            "image_url": image_url,
            "admin_role": admin_role.id if admin_role else None,
            "panel_title": panel_title,
            "panel_desc": panel_desc,
            "ask_on_open": ask_on_open,
            "channel_id": channel.id,
            "message_id": None
        }
        ticket_configs[gid] = cfg
        await save_ticket_configs()

        embed = discord.Embed(title=panel_title or "🎫 Ticket Panel", description=(panel_desc or ("Choose ticket type from the menu." if use_menu else "Choose ticket type from the buttons.")), color=discord.Color.blue())
        if image_url:
            try: embed.set_image(url=image_url)
            except Exception: pass

        try:
            msg = await channel.send(embed=embed, view=TicketPanelView(admin_role.id if admin_role else None, buttons, image_url, use_menu, ask_on_open, panel_title, panel_desc))
            ticket_configs[gid]["message_id"] = msg.id
            await save_ticket_configs()
        except Exception as e:
            return await interaction.response.send_message(f"Failed to post panel: {e}", ephemeral=True)

        await interaction.response.send_message(f"Ticket panel posted in {channel.mention}", ephemeral=True)

    @app_commands.command(name="ticket_points", description="Show ticket collect points (top 10)")
    @app_commands.describe(member="Optional member to show points for")
    async def ticket_points_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        gid = str(interaction.guild.id)
        if gid not in ticket_points or not ticket_points[gid]:
            return await interaction.response.send_message("No points recorded in this guild yet.", ephemeral=False)
        if member:
            pts = ticket_points[gid].get(str(member.id), 0)
            return await interaction.response.send_message(f"{member.mention} has **{pts}** ticket points in this guild.", ephemeral=False)
        sorted_points = sorted(ticket_points[gid].items(), key=lambda x: x[1], reverse=True)[:10]
        embed = discord.Embed(title=f"📊 Ticket Points - Top 10 ({interaction.guild.name})", color=discord.Color.gold())
        for uid, pts in sorted_points:
            user = interaction.guild.get_member(int(uid))
            name = user.display_name if user else uid
            embed.add_field(name=name, value=f"{pts} points", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="ticket_feedback", description="Show feedback/ratings summary for guild or member")
    @app_commands.describe(member="Optional member to show their collected-ticket count and average rating")
    async def ticket_feedback_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        gid = str(interaction.guild.id)
        fb = ticket_feedback.get(gid, {})
        if member:
            uid = str(member.id)
            collected_count = 0
            ratings_given = []
            for key, rec in fb.items():
                if rec.get("collected_by") == uid:
                    collected_count += 1
                for r in rec.get("ratings", []):
                    if r.get("by") == uid:
                        ratings_given.append(r.get("rating"))
            avg_rating = (sum(ratings_given)/len(ratings_given)) if ratings_given else 0.0
            return await interaction.response.send_message(f"{member.mention} collected **{collected_count}** tickets. Given ratings: {len(ratings_given)}, avg rating: {avg_rating:.2f}", ephemeral=False)
        items = []
        for key, rec in fb.items():
            cnt = rec.get("count", 0)
            avg = rec.get("average", 0.0)
            items.append((avg, cnt, key))
        if not items:
            return await interaction.response.send_message("No feedback recorded for this guild yet.", ephemeral=False)
        items.sort(reverse=True, key=lambda x: (x[0], x[1]))
        embed = discord.Embed(title=f"📊 Ticket Feedback Summary - {interaction.guild.name}", color=discord.Color.blurple())
        for avg, cnt, key in items[:10]:
            parsed = parse_key(key)
            opener_name = "unknown"
            ttype = "unknown"
            if parsed:
                gid_p, opener_id, ttype = parsed
                opener = interaction.guild.get_member(opener_id)
                opener_name = opener.display_name if opener else str(opener_id)
            embed.add_field(name=f"{opener_name} - {ttype}", value=f"Avg: {avg:.2f} ({cnt} ratings)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

# Setup function
async def setup(bot: commands.Bot):
    cog = TicketManager(bot)
    await bot.add_cog(cog)
    await load_all_files()
    # restore panel views
    for gid_str, cfg in list(ticket_configs.items()):
        try:
            msg_id = cfg.get("message_id")
            buttons = cfg.get("buttons", [])
            use_menu = cfg.get("use_menu", False)
            image_url = cfg.get("image_url")
            admin_role_id = cfg.get("admin_role")
            ask_on_open = cfg.get("ask_on_open", False)
            panel_title = cfg.get("panel_title")
            panel_desc = cfg.get("panel_desc")
            if msg_id:
                try:
                    bot.add_view(TicketPanelView(admin_role_id, buttons, image_url, use_menu, ask_on_open, panel_title, panel_desc), message_id=msg_id)
                except Exception:
                    pass
        except Exception:
            continue
    # restore close views for active tickets
    for key_str, ch_id in list(active_tickets.items()):
        parsed = parse_key(key_str)
        if not parsed:
            try:
                del active_tickets[key_str]
            except Exception:
                pass
            continue
        gid, uid, ttype = parsed
        admin_role_id = ticket_configs.get(str(gid), {}).get("admin_role")
        try:
            bot.add_view(CloseTicketView(admin_role_id, key_str))
        except Exception:
            pass