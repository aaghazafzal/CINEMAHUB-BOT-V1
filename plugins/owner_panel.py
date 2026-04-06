"""
╔══════════════════════════════════════╗
║   CINEMAHUB BOT — OWNER CONTROL PANEL
║   Only for ADMINS (Bot Owner)
╚══════════════════════════════════════╝
Commands:
  /glist         — List all groups bot is in
  /ginfo <id>    — Full info + control panel for a group
  /gverify <id>  — Toggle Verify On/Off for a group
  /gban <id>     — Ban a group
  /gunban <id>   — Unban a group
  /gleave <id>   — Force leave a group
  /greset <id>   — Reset group settings to default
  /gall          — Show all group IDs
"""

import logging
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from info import ADMINS, LOG_CHANNEL
from database.users_chats_db import db
from utils import get_settings, save_group_settings, temp

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# GUARD: Only ADMINS
# ─────────────────────────────────────────
def is_owner(user_id):
    return user_id in ADMINS


# ─────────────────────────────────────────
# Helper: Build Control Panel Buttons for a Group
# ─────────────────────────────────────────
async def build_group_control_panel(grp_id):
    settings = await get_settings(int(grp_id))
    gid = str(grp_id)

    verify   = settings.get("is_verify", True)
    autofl   = settings.get("auto_ffilter", True)
    spellck  = settings.get("spell_check", True)
    autodel  = settings.get("auto_delete", True)
    welcome  = settings.get("welcome", False)
    imdb     = settings.get("imdb", False)
    filesec  = settings.get("file_secure", False)
    maxbtn   = settings.get("max_btn", True)
    btn_mode = settings.get("button", True)

    buttons = [
        [
            InlineKeyboardButton("🔐 Verify",    callback_data=f"ownergs#is_verify#{verify}#{gid}"),
            InlineKeyboardButton("✅ ON" if verify else "❌ OFF", callback_data=f"ownergs#is_verify#{verify}#{gid}"),
        ],
        [
            InlineKeyboardButton("🔍 AutoFilter", callback_data=f"ownergs#auto_ffilter#{autofl}#{gid}"),
            InlineKeyboardButton("✅ ON" if autofl else "❌ OFF", callback_data=f"ownergs#auto_ffilter#{autofl}#{gid}"),
        ],
        [
            InlineKeyboardButton("🔤 SpellCheck", callback_data=f"ownergs#spell_check#{spellck}#{gid}"),
            InlineKeyboardButton("✅ ON" if spellck else "❌ OFF", callback_data=f"ownergs#spell_check#{spellck}#{gid}"),
        ],
        [
            InlineKeyboardButton("⏱ AutoDelete",  callback_data=f"ownergs#auto_delete#{autodel}#{gid}"),
            InlineKeyboardButton("✅ ON" if autodel else "❌ OFF", callback_data=f"ownergs#auto_delete#{autodel}#{gid}"),
        ],
        [
            InlineKeyboardButton("👋 Welcome Msg", callback_data=f"ownergs#welcome#{welcome}#{gid}"),
            InlineKeyboardButton("✅ ON" if welcome else "❌ OFF", callback_data=f"ownergs#welcome#{welcome}#{gid}"),
        ],
        [
            InlineKeyboardButton("🎬 IMDB Poster", callback_data=f"ownergs#imdb#{imdb}#{gid}"),
            InlineKeyboardButton("✅ ON" if imdb else "❌ OFF", callback_data=f"ownergs#imdb#{imdb}#{gid}"),
        ],
        [
            InlineKeyboardButton("🔒 File Secure", callback_data=f"ownergs#file_secure#{filesec}#{gid}"),
            InlineKeyboardButton("✅ ON" if filesec else "❌ OFF", callback_data=f"ownergs#file_secure#{filesec}#{gid}"),
        ],
        [
            InlineKeyboardButton("📋 Result Mode", callback_data=f"ownergs#button#{btn_mode}#{gid}"),
            InlineKeyboardButton("Button" if btn_mode else "Text", callback_data=f"ownergs#button#{btn_mode}#{gid}"),
        ],
        [
            InlineKeyboardButton("📊 Group Info", callback_data=f"ownergs#info#{gid}"),
        ],
        [
            InlineKeyboardButton("🔄 Reset Settings", callback_data=f"ownergs#reset#{gid}"),
            InlineKeyboardButton("🚫 Ban Group",       callback_data=f"ownergs#ban#{gid}"),
        ],
        [
            InlineKeyboardButton("✅ Unban Group", callback_data=f"ownergs#unban#{gid}"),
            InlineKeyboardButton("🚪 Force Leave", callback_data=f"ownergs#leave#{gid}"),
        ],
        [
            InlineKeyboardButton("🔙 Back to List", callback_data="ownergs#glist#1"),
        ],
    ]
    return buttons


# ─────────────────────────────────────────
# /glist — Paginated list of all groups
# ─────────────────────────────────────────
PAGE_SIZE = 8

@Client.on_message(filters.command("glist") & filters.private & filters.incoming)
async def glist_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    await send_glist(client, message, page=1)


async def send_glist(client, message_or_query, page=1):
    all_chats_cursor = await db.get_all_chats()
    all_chats = [chat async for chat in all_chats_cursor]
    total = len(all_chats)

    if total == 0:
        text = "<b>⚠️ Koi bhi group DB mein nahi hai!</b>"
        if hasattr(message_or_query, 'message'):
            return await message_or_query.message.edit(text)
        return await message_or_query.reply(text)

    start = (page - 1) * PAGE_SIZE
    end   = start + PAGE_SIZE
    page_chats = all_chats[start:end]
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    buttons = []
    for chat in page_chats:
        title   = chat.get("title", "Unknown")[:20]
        chat_id = chat.get("id", 0)
        banned  = chat.get("chat_status", {}).get("is_disabled", False)
        status  = "🚫" if banned else "✅"
        buttons.append([
            InlineKeyboardButton(f"{status} {title}", callback_data=f"ownergs#panel#{chat_id}"),
        ])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"ownergs#glist#{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="ownergs#noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"ownergs#glist#{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"ownergs#glist#{page}")])

    text = (
        f"<b>📋 सभी Groups ({total} total)</b>\n"
        f"<i>Group par click karo uska control panel kholne ke liye</i>\n\n"
        f"🟢 = Active &nbsp; 🚫 = Banned"
    )
    markup = InlineKeyboardMarkup(buttons)

    if hasattr(message_or_query, 'message'):
        try:
            await message_or_query.message.edit(text, reply_markup=markup)
        except:
            pass
    else:
        await message_or_query.reply(text, reply_markup=markup)


# ─────────────────────────────────────────
# /ginfo <group_id> — Direct group panel
# ─────────────────────────────────────────
@Client.on_message(filters.command("ginfo") & filters.private & filters.incoming)
async def ginfo_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    if len(message.command) < 2:
        return await message.reply("<b>Usage: /ginfo <group_id></b>")
    grp_id = message.command[1]
    try:
        grp_id = int(grp_id)
    except:
        return await message.reply("<b>Invalid Group ID!</b>")
    await send_group_panel(client, message, grp_id)


async def send_group_panel(client, msg_or_query, grp_id):
    try:
        chat = await client.get_chat(grp_id)
        title = chat.title
        try:
            members = await client.get_chat_members_count(grp_id)
        except:
            members = "Unknown"
    except:
        title = f"ID: {grp_id}"
        members = "Unknown"

    settings = await get_settings(int(grp_id))
    chat_status = await db.get_chat(grp_id)
    is_banned = chat_status.get("is_disabled", False) if chat_status else False

    text = (
        f"<b>⚙️ Group Control Panel</b>\n\n"
        f"🏷 <b>Name:</b> <code>{title}</code>\n"
        f"🆔 <b>ID:</b> <code>{grp_id}</code>\n"
        f"👥 <b>Members:</b> <code>{members}</code>\n"
        f"🔐 <b>Verify:</b> {'✅ ON' if settings.get('is_verify', True) else '❌ OFF'}\n"
        f"🚫 <b>Banned:</b> {'Yes 🔴' if is_banned else 'No 🟢'}\n\n"
        f"<i>Neeche buttons se koi bhi setting toggle karo:</i>"
    )
    buttons = await build_group_control_panel(grp_id)
    markup = InlineKeyboardMarkup(buttons)

    if hasattr(msg_or_query, 'message'):
        await msg_or_query.message.edit(text, reply_markup=markup)
    else:
        await msg_or_query.reply(text, reply_markup=markup)


# ─────────────────────────────────────────
# Callback Handler — All owner panel actions
# ─────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^ownergs#"))
async def owner_panel_callback(client, query):
    if not is_owner(query.from_user.id):
        return await query.answer("❌ Sirf Bot Owner kar sakta hai!", show_alert=True)

    parts = query.data.split("#")
    action = parts[1]

    # ── Page Navigation ──
    if action == "glist":
        page = int(parts[2]) if len(parts) > 2 else 1
        return await send_glist(client, query, page=page)

    if action == "noop":
        return await query.answer()

    # ── Open Group Panel ──
    if action == "panel":
        grp_id = int(parts[2])
        return await send_group_panel(client, query, grp_id)

    # ── Toggle Settings ──
    toggle_keys = ["is_verify", "auto_ffilter", "spell_check", "auto_delete", "welcome", "imdb", "file_secure", "button", "max_btn"]
    if action in toggle_keys:
        current_val_str = parts[2]
        grp_id = int(parts[3])
        # Parse boolean
        if current_val_str.lower() == "true":
            new_val = False
        else:
            new_val = True
        await save_group_settings(grp_id, action, new_val)
        status = "✅ ON" if new_val else "❌ OFF"
        await query.answer(f"{action} → {status}", show_alert=False)
        # Refresh the panel
        return await send_group_panel(client, query, grp_id)

    # ── Group Info ──
    if action == "info":
        grp_id = int(parts[2])
        try:
            chat = await client.get_chat(grp_id)
            title = chat.title
            desc  = chat.description or "N/A"
            invite = chat.invite_link or "N/A"
            try:
                members = await client.get_chat_members_count(grp_id)
            except:
                members = "Unknown"
        except Exception as e:
            return await query.answer(f"Error: {e}", show_alert=True)
        settings = await get_settings(int(grp_id))
        text = (
            f"<b>📊 Group Full Info</b>\n\n"
            f"🏷 <b>Name:</b> {title}\n"
            f"🆔 <b>ID:</b> <code>{grp_id}</code>\n"
            f"👥 <b>Members:</b> {members}\n"
            f"🔗 <b>Invite:</b> {invite}\n"
            f"📝 <b>Desc:</b> {desc[:100]}\n\n"
            f"🔐 <b>Verify:</b> {settings.get('is_verify', True)}\n"
            f"🔍 <b>AutoFilter:</b> {settings.get('auto_ffilter', True)}\n"
            f"🔤 <b>SpellCheck:</b> {settings.get('spell_check', True)}\n"
            f"⏱ <b>AutoDelete:</b> {settings.get('auto_delete', True)}\n"
            f"👋 <b>Welcome:</b> {settings.get('welcome', False)}\n"
            f"🎬 <b>IMDB:</b> {settings.get('imdb', False)}\n"
            f"🔒 <b>FileSecure:</b> {settings.get('file_secure', False)}\n"
        )
        back_btn = [[InlineKeyboardButton("🔙 Back", callback_data=f"ownergs#panel#{grp_id}")]]
        return await query.message.edit(text, reply_markup=InlineKeyboardMarkup(back_btn))

    # ── Reset Settings ──
    if action == "reset":
        grp_id = int(parts[2])
        await db.grp.update_one({'id': grp_id}, {'$unset': {'settings': ""}})
        if grp_id in temp.SETTINGS:
            del temp.SETTINGS[grp_id]
        await query.answer("✅ Settings reset ho gayi!", show_alert=True)
        return await send_group_panel(client, query, grp_id)

    # ── Ban Group ──
    if action == "ban":
        grp_id = int(parts[2])
        await db.disable_chat(grp_id, "Banned by Owner via Control Panel")
        temp.BANNED_CHATS.append(grp_id)
        await query.answer("🚫 Group ban ho gaya!", show_alert=True)
        try:
            await client.send_message(LOG_CHANNEL, f"<b>#GroupBanned\n\n🆔 ID: <code>{grp_id}</code>\nBanned by: {query.from_user.mention}</b>")
        except:
            pass
        return await send_group_panel(client, query, grp_id)

    # ── Unban Group ──
    if action == "unban":
        grp_id = int(parts[2])
        await db.re_enable_chat(grp_id)
        if grp_id in temp.BANNED_CHATS:
            temp.BANNED_CHATS.remove(grp_id)
        await query.answer("✅ Group unban ho gaya!", show_alert=True)
        try:
            await client.send_message(LOG_CHANNEL, f"<b>#GroupUnbanned\n\n🆔 ID: <code>{grp_id}</code>\nUnbanned by: {query.from_user.mention}</b>")
        except:
            pass
        return await send_group_panel(client, query, grp_id)

    # ── Force Leave ──
    if action == "leave":
        grp_id = int(parts[2])
        try:
            await client.leave_chat(grp_id)
            await query.answer("🚪 Bot ne group chhod diya!", show_alert=True)
            try:
                await client.send_message(LOG_CHANNEL, f"<b>#BotLeft\n\n🆔 ID: <code>{grp_id}</code>\nForce left by: {query.from_user.mention}</b>")
            except:
                pass
            return await send_glist(client, query, page=1)
        except Exception as e:
            return await query.answer(f"Error: {e}", show_alert=True)

    await query.answer()


# ─────────────────────────────────────────
# Quick inline commands (optional shortcuts)
# ─────────────────────────────────────────
@Client.on_message(filters.command("gverify") & filters.private & filters.incoming)
async def gverify_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    if len(message.command) < 2:
        return await message.reply("<b>Usage: /gverify &lt;group_id&gt;</b>")
    try:
        grp_id = int(message.command[1])
    except:
        return await message.reply("<b>Invalid Group ID!</b>")
    settings = await get_settings(grp_id)
    current = settings.get("is_verify", True)
    new_val = not current
    await save_group_settings(grp_id, "is_verify", new_val)
    status = "✅ ON" if new_val else "❌ OFF"
    await message.reply(f"<b>🔐 Group <code>{grp_id}</code> ka Verify → {status}</b>")


@Client.on_message(filters.command("gban") & filters.private & filters.incoming)
async def gban_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    if len(message.command) < 2:
        return await message.reply("<b>Usage: /gban &lt;group_id&gt;</b>")
    try:
        grp_id = int(message.command[1])
    except:
        return await message.reply("<b>Invalid Group ID!</b>")
    await db.disable_chat(grp_id, "Banned by Owner")
    if grp_id not in temp.BANNED_CHATS:
        temp.BANNED_CHATS.append(grp_id)
    await message.reply(f"<b>🚫 Group <code>{grp_id}</code> ban ho gaya!</b>")


@Client.on_message(filters.command("gunban") & filters.private & filters.incoming)
async def gunban_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    if len(message.command) < 2:
        return await message.reply("<b>Usage: /gunban &lt;group_id&gt;</b>")
    try:
        grp_id = int(message.command[1])
    except:
        return await message.reply("<b>Invalid Group ID!</b>")
    await db.re_enable_chat(grp_id)
    if grp_id in temp.BANNED_CHATS:
        temp.BANNED_CHATS.remove(grp_id)
    await message.reply(f"<b>✅ Group <code>{grp_id}</code> unban ho gaya!</b>")


@Client.on_message(filters.command("gleave") & filters.private & filters.incoming)
async def gleave_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    if len(message.command) < 2:
        return await message.reply("<b>Usage: /gleave &lt;group_id&gt;</b>")
    try:
        grp_id = int(message.command[1])
    except:
        return await message.reply("<b>Invalid Group ID!</b>")
    try:
        await client.leave_chat(grp_id)
        await message.reply(f"<b>🚪 Bot ne group <code>{grp_id}</code> chhod diya!</b>")
    except Exception as e:
        await message.reply(f"<b>Error: {e}</b>")


@Client.on_message(filters.command("greset") & filters.private & filters.incoming)
async def greset_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    if len(message.command) < 2:
        return await message.reply("<b>Usage: /greset &lt;group_id&gt;</b>")
    try:
        grp_id = int(message.command[1])
    except:
        return await message.reply("<b>Invalid Group ID!</b>")
    await db.grp.update_one({'id': grp_id}, {'$unset': {'settings': ""}})
    if grp_id in temp.SETTINGS:
        del temp.SETTINGS[grp_id]
    await message.reply(f"<b>🔄 Group <code>{grp_id}</code> ki settings reset ho gayi!</b>")


@Client.on_message(filters.command("gall") & filters.private & filters.incoming)
async def gall_cmd(client, message):
    if not is_owner(message.from_user.id):
        return await message.reply("<b>❌ Sirf Owner use kar sakta hai!</b>")
    all_chats_cursor = await db.get_all_chats()
    lines = []
    async for chat in all_chats_cursor:
        tid   = chat.get("id", "?")
        title = chat.get("title", "Unknown")[:25]
        ban   = "🚫" if chat.get("chat_status", {}).get("is_disabled") else "🟢"
        lines.append(f"{ban} <code>{tid}</code> — {title}")
    if not lines:
        return await message.reply("<b>Koi group nahi hai DB mein!</b>")
    text = "<b>📋 All Groups in DB:</b>\n\n" + "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n<i>...aur bhi hain</i>"
    await message.reply(text)
