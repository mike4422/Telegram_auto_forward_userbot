import asyncio
import json
import os
import re
import time
from collections import defaultdict
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage

API_ID = 26376666  # <-- Your api_id here
API_HASH = '61ee2def31a7a12026ecfa1c72474489'
PHONE_NUMBER = '+14053131520'  # <-- Your phone number

SETTINGS_FILE = "user_settings.json"

# --- Utility: Username Cleaning ---
def clean_username(u):
    u = u.strip()
    if u.startswith("https://t.me/"):
        u = u.replace("https://t.me/", "")
    elif u.startswith("http://t.me/"):
        u = u.replace("http://t.me/", "")
    elif u.startswith("t.me/"):
        u = u.replace("t.me/", "")
    return u.lstrip("@")

# --- Settings Handling ---
def load_user_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_user_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def get_settings(user_id):
    settings = load_user_settings()
    if str(user_id) not in settings:
        settings[str(user_id)] = {
            "src": [],
            "dst": [],
            "lang": "en",
            "username": "",
            "active": True,
            "allow_forwarded": True,
        }
        save_user_settings(settings)
    # ADD THIS in case you're updating a bot that already has users
    if "allow_forwarded" not in settings[str(user_id)]:
        settings[str(user_id)]["allow_forwarded"] = True
        save_user_settings(settings)
    return settings[str(user_id)]

def update_settings(user_id, **kwargs):
    settings = load_user_settings()
    user_id = str(user_id)
    if user_id not in settings:
        settings[user_id] = {
            "src": [],
            "dst": [],
            "lang": "en",
            "username": "",
            "active": True,
            "allow_forwarded": True,
        }
    if "allow_forwarded" not in settings[user_id]:
        settings[user_id]["allow_forwarded"] = True
    for k, v in kwargs.items():
        if k in ["src", "dst"] and isinstance(v, list):
            settings[user_id][k] = v
        else:
            settings[user_id][k] = v
    save_user_settings(settings)
    print(f"Updated settings for user {user_id}: {settings[user_id]}")

# --- Text/Clean/Translate Helpers (You already have these) ---
def translate_preserving_usernames(text: str, dest: str = "ar") -> str:
    if not text:
        return text
    parts = re.split(r'(@[a-zA-Z0-9_]{4,})', text)
    out = []
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        GoogleTranslator = None
    for part in parts:
        if part.startswith('@') and len(part) > 4:
            out.append(part)
        else:
            try:
                if GoogleTranslator:
                    out.append(GoogleTranslator(source='auto', target=dest).translate(part) if part.strip() else part)
                else:
                    out.append(part)
            except Exception as e:
                print(f"Translation error: {e}")
                out.append(part)
    return ''.join(out)

def break_telegram_mention(match):
    at_name = match.group(0)
    return "@\u200b" + at_name[1:]

def link_replacer(match, username="@username"):
    url = match.group(0)
    if (
        re.match(r'https?://(www\.)?tronscan', url) or
        re.match(r'https?://(www\.)?blockchain', url) or
        re.match(r'www\.blockchain', url) or
        re.match(r'blockchain', url)
    ):
        return url
    return username



def clean_text(text, username="@destinationusername"):
    if not text:
        return text

    dest_no_at = username.lstrip("@")
    html_link = f'<a href="https://t.me/{dest_no_at}">{username}</a>'

    # Remove t.me/@1234xxxx links (where username starts with 4 digits)
    text = re.sub(
        r'(https?://)?(www\.)?t\.me/@?(\d{4}[a-zA-Z0-9_]+)',
        lambda m: f"@{m.group(3)}",
        text,
        flags=re.IGNORECASE
    )

    # Replace t.me/username (where username does NOT start with 4 digits) with HTML link
    text = re.sub(
        r'(https?://)?(www\.)?t\.me/@?([a-zA-Z_][a-zA-Z0-9_]+)',
        html_link,
        text,
        flags=re.IGNORECASE
    )

    # Now for @-mentions
    # Keep @1234xxxx as plain text (not linkified, not replaced)
    text = re.sub(
        r'@(\d{4}[a-zA-Z0-9_]+)',
        lambda m: m.group(0),  # just leave as is
        text
    )

    # Replace all other @usernames with HTML link
    text = re.sub(
        r'@([a-zA-Z_][a-zA-Z0-9_]+)',
        html_link,
        text
    )

    # Replace emails with HTML link
    text = re.sub(r'\b\S+@\S+\.\S+\b', html_link, text)

    return text




def force_link_usernames(text):
    def make_link(match):
        username = match.group(1)
        return f'<a href="https://t.me/{username}">@{username}</a>'
    return re.sub(r'@([a-zA-Z_][a-zA-Z0-9_]{4,})', make_link, text)

def process_caption_or_text(txt, username=None, lang=None):
    if not username:
        username = "@username"
    if not lang:
        lang = "en"
    cleaned = clean_text(txt, username=username)
    translated = translate_preserving_usernames(cleaned, dest=lang)
    final = force_link_usernames(translated)
    return final

# --- Userbot Setup ---
client = TelegramClient('userbot_session', API_ID, API_HASH)

# --- Menu/Commands ---
@client.on(events.NewMessage(incoming=True))
async def handle_dm_command(event):
    if not event.is_private:
        return

    user_id = event.sender_id
    text = event.raw_text.strip()
    text_lower = text.lower()
    settings = get_settings(user_id)

    if text_lower in ['/start', 'start']:
        await event.reply(
            "**Telegram Userbot Auto-Forwarder**\n\n"
            "Available Commands:\n"
            "👉 `/setsrc channel1 channel2` - Set source channels\n"
            "👉 `/setdst dest1 dest2` - Set destination channels\n"
            "👉 `/setlang en` - Set language\n"
            "👉 `/setusername @user` - Set username\n"
            "👉 `/startforwarding` - Enable forwarding\n"
            "👉 `/stopforwarding` - Disable forwarding\n"
            "👉 `/allowforwarded on` - Allow 'forwarded from' posts\n"
            "👉 `/allowforwarded off` - Block 'forwarded from' posts\n"
            "👉 `/status` - Show status\n"
            "\n*Paste or tap, then edit and send your values.*"
        )
    elif text_lower.startswith('/allowforwarded'):
        val = text_lower.replace('/allowforwarded', '').strip()
        if val in ['on', 'yes', 'true']:
            update_settings(user_id, allow_forwarded=True)
            await event.reply("✅ 'Forwarded from' posts will now be forwarded.")
        elif val in ['off', 'no', 'false']:
            update_settings(user_id, allow_forwarded=False)
            await event.reply("⛔️ 'Forwarded from' posts will NOT be forwarded.")
        else:
            await event.reply("Usage: `/allowforwarded on` or `/allowforwarded off`")
    elif text_lower.startswith('/setsrc '):
        parts = text[8:].replace(',', ' ').split()
        sources = [clean_username(p) for p in parts if p]
        update_settings(user_id, src=sources)
        await event.reply(f"✅ Source channels set: {', '.join(sources)}")
    elif text_lower.startswith('/setdst '):
        parts = text[8:].replace(',', ' ').split()
        destinations = [clean_username(p) for p in parts if p]
        update_settings(user_id, dst=destinations)
        await event.reply(f"✅ Destination channels set: {', '.join(destinations)}")
    elif text_lower.startswith('/setlang '):
        code = text[9:].strip()
        update_settings(user_id, lang=code)
        await event.reply(f"✅ Language set to: {code}")
    elif text_lower.startswith('/setusername '):
        uname = text[13:].strip()
        update_settings(user_id, username=uname)
        await event.reply(f"✅ Username set to: {uname}")
    elif text_lower.startswith('/startforwarding'):
        update_settings(user_id, active=True)
        await event.reply("✅ Forwarding ENABLED!")
    elif text_lower.startswith('/stopforwarding'):
        update_settings(user_id, active=False)
        await event.reply("⛔️ Forwarding DISABLED.")
    elif text_lower.startswith('/status'):
        conf = get_settings(user_id)
        msg = (
            "**Your Forwarder Settings**\n"
            f"Source(s): {conf.get('src')}\n"
            f"Destination(s): {conf.get('dst')}\n"
            f"Language: {conf.get('lang')}\n"
            f"Username: {conf.get('username')}\n"
            f"Active: {conf.get('active')}\n"
            f"Allow Forwarded: {conf.get('allow_forwarded', True)}\n"
        )
        await event.reply(msg, parse_mode='markdown')


def should_skip_due_to_links(text):
    """
    Returns True if the text has a forbidden link (not in whitelist, not t.me), else False.
    """
    if not text:
        return False

    # Find all links in the text
    links = re.findall(r'(https?://[^\s]+|www\.[^\s]+)', text, flags=re.IGNORECASE)
    whitelist = ['https://tronscan', 'https://blockchain', 'https://www.blockchain']

    for link in links:
        link_low = link.lower()
        # Allow t.me links always
        if 't.me/' in link_low:
            continue
        # Allow whitelisted blockchain/tronscan links
        if any(link_low.startswith(wl) for wl in whitelist):
            continue
        # Otherwise: forbidden external link
        return True
    return False


# --- Message & Reply/Album/Forward Mapping ---
media_group_cache = defaultdict(list)
media_group_timestamps = {}
reply_map = {}  # (src_chat_id, src_msg_id, dst_chat_id) => dst_msg_id

@client.on(events.NewMessage)
async def my_handler(event):
    if event.is_private:
        return

    src_username = getattr(event.chat, 'username', None)
    if not src_username:
        return

    settings = load_user_settings()
    for user_id, conf in settings.items():
        if not conf.get("active", True):
            continue
        sources = conf.get("src", [])
        destinations = conf.get("dst", [])
        allow_forwarded = conf.get("allow_forwarded", True)
        if src_username.lower() in [s.lower() for s in sources]:
            lang = conf.get("lang", "en")
            username = conf.get("username", "@username")
            msg = event.message

            async def send_album(dst, album_events):
                album_events.sort(key=lambda e: e.id)
                files = []
                caption = None
                reply_to = None
                src_ids = []
                for idx, e in enumerate(album_events):
                    m = e.message
                    file = m.photo or m.document
                    if file:
                        files.append(file)
                        src_ids.append((e.chat_id, m.id))
                        if idx == 0:
                            caption = process_caption_or_text(m.message, username=username, lang=lang) if m.message else None
                            if m.reply_to_msg_id:
                                key = (e.chat_id, m.reply_to_msg_id, dst)
                                reply_to = reply_map.get(key)
                if files:
                    try:
                        sent_list = await client.send_file(
                            dst,
                            files,
                            caption=caption,
                            parse_mode='html',
                            reply_to=reply_to
                        )
                        if not isinstance(sent_list, list):
                            sent_list = [sent_list]
                        for src, sent in zip(src_ids, sent_list):
                            reply_map[src] = sent.id
                        print(f"Forwarded album to {dst} (reply_to {reply_to})")
                    except Exception as e:
                        print(f"Forward album error to {dst}: {e}")

            async def send_album_as_natively_forwarded(dst, album_events):
                if not allow_forwarded:
                    print(f"Skipped forwarded album for user {user_id} to {dst}: 'allow_forwarded' is off.")
                    return
                album_events.sort(key=lambda e: e.id)
                for e in album_events:
                    m = e.message
                    try:
                        sent = await client.forward_messages(dst, m)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(e.chat_id, m.id, dst)] = sent.id
                    except Exception as e:
                        print(f"Native forward album part error: {e}")

            if msg.grouped_id:
                group_id = (event.chat_id, msg.grouped_id)
                media_group_cache[group_id].append(event)
                media_group_timestamps[group_id] = time.time()

                async def send_album_later(group_id, destinations):
                    await asyncio.sleep(1.7)
                    album_events = media_group_cache.pop(group_id, [])
                    media_group_timestamps.pop(group_id, None)
                    if not album_events:
                        return
                    for dst in destinations:
                        # If any part of the album is forwarded and allow_forwarded is False, skip whole album
                        if any(getattr(e.message, "fwd_from", None) for e in album_events):
                            if not allow_forwarded:
                                print(f"Skipped forwarded album for user {user_id} to {dst}: 'allow_forwarded' is off.")
                                continue
                            await send_album_as_natively_forwarded(dst, album_events)
                        else:
                            await send_album(dst, album_events)

                if len(media_group_cache[group_id]) == 1:
                    asyncio.create_task(send_album_later(group_id, destinations))
                return

            # --- Single message/media/forwarded ---
            for dst in destinations:
                # SKIP POST IF IT'S A FORWARDED POST AND FORWARDING IS DISABLED
                if getattr(msg, "fwd_from", None) and not allow_forwarded:
                    print(f"Skipped forwarded-from post for user {user_id} to {dst}: 'allow_forwarded' is off.")
                    continue

                # --- ADD THIS BLOCK: SKIP POST IF IT HAS FORBIDDEN LINKS ---
                text_to_check = ""
                if msg.message:
                    text_to_check += msg.message + " "
                if hasattr(msg, "text") and msg.text:
                    text_to_check += msg.text + " "
                if hasattr(msg, "caption") and msg.caption:
                    text_to_check += msg.caption + " "

                if should_skip_due_to_links(text_to_check):
                    print(f"Skipped post for user {user_id} to {dst}: contains non-whitelisted external link.")
                    continue

                try:
                    reply_to = None
                    if msg.reply_to_msg_id:
                        key = (event.chat_id, msg.reply_to_msg_id, dst)
                        reply_to = reply_map.get(key)
                    # --- Native forwarded message ---
                    if getattr(msg, "fwd_from", None):
                        sent = await client.forward_messages(dst, msg)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    # --- Media file (photo/doc/video/audio...) ---
                    elif msg.media:
                        if isinstance(msg.media, MessageMediaWebPage):
                            final_text = process_caption_or_text(msg.message, username=username, lang=lang)
                            sent = await client.send_message(dst, final_text, parse_mode='html', reply_to=reply_to)
                            sent_id = sent[0].id if isinstance(sent, list) else sent.id
                            reply_map[(event.chat_id, msg.id, dst)] = sent_id
                            continue
                        final_caption = process_caption_or_text(msg.message, username=username, lang=lang) if msg.message else None
                        sent = await client.send_file(dst, msg.media, caption=final_caption, parse_mode='html', reply_to=reply_to)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    elif msg.message:
                        final_text = process_caption_or_text(msg.message, username=username, lang=lang)
                        sent = await client.send_message(dst, final_text, parse_mode='html', reply_to=reply_to)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    else:
                        sent = await client.forward_messages(dst, msg)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    print(f"Forwarded from {src_username} to {dst} (reply_to {reply_to})")
                except Exception as e:
                    print(f"Forward error for user {user_id} to {dst}: {e}")


# --- Message Edit Mirroring ---
@client.on(events.MessageEdited)
async def edit_handler(event):
    if event.is_private:
        return

    src_chat_id = event.chat_id
    msg_id = event.message.id

    settings = load_user_settings()
    for user_id, conf in settings.items():
        username = conf.get("username", "@username")
        lang = conf.get("lang", "en")
        for dst in conf.get("dst", []):
            dst_msg_id = reply_map.get((src_chat_id, msg_id, dst))
            if not dst_msg_id:
                continue
            try:
                if event.message.text:
                    final_text = process_caption_or_text(event.message.text, username=username, lang=lang)
                    await client.edit_message(dst, dst_msg_id, final_text, parse_mode='html')
                    print(f"Edited text message in {dst}")
                elif event.message.media:
                    final_caption = process_caption_or_text(event.message.message, username=username, lang=lang) if event.message.message else None
                    await client.edit_message(dst, dst_msg_id, final_caption, parse_mode='html')
                    print(f"Edited caption in {dst}")
                else:
                    print(f"Edit: Unsupported or native-forwarded message in {dst}, cannot edit.")
            except Exception as e:
                print(f"Edit error for {dst}: {e}")

if __name__ == '__main__':
    print("Telethon userbot running! Type /start in private chat for command menu.")
    client.start(phone=PHONE_NUMBER)
    client.run_until_disconnected()
