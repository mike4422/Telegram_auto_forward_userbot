import asyncio
import json
import os
import re
import time
from collections import defaultdict
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage
from collections import defaultdict, deque
import heapq
from itertools import count
from telethon.tl.custom import Button

heap_counter = count()

destination_queues = {}         # dst_chat_id: heapq [(timestamp, jobdict)]
destination_queue_tasks = {}    # dst_chat_id: asyncio.Task
destination_queue_locks = {}    # dst_chat_id: asyncio.Lock

SEO_HASHTAGS = "#CryptoSignals #Futures #Spot #Trading #Bitcoin #Ethereum #Altcoins #SignalsVIP #CryptoTrading"

def add_seo_hashtags(text):
    text = text or ""
    if SEO_HASHTAGS in text:
        return text  # avoid double
    return text.rstrip() + "\n\n" + SEO_HASHTAGS


def queue_forward_job(dst, timestamp, job):
    if dst not in destination_queues:
        destination_queues[dst] = []
        destination_queue_locks[dst] = asyncio.Lock()
    heapq.heappush(destination_queues[dst], (timestamp, next(heap_counter), job))

async def destination_queue_worker(dst):
    while True:
        await asyncio.sleep(0.1)
        if dst not in destination_queues:
            continue
        async with destination_queue_locks[dst]:
            if destination_queues[dst]:
                timestamp, _, job = heapq.heappop(destination_queues[dst])
                try:
                    await job['func'](*job['args'], **job['kwargs'])
                except Exception as e:
                    print(f"Destination queue error for {dst}: {e}")


API_ID = 26376666  # <-- Your api_id here
API_HASH = '61ee2def31a7a12026ecfa1c72474489'
PHONE_NUMBER = '+14053131520'  # <-- Your phone number

SETTINGS_FILE = "user_settings.json"

outbound_queues = defaultdict(asyncio.Queue)  # dest_id -> queue of (timestamp, coroutine)
queue_workers_started = set()


async def enqueue_forward_job(dst, job):
    # Each job is a (timestamp, coroutine)
    await outbound_queues[dst].put(job)
    # Start worker if not running
    if dst not in queue_workers_started:
        asyncio.create_task(forward_worker(dst))
        queue_workers_started.add(dst)

async def forward_worker(dst):
    while True:
        job = await outbound_queues[dst].get()
        ts, coro = job
        try:
            await coro
        except Exception as e:
            print(f"Forward queue worker error for {dst}: {e}")
        outbound_queues[dst].task_done()



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

def replace_wa_me_link(text, username="@username"):
    if not text:
        return text
    return re.sub(r'(https?://)?(www\.)?wa\.me/\S+', "___WA_ME_TELEGRAM_LINK___", text, flags=re.IGNORECASE)


def users_for_source_channel(src_username):
    settings = load_user_settings()
    results = []
    for user_id, conf in settings.items():
        sources = conf.get("src", [])
        if src_username.lower() in [s.lower() for s in sources]:
            results.append((user_id, conf))
    return results


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
            "use_seo_hashtags": False,
        }
        save_user_settings(settings)
    # ADD THIS in case you're updating a bot that already has users
    if "allow_forwarded" not in settings[str(user_id)]:
        settings[str(user_id)]["allow_forwarded"] = True
        save_user_settings(settings)
    if "use_seo_hashtags" not in settings[str(user_id)]:
        settings[str(user_id)]["use_seo_hashtags"] = False
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
            "use_seo_hashtags": False,
        }
    if "allow_forwarded" not in settings[user_id]:
        settings[user_id]["allow_forwarded"] = True
    if "use_seo_hashtags" not in settings[user_id]:
        settings[user_id]["use_seo_hashtags"] = False
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
    replaced = replace_wa_me_link(txt, username=username)
    cleaned = clean_text(replaced, username=username)
    translated = translate_preserving_usernames(cleaned, dest=lang)
    final = force_link_usernames(translated)
    dest_no_at = username.lstrip("@")
    html_link = f'<a href="https://t.me/{dest_no_at}">{username}</a>'
    final = final.replace("___WA_ME_TELEGRAM_LINK___", html_link)
    return final

def rewrite_buttons(reply_markup, username):
    """
    Returns new reply_markup with all buttons changed to "CONTACT ME" -> https://t.me/<username>
    """
    if not reply_markup or not hasattr(reply_markup, 'rows'):
        return None

    dest_no_at = username.lstrip('@')
    link = f"https://t.me/{dest_no_at}"

    new_buttons = []
    for row in reply_markup.rows:
        button_row = []
        for btn in row.buttons:
            # Only replace URL buttons, ignore others
            if hasattr(btn, 'url') and btn.url:
                button_row.append(Button.url("CONTACT ME", link))
            else:
                # For non-url buttons, you could ignore or keep them, here we ignore.
                continue
        if button_row:
            new_buttons.append(button_row)
    if new_buttons:
        return new_buttons
    return None


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
            "👉 `/seo_hashtags on` - Add SEO hashtags to all posts\n"
            "👉 `/seo_hashtags off` - Do not add hashtags\n"
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
    elif text_lower.startswith('/seo_hashtags'):
        val = text_lower.replace('/seo_hashtags', '').strip()
        if val in ['on', 'yes', 'true']:
            update_settings(user_id, use_seo_hashtags=True)
            await event.reply("✅ SEO hashtags will be added to your posts.")
        elif val in ['off', 'no', 'false']:
            update_settings(user_id, use_seo_hashtags=False)
            await event.reply("⛔️ SEO hashtags will not be added to your posts.")
        else:
            await event.reply("Usage: `/seo_hashtags on` or `/seo_hashtags off`")
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
            f"SEO Hashtags: {'ON' if conf.get('use_seo_hashtags', False) else 'OFF'}\n"
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

def has_forbidden_forwarded_link(text):
    if not text:
        return False
    # Any t.me/username or http(s)://t.me/username
    if re.search(r'(https?://)?(www\.)?t\.me/@?[a-zA-Z0-9_]{4,}', text, flags=re.IGNORECASE):
        return True
    # Any http(s):// or www.
    if re.search(r'(https?://\S+|www\.\S+)', text, flags=re.IGNORECASE):
        return True
    # Any @mention that is NOT 4 digits after the @
    for match in re.finditer(r'(?<![\w.])@([a-zA-Z0-9_]{4,})', text):
        username = match.group(1)
        if not username[:4].isdigit():
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
                final_reply_markup = None
                for idx, e in enumerate(album_events):
                    m = e.message
                    file = m.photo or m.document
                    if file:
                        files.append(file)
                        src_ids.append((e.chat_id, m.id))
                        if idx == 0:
                            caption = process_caption_or_text(m.message, username=username,
                                                              lang=lang) if m.message else None
                            if conf.get("use_seo_hashtags", False) and caption:
                                caption = add_seo_hashtags(caption)

                            # --- HANDLE BUTTONS ON FIRST CAPTION ONLY ---
                            if hasattr(m, "reply_markup") and m.reply_markup:
                                final_reply_markup = rewrite_buttons(m.reply_markup, username)
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
                            reply_to=reply_to,
                            buttons=final_reply_markup  # <<<< ADD THIS ARGUMENT
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
                # -- ADD THIS BLOCK TO CHECK ALL PARTS FOR FORBIDDEN CONTENT --
                for e in album_events:
                    m = e.message
                    text_to_check = ""
                    if m.message:
                        text_to_check += m.message + " "
                    if hasattr(m, "text") and m.text:
                        text_to_check += m.text + " "
                    if hasattr(m, "caption") and m.caption:
                        text_to_check += m.caption + " "
                    if has_forbidden_forwarded_link(text_to_check):
                        print(f"Skipped forwarded album for {dst}: forbidden @username, t.me, or link found.")
                        await asyncio.sleep(0)  # just yield, but don't forward
                        return
                # -- END BLOCK --
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

                async def handle_album_enqueue(group_id, destinations):
                    """
                    Wait for the album to be fully received, then process it for all destinations.
                    Robust against partial/incomplete albums and race conditions.
                    """
                    # Wait for more parts of the album, up to 3 seconds max (checks every 0.5s)
                    last_count = 0
                    for _ in range(6):  # 6 * 0.5s = 3s max wait
                        await asyncio.sleep(0.5)
                        current_count = len(media_group_cache[group_id])
                        if current_count == last_count:
                            break  # No new parts arrived since last check, album is done
                        last_count = current_count

                    album_events = media_group_cache.pop(group_id, [])
                    media_group_timestamps.pop(group_id, None)
                    if not album_events:
                        return

                    # The username/lang/other context is inferred from first message's chat
                    first_event = album_events[0]
                    src_username = getattr(first_event.chat, 'username', None)
                    # It's possible you want to pull username/lang from user_settings
                    settings = load_user_settings()
                    conf = None
                    for user_id, c in settings.items():
                        if src_username and src_username.lower() in [s.lower() for s in c.get("src", [])]:
                            conf = c
                            break
                    username = conf.get("username", "@username") if conf else "@username"

                    for dst in destinations:
                        forbidden = False
                        for e in album_events:
                            m = e.message
                            text_to_check = ""
                            if m.message:
                                text_to_check += m.message + " "
                            if hasattr(m, "text") and m.text:
                                text_to_check += m.text + " "
                            if hasattr(m, "caption") and m.caption:
                                text_to_check += m.caption + " "

                            # --- ADD THIS LINE ---
                            text_to_check = replace_wa_me_link(text_to_check, username=username)

                            if should_skip_due_to_links(text_to_check):
                                forbidden = True
                                break
                        if forbidden:
                            print(
                                f"Skipped album for destination {dst}: contains non-whitelisted external link in at least one media/caption.")
                            continue

                        # Decide function/callback for album
                        if any(getattr(e.message, "fwd_from", None) for e in album_events):
                            ts = min(e.message.date.timestamp() for e in album_events)
                            queue_forward_job(
                                dst, ts,
                                {
                                    'func': send_album_as_natively_forwarded,
                                    'args': (dst, album_events),
                                    'kwargs': {},
                                }
                            )
                        else:
                            ts = min(e.message.date.timestamp() for e in album_events)
                            queue_forward_job(
                                dst, ts,
                                {
                                    'func': send_album,
                                    'args': (dst, album_events),
                                    'kwargs': {},
                                }
                            )
                        # Launch the worker if not already
                        if dst not in destination_queue_tasks or destination_queue_tasks[dst].done():
                            destination_queue_tasks[dst] = asyncio.create_task(destination_queue_worker(dst))

                # Only start the timer once per new album
                if len(media_group_cache[group_id]) == 1:
                    asyncio.create_task(handle_album_enqueue(group_id, destinations))
                return

            # --- Single messages: enqueue instead of direct send ---
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

                # --- ADD THIS LINE ---
                text_to_check = replace_wa_me_link(text_to_check, username=username)

                if should_skip_due_to_links(text_to_check):
                    print(f"Skipped post for user {user_id} to {dst}: contains non-whitelisted external link.")
                    continue

                # Build send function
                async def do_forward_single(dst, msg=msg, event=event, user_id=user_id, lang=lang, username=username, conf=conf):
                    print(
                        f"[DEBUG] do_forward_single called for user {user_id} to {dst}, SEO hashtags enabled: {conf.get('use_seo_hashtags', False)}")

                    reply_to = None
                    if msg.reply_to_msg_id:
                        key = (event.chat_id, msg.reply_to_msg_id, dst)
                        reply_to = reply_map.get(key)
                    # --- Native forwarded message ---
                    if getattr(msg, "fwd_from", None):
                        text_to_check = ""
                        if msg.message:
                            text_to_check += msg.message + " "
                        if hasattr(msg, "text") and msg.text:
                            text_to_check += msg.text + " "
                        if hasattr(msg, "caption") and msg.caption:
                            text_to_check += msg.caption + " "
                        if has_forbidden_forwarded_link(text_to_check):
                            print(f"Skipped forwarded-from post to {dst}: forbidden @username, t.me, or link found.")
                            await asyncio.sleep(0)  # just yield, don't break order!
                            return

                        sent = await client.forward_messages(dst, msg)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    elif msg.media:
                        if isinstance(msg.media, MessageMediaWebPage):
                            final_text = process_caption_or_text(msg.message, username=username, lang=lang)
                            if conf.get("use_seo_hashtags", False) and final_text:
                                final_text = add_seo_hashtags(final_text)  # Add SEO hashtags here
                            sent = await client.send_message(dst, final_text, parse_mode='html', reply_to=reply_to)
                            sent_id = sent[0].id if isinstance(sent, list) else sent.id
                            reply_map[(event.chat_id, msg.id, dst)] = sent_id
                            return
                        final_caption = process_caption_or_text(msg.message, username=username,
                                                                lang=lang) if msg.message else None
                        if conf.get("use_seo_hashtags", False) and final_caption:
                            final_caption = add_seo_hashtags(final_caption)

                        final_reply_markup = None
                        if hasattr(msg, "reply_markup") and msg.reply_markup:
                            final_reply_markup = rewrite_buttons(msg.reply_markup, username)
                        sent = await client.send_file(
                            dst,
                            msg.media,
                            caption=final_caption,
                            parse_mode='html',
                            reply_to=reply_to,
                            buttons=final_reply_markup
                        )

                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    elif msg.message and not msg.media:
                        final_text = process_caption_or_text(msg.message, username=username, lang=lang)
                        print(f"[DEBUG] SEO hashtags ON? {conf.get('use_seo_hashtags', False)} For user {user_id}")
                        if conf.get("use_seo_hashtags", False) and final_text:
                            final_text = add_seo_hashtags(final_text)
                        final_reply_markup = None
                        if hasattr(msg, "reply_markup") and msg.reply_markup:
                            final_reply_markup = rewrite_buttons(msg.reply_markup, username)
                        sent = await client.send_message(
                            dst,
                            final_text,
                            parse_mode='html',
                            reply_to=reply_to,
                            buttons=final_reply_markup
                        )
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    else:
                        sent = await client.forward_messages(dst, msg)
                        sent_id = sent[0].id if isinstance(sent, list) else sent.id
                        reply_map[(event.chat_id, msg.id, dst)] = sent_id
                    print(f"Forwarded from {src_username} to {dst} (reply_to {reply_to})")

                # Enqueue job
                ts = msg.date.timestamp()
                queue_forward_job(
                    dst, ts,
                    {
                        'func': do_forward_single,
                        'args': (dst,),
                        'kwargs': {},
                    }
                )
                if dst not in destination_queue_tasks:
                    destination_queue_tasks[dst] = asyncio.create_task(destination_queue_worker(dst))


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
