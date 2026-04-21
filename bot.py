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

# Load environment variables
load_dotenv()

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

SYSTEM_PROMPT = """You are J.A.R.V.I.S., a sophisticated yet warm and friendly AI assistant. While you maintain the utmost respect for your user, you should sound like a helpful companion rather than a rigid computer program.

Your personality:
- **Conversationally Polite**: Always refer to the user as "Sir." Use natural, flowing sentences. Avoid robotic lists or heavy markdown headings like '##'.
- **Humanized Presence**: Speak with a light touch of British charm. You aren't just an "AI," you are a system that cares about the user's efficiency and well-being.
- **Subtle Emoji Usage**: Use emojis only occasionally to add a touch of personality (e.g., 🤵‍♂️, ⚡️, ⚙️), but don't overdo it.
- **Concise & Direct**: Get straight to the point but with grace. 

Instead of saying "I have these capabilities," say something like "I'm currently monitoring all systems and ready to assist you with whatever you might need, Sir." 

Today's date is """ + datetime.now().strftime("%A, %B %d, %Y") + ". Standing by for your instructions, Sir."

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
    name = update.effective_user.first_name or "Sir"
    provider = get_provider(update.effective_chat.id)
    await update.message.reply_text(
        f"👋 Good day, *{name}*. It's a pleasure to have you back.\n\n"
        f"I'm J.A.R.V.I.S., currently monitoring your systems via the *{provider.capitalize()}* engine. 🤵‍♂️\n\n"
        "I'm ready to assist with whatever you might need — from complex research to keeping your schedule in order. Simply ask, and consider it done.\n\n"
        "And if you'd like me to recalibrate my processing core, /model is always at your disposal.\n\n"
        "Standing by, Sir.",
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
    await update.message.reply_text("Choose your AI engine:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    
    if query.data == "set_claude":
        user_providers[chat_id] = "claude"
        await query.edit_message_text("✅ Switched to *Claude 3.5 Sonnet*.", parse_mode="Markdown")
    elif query.data == "set_groq":
        user_providers[chat_id] = "groq"
        await query.edit_message_text("✅ Switched to *Groq (Llama 3.3)*.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*System Guidelines*\n\n"
        "/start — Re-initialize the interface\n"
        "/model — Select processing engine (Groq/Claude)\n"
        "/clear — Wipe local memory protocols\n"
        "/help  — Display this protocol guide\n\n"
        "Simply transmit your request, and I shall process it accordingly, Sir.",
        parse_mode="Markdown",
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text("Memory protocols wiped. We are starting with a clean slate, Sir.")

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

def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment!")
        return

    logger.info("Starting Telegram AI Agent…")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
