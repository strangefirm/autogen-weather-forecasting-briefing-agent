# 🌦️ Weather Briefing Agent

An AI agent built with **Microsoft AutoGen** and **Streamlit** that produces a concise weather briefing for any city and, optionally, emails it to you. The agent decides which tools to call, in order, and streams its answer to the page in real time.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B)
![AutoGen](https://img.shields.io/badge/agent-AutoGen-6f42c1)
![Model](https://img.shields.io/badge/LLM-gpt--4o--mini-10a37f)

---

## Features

- **Autonomous tool use**: an AutoGen `AssistantAgent` chains four tools without hard-coded control flow.
- **Live workflow tracker**: seven steps (Collect → Geocode → Fetch → Process → Summarize → Use AI → Email) update as the agent works.
- **Streaming briefing**: the AI-written Markdown briefing appears token by token.
- **Forecast visuals**: 5-day cards, a max/min temperature line chart and a rain-chance bar chart.
- **Email delivery**: sends the briefing through the Gmail API using OAuth.
- **Caching**: forecast requests are cached for 10 minutes.

## How it works

```
 City (+ optional email)
        │
        ▼
 ┌──────────────────┐   1. geocode_city          → Open-Meteo Geocoding API
 │  AutoGen Agent   │   2. get_5_day_forecast    → Open-Meteo Forecast API
 │  (gpt-4o-mini)   │   3. search_weather_news   → DuckDuckGo News
 └──────────────────┘   4. send_email            → Gmail API (optional)
        │
        ▼
 Streamed Markdown briefing + forecast cards and charts
```

| Tool | Purpose | Source |
|------|---------|--------|
| `geocode_city` | City → latitude, longitude, country | Open-Meteo (no key) |
| `get_5_day_forecast` | Daily conditions, temperatures, rain chance, wind | Open-Meteo (no key) |
| `search_weather_news` | Latest weather headlines | DuckDuckGo via `ddgs` |
| `send_email` | Send the briefing | Gmail API (OAuth) |

## Project structure

```
W5D2/
├── app1.py            # Streamlit app: full agent + UI (main entry point)
├── app.py             # Minimal console version: single-tool agent
├── requirements.txt   # Python dependencies
├── .streamlit/
│   └── config.toml    # Streamlit configuration
├── .env               # API keys (not committed)
├── credentials.json   # Google OAuth client secrets (not committed)
└── token.json         # Generated Gmail token (not committed)
```

## Getting started

### Prerequisites

- Python 3.10+
- An [OpenAI API key](https://platform.openai.com/api-keys)
- *(Optional, for email)* a Google Cloud project with the Gmail API enabled

### 1. Clone and install

```bash
git clone <your-repo-url>
cd <repo>/W5D2

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in `W5D2/`:

```env
OPENAI_API_KEY=your-openai-api-key
```

### 3. (Optional) Enable email

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Gmail API**.
2. Create an **OAuth client ID** of type *Desktop app* and download the JSON.
3. Save it as `W5D2/credentials.json`.
4. On the first email send, a browser window opens to authorize access. A `token.json` is then created and reused.

Only the `gmail.send` scope is requested. The app cannot read your mailbox.

### 4. Run

```bash
streamlit run app1.py
```

Enter a city in the sidebar, optionally add an email address, and click **Get my briefing**.

For the minimal console agent:

```bash
python app.py
```

## Configuration

| Setting | Location | Notes |
|---------|----------|-------|
| `OPENAI_API_KEY` | `.env` | Required |
| Model | `build_agent()` in `app1.py` | Defaults to `gpt-4o-mini` |
| Max tool calls per run | `max_tool_iterations` in `build_agent()` | Defaults to `6` |
| Forecast cache TTL | `@st.cache_data(ttl=600)` | 10 minutes |

## Security

Never commit secrets. Add this to your `.gitignore` before the first commit:

```gitignore
.env
credentials.json
token.json
venv/
__pycache__/
```

If any of these files were ever pushed, revoke and rotate the keys.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `OPENAI_API_KEY is not set` | Add the key to `W5D2/.env` and restart Streamlit |
| `Email not sent: credentials.json is missing` | Complete the optional email setup above |
| Google sign-in does not appear | Delete `token.json` and retry |
| City not found | Try a more specific name, e.g. `Paris` instead of `Paris, TX` |
| No news results | DuckDuckGo may be rate-limiting; wait and retry |

## Tech stack

[AutoGen](https://microsoft.github.io/autogen/) · [Streamlit](https://streamlit.io/) · [Open-Meteo](https://open-meteo.com/) · [ddgs](https://pypi.org/project/ddgs/) · [Google Gmail API](https://developers.google.com/gmail/api) · [pandas](https://pandas.pydata.org/)

## License
MIT license