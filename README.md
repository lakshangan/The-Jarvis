# 🤖 Multi-LLM Telegram AI Agent

A smart Telegram bot powered by **Groq (Llama 3.3)** and **Anthropic (Claude 3.5)**. It can answer questions, help with research, track tasks, and hold multi-turn conversations.

---

## ✨ Features

- 🚀 **Dual AI Engines** — Switch between **Groq** (insanely fast) and **Claude** (highly intelligent).
- 🧠 **Memory** — Remembers conversation context (last 20 messages).
- ✅ **Task tracking** — Ask it to remember tasks, reminders, or lists.
- 💬 **Command-based toggling** — Use `/model` to switch providers on the fly.
- ♾️ **Long messages** — Auto-splits responses over Telegram's 4096-char limit.

---

## 🚀 Setup Guide (Local)

### 1. Configure Keys
I have created a `.env` file for you. Ensure it contains your keys:
```env
TELEGRAM_BOT_TOKEN=your_token
GROQ_API_KEY=your_groq_key
# ANTHROPIC_API_KEY=your_claude_key
```

### 2. Install & Run
Since macOS manages Python environments, use a virtual environment:

```bash
# Set up venv
python3 -m venv venv

# Activate venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

---

## 💬 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message & current status |
| `/model` | **Switch between Groq and Claude** |
| `/clear` | Reset conversation history |
| `/help` | Show available commands |

---

## ☁️ Deployment

### Render.com / Railway.app
1. Push to GitHub.
2. Add your environment variables (`TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, etc.) in the dashboard.
3. The bot will automatically use the `Dockerfile` or `render.yaml`.

---

## 📄 License
MIT — use freely!
