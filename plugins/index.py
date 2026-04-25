import logging
import time
import re
import asyncio
import gc
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from info import ADMINS, INDEX_REQ_CHANNEL as LOG_CHANNEL, CHANNELS
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp, get_readable_time
from math import ceil

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

lock = asyncio.Lock()
ACTIVE_INDEX = {}  # {chat_id: {progress, total, status}}

# ──────────────────────────────────────────────────────────────────
# AUTO-INDEX REGISTRY — persists "last indexed message id" per channel
# stored in DB so bot knows where to resume from
# ──────────────────────────────────────────────────────────────────
_AUTO_INDEX_REGISTRY: dict = {}   # {chat_id: last_msg_id}

async def _load_auto_registry(bot):
    """Load auto-index channel registry from DB on startup."""
    from database.users_chats_db import db as user_db
    try:
        data = await user_db.get_bot_setting(bot.me.id, "AUTO_INDEX_REGISTRY", {})
        if isinstance(data, dict):
            _AUTO_INDEX_REGISTRY.update({int(k): int(v) for k, v in data.items()})
            logger.info(f"[AUTO-INDEX] Loaded {len(_AUTO_INDEX_REGISTRY)} channels from registry.")
    except Exception as e:
        logger.warning(f"[AUTO-INDEX] Could not load registry: {e}")

async def _save_auto_registry(bot):
    """Persist registry to DB."""
    from database.users_chats_db import db as user_db
    try:
        await user_db.update_bot_setting(bot.me.id, "AUTO_INDEX_REGISTRY",
                                         {str(k): v for k, v in _AUTO_INDEX_REGISTRY.items()})
    except Exception as e:
        logger.warning(f"[AUTO-INDEX] Could not save registry: {e}")


# ──────────────────────────────────────────────────────────────────
# CALLBACK: Cancel / Accept / Reject index
# ──────────────────────────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        return await query.answer("Cancelling Indexing")
    _, raju, chat, lst_msg_id, from_user = query.data.split("#")
    if raju == 'reject':
        await query.message.delete()
        await bot.send_message(int(from_user),
                               f'Your Submission for indexing {chat} has been declined by our moderators.',
                               reply_to_message_id=int(lst_msg_id))
        return

    if lock.locked():
        return await query.answer('Wait until previous process complete.', show_alert=True)
    msg = query.message

    await query.answer('Processing...⏳', show_alert=True)
    if int(from_user) not in ADMINS:
        await bot.send_message(int(from_user),
                               f'Your Submission for indexing {chat} has been accepted by our moderators and will be added soon.',
                               reply_to_message_id=int(lst_msg_id))
    await msg.edit(
        "Starting Indexing",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
        )
    )
    try:
        chat = int(chat)
    except:
        chat = chat
    await index_files_to_db(int(lst_msg_id), chat, msg, bot, register_auto=True)


# ──────────────────────────────────────────────────────────────────
# MESSAGE HANDLER: Parse Telegram link and start indexing
# ──────────────────────────────────────────────────────────────────
@Client.on_message((filters.forwarded | (filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")) & filters.text) & filters.private & filters.incoming)
async def send_for_index(bot, message):
    if message.text:
        regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return await message.reply('Invalid link')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int(("-100" + chat_id))
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return
    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply('This may be a private channel / group. Make me an admin over there to index the files.')
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('Invalid Link specified.')
    except Exception as e:
        logger.exception(e)
        return await message.reply(f'Errors - {e}')
    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except:
        return await message.reply('Make Sure That Iam An Admin In The Channel, if channel is private')
    if k.empty:
        return await message.reply('This may be group and i am not a admin of the group.')

    if message.from_user.id in ADMINS:
        buttons = [
            [InlineKeyboardButton('Yes', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}')],
            [InlineKeyboardButton('Close', callback_data='close_data')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        return await message.reply(
            f'Do you Want To Index This Channel/ Group ?\n\nChat ID/ Username: <code>{chat_id}</code>\nLast Message ID: <code>{last_msg_id}</code>\n\nɴᴇᴇᴅ sᴇᴛsᴋɪᴘ 👉🏻 /setskip',
            reply_markup=reply_markup)

    if type(chat_id) is int:
        try:
            link = (await bot.create_chat_invite_link(chat_id)).invite_link
        except ChatAdminRequired:
            return await message.reply('Make sure I am an admin in the chat and have permission to invite users.')
    else:
        link = f"@{message.forward_from_chat.username}"
    buttons = [
        [InlineKeyboardButton('Accept Index', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}')],
        [InlineKeyboardButton('Reject Index', callback_data=f'index#reject#{chat_id}#{message.id}#{message.from_user.id}')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await bot.send_message(LOG_CHANNEL,
                           f'#IndexRequest\n\nBy : {message.from_user.mention} (<code>{message.from_user.id}</code>)\nChat ID/ Username - <code> {chat_id}</code>\nLast Message ID - <code>{last_msg_id}</code>\nInviteLink - {link}',
                           reply_markup=reply_markup)
    await message.reply('ThankYou For the Contribution, Wait For My Moderators to verify the files.')


# ──────────────────────────────────────────────────────────────────
# SETSKIP — manually set the starting message ID offset
# ──────────────────────────────────────────────────────────────────
@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot, message):
    if ' ' in message.text:
        _, skip = message.text.split(" ")
        try:
            skip = int(skip)
        except:
            return await message.reply("Skip number should be an integer.")
        await message.reply(f"Successfully set SKIP number as {skip}")
        temp.CURRENT = int(skip)
    else:
        await message.reply("Give me a skip number")


def get_progress_bar(percent, length=10):
    """Creates an emoji-based progress bar."""
    filled = int(length * percent / 100)
    unfilled = length - filled
    return '🟩' * filled + '⬜️' * unfilled


# ──────────────────────────────────────────────────────────────────
# INDEX STATS — show current status
# ──────────────────────────────────────────────────────────────────
@Client.on_message(filters.command('index_stats') & filters.user(ADMINS))
async def get_index_stats(bot, message):
    from database.users_chats_db import db as user_db

    auto_status = await user_db.get_bot_setting(bot.me.id, "AUTO_INDEX", True)
    auto_text = "ENABLED ✅" if auto_status else "DISABLED ❌"

    active = ""
    if ACTIVE_INDEX:
        for chat_id, data in ACTIVE_INDEX.items():
            active += (
                f"\n✨ **Active Job:** `{chat_id}`\n"
                f"📊 Progress: `{data['percent']}%`\n"
                f"📥 Fetched: `{data['current']}/{data['total']}`\n"
                f"✅ Saved: `{data['saved']}`\n"
            )
    else:
        active = "\n❌ No manual indexing job running."

    registry_list = "\n".join([f"• `{ch}` — last msg `{mid}`" for ch, mid in _AUTO_INDEX_REGISTRY.items()]) or "None"

    text = (
        f"🛠 **Indexing Control Panel**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📢 **Auto-Index:** {auto_text}\n"
        f"📍 **Registered Channels:**\n{registry_list}\n"
        f"{active}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💡 *Use /auto_index to toggle Auto-Indexing.*"
    )

    btn = [
        [InlineKeyboardButton("🛑 STOP MANUAL INDEX", callback_data="index_cancel")],
        [InlineKeyboardButton("🔄 TOGGLE AUTO-INDEX", callback_data="toggle_auto_index_cb")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(btn))


@Client.on_callback_query(filters.regex("toggle_auto_index_cb"))
async def toggle_auto_index_cb(bot, query):
    from database.users_chats_db import db as user_db
    current_status = await user_db.get_bot_setting(bot.me.id, "AUTO_INDEX", True)
    await user_db.update_bot_setting(bot.me.id, "AUTO_INDEX", not current_status)
    await query.answer(f"Auto Indexing {'Disabled' if current_status else 'Enabled'}", show_alert=True)
    await get_index_stats(bot, query.message)


@Client.on_message(filters.command('stop_indexing') & filters.user(ADMINS))
async def stop_indexing_cmd(bot, message):
    temp.CANCEL = True
    ACTIVE_INDEX.clear()
    await message.reply_text("✅ Indexing has been requested to stop.")


# ──────────────────────────────────────────────────────────────────
# CORE INDEXING FUNCTION — FIXED
# Bug fixes:
#   1. temp.CURRENT is now ALWAYS reset to 0 at start of each job
#      (unless /setskip was used, which sets a specific value)
#   2. total_fetch is protected against negative values
#   3. current starts from 0, not from an old global state
# ──────────────────────────────────────────────────────────────────
async def index_files_to_db(lst_msg_id, chat, msg, bot, skip_from=0, register_auto=False, silent=False):
    """
    Index files from a channel into the database.
    
    Args:
        lst_msg_id: Last message ID to index up to
        chat: Chat ID or username
        msg: Message object for progress updates
        bot: Bot client
        skip_from: Start indexing from this message ID (0 = beginning)
        register_auto: If True, register this channel for auto-indexing
        silent: If True, don't update the message (for background auto-indexing)
    """
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    BATCH_SIZE = 200
    start_time = time.time()

    async with lock:
        try:
            # ✅ FIX 1: Always reset CURRENT for a fresh job
            # Only use temp.CURRENT if admin explicitly used /setskip
            # Otherwise start from beginning (or skip_from for auto-index resume)
            current = skip_from  # Start from specified position (default 0)
            temp.CANCEL = False

            total_messages = lst_msg_id
            # ✅ FIX 2: total_fetch must always be positive
            total_fetch = max(0, lst_msg_id - current)

            ACTIVE_INDEX[chat] = {
                "total": total_fetch,
                "current": 0,
                "percent": 0,
                "saved": 0
            }

            if total_messages <= 0 or total_fetch <= 0:
                if not silent:
                    await msg.edit(
                        f"🚫 No new messages to index.\n"
                        f"Total Messages: <code>{total_messages}</code>\n"
                        f"Already indexed up to message: <code>{current}</code>",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='close_data')]])
                    )
                return

            batches = ceil(total_fetch / BATCH_SIZE)
            batch_times = []

            if not silent:
                await msg.edit(
                    f"📊 Indexing Starting......\n"
                    f"💬 Total Messages: <code>{total_messages}</code>\n"
                    f"📋 To Fetch: <code>{total_fetch}</code>\n"
                    f"▶️ Starting from: <code>{current}</code>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Cancel', callback_data='index_cancel')]])
                )

            for batch in range(batches):
                if temp.CANCEL:
                    break
                batch_start = time.time()
                start_id = current + 1
                end_id = min(current + BATCH_SIZE, lst_msg_id)
                message_ids = list(range(start_id, end_id + 1))

                try:
                    # Handle FloodWait
                    while True:
                        try:
                            messages = await bot.get_messages(chat, message_ids)
                            break
                        except FloodWait as fw:
                            logger.warning(f"FloodWait {fw.value}s during indexing, sleeping...")
                            await asyncio.sleep(fw.value + 2)

                    if not isinstance(messages, list):
                        messages = [messages]
                except Exception as e:
                    logger.error(f"Batch fetch error: {e}")
                    errors += len(message_ids)
                    current += len(message_ids)
                    continue

                save_tasks = []
                for message in messages:
                    current += 1
                    try:
                        if message.empty:
                            deleted += 1
                            continue
                        elif not message.media:
                            no_media += 1
                            continue
                        elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
                            unsupported += 1
                            continue
                        media = getattr(message, message.media.value, None)
                        if not media:
                            unsupported += 1
                            continue
                        media.file_type = message.media.value
                        media.caption = message.caption
                        save_tasks.append(save_file(media))
                    except Exception:
                        errors += 1
                        continue

                if save_tasks:
                    results = await asyncio.gather(*save_tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            errors += 1
                        else:
                            ok, code = result
                            if ok:
                                total_files += 1
                            elif code == 0:
                                duplicate += 1
                            else:
                                errors += 1

                # Memory cleanup
                del messages
                del save_tasks
                gc.collect()

                batch_time = time.time() - batch_start
                batch_times.append(batch_time)
                progress = current - skip_from
                percentage = (progress / total_fetch) * 100 if total_fetch > 0 else 100
                ACTIVE_INDEX[chat].update({
                    "current": progress,
                    "percent": round(percentage, 1),
                    "saved": total_files
                })
                elapsed = time.time() - start_time
                avg_batch_time = sum(batch_times) / len(batch_times) if batch_times else 1
                eta = max(0, (total_fetch - progress) / BATCH_SIZE * avg_batch_time)
                progress_bar = get_progress_bar(int(percentage))

                if not silent:
                    try:
                        await msg.edit(
                            f"📊 Indexing Progress 📦 Batch {batch + 1}/{batches}\n"
                            f"{progress_bar} <code>{percentage:.1f}%</code>\n\n"
                            f"Total Messages: <code>{total_messages}</code>\n"
                            f"Total Fetched: <code>{total_fetch}</code>\n"
                            f"Fetched: <code>{progress}</code>\n"
                            f"Saved: <code>{total_files}</code>\n"
                            f"Duplicates: <code>{duplicate}</code>\n"
                            f"Deleted: <code>{deleted}</code>\n"
                            f"Non-Media: <code>{no_media + unsupported}</code> (Unsupported: <code>{unsupported}</code>)\n"
                            f"Errors: <code>{errors}</code>\n"
                            f"⏱️ Elapsed: <code>{get_readable_time(elapsed)}</code>\n"
                            f"⏰ ETA: <code>{get_readable_time(eta)}</code>",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Cancel', callback_data='index_cancel')]])
                        )
                    except Exception:
                        pass

                # Yield event loop every batch
                await asyncio.sleep(0.5)

            # ── Register channel for auto-indexing ──
            if register_auto:
                _AUTO_INDEX_REGISTRY[int(chat) if str(chat).lstrip('-').isnumeric() else chat] = current
                await _save_auto_registry(bot)
                logger.info(f"[AUTO-INDEX] Registered channel {chat} at msg {current}")

            elapsed = time.time() - start_time
            if not silent:
                await msg.edit(
                    f"✅ Indexing Completed!\n"
                    f"Total Messages: <code>{total_messages}</code>\n"
                    f"Total Fetched: <code>{total_fetch}</code>\n"
                    f"Fetched: <code>{current - skip_from}</code>\n"
                    f"Saved: <code>{total_files}</code>\n"
                    f"Duplicates: <code>{duplicate}</code>\n"
                    f"Deleted: <code>{deleted}</code>\n"
                    f"Non-Media: <code>{no_media + unsupported}</code> (Unsupported: <code>{unsupported}</code>)\n"
                    f"Errors: <code>{errors}</code>\n"
                    f"⏱️ Elapsed: <code>{get_readable_time(elapsed)}</code>\n"
                    f"{'📡 Auto-monitoring: ENABLED ✅' if register_auto else ''}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='close_data')]])
                )
            ACTIVE_INDEX.pop(chat, None)
            return current  # Return last indexed msg ID for auto-index resume

        except Exception as e:
            ACTIVE_INDEX.pop(chat, None)
            if not silent:
                await msg.edit(
                    f"❌ Error: <code>{e}</code>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='close_data')]])
                )
            logger.exception(f"Indexing error for {chat}: {e}")


# ──────────────────────────────────────────────────────────────────
# AUTO-INDEX BACKGROUND LOOP
# Runs every 30 minutes, checks all registered channels for new msgs
# ──────────────────────────────────────────────────────────────────
async def auto_index_loop(bot):
    """
    Background task: every 30 minutes, check all registered channels
    for new messages and index them silently into the DB.
    """
    await asyncio.sleep(60)  # Wait 60s after startup before first check
    await _load_auto_registry(bot)

    # Also add channels from info.py CHANNELS list to auto-registry
    for ch in CHANNELS:
        ch_int = int(ch) if str(ch).lstrip('-').isnumeric() else ch
        if ch_int not in _AUTO_INDEX_REGISTRY:
            _AUTO_INDEX_REGISTRY[ch_int] = 0  # Start from beginning if not tracked

    logger.info(f"[AUTO-INDEX] Starting auto-index loop with {len(_AUTO_INDEX_REGISTRY)} channels.")

    while True:
        try:
            from database.users_chats_db import db as user_db
            auto_enabled = await user_db.get_bot_setting(bot.me.id, "AUTO_INDEX", True)

            if auto_enabled and _AUTO_INDEX_REGISTRY:
                for chat_id, last_indexed_id in list(_AUTO_INDEX_REGISTRY.items()):
                    try:
                        if temp.CANCEL:
                            break

                        # Get latest message ID in channel
                        chat_info = await bot.get_chat(chat_id)
                        latest_msg_id = None

                        # Use iter_messages to get the latest message ID
                        async for msg in bot.get_chat_history(chat_id, limit=1):
                            latest_msg_id = msg.id
                            break

                        if not latest_msg_id:
                            continue

                        if latest_msg_id <= last_indexed_id:
                            logger.info(f"[AUTO-INDEX] {chat_id}: No new messages (last={last_indexed_id}, latest={latest_msg_id})")
                            continue

                        new_count = latest_msg_id - last_indexed_id
                        logger.info(f"[AUTO-INDEX] {chat_id}: {new_count} new messages to index (from {last_indexed_id} to {latest_msg_id})")

                        # Send a log notification to LOG_CHANNEL
                        try:
                            await bot.send_message(
                                LOG_CHANNEL,
                                f"🔄 **Auto-Indexing Started**\n"
                                f"📢 Channel: `{chat_id}`\n"
                                f"📨 New Messages: `{new_count}`\n"
                                f"▶️ From msg `{last_indexed_id}` → `{latest_msg_id}`"
                            )
                        except Exception:
                            pass

                        # Create a dummy message for silent indexing
                        dummy_msg = await bot.send_message(
                            LOG_CHANNEL,
                            f"⏳ Auto-indexing `{chat_id}`..."
                        )

                        # Index only the NEW messages (from last_indexed_id onwards)
                        new_last_id = await index_files_to_db(
                            lst_msg_id=latest_msg_id,
                            chat=chat_id,
                            msg=dummy_msg,
                            bot=bot,
                            skip_from=last_indexed_id,
                            register_auto=False,
                            silent=False
                        )

                        # Update registry with new last ID
                        if new_last_id:
                            _AUTO_INDEX_REGISTRY[chat_id] = new_last_id
                            await _save_auto_registry(bot)

                        # Small delay between channels to avoid flood
                        await asyncio.sleep(10)

                    except FloodWait as fw:
                        logger.warning(f"[AUTO-INDEX] FloodWait {fw.value}s")
                        await asyncio.sleep(fw.value + 5)
                    except Exception as e:
                        logger.error(f"[AUTO-INDEX] Error for channel {chat_id}: {e}")
                        continue

        except Exception as e:
            logger.error(f"[AUTO-INDEX] Loop error: {e}")

        # Wait 30 minutes before next check
        await asyncio.sleep(30 * 60)



@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        return await query.answer("Cancelling Indexing")
    _, raju, chat, lst_msg_id, from_user = query.data.split("#")
    if raju == 'reject':
        await query.message.delete()
        await bot.send_message(int(from_user),
                               f'Your Submission for indexing {chat} has been declined by our moderators.',
                               reply_to_message_id=int(lst_msg_id))
        return

    if lock.locked():
        return await query.answer('Wait until previous process complete.', show_alert=True)
    msg = query.message

    await query.answer('Processing...⏳', show_alert=True)
    if int(from_user) not in ADMINS:
        await bot.send_message(int(from_user),
                               f'Your Submission for indexing {chat} has been accepted by our moderators and will be added soon.',
                               reply_to_message_id=int(lst_msg_id))
    await msg.edit(
        "Starting Indexing",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
        )
    )
    try:
        chat = int(chat)
    except:
        chat = chat
    await index_files_to_db(int(lst_msg_id), chat, msg, bot)


@Client.on_message((filters.forwarded | (filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")) & filters.text ) & filters.private & filters.incoming)
async def send_for_index(bot, message):
    if message.text:
        regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return await message.reply('Invalid link')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id  = int(("-100" + chat_id))
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return
    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply('This may be a private channel / group. Make me an admin over there to index the files.')
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('Invalid Link specified.')
    except Exception as e:
        logger.exception(e)
        return await message.reply(f'Errors - {e}')
    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except:
        return await message.reply('Make Sure That Iam An Admin In The Channel, if channel is private')
    if k.empty:
        return await message.reply('This may be group and i am not a admin of the group.')

    if message.from_user.id in ADMINS:
        buttons = [
            [InlineKeyboardButton('Yes', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}')],
            [InlineKeyboardButton('Close', callback_data='close_data')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        return await message.reply(
            f'Do you Want To Index This Channel/ Group ?\n\nChat ID/ Username: <code>{chat_id}</code>\nLast Message ID: <code>{last_msg_id}</code>\n\nɴᴇᴇᴅ sᴇᴛsᴋɪᴘ 👉🏻 /setskip',
            reply_markup=reply_markup)

    if type(chat_id) is int:
        try:
            link = (await bot.create_chat_invite_link(chat_id)).invite_link
        except ChatAdminRequired:
            return await message.reply('Make sure I am an admin in the chat and have permission to invite users.')
    else:
        link = f"@{message.forward_from_chat.username}"
    buttons = [
        [InlineKeyboardButton('Accept Index', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}')],
        [InlineKeyboardButton('Reject Index', callback_data=f'index#reject#{chat_id}#{message.id}#{message.from_user.id}')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await bot.send_message(LOG_CHANNEL,
                           f'#IndexRequest\n\nBy : {message.from_user.mention} (<code>{message.from_user.id}</code>)\nChat ID/ Username - <code> {chat_id}</code>\nLast Message ID - <code>{last_msg_id}</code>\nInviteLink - {link}',
                           reply_markup=reply_markup)
    await message.reply('ThankYou For the Contribution, Wait For My Moderators to verify the files.')


@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot, message):
    if ' ' in message.text:
        _, skip = message.text.split(" ")
        try:
            skip = int(skip)
        except:
            return await message.reply("Skip number should be an integer.")
        await message.reply(f"Successfully set SKIP number as {skip}")
        temp.CURRENT = int(skip)
    else:
        await message.reply("Give me a skip number")

def get_progress_bar(percent, length=10):
    """Creates an emoji-based progress bar."""
    filled = int(length * percent / 100)
    unfilled = length - filled
    return '🟩' * filled + '⬜️' * unfilled

@Client.on_message(filters.command('index_stats') & filters.user(ADMINS))
async def get_index_stats(bot, message):
    from info import CHANNELS
    from database.users_chats_db import db as user_db
    
    auto_status = await user_db.get_bot_setting(bot.me.id, "AUTO_INDEX", True)
    auto_text = "ENABLED ✅" if auto_status else "DISABLED ❌"
    
    active = ""
    if ACTIVE_INDEX:
        for chat_id, data in ACTIVE_INDEX.items():
            active += (
                f"\n✨ **Active Job:** `{chat_id}`\n"
                f"📊 Progress: `{data['percent']}%`\n"
                f"📥 Fetched: `{data['current']}/{data['total']}`\n"
                f"✅ Saved: `{data['saved']}`\n"
            )
    else:
        active = "\n❌ No manual indexing job running."

    ch_list = "\n".join([f"• `{ch}`" for ch in CHANNELS]) if CHANNELS else "None"
    
    text = (
        f"🛠 **Indexing Control Panel**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📢 **Auto-Index:** {auto_text}\n"
        f"📍 **Monitoring Channels:**\n{ch_list}\n"
        f"{active}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💡 *Use /auto_index to toggle Auto-Indexing.*"
    )
    
    btn = [
        [InlineKeyboardButton("🛑 STOP MANUAL INDEX", callback_data="index_cancel")],
        [InlineKeyboardButton("🔄 TOGGLE AUTO-INDEX", callback_data="toggle_auto_index_cb")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(btn))

@Client.on_callback_query(filters.regex("toggle_auto_index_cb"))
async def toggle_auto_index_cb(bot, query):
    from database.users_chats_db import db as user_db
    current_status = await user_db.get_bot_setting(bot.me.id, "AUTO_INDEX", True)
    await user_db.update_bot_setting(bot.me.id, "AUTO_INDEX", not current_status)
    await query.answer(f"Auto Indexing {'Disabled' if current_status else 'Enabled'}", show_alert=True)
    await get_index_stats(bot, query.message)

@Client.on_message(filters.command('stop_indexing') & filters.user(ADMINS))
async def stop_indexing_cmd(bot, message):
    temp.CANCEL = True
    ACTIVE_INDEX.clear()
    await message.reply_text("✅ Indexing has been requested to stop.")


async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    BATCH_SIZE = 200
    start_time = time.time()

    async with lock:
        try:
            current = temp.CURRENT
            temp.CANCEL = False
            total_messages = lst_msg_id
            total_fetch = lst_msg_id - current
            ACTIVE_INDEX[chat] = {
                "total": total_fetch,
                "current": 0,
                "percent": 0,
                "saved": 0
            }
            if total_messages <= 0:
                await msg.edit(
                    "🚫 No Messages To Index.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='close_data')]])
                )
                return
            batches = ceil(total_messages / BATCH_SIZE)
            batch_times = []
            await msg.edit(
                f"📊 Indexing Starting......\n"
                f"💬 Total Messages: <code>{total_messages}</code>\n"
                f"📋 Total Fetch: <code> {total_fetch}</code>\n"
                f"⏰ Elapsed: <code>{get_readable_time(time.time() - start_time)}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Cancel', callback_data='index_cancel')]])
            )
            for batch in range(batches):
                if temp.CANCEL:
                    break
                batch_start = time.time()
                start_id = current + 1
                end_id = min(current + BATCH_SIZE, lst_msg_id)
                message_ids = range(start_id, end_id + 1)
                try:
                    messages = await bot.get_messages(chat, list(message_ids))
                    if not isinstance(messages, list):
                        messages = [messages]
                except Exception as e:
                    errors += len(message_ids)
                    current += len(message_ids)
                    continue
                save_tasks = []
                for message in messages:
                    current += 1
                    try:
                        if message.empty:
                            deleted += 1
                            continue
                        elif not message.media:
                            no_media += 1
                            continue
                        elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
                            unsupported += 1
                            continue
                        media = getattr(message, message.media.value, None)
                        if not media:
                            unsupported += 1
                            continue
                        media.file_type = message.media.value
                        media.caption = message.caption
                        save_tasks.append(save_file(media))

                    except Exception:
                        errors += 1
                        continue
                results = await asyncio.gather(*save_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        errors += 1
                    else:
                        ok, code = result
                        if ok:
                            total_files += 1
                        elif code == 0:
                            duplicate += 1
                        elif code == 2:
                            errors += 1
                batch_time = time.time() - batch_start
                batch_times.append(batch_time)
                progress = current - temp.CURRENT
                percentage = (progress / total_fetch) * 100
                ACTIVE_INDEX[chat].update({
                    "current": progress,
                    "percent": round(percentage, 1),
                    "saved": total_files
                })
                elapsed = time.time() - start_time
                avg_batch_time = sum(batch_times) / len(batch_times) if batch_times else 1
                eta = (total_fetch - progress) / BATCH_SIZE * avg_batch_time
                progress_bar = get_progress_bar(int(percentage))
                await msg.edit(
                    f"📊 Indexing Progress 📦 Batch {batch + 1}/{batches}\n"
                    f"{progress_bar} <code>{percentage:.1f}%</code>\n\n"
                    f"Total Messages: <code>{total_messages}</code>\n"
                    f"Total Fetched: <code>{total_fetch}</code>\n"
                    f"Fetched: <code>{current}</code>\n"
                    f"Saved: <code>{total_files}</code>\n"
                    f"Duplicates: <code>{duplicate}</code>\n"
                    f"Deleted: <code>{deleted}</code>\n"
                    f"Non-Media: <code>{no_media + unsupported}</code> (Unsupported: <code>{unsupported}</code>)\n"
                    f"Errors: <code>{errors}</code>\n"
                    f"⏱️ Elapsed: <code>{get_readable_time(elapsed)}</code>\n"
                    f"⏰ ETA: <code>{get_readable_time(eta)}</code>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Cancel', callback_data='index_cancel')]])
                )
            elapsed = time.time() - start_time
            await msg.edit(
                f"✅ Indexing Completed!\n"
                f"Total Messages: <code>{total_messages}</code>\n"
                f"Total Fetched: <code>{total_fetch}</code>\n"
                f"Fetched: <code>{current}</code>\n"
                f"Saved: <code>{total_files}</code>\n"
                f"Duplicates: <code>{duplicate}</code>\n"
                f"Deleted: <code>{deleted}</code>\n"
                f"Non-Media: <code>{no_media + unsupported}</code> (Unsupported: <code>{unsupported}</code>)\n"
                f"Errors: <code>{errors}</code>\n"
                f"⏱️ Elapsed: <code>{get_readable_time(elapsed)}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='close_data')]])
            )
            ACTIVE_INDEX.pop(chat, None)
        except Exception as e:
            ACTIVE_INDEX.pop(chat, None)
            await msg.edit(
                f"❌ Error: <code>{e}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Close', callback_data='close_data')]])
            )

