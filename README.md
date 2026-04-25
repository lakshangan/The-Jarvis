# 🤖 J.A.R.V.I.S. — Multi-LLM AI Agent

**J.A.R.V.I.S.** is a professional-grade Telegram AI agent designed for speed, intelligence, and utility. It seamlessly integrates real-time web search, proactive reminders, and state-of-the-art language models (LLMs) into a single, responsive interface.

---

## 🚀 Overview
At its core, this agent acts as a "Neural Link" between your Telegram chat and the world's most powerful AI engines. Whether you need deep reasoning from **Claude 3.5 Sonnet** or lightning-fast responses from **Groq (Llama 3.3)**, J.A.R.V.I.S. adapts to your workflow.

---

## ✨ Features

### 🧠 Intelligence & Knowledge
- **Dual-Engine Architecture**: Toggle between **Anthropic Claude 3.5** (Intelligence) and **Groq Llama 3.3** (Speed) using `/model`.
- **🔍 Live Web Search**: Integrated **DuckDuckGo** search engine. If the AI lacks real-time info, it autonomously searches the web to provide up-to-date answers.
- **Contextual Memory**: Maintains a sliding window of the last 20 messages for multi-turn reasoning.

### ⏰ Productivity & Utility
- **Proactive Reminders**: Set time-based notifications using the `/remind` command (e.g., `/remind 15m Join the standup`).
- **Terminal Simulation**: A high-fidelity `/terminal` mode for system status and uptime visualization.
- **Auto-Message Splitting**: Gracefully handles large AI responses by auto-splitting data over Telegram’s 4096-character limit.

### 🛠️ Technical Excellence
- **Polling Architecture**: Built on `python-telegram-bot` v21+, utilizing an asynchronous event loop for zero-latency interaction.
- **Health Monitoring**: Integrated `aiohttp` server providing a `/` health-check endpoint for 24/7 uptime monitoring (perfect for Render/Railway).
- **Global Error Handling**: Robust error-trapping and admin notification system to ensure stability.

---

## 🛠️ Technical Stack
- **Framework**: Python 3.11+ | `python-telegram-bot`
- **AI Engines**: Groq (Llama 3.3 70B), Anthropic (Claude 3.5 Sonnet)
- **Networking**: `httpx`, `aiohttp` (Health Checks)
- **Utilities**: `duckduckgo-search` (Web Access), `APScheduler` (JobQueue)

---

## 🚀 Setup Guide

### 1. Environment Variables
Create a `.env` file in the root directory:
```env
TELEGRAM_BOT_TOKEN=your_telegram_token
GROQ_API_KEY=your_groq_key
ANTHROPIC_API_KEY=your_claude_key (Optional)
ADMIN_CHAT_ID=your_id (Get it via /id)
```

### 2. Local Installation
```bash
# Set up environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run Agent
python bot.py
```

---

## 💬 Core Commands

| Command | Protocol Description |
|---------|----------------------|
| `/start` | System initialization & greeting |
| `/model` | Toggle between AI engines (Groq/Claude) |
| `/remind` | Schedule time-based reminders (`/remind 10m Message`) |
| `/brief` | Daily status and mission briefing |
| `/id` | Retrieve your unique Telegram Chat ID |
| `/clear` | Wipe short-term memory buffer |

---

## ☁️ Deployment
This repository is optimized for **Render.com** (as a Worker) or **Docker**.
1. Connect your GitHub.
2. Add your `.env` variables in the dashboard.
3. The `render.yaml` and `Dockerfile` will handle the rest automatically.
