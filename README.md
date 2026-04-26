# J.A.R.V.I.S. — Advanced Multi-Modal AI Agent

**J.A.R.V.I.S.** is a state-of-the-art Telegram AI agent designed for power users who need a seamless "Neural Link" to the world's most capable AI engines. It integrates real-time web browsing, multi-modal analysis (Vision/Voice/Docs), and persistent productivity tools.

---

## 🚀 Key Features

### 🧠 Intelligence & Knowledge
- **Multi-LLM Core**: Toggle between **Anthropic Claude 3.5 Sonnet** (Complex Reasoning & Vision) and **Groq Llama 3.3** (Lightning Fast) via `/model`.
- **Live Web Browsing**: 
  - **Global Search**: Autonomously searches DuckDuckGo for real-time facts.
  - **Neural Web Link**: Directly fetches and summarizes content from any URL provided (`[READ: url]`).
- **Contextual Memory**: Remembers your conversation history for nuanced follow-up discussions.

### 🎙️ Multi-Modal Capabilities
- **Voice Intelligence**: Send voice notes to J.A.R.V.I.S. He uses **Groq Whisper-v3** for near-instant transcription and response.
- **Vision Core**: Upload images for analysis. Claude 3.5 Sonnet can describe scenes, read charts, or explain diagrams.
- **Document Intelligence**: Upload code (`.py`, `.js`), logs, or text files for deep analysis, debugging, or summarization.

### ⚡ Productivity & Systems
- **AI-Driven Reminders**: Set reminders using natural language (*"Remind me in 1 hour to check the oven"*) or command `/remind`.
- **Persistent Job Queue**: Reminders are saved to disk and re-scheduled automatically if the bot restarts.
- **System Telemetry**: Real-time hardware monitoring via `/terminal` (CPU Load, RAM usage, and active tasks).
- **Status Protocol**: View all active alerts and countdowns via `/status`.

---

## 🛠️ Technical Stack

- **Core Framework**: `python-telegram-bot` v21.6 (Async/Await)
- **AI Providers**:
  - **Anthropic**: Claude 3.5 Sonnet (Vision & Logic)
  - **Groq**: Llama 3.3 70B (Text) & Whisper-v3 (Voice)
- **Web Intelligence**: `beautifulsoup4` (Scraping), `duckduckgo-search` (API)
- **Systems & Ops**: 
  - `psutil`: Hardware monitoring
  - `APScheduler`: Persistent job management
  - `aiohttp`: Health-check server for 24/7 uptime

---

## ⚙️ Setup Guide

### 1. Environment Variables
Create a `.env` file:
```env
TELEGRAM_BOT_TOKEN=your_token
GROQ_API_KEY=your_groq_key
ANTHROPIC_API_KEY=your_claude_key
ADMIN_CHAT_ID=your_id (Get via /id)
```

### 2. Installation
```bash
pip install -r requirements.txt
python bot.py
```

---

## 🎮 Core Protocols

| Protocol | Description |
|---------|-------------|
| `/start` | Re-initialize JARVIS systems |
| `/model` | Switch between Claude and Groq engines |
| `/remind` | Schedule an alert (or just talk to JARVIS) |
| `/status` | View all active persistent reminders |
| `/terminal` | View live system telemetry (CPU/RAM/Tasks) |
| `/brief` | Mission briefing & daily summary |
| `/clear` | Wipe short-term memory buffer |

---

## 🚢 Deployment
Optimized for **Render.com** (Worker service) or **Docker**.
1. Connect GitHub.
2. The `render.yaml` and `Dockerfile` are pre-configured for automated builds.
3. Ensure `ADMIN_CHAT_ID` is set to receive critical system alerts.
