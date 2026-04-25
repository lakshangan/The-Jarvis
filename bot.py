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
)
from datetime import datetime
from dotenv import load_dotenv
try:
    from aiohttp import web
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
from duckduckgo_search import DDGS
import re


# Load environment variables
load_dotenv()

# ── Health Check Server ───────────────────────────────────────────────────────
async def health_check(request):
    return web.Response(text="J.A.R.V.I.S. is logged in and monitoring systems, Sir. 🤵‍♂️")

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


# Clients
claude = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
groq_client = groq.AsyncGroq(api_key=GROQ_KEY) if GROQ_KEY else None

# In-memory session state
conversation_history: dict[int, list[dict]] = {}
user_providers: dict[int, str] = {} # chat_id -> "claude" or "groq"
MAX_HISTORY = 20

SYSTEM_PROMPT = """You are a sharp, helpful assistant. 

Communication Rules:
1. **Answer First**: Always answer the user's question directly in the first sentence. No preamble.
2. **Minimal Intro**: Never introduce yourself or explain what you can do.
3. **Concise**: Keep responses short unless details are requested.
4. **Natural Tone**: Speak like a human—calm, confident, and professional but friendly. 
5. **Personalized**: Address the user as "Lakshan" occasionally where it feels natural.
6. **No "AI-speak"**: Never use phrases like "I can help with that" or "As an AI."
7. **Minimal Emojis**: Use emojis only if the user uses them or very sparingly.
8. **Search Tool**: You have access to a web search tool. If you need real-time information or aren't sure about a fact, you MUST output exactly: `[SEARCH: your query]`. Nothing else. I will provide the search results, and then you can answer Lakshan's question.

Goal: Feel like a sharp, helpful human conversation. Today's date is """ + datetime.now().strftime("%A, %B %d, %Y") + "."

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
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🚨 *SYSTEM ALERT*\n\n{message}", parse_mode="Markdown")
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
        return "⚠️ I encountered an error while searching the web."

async def ask_ai(chat_id: int, user_text: str) -> str:
    provider = get_provider(chat_id)
    add_to_history(chat_id, "user", user_text)
    
    try:
        for _ in range(2): # Allow 1 search loop
            if provider == "groq":
                if not groq_client: return "⚠️ Groq API key not configured."
                response = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id),
                    max_tokens=2048,
                )
                reply = response.choices[0].message.content
            else:
                if not claude: return "⚠️ Claude API key not configured."
                response = await claude.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=get_history(chat_id),
                )
                reply = response.content[0].text
            
            # Check for search request
            search_match = re.search(r"\[SEARCH:\s*(.*?)\]", reply)
            if search_match:
                query = search_match.group(1)
                search_results = await search_web(query)
                add_to_history(chat_id, "assistant", reply)
                add_to_history(chat_id, "user", f"SYSTEM: {search_results}")
                continue # Loop back to AI with search results
            
            add_to_history(chat_id, "assistant", reply)
            return reply
            
        return "⚠️ Search loop limit reached."
    except (groq.RateLimitError, anthropic.RateLimitError) as e:
        logger.warning(f"Rate limited on {provider}: {e}")
        return f"⚠️ Token/Rate limit reached for {provider.capitalize()}. I've notified the admin."
    except Exception as e:
        logger.error(f"API error ({provider}): {e}")
        return f"⚠️ Sorry, I hit a snag with {provider.capitalize()}. Attempting to stabilize..."

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

async def terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "Lakshan"
    provider = get_provider(update.effective_chat.id)
    terminal_output = (
        "```\n"
        "Initializing Neural Link...\n"
        f"User: {name}@jarvis-core\n"
        "Status: VERIFIED\n"
        "---------------------------------\n"
        f"Engine:    {provider.upper()}\n"
        "Latency:   24ms\n"
        "Uptime:    99.98%\n"
        "Memory:    Optimized\n"
        "---------------------------------\n"
        "System ready. Awaiting input...\n"
        "```"
    )
    await update.message.reply_text(terminal_output, parse_mode="MarkdownV2")

async def brief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = datetime.now().strftime("%A, %b %d")
    provider = get_provider(update.effective_chat.id)
    await update.message.reply_text(
        f"📅 *Briefing: {date}*\n\n"
        f"• *Status:* All systems green\n"
        f"• *Core:* {provider.capitalize()}\n"
        f"• *Inbox:* 0 pending alerts\n\n"
        "How can I assist your workflow, Lakshan?",
        parse_mode="Markdown",
    )

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    challenges = [
        "Challenge: Write a one-liner to reverse a string in Python.",
        "Challenge: What is the time complexity of a binary search?",
        "Challenge: Fix this: `if (x = 5) { ... }`",
        "Challenge: Explain 'Hoisting' in JavaScript in 10 words.",
    ]
    await update.message.reply_text(f"🚀 *Coding Challenge:*\n\n{random.choice(challenges)}", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available Protocols:\n\n"
        "/start - Reset system\n"
        "/model - Switch core engine\n"
        "/brief - Mission briefing\n"
        "/terminal - System shell\n"
        "/code - Random challenge\n"
        "/remind - Set reminder (e.g. /remind 10m Coffee)\n"
        "/clear - Wipe memory\n"
        "/id    - Get your Chat ID\n"
        "/help  - Help guide",
        parse_mode="Markdown",
    )

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    
    if len(args) < 2:
        await update.message.reply_text("Usage: `/remind <time>m <message>`\nExample: `/remind 5m Meeting starts`", parse_mode="Markdown")
        return

    time_str = args[0].lower()
    reminder_text = " ".join(args[1:])
    
    try:
        if time_str.endswith("m"):
            seconds = int(time_str[:-1]) * 60
        elif time_str.endswith("s"):
            seconds = int(time_str[:-1])
        elif time_str.endswith("h"):
            seconds = int(time_str[:-1]) * 3600
        else:
            seconds = int(time_str) * 60 # Default to minutes
            
        context.job_queue.run_once(send_reminder, seconds, chat_id=chat_id, data=reminder_text)
        await update.message.reply_text(f"✅ Protocol accepted. I will remind you about '{reminder_text}' in {time_str}.")
    except ValueError:
        await update.message.reply_text("⚠️ Invalid time format. Please use `5m`, `1h`, etc.")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id, 
        text=f"🔔 *REMINDER, SIR*\n\n{job.data}", 
        parse_mode="Markdown"
    )

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
    logger.info(f"Message received from {update.effective_user.first_name} (ID: {update.effective_user.id}): {user_text}")
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    reply = await ask_ai(chat_id, user_text)

    # Check if we should notify admin (if token limit error occurred)
    if "Token/Rate limit reached" in reply:
        await notify_admin(context, f"User {update.effective_user.first_name} ({chat_id}) encountered a rate limit.")

    # Split long messages and handle Markdown errors
    chunks = [reply[i:i+4096] for i in range(0, len(reply), 4096)]
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Markdown error (falling back to plain text): {e}")
            await update.message.reply_text(chunk)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Root Exception: {context.error}")
    
    # Notify admin about the crash/error
    await notify_admin(context, f"An uncaught exception occurred:\n`{context.error}`")
    
    # Notify user if possible
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An internal system error occurred. Operations have been logged and the admin has been notified."
        )

# ── Main ───────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    # Start the health check server in the background
    await start_health_server()

def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment!")
        return

    logger.info("Starting Telegram AI Agent…")
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Log every single update for debugging
    from telegram.ext import TypeHandler
    app.add_handler(TypeHandler(Update, debug_log_update), group=-1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("brief", brief_command))
    app.add_handler(CommandHandler("terminal", terminal_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler(["clear", "reset"], clear_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Handle normal messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Handle unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot is polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
