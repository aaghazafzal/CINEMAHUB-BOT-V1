from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid
from info import ADMINS,MULTIPLE_DB, LOG_CHANNEL, OWNER_LNK, MELCOW_PHOTO
from database.users_chats_db import db, db2
from database.ia_filterdb import Media, Media2, db as db_stats, db2 as db2_stats
from utils import get_size, temp, get_settings, get_readable_time
from Script import script
from pyrogram.errors import ChatAdminRequired
import asyncio
import psutil
import logging
from time import time
from bot import botStartTime

"""-----------------------------------------https://t.me/dreamxbotz--------------------------------------"""

from pyrogram.enums import ChatMemberStatus, ChatType

@Client.on_message(filters.new_chat_members & filters.group)
async def save_group(bot, message):
    dreamx_check = [u.id for u in message.new_chat_members]
    if temp.ME in dreamx_check:
        chat = message.chat
        adder = message.from_user.mention if message.from_user else "Anonymous"
        try:
            total = await bot.get_chat_members_count(chat.id)
        except:
            total = "Unknown"

        # Log: new group or re-added
        exists = await db.get_chat(chat.id)
        if not exists:
            await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(chat.title, chat.id, total, adder))
            await db.add_chat(chat.id, chat.title)
        else:
            await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_G_READD.format(chat.title, chat.id, total, adder))

        # Banned group check
        if chat.id in temp.BANNED_CHATS:
            buttons = [[InlineKeyboardButton('📌 ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ 📌', url=OWNER_LNK)]]
            reply_markup = InlineKeyboardMarkup(buttons)
            k = await message.reply(
                text='<b>ᴄʜᴀᴛ ɴᴏᴛ ᴀʟʟᴏᴡᴇᴅ 🐞\n\nᴍʏ ᴀᴅᴍɪɴꜱ ʜᴀꜱ ʀᴇꜱᴛʀɪᴄᴛᴇᴅ ᴍᴇ ꜰʀᴏᴍ ᴡᴏʀᴋɪɴɢ ʜᴇʀᴇ ! ɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴋɴᴏᴡ ᴍᴏʀᴇ ᴀʙᴏᴜᴛ ɪᴛ ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ.</b>',
                reply_markup=reply_markup)
            try:
                await k.pin()
            except:
                pass
            await bot.leave_chat(chat.id)
            return

        buttons = [[InlineKeyboardButton("👩‍🌾 Bot Owner 👩‍🌾", url=OWNER_LNK)]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_text(
            text=f"<b>Thankyou For Adding Me In {chat.title} ❣️\n\nIf you have any questions & doubts about using me contact support.</b>",
            reply_markup=reply_markup)
        try:
            await db.connect_group(chat.id, message.from_user.id)
        except Exception as e:
            logging.error(f"DB error connecting group: {e}")
    else:
        settings = await get_settings(message.chat.id)
        if settings.get("welcome"):
            for u in message.new_chat_members:
                if temp.MELCOW.get('welcome'):
                    try:
                        await temp.MELCOW['welcome'].delete()
                    except:
                        pass
                try:
                    temp.MELCOW['welcome'] = await message.reply_photo(
                        photo=MELCOW_PHOTO,
                        caption=script.MELCOW_ENG.format(u.mention, message.chat.title),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📌 ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ 📌", url=OWNER_LNK)]
                        ]), parse_mode=enums.ParseMode.HTML)
                except Exception as e:
                    print(f"Welcome photo send failed: {e}")
        if settings.get("auto_delete"):
            await asyncio.sleep(600)
            try:
                if temp.MELCOW.get('welcome'):
                    await temp.MELCOW['welcome'].delete()
                    temp.MELCOW['welcome'] = None
            except:
                pass
               
# ── ChatMemberUpdated: Handles Admin-add (group), Channel add, Re-add, and ALL removals ──
@Client.on_chat_member_updated(filters.group | filters.channel)
async def log_new_chat(bot, update):
    new = update.new_chat_member
    old = update.old_chat_member
    if not new or not new.user.is_self:
        return  # Not about the bot, ignore

    chat = update.chat
    actor = update.from_user.mention if update.from_user else "Anonymous"
    is_channel = chat.type == ChatType.CHANNEL
    is_group = chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    try:
        total = await bot.get_chat_members_count(chat.id)
    except:
        total = "Unknown"

    # ── BOT ADDED / RE-ADDED ──
    if new.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
        if is_channel:
            # Channels always handled here (no new_chat_members event for channels)
            exists = await db.get_chat(chat.id)
            if not exists:
                await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_C.format(chat.title, chat.id, total, actor))
                await db.add_chat(chat.id, chat.title)
            else:
                await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_G_READD.format(chat.title, chat.id, total, actor))

        elif is_group:
            # For groups: only fire here if old status was kicked/banned/left (i.e. re-add)
            # Normal add is already handled by new_chat_members event (save_group)
            old_status = old.status if old else None
            if old_status in [ChatMemberStatus.BANNED, ChatMemberStatus.LEFT, ChatMemberStatus.RESTRICTED]:
                exists = await db.get_chat(chat.id)
                if not exists:
                    await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(chat.title, chat.id, total, actor))
                    await db.add_chat(chat.id, chat.title)
                else:
                    await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_G_READD.format(chat.title, chat.id, total, actor))
            # Always connect group to the adder
            if update.from_user:
                try:
                    await db.connect_group(chat.id, update.from_user.id)
                except Exception as e:
                    logging.error(f"DB connect_group error: {e}")

    # ── BOT REMOVED / KICKED ──
    elif new.status in [ChatMemberStatus.BANNED, ChatMemberStatus.LEFT, ChatMemberStatus.RESTRICTED]:
        if is_channel:
            await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_REMOVE_C.format(chat.title, chat.id, actor))
        elif is_group:
            await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_REMOVE_G.format(chat.title, chat.id, actor))

@Client.on_message(filters.command('leave') & filters.user(ADMINS))
async def leave_a_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply('Give me a chat id')
    chat = message.command[1]
    try:
        chat = int(chat)
    except:
        chat = chat
    try:
        buttons = [[
                  InlineKeyboardButton("📌 ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ 📌", url=OWNER_LNK)
                  ]]
        reply_markup=InlineKeyboardMarkup(buttons)
        await bot.send_message(
            chat_id=chat,
            text='<b>ʜᴇʟʟᴏ ꜰʀɪᴇɴᴅꜱ, \nᴍʏ ᴀᴅᴍɪɴ ʜᴀꜱ ᴛᴏʟᴅ ᴍᴇ ᴛᴏ ʟᴇᴀᴠᴇ ꜰʀᴏᴍ ɢʀᴏᴜᴘ, ꜱᴏ ɪ ʜᴀᴠᴇ ᴛᴏ ɢᴏ ! \nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ ᴍᴇ ᴀɢᴀɪɴ ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ.</b>',
            reply_markup=reply_markup,
        )

        await bot.leave_chat(chat)
        await message.reply(f"left the chat `{chat}`")
    except Exception as e:
        await message.reply(f'Error - {e}')

@Client.on_message(filters.command('disable') & filters.user(ADMINS))
async def disable_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply('Give me a chat id')
    r = message.text.split(None)
    if len(r) > 2:
        reason = message.text.split(None, 2)[2]
        chat = message.text.split(None, 2)[1]
    else:
        chat = message.command[1]
        reason = "No reason Provided"
    try:
        chat_ = int(chat)
    except:
        return await message.reply('Give Me A Valid Chat ID')
    cha_t = await db.get_chat(int(chat_))
    if not cha_t:
        return await message.reply("Chat Not Found In DB")
    if cha_t['is_disabled']:
        return await message.reply(f"This chat is already disabled:\nReason-<code> {cha_t['reason']} </code>")
    await db.disable_chat(int(chat_), reason)
    temp.BANNED_CHATS.append(int(chat_))
    await message.reply('Chat Successfully Disabled')
    try:
        buttons = [[
            InlineKeyboardButton('📌 ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ 📌', url=OWNER_LNK)
        ]]
        reply_markup=InlineKeyboardMarkup(buttons)
        await bot.send_message(
            chat_id=chat_, 
            text=f'<b>ʜᴇʟʟᴏ ꜰʀɪᴇɴᴅꜱ, \nᴍʏ ᴀᴅᴍɪɴ ʜᴀꜱ ᴛᴏʟᴅ ᴍᴇ ᴛᴏ ʟᴇᴀᴠᴇ ꜰʀᴏᴍ ɢʀᴏᴜᴘ, ꜱᴏ ɪ ʜᴀᴠᴇ ᴛᴏ ɢᴏ ! \nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ ᴍᴇ ᴀɢᴀɪɴ ᴄᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ..</b> \nReason : <code>{reason}</code>',
            reply_markup=reply_markup)
        await bot.leave_chat(chat_)
    except Exception as e:
        await message.reply(f"Error - {e}")


@Client.on_message(filters.command('enable') & filters.user(ADMINS))
async def re_enable_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply('Give me a chat id')
    chat = message.command[1]
    try:
        chat_ = int(chat)
    except:
        return await message.reply('Give Me A Valid Chat ID')
    sts = await db.get_chat(int(chat))
    if not sts:
        return await message.reply("Chat Not Found In DB !")
    if not sts.get('is_disabled'):
        return await message.reply('This chat is not yet disabled.')
    await db.re_enable_chat(int(chat_))
    temp.BANNED_CHATS.remove(int(chat_))
    await message.reply("Chat Successfully re-enabled")


@Client.on_message(filters.command('stats') & filters.user(ADMINS))
async def get_stats(bot, message):
    try:
        msg = await message.reply("<b>📊 ɢᴀᴛʜᴇʀɪɴɢ ꜱᴛᴀᴛꜱ ꜰʀᴏᴍ ᴀʟʟ ᴅʙꜱ... ⏳</b>")

        # ── User / Group Stats ──
        total_users, total_chats, banned_data = await asyncio.gather(
            db.total_users_count(),
            db.total_chat_count(),
            db.get_banned()
        )
        banned_users_count = len(banned_data[0])
        banned_chats_count = len(banned_data[1])
        try:
            premium = await db.all_premium_users()
        except:
            premium = "N/A"


        # ── System Stats ──
        uptime    = get_readable_time(time() - botStartTime)
        ram       = psutil.virtual_memory()
        cpu       = psutil.cpu_percent(interval=0.5)
        disk      = psutil.disk_usage('/')
        ram_pct   = ram.percent
        ram_used  = get_size(ram.used)
        ram_total = get_size(ram.total)
        disk_used  = get_size(disk.used)
        disk_total = get_size(disk.total)
        disk_pct   = round(disk.percent, 1)

        # ── Per-DB Stats (parallel) ──
        from database.ia_filterdb import get_all_db_stats
        db_stats_list = await get_all_db_stats()

        FREE_TIER_MB    = 512.0
        total_files_all = sum(s["files"]   for s in db_stats_list)
        total_used_mb   = sum(s["size_mb"] for s in db_stats_list)
        total_free_mb   = sum(s["free_mb"] for s in db_stats_list)
        total_cap_mb    = FREE_TIER_MB * len(db_stats_list)
        total_pct       = round((total_used_mb / total_cap_mb) * 100, 1) if total_cap_mb else 0

        # ── Build DB section ──
        def _bar(pct, length=10):
            filled = int(length * pct / 100)
            return '🟩' * filled + '⬜' * (length - filled)

        db_lines = ""
        for s in db_stats_list:
            if s.get("error"):
                db_lines += (
                    f"\n<b>├──[ 🗄 ᴅᴀᴛᴀʙᴀꜱᴇ {s['index']} ]</b>\n"
                    f"│ └ ⚠️ <b>Error:</b> <code>{s['error']}</code>\n"
                )
            else:
                icon  = "🔴" if s["pct"] >= 90 else ("🟡" if s["pct"] >= 70 else "🟢")
                bar   = _bar(s["pct"])
                db_lines += (
                    f"\n<b>├──[ 🗄 ᴅᴀᴛᴀʙᴀꜱᴇ {s['index']} ]</b>\n"
                    f"│ ├ 📁 ꜰɪʟᴇꜱ    ‣ <code>{s['files']:,}</code>\n"
                    f"│ ├ 💾 ᴜꜱᴇᴅ     ‣ <code>{s['size_mb']} MB</code>\n"
                    f"│ ├ 🆓 ꜰʀᴇᴇ    ‣ <code>{s['free_mb']} MB</code>\n"
                    f"│ ├ {icon} ᴜꜱᴀɢᴇ   ‣ <code>{s['pct']}%</code>\n"
                    f"│ └ {bar} <code>{s['pct']}%</code>\n"
                )


        text = (
            f"<b>╔══[ 🏆 ᴄɪɴᴇᴍᴀʜᴜʙ ʙᴏᴛ — ꜰᴜʟʟ ꜱᴛᴀᴛꜱ ]══⍟</b>\n"
            f"│\n"
            f"<b>├──[ 👥 ᴜꜱᴇʀ & ɢʀᴏᴜᴘ ᴅᴀᴛᴀ ]</b>\n"
            f"├⋟ ᴛᴏᴛᴀʟ ᴜꜱᴇʀꜱ   ‣ <code>{total_users:,}</code>\n"
            f"├⋟ ᴛᴏᴛᴀʟ ɢʀᴏᴜᴘꜱ  ‣ <code>{total_chats:,}</code>\n"
            f"├⋟ ᴘʀᴇᴍɪᴜᴍ       ‣ <code>{premium}</code>\n"
            f"├⋟ ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ  ‣ <code>{banned_users_count}</code>\n"
            f"├⋟ ʙᴀɴɴᴇᴅ ɢʀᴏᴜᴘꜱ ‣ <code>{banned_chats_count}</code>\n"
            f"│\n"
            f"<b>├──[ 🗃 ᴅᴀᴛᴀʙᴀꜱᴇ ꜱᴜᴍᴍᴀʀʏ ({len(db_stats_list)} ᴅʙꜱ ᴀᴄᴛɪᴠᴇ) ]</b>\n"
            f"├⋟ ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ   ‣ <code>{total_files_all:,}</code>\n"
            f"├⋟ ᴛᴏᴛᴀʟ ᴜꜱᴇᴅ    ‣ <code>{round(total_used_mb,1)} MB</code>\n"
            f"├⋟ ᴛᴏᴛᴀʟ ꜰʀᴇᴇ    ‣ <code>{round(total_free_mb,1)} MB</code>\n"
            f"├⋟ ᴛᴏᴛᴀʟ ᴄᴀᴘ     ‣ <code>{round(total_cap_mb,0)} MB ({len(db_stats_list)} × 512 MB)</code>\n"
            f"├⋟ ᴏᴠᴇʀᴀʟʟ ᴜꜱᴀɢᴇ ‣ <code>{total_pct}%</code>  {_bar(total_pct)}\n"
            f"│\n"
            f"<b>├──[ 🗂 ᴘᴇʀ-ᴅᴀᴛᴀʙᴀꜱᴇ ᴅᴇᴛᴀɪʟꜱ ]</b>\n"
            f"{db_lines}"
            f"│\n"
            f"<b>├──[ 🖥️ ꜱʏꜱᴛᴇᴍ ɪɴꜰᴏ ]</b>\n"
            f"├⋟ ʙᴏᴛ ᴜᴘᴛɪᴍᴇ  ‣ <code>{uptime}</code>\n"
            f"├⋟ ʀᴀᴍ ᴜꜱᴇᴅ    ‣ <code>{ram_used} / {ram_total} ({ram_pct}%)</code>  {_bar(ram_pct)}\n"
            f"├⋟ ᴄᴘᴜ ᴜꜱᴀɢᴇ   ‣ <code>{cpu}%</code>  {_bar(cpu)}\n"
            f"├⋟ ᴅɪꜱᴋ ᴜꜱᴇᴅ   ‣ <code>{disk_used} / {disk_total} ({disk_pct}%)</code>  {_bar(disk_pct)}\n"
            f"│\n"
            f"<b>╚═══════════════════════════════⍟</b>"
        )

        await msg.edit(text, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error In /stats: {e}")
        try:
            await msg.edit(f"<b>Error: <code>{e}</code></b>")
        except:
            pass


@Client.on_message(filters.command('invite') & filters.user(ADMINS))
async def gen_invite(bot, message):
    if len(message.command) == 1:
        return await message.reply('Give me a chat id')
    chat = message.command[1]
    try:
        chat = int(chat)
    except:
        return await message.reply('Give Me A Valid Chat ID')
    try:
        link = await bot.create_chat_invite_link(chat)
    except ChatAdminRequired:
        return await message.reply("Invite Link Generation Failed, Iam Not Having Sufficient Rights")
    except Exception as e:
        return await message.reply(f'Error {e}')
    await message.reply(f'Here is your Invite Link {link.invite_link}')

@Client.on_message(filters.command('ban') & filters.user(ADMINS))
async def ban_a_user(bot, message):
    if len(message.command) == 1:
        return await message.reply('Give me a user id / username')
    r = message.text.split(None)
    if len(r) > 2:
        reason = message.text.split(None, 2)[2]
        chat = message.text.split(None, 2)[1]
    else:
        chat = message.command[1]
        reason = "No reason Provided"
    try:
        chat = int(chat)
    except:
        pass
    try:
        k = await bot.get_users(chat)
    except PeerIdInvalid:
        return await message.reply("This is an invalid user, make sure I have met him before.")
    except IndexError:
        return await message.reply("This might be a channel, make sure its a user.")
    except Exception as e:
        return await message.reply(f'Error - {e}')
    else:
        jar = await db.get_ban_status(k.id)
        if jar['is_banned']:
            return await message.reply(f"{k.mention} is already banned\nReason: {jar['ban_reason']}")
        await db.ban_user(k.id, reason)
        temp.BANNED_USERS.append(k.id)
        await message.reply(f"Successfully banned {k.mention}")


    
@Client.on_message(filters.command('unban') & filters.user(ADMINS))
async def unban_a_user(bot, message):
    if len(message.command) == 1:
        return await message.reply('Give me a user id / username')
    r = message.text.split(None)
    if len(r) > 2:
        reason = message.text.split(None, 2)[2]
        chat = message.text.split(None, 2)[1]
    else:
        chat = message.command[1]
        reason = "No reason Provided"
    try:
        chat = int(chat)
    except:
        pass
    try:
        k = await bot.get_users(chat)
    except PeerIdInvalid:
        return await message.reply("This is an invalid user, make sure ia have met him before.")
    except IndexError:
        return await message.reply("Thismight be a channel, make sure its a user.")
    except Exception as e:
        return await message.reply(f'Error - {e}')
    else:
        jar = await db.get_ban_status(k.id)
        if not jar['is_banned']:
            return await message.reply(f"{k.mention} is not yet banned.")
        await db.remove_ban(k.id)
        temp.BANNED_USERS.remove(k.id)
        await message.reply(f"Successfully unbanned {k.mention}")


    
@Client.on_message(filters.command('users') & filters.user(ADMINS))
async def list_users(bot, message):
    dreamxbotz = await message.reply('Getting List Of Users')
    users = await db.get_all_users()
    out = "Users Saved In DB Are:\n\n"
    async for user in users:
        out += f"<a href=tg://user?id={user['id']}>{user['name']}</a>"
        if user['ban_status']['is_banned']:
            out += '( Banned User )'
        out += '\n'
    try:
        await dreamxbotz.edit_text(out)
    except MessageTooLong:
        with open('users.txt', 'w+') as outfile:
            outfile.write(out)
        await message.reply_document('users.txt', caption="List Of Users")

@Client.on_message(filters.command('chats') & filters.user(ADMINS))
async def list_chats(bot, message):
    dreamxbotz = await message.reply('Getting List Of chats')
    chats = await db.get_all_chats()
    out = "Chats Saved In DB Are:\n\n"
    async for chat in chats:
        out += f"**Title:** `{chat['title']}`\n**- ID:** `{chat['id']}`"
        if chat['chat_status']['is_disabled']:
            out += '( Disabled Chat )'
        out += '\n'
    try:
        await dreamxbotz.edit_text(out)
    except MessageTooLong:
        with open('chats.txt', 'w+') as outfile:
            outfile.write(out)
        await message.reply_document('chats.txt', caption="List Of Chats")


@Client.on_message(filters.command('group_cmd'))
async def group_commands(client, message):
    user = message.from_user.mention
    user_id = message.from_user.id
    await message.reply_text(script.GROUP_CMD, disable_web_page_preview=True)

@Client.on_message(filters.command('admin_cmd') & filters.user(ADMINS))
async def admin_commands(client, message):
    user = message.from_user.mention
    user_id = message.from_user.id
    await message.reply_text(script.ADMIN_CMD, disable_web_page_preview=True)
    