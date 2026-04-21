import os
import logging
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
from aiohttp import web

# Load environment variables
load_dotenv()

# ── Health Check Server ───────────────────────────────────────────────────────
async def health_check(request):
    return web.Response(text="J.A.R.V.I.S. is logged in and monitoring systems, Sir. 🤵‍♂️")

async def start_health_server():
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

# Clients
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
groq_client = groq.Groq(api_key=GROQ_KEY) if GROQ_KEY else None

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

Goal: Feel like a sharp, helpful human conversation. Today's date is """ + datetime.now().strftime("%A, %B %d, %Y") + "."

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_history(chat_id: int) -> list[dict]:
    return conversation_history.setdefault(chat_id, [])

def add_to_history(chat_id: int, role: str, content: str):
    history = get_history(chat_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        conversation_history[chat_id] = history[-MAX_HISTORY:]

def get_provider(chat_id: int) -> str:
    # Default to Groq if key is available, otherwise Claude
    if chat_id not in user_providers:
        if GROQ_KEY:
            user_providers[chat_id] = "groq"
        elif ANTHROPIC_KEY:
            user_providers[chat_id] = "claude"
        else:
            user_providers[chat_id] = "unknown"
    return user_providers[chat_id]

async def ask_ai(chat_id: int, user_text: str) -> str:
    provider = get_provider(chat_id)
    add_to_history(chat_id, "user", user_text)
    
    try:
        if provider == "groq":
            if not groq_client: return "⚠️ Groq API key not configured."
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + get_history(chat_id),
                max_tokens=2048,
            )
            reply = response.choices[0].message.content
        else:
            if not claude: return "⚠️ Claude API key not configured."
            response = claude.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=get_history(chat_id),
            )
            reply = response.content[0].text
            
        add_to_history(chat_id, "assistant", reply)
        return reply
    except Exception as e:
        logger.error(f"API error ({provider}): {e}")
        return f"⚠️ Sorry, I hit an error with {provider.capitalize()}. Please try again or switch providers."

# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "Lakshan"
    provider = get_provider(update.effective_chat.id)
    await update.message.reply_text(
        f"Hi {name}, I'm ready to help. I'm currently using {provider.capitalize()}.\n\n"
        "Use /model to switch engines or just send a message to start.",
        parse_mode="Markdown",
    )

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
    import random
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
        "/clear - Wipe memory\n"
        "/help  - Help guide",
        parse_mode="Markdown",
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text("Memory wiped.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    if not user_text: return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    reply = await ask_ai(chat_id, user_text)

    # Split long messages
    if len(reply) <= 4096:
        await update.message.reply_text(reply, parse_mode="Markdown")
    else:
        for i in range(0, len(reply), 4096):
            await update.message.reply_text(reply[i:i+4096], parse_mode="Markdown")

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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("brief", brief_command))
    app.add_handler(CommandHandler("terminal", terminal_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
