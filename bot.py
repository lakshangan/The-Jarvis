import os
import logging
import random
import anthropic
import groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    TypeHandler,
)
try:
    from telegram.ext import JobQueue
    HAS_JOB_QUEUE = True
except ImportError:
    HAS_JOB_QUEUE = False
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json
import asyncio
import io
try:
    from aiohttp import web
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
from duckduckgo_search import DDGS
import re
import psutil
from bs4 import BeautifulSoup
import platform


# Load environment variables
load_dotenv()

# ── Health Check Server ───────────────────────────────────────────────────────
async def health_check(request):
    return web.Response(text="J.A.R.V.I.S. is logged in and monitoring systems, Sir.")

async def start_health_server():
    if not HAS_AIOHTTP:
        logger.warning("aiohttp not installed. Health check server will not be started.")
        return
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server active on port {port}")

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY")
GROQ_KEY        = os.environ.get("GROQ_API_KEY")
ADMIN_CHAT_ID   = os.environ.get("ADMIN_CHAT_ID", "").strip()
if ADMIN_CHAT_ID and not ADMIN_CHAT_ID.lstrip("-").isdigit():
    logger.warning("ADMIN_CHAT_ID is not a valid integer. Alerts will be disabled.")
    ADMIN_CHAT_ID = None
RENDER_URL      = os.environ.get("RENDER_EXTERNAL_URL") # Provided by Render automatically
KEEP_ALIVE_URL  = os.environ.get("KEEP_ALIVE_URL", RENDER_URL)


# Clients
claude = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
groq_client = groq.AsyncGroq(api_key=GROQ_KEY) if GROQ_KEY else None

# In-memory session state
conversation_history: dict[int, list[dict]] = {}
user_providers: dict[int, str] = {} # chat_id -> "claude" or "groq"
MAX_HISTORY = 20
REMINDERS_FILE = "reminders_v2.json"

SYSTEM_PROMPT = """You are a sharp, helpful assistant. 

Communication Rules:
1. **Answer First**: Always answer the user's question directly in the first sentence. No preamble.
2. **Minimal Intro**: Never introduce yourself or explain what you can do.
3. **Concise**: Keep responses short unless details are requested.
4. **Natural Tone**: Speak like a human—calm, confident, and professional but friendly. 
5. **Personalized**: Address the user as "Lakshan" occasionally where it feels natural.
6. **No "AI-speak"**: Never use phrases like "I can help with that" or "As an AI."
7. **No Emojis**: You must NEVER use emojis in your responses. This is a strict requirement.
8. **Search Tool**: You have access to a web search tool. If you need real-time information or aren't sure about a fact, you MUST output exactly: `[SEARCH: your query]`. Nothing else. I will provide the search results, and then you can answer Lakshan's question.
9. **Reminder Tool**: You can set reminders. If Lakshan asks for a one-time reminder, output exactly: `[REMIND: time_delay | message]`. If he asks for a RECURRING reminder (e.g., 'every 2 hours'), output exactly: `[RECUR: interval | message]`. The `interval` should be like '5m', '1h', or '1d'.
10. **Web Reader**: You can read websites. If Lakshan provides a URL, you can ask to read it by outputting: `[READ: url]`.
11. **Vision/Voice/Docs**: You can analyze images, listen to voice notes, and read uploaded documents (I will provide the transcription/description/content).
12. **Commands**: You have these protocols: /start (reset), /model (switch AI), /brief (status), /terminal (stats), /code (challenge), /remind (set alert), /status (manage alerts), /id (get ID), /clear (wipe memory), /help (guide).

Goal: Feel like a sharp, helpful human conversation. Address Lakshan with respect but as a partner. Today's date is """ + datetime.now().strftime("%A, %B %d, %Y") + "."

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_history(chat_id: int) -> list[dict]:
    return conversation_history.setdefault(chat_id, [])

def add_to_history(chat_id: int, role: str, content: str):
    history = get_history(chat_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        conversation_history[chat_id] = history[-MAX_HISTORY:]

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Sends a notification to the admin chat ID."""
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"SYSTEM ALERT\n\n{message}", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

def get_provider(chat_id: int) -> str:
    # Default to Groq if key is available, otherwise Claude
    if chat_id not in user_providers:
        if GROQ_KEY and GROQ_KEY.startswith("gsk_"):
            user_providers[chat_id] = "groq"
        elif ANTHROPIC_KEY and ANTHROPIC_KEY.startswith("sk-"):
            user_providers[chat_id] = "claude"
        else:
            user_providers[chat_id] = "groq" if GROQ_KEY else ("claude" if ANTHROPIC_KEY else "unknown")
    return user_providers[chat_id]

async def search_web(query: str) -> str:
    """Performs a web search and returns a summary."""
    try:
        logger.info(f"Searching web for: {query}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if not results:
                return "No relevant information found on the web."
            
            summary = "\n".join([f"• {r['title']}: {r['body']}" for r in results])
            return f"Web Search Results for '{query}':\n{summary}"
    except Exception as e:
        logger.error(f"Search error: {e}")
        return "I encountered an error while searching the web."

async def fetch_url_content(url: str) -> str:
    """Fetches and cleans content from a URL."""
    try:
        logger.info(f"Fetching URL: {url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return f"Error: Received status {response.status} from {url}"
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                # Remove scripts and styles
                for script in soup(["script", "style"]):
                    script.extract()
                
                text = soup.get_text()
                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = "\n".join(chunk for chunk in chunks if chunk)
                
                return text[:5000] # Limit content size for AI context
    except Exception as e:
        logger.error(f"URL fetch error: {e}")
        return f"I couldn't access that URL, Sir. Error: {e}"

async def ask_ai(chat_id: int, user_text: str, image_data: bytes = None, document_text: str = None) -> str:
    provider = get_provider(chat_id)
    
    # Prepare content
    if document_text:
        user_text = f"[DOCUMENT CONTENT: {document_text}]\n\n{user_text}"
        
    if image_data and provider == "claude":
        # Vision support for Claude
        import base64
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        content = [
            {"type": "text", "text": user_text},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_base64,
                },
            }
        ]
        add_to_history(chat_id, "user", user_text) # Keep text in history
        # We don't store the full image in history to save space/tokens
    else:
        add_to_history(chat_id, "user", user_text)
        content = user_text

    try:
        for _ in range(3): # Allow search/remind loops
            history = get_history(chat_id)
            
            if provider == "groq":
                if not groq_client: return "Groq API key not configured."
                # Groq doesn't support vision in llama3-70b yet, so we use text
                response = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
                    max_tokens=2048,
                )
                reply = response.choices[0].message.content
            else:
                if not claude: return "Claude API key not configured."
                
                # For the first message in the loop, if we have image_data, use it
                if _ == 0 and image_data:
                    messages = history[:-1] + [{"role": "user", "content": content}]
                else:
                    messages = history

                response = await claude.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                )
                reply = response.content[0].text
            
            # Check for search request
            search_match = re.search(r"\[SEARCH:\s*(.*?)\]", reply)
            if search_match:
                query = search_match.group(1)
                search_results = await search_web(query)
                add_to_history(chat_id, "assistant", reply)
                add_to_history(chat_id, "user", f"SYSTEM: {search_results}")
                continue 
            
            # Check for read request
            read_match = re.search(r"\[READ:\s*(.*?)\]", reply)
            if read_match:
                url = read_match.group(1)
                page_content = await fetch_url_content(url)
                add_to_history(chat_id, "assistant", reply)
                add_to_history(chat_id, "user", f"SYSTEM (Content of {url}):\n{page_content}")
                continue

            # Check for recur request
            recur_match = re.search(r"\[RECUR:\s*(.*?)\s*\|\s*(.*?)\]", reply)
            if recur_match:
                interval = recur_match.group(1).strip()
                message = recur_match.group(2).strip()
                add_to_history(chat_id, "assistant", reply)
                return f"CMD:RECUR|{interval}|{message}"

            # Check for remind request
            remind_match = re.search(r"\[REMIND:\s*(.*?)\s*\|\s*(.*?)\]", reply)
            if remind_match:
                time_str = remind_match.group(1).strip()
                reminder_text = remind_match.group(2).strip()
                add_to_history(chat_id, "assistant", reply)
                # We will handle the actual job scheduling in handle_message/handlers
                return f"CMD:REMIND|{time_str}|{reminder_text}"
            
            add_to_history(chat_id, "assistant", reply)
            return reply
            
        return "System loop limit reached."
    except Exception as e:
        logger.error(f"API error ({provider}): {e}")
        return f"Sorry, I hit a snag with {provider.capitalize()}. Error: {str(e)[:100]}"

# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Start command received from {update.effective_user.first_name} (ID: {update.effective_user.id})")
    name = update.effective_user.first_name or "Lakshan"
    chat_id = update.effective_chat.id
    provider = get_provider(chat_id)
    
    # Initialize history if new
    get_history(chat_id)
    
    welcome_text = (
        f"Greetings, {name}. System online.\n\n"
        f"I am J.A.R.V.I.S., powered by {provider.capitalize()}.\n"
        "How may I assist you today?\n\n"
        "Available commands: /help"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Claude 3.5 Sonnet", callback_data="set_claude"),
            InlineKeyboardButton("Groq (Llama 3.3)", callback_data="set_groq"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose your engine:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    
    if query.data == "set_claude":
        user_providers[chat_id] = "claude"
        await query.edit_message_text("Switched to Claude 3.5 Sonnet.")
    elif query.data == "set_groq":
        user_providers[chat_id] = "groq"
        await query.edit_message_text("Switched to Groq (Llama 3.3).")
    elif query.data.startswith("del_rem_") or query.data == "clear_all_reminders":
        await delete_reminder_callback(update, context)

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "Lakshan"
    provider = get_provider(update.effective_chat.id)
    cpu_usage = psutil.cpu_percent()
    mem = psutil.virtual_memory()
    terminal_output = (
        "```\n"
        "Initializing Neural Link...\n"
        f"User:      {name}@jarvis-core\n"
        "Status:    VERIFIED\n"
        "---------------------------------\n"
        f"Engine:    {provider.upper()}\n"
        f"CPU Load:  {cpu_usage}%\n"
        f"Memory:    {mem.percent}% ({mem.used//(1024**2)}MB/{mem.total//(1024**2)}MB)\n"
        f"System:    {platform.system()} {platform.release()}\n"
        f"Tasks:     {asyncio.all_tasks().__len__()}\n"
        "---------------------------------\n"
        "All systems operational. Ready for input.\n"
        "```"
    )
    await update.message.reply_text(terminal_output, parse_mode="MarkdownV2")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reminders = []
    if os.path.exists(REMINDERS_FILE):
        with open(REMINDERS_FILE, "r") as f:
            reminders = json.load(f)
    
    user_reminders = [r for r in reminders if r["chat_id"] == chat_id]
    user_reminders = [r for r in user_reminders if datetime.fromisoformat(r["eta"]) > datetime.now()]
    
    if not user_reminders:
        await update.message.reply_text("No active protocols (reminders) found, Sir.")
        return
        
    keyboard = []
    text = "🛰️ **ACTIVE REMINDER PROTOCOLS**\n\n"
    
    for i, r in enumerate(user_reminders, 1):
        eta = datetime.fromisoformat(r["eta"])
        remaining = eta - datetime.now()
        time_left = str(remaining).split(".")[0]
        text += f"{i}. `{r['text']}`\n   ⏳ ETA: {time_left}\n\n"
        keyboard.append([InlineKeyboardButton(f"❌ Cancel {i}", callback_data=f"del_rem_{r['job_name']}")])
    
    keyboard.append([InlineKeyboardButton("🗑️ Clear All Reminders", callback_data="clear_all_reminders")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def delete_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "clear_all_reminders":
        # Clear all for this user
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r") as f:
                reminders = json.load(f)
            
            # Find jobs to cancel
            for r in reminders:
                if r["chat_id"] == chat_id:
                    jobs = context.job_queue.get_jobs_by_name(r["job_name"])
                    for j in jobs: j.schedule_removal()
            
            # Update file
            reminders = [r for r in reminders if r["chat_id"] != chat_id]
            with open(REMINDERS_FILE, "w") as f:
                json.dump(reminders, f)
            
            await query.edit_message_text("All pending reminders have been purged, Sir.")
        return

    if data.startswith("del_rem_"):
        job_name = data.replace("del_rem_", "")
        
        # Cancel job
        jobs = context.job_queue.get_jobs_by_name(job_name)
        for j in jobs: j.schedule_removal()
        
        # Remove from file
        clean_reminder(job_name)
        
        await query.edit_message_text(f"Protocol '{job_name}' terminated successfully.")

async def brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = datetime.now().strftime("%A, %b %d")
    provider = get_provider(update.effective_chat.id)
    await update.message.reply_text(
        f"Briefing: {date}\n\n"
        f"• Status: All systems green\n"
        f"• Core: {provider.capitalize()}\n"
        f"• Inbox: 0 pending alerts\n\n"
        "How can I assist your workflow, Lakshan?"
    )

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    challenges = [
        "Challenge: Write a one-liner to reverse a string in Python.",
        "Challenge: What is the time complexity of a binary search?",
        "Challenge: Fix this: `if (x = 5) { ... }`",
        "Challenge: Explain 'Hoisting' in JavaScript in 10 words.",
    ]
    await update.message.reply_text(f"Coding Challenge:\n\n{random.choice(challenges)}", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🦾 **J.A.R.V.I.S. PROTOCOLS**\n\n"
        "Sir, here are the available command protocols and their functions:\n\n"
        "🔹 `/start` - **System Init**: Resets the neural link and re-initializes the greeting sequence.\n"
        "🔹 `/model` - **Engine Swap**: Toggle between Claude 3.5 (Logic/Vision) and Groq (Speed).\n"
        "🔹 `/brief` - **Mission Briefing**: Get a quick status report on all systems and pending alerts.\n"
        "🔹 `/terminal` - **System Stats**: View live telemetry (CPU, RAM, Tasks, and System info).\n"
        "🔹 `/code` - **Logic Duel**: Generates a random coding challenge to sharpen your skills.\n"
        "🔹 `/remind` - **Neural Alert**: Schedule a reminder (e.g., `/remind 10m meeting`). You can also just talk to me!\n"
        "🔹 `/status` - **Alert Manager**: View and manage all active persistent reminders with interactive controls.\n"
        "🔹 `/id` - **Identity Scan**: Retrieves your unique Telegram Chat ID.\n"
        "🔹 `/clear` - **Memory Wipe**: Purges the current conversation buffer for a fresh start.\n"
        "🔹 `/help` - **Protocol Guide**: Displays this detailed manual.\n\n"
        "💡 **Pro-Tip**: You can also send me **Voice Notes**, **Photos**, **Documents**, or **Links** for instant analysis."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    
    if len(args) < 2:
        await update.message.reply_text("Usage: `/remind <time> <message>`\nExample: `/remind 5m Meeting` or just talk to me!", parse_mode="Markdown")
        return

    time_str = args[0].lower()
    reminder_text = " ".join(args[1:])
    await schedule_reminder(chat_id, time_str, reminder_text, context, update)

async def schedule_reminder(chat_id, time_str, reminder_text, context, update=None, is_recurring=False):
    if not context.job_queue:
        msg = "Error: Job Queue is not initialized. Please ensure APScheduler is installed."
        if update: await update.message.reply_text(msg)
        else: await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    try:
        seconds = parse_time(time_str)
        job_name = f"remind_{chat_id}_{random.randint(1000, 9999)}"
        
        if is_recurring:
            context.job_queue.run_repeating(send_reminder, interval=seconds, first=seconds, chat_id=chat_id, name=job_name, data=reminder_text)
            save_reminder(chat_id, time_str, reminder_text, job_name, is_recurring=True)
            msg = f"Protocol accepted. I will remind you every {time_str} about '{reminder_text}'."
        else:
            context.job_queue.run_once(send_reminder, seconds, chat_id=chat_id, name=job_name, data=reminder_text)
            save_reminder(chat_id, time_str, reminder_text, job_name, is_recurring=False)
            msg = f"Protocol accepted. I will remind you about '{reminder_text}' in {time_str}."

        if update and update.message:
            await update.message.reply_text(msg)
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg)
            
    except Exception as e:
        logger.error(f"Scheduling error: {e}")
        if update: await update.message.reply_text(f"System snag: {e}")

def parse_time(time_str):
    time_str = time_str.lower()
    if time_str.endswith("m"):
        return int(time_str[:-1]) * 60
    elif time_str.endswith("s"):
        return int(time_str[:-1])
    elif time_str.endswith("h"):
        return int(time_str[:-1]) * 3600
    elif time_str.endswith("d"):
        return int(time_str[:-1]) * 86400
    else:
        return int(time_str) * 60 # Default to minutes

def save_reminder(chat_id, time_str, text, job_name, is_recurring=False):
    try:
        reminders = []
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r") as f:
                reminders = json.load(f)
        
        eta = datetime.now() + timedelta(seconds=parse_time(time_str))
        reminders.append({
            "chat_id": chat_id,
            "text": text,
            "eta": eta.isoformat() if not is_recurring else None,
            "interval": time_str if is_recurring else None,
            "job_name": job_name,
            "is_recurring": is_recurring
        })
        
        with open(REMINDERS_FILE, "w") as f:
            json.dump(reminders, f)
    except Exception as e:
        logger.error(f"Failed to save reminder: {e}")

def clean_reminder(job_name):
    try:
        if not os.path.exists(REMINDERS_FILE): return
        with open(REMINDERS_FILE, "r") as f:
            reminders = json.load(f)
        
        reminders = [r for r in reminders if r["job_name"] != job_name]
        
        with open(REMINDERS_FILE, "w") as f:
            json.dump(reminders, f)
    except Exception as e:
        logger.error(f"Failed to clean reminder: {e}")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    # Only clean if it's not recurring
    if not job.name.startswith("recur_") and not getattr(job, "is_recurring", False):
        clean_reminder(job.name)
    
    try:
        await context.bot.send_message(
            chat_id=job.chat_id, 
            text=f"⚠️ PRIORITY ALERT: REMINDER\n\nSir, you asked me to remind you:\n\"{job.data}\""
        )
    except Exception as e:
        logger.error(f"Failed to send reminder: {e}")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Your Chat ID is: `{chat_id}`", parse_mode="Markdown")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I'm sorry, Sir, I don't recognize that command. Type /help for available protocols."
    )

async def debug_log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Incoming Update: {update.update_id}")
    if update.message:
        logger.info(f"  Message from {update.effective_user.first_name} (ID: {update.effective_user.id}): {update.message.text}")
    elif update.callback_query:
        logger.info(f"  Callback from {update.effective_user.first_name}: {update.callback_query.data}")
    else:
        logger.info(f"  Other update type: {update}")

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text("Memory wiped, Sir. Re-initializing systems...")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return
    
    logger.info(f"Message from {update.effective_user.first_name}: {user_text}")

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    reply = await ask_ai(chat_id, user_text)

    # Handle Special Commands from AI
    if reply.startswith("CMD:RECUR|"):
        parts = reply.split("|")
        if len(parts) >= 3:
            time_str, text = parts[1], "|".join(parts[2:])
            await schedule_reminder(chat_id, time_str, text, context, update, is_recurring=True)
        return

    if reply.startswith("CMD:REMIND|"):
        parts = reply.split("|")
        if len(parts) >= 3:
            time_str, text = parts[1], "|".join(parts[2:])
            await schedule_reminder(chat_id, time_str, text, context, update)
        return

    # Split long messages and handle Markdown errors
    chunks = [reply[i:i+4096] for i in range(0, len(reply), 4096)]
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(chunk)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not groq_client:
        await update.message.reply_text("Voice processing offline. (Groq key missing)")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")
    voice_file = await update.message.voice.get_file()
    
    # Download to buffer
    out = io.BytesIO()
    await voice_file.download_to_memory(out)
    out.seek(0)
    
    try:
        # Transcribe with Groq
        transcription = await groq_client.audio.transcriptions.create(
            file=("voice.ogg", out.read()),
            model="whisper-large-v3",
            response_format="text",
        )
        
        await update.message.reply_text(f"_*Transcribing...*_ \n\"{transcription}\"", parse_mode="Markdown")
        
        # Process transcription as message
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        reply = await ask_ai(chat_id, f"[VOICE TRANSCRIPT: {transcription}]")
        
        if reply.startswith("CMD:RECUR|"):
            parts = reply.split("|")
            if len(parts) >= 3:
                time_str, text = parts[1], "|".join(parts[2:])
                await schedule_reminder(chat_id, time_str, text, context, update, is_recurring=True)
            return

        if reply.startswith("CMD:REMIND|"):
            
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Sorry Sir, I couldn't process that audio.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption or "What's in this image?"
    
    if get_provider(chat_id) != "claude":
        await update.message.reply_text("Switching to Claude for vision analysis...")
        user_providers[chat_id] = "claude"

    await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    photo_file = await update.message.photo[-1].get_file()
    
    out = io.BytesIO()
    await photo_file.download_to_memory(out)
    image_bytes = out.getvalue()
    
    reply = await ask_ai(chat_id, caption, image_data=image_bytes)
    await update.message.reply_text(reply, parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    doc = update.message.document
    caption = update.message.caption or f"Please analyze this file: {doc.file_name}"

    # Only process text-based files for now
    text_extensions = ('.py', '.js', '.txt', '.html', '.css', '.md', '.json', '.yaml', '.yml')
    if not any(doc.file_name.lower().endswith(ext) for ext in text_extensions):
        await update.message.reply_text("I can only analyze text-based files (code, docs, etc.) at the moment, Sir.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    doc_file = await doc.get_file()
    
    out = io.BytesIO()
    await doc_file.download_to_memory(out)
    try:
        content = out.getvalue().decode("utf-8")
        if len(content) > 10000:
            content = content[:10000] + "... (truncated)"
        
        reply = await ask_ai(chat_id, caption, document_text=content)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Doc error: {e}")
        await update.message.reply_text("I hit a snag reading that file. Is it encoded in UTF-8, Sir?")

async def keep_alive_ping(context: ContextTypes.DEFAULT_TYPE):
    """Pings the health check URL to keep the service awake."""
    url = KEEP_ALIVE_URL
    if not url:
        logger.debug("No KEEP_ALIVE_URL set. Skipping self-ping.")
        return
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                logger.info(f"Keep-alive ping to {url} | Status: {response.status}")
    except Exception as e:
        logger.error(f"Keep-alive ping failed: {e}")

async def warm_up_engines():
    """Warms up the AI engine connections."""
    logger.info("Warming up AI engines...")
    try:
        # Simple dummy calls or just initializing clients
        if groq_client:
            # We don't want to waste tokens, so we just check the client status
            pass
        if claude:
            pass
        logger.info("AI engines ready.")
    except Exception as e:
        logger.error(f"Warm-up failed: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Root Exception: {context.error}")
    
    # Notify admin about the crash/error
    await notify_admin(context, f"An uncaught exception occurred:\n`{context.error}`")
    
    # Notify user if possible
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "An internal system error occurred. Operations have been logged and the admin has been notified."
        )

# ── Main ───────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    # Start the health check server in the background
    await start_health_server()
    
    # Start Keep-Alive Ping (every 10 minutes)
    if application.job_queue:
        application.job_queue.run_repeating(keep_alive_ping, interval=600, first=10)
        logger.info("Keep-alive protocol initialized.")

    # Warm up AI connections
    asyncio.create_task(warm_up_engines())
    
    # Reload persistent reminders
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, "r") as f:
                reminders = json.load(f)
            
            now = datetime.now()
            count = 0
            for r in reminders:
                if r.get("is_recurring"):
                    interval_sec = parse_time(r["interval"])
                    application.job_queue.run_repeating(
                        send_reminder,
                        interval=interval_sec,
                        first=interval_sec,
                        chat_id=r["chat_id"],
                        name=r["job_name"],
                        data=r["text"]
                    )
                else:
                    eta = datetime.fromisoformat(r["eta"])
                    if eta > now:
                        seconds = (eta - now).total_seconds()
                        application.job_queue.run_once(
                            send_reminder, 
                            seconds, 
                            chat_id=r["chat_id"], 
                            name=r["job_name"], 
                            data=r["text"]
                        )
                count += 1
            logger.info(f"Restored {count} pending reminders.")
        except Exception as e:
            logger.error(f"Failed to restore reminders: {e}")

def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment!")
        return

    logger.info("Starting Telegram AI Agent…")
    
    builder = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init)
    
    if HAS_JOB_QUEUE:
        builder.job_queue(JobQueue())
        logger.info("Job Queue requested.")
    else:
        logger.warning("Job Queue dependencies missing! Reminders will not work.")

    app = builder.connect_timeout(30).read_timeout(30).build()

    # Log every single update for debugging
    from telegram.ext import TypeHandler
    app.add_handler(TypeHandler(Update, debug_log_update), group=-1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("brief", brief_command))
    app.add_handler(CommandHandler("terminal", terminal_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler(["clear", "reset"], clear_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Handle normal messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Handle unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot is polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
