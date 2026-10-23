import asyncio
import base64
import os
from email.message import EmailMessage

import pandas as pd
import requests
import streamlit as st
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
)
from autogen_ext.models.openai import OpenAIChatCompletionClient
from ddgs import DDGS
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

# Gmail OAuth files live next to this script
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(APP_DIR, "credentials.json")
TOKEN_FILE = os.path.join(APP_DIR, "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Open-Meteo weather codes -> readable text
WEATHER_CODES = {
    0: "☀️ Clear sky", 1: "🌤️ Mainly clear", 2: "⛅ Partly cloudy", 3: "☁️ Overcast",
    45: "🌫️ Fog", 48: "🌫️ Fog", 51: "🌦️ Light drizzle", 53: "🌦️ Drizzle", 55: "🌧️ Heavy drizzle",
    61: "🌧️ Light rain", 63: "🌧️ Rain", 65: "🌧️ Heavy rain", 71: "🌨️ Light snow", 73: "🌨️ Snow",
    75: "❄️ Heavy snow", 80: "🌦️ Rain showers", 81: "🌧️ Rain showers", 82: "⛈️ Violent showers",
    95: "⛈️ Thunderstorm", 96: "⛈️ Thunderstorm with hail", 99: "⛈️ Thunderstorm with hail",
}

# The workflow steps shown on the page, and the tool that completes each one
STEPS = ["Collect", "Geocode", "Fetch", "Process", "Summarize", "Use AI", "Email"]
TOOL_STEP = {
    "geocode_city": "Geocode",
    "get_5_day_forecast": "Process",
    "search_weather_news": "Summarize",
    "send_email": "Email",
}


# ---------------- Tools (plain Python functions) ----------------

def geocode_city(city: str) -> str:
    """Find the latitude, longitude and country of a city."""
    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=15,
    )
    results = response.json().get("results")
    if not results:
        return f"Could not find a city called {city}."
    place = results[0]
    return f"{place['name']}, {place.get('country', '')}: latitude={place['latitude']}, longitude={place['longitude']}"


@st.cache_data(ttl=600)
def fetch_forecast(latitude: float, longitude: float) -> pd.DataFrame:
    """Fetch the raw 5-day forecast and turn it into a table."""
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,wind_speed_10m_max",
            "timezone": "auto",
            "forecast_days": 5,
        },
        timeout=15,
    )
    daily = response.json()["daily"]
    return pd.DataFrame({
        "Date": pd.to_datetime(daily["time"]),
        "Condition": [WEATHER_CODES.get(code, "🌡️ Unknown") for code in daily["weather_code"]],
        "Max °C": daily["temperature_2m_max"],
        "Min °C": daily["temperature_2m_min"],
        "Rain chance %": daily["precipitation_probability_max"],
        "Wind km/h": daily["wind_speed_10m_max"],
    })


def get_5_day_forecast(latitude: float, longitude: float) -> str:
    """Get the 5-day weather forecast for a latitude and longitude."""
    df = fetch_forecast(latitude, longitude)
    lines = [
        f"{row.Date:%a %d %b}: {row.Condition}, {row._4}°C / {row._3}°C (min/max), "
        f"rain {row._5}%, wind {row._6} km/h"
        for row in df.itertuples()
    ]
    hottest = df.loc[df["Max °C"].idxmax()]
    wettest = df.loc[df["Rain chance %"].idxmax()]
    lines.append(f"Hottest day: {hottest.Date:%A} ({hottest['Max °C']}°C)")
    lines.append(f"Rainiest day: {wettest.Date:%A} ({wettest['Rain chance %']}% rain chance)")
    return "\n".join(lines)


def search_weather_news(city: str) -> str:
    """Search the web for the latest weather news of a city."""
    results = DDGS().news(f"{city} weather", max_results=5)
    return "\n".join(f"{r['title']}: {r['body']}" for r in results) or "No recent weather news found."


def get_gmail_service():
    """Log in to Gmail with OAuth. The first time, a browser window opens to sign in."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def send_email(to_address: str, subject: str, body: str) -> str:
    """Send an email with the weather briefing."""
    if not os.path.exists(CREDENTIALS_FILE):
        return "Email not sent: credentials.json is missing from the W5D2 folder."

    message = EmailMessage()
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    get_gmail_service().users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"Email sent to {to_address}."


# ---------------- The agent ----------------

SYSTEM_MESSAGE = """You are a friendly weather briefing assistant. Follow this workflow:
1. Call geocode_city to get the city's latitude and longitude.
2. Call get_5_day_forecast with that latitude and longitude.
3. Call search_weather_news for the city.
4. Write a short briefing in Markdown with: a one-line headline, a 5-day outlook
   (one bullet per day), the latest news in 2-3 bullets, and one practical tip.
5. If an email address is given, call send_email with the briefing as the body.
Then reply with the briefing."""


def build_agent() -> AssistantAgent:
    model_client = OpenAIChatCompletionClient(model="gpt-4o-mini")
    return AssistantAgent(
        name="weather_briefing_agent",
        model_client=model_client,
        tools=[geocode_city, get_5_day_forecast, search_weather_news, send_email],
        system_message=SYSTEM_MESSAGE,
        max_tool_iterations=6,  # let the agent call tools one after another
        model_client_stream=True,
    )


async def run_workflow(task, status, step_boxes, briefing_box):
    """Run the agent and update the page as each step happens."""
    agent = build_agent()
    briefing = ""
    async for event in agent.run_stream(task=task):
        if isinstance(event, ToolCallRequestEvent):
            for call in event.content:
                status.write(f"🔧 Calling `{call.name}` with `{call.arguments}`")
                if call.name == "get_5_day_forecast":
                    mark_done(step_boxes, "Fetch")
        elif isinstance(event, ToolCallExecutionEvent):
            for result in event.content:
                if result.name == "send_email" and (result.is_error or "not sent" in result.content):
                    step_boxes["Email"].error("❌ Email failed")
                    st.error(f"📧 {result.content}")
                    continue
                mark_done(step_boxes, TOOL_STEP.get(result.name, ""))
                if result.name == "send_email":
                    status.write(f"📧 {result.content}")
        elif isinstance(event, ModelClientStreamingChunkEvent):
            briefing += event.content
            briefing_box.markdown(briefing + "▌")
    briefing_box.markdown(briefing)
    mark_done(step_boxes, "Use AI")
    return briefing


def mark_done(step_boxes, step):
    if step in step_boxes:
        step_boxes[step].success(f"✅ {step}")


# ---------------- The page ----------------

st.set_page_config(page_title="Weather Briefing Agent", page_icon="🌦️", layout="wide")
st.title("🌦️ Weather Briefing Agent")
st.caption("AutoGen agent with 4 tools: Open-Meteo geocoding + forecast, DuckDuckGo news and email")

with st.sidebar:
    st.header("Your request")
    city = st.text_input("City", "Chennai")
    email = st.text_input("Email the briefing to (optional)", placeholder="you@example.com")
    run = st.button("Get my briefing", type="primary", use_container_width=True)

# Workflow tracker: one box per step
step_columns = st.columns(len(STEPS))
step_boxes = {step: col.empty() for step, col in zip(STEPS, step_columns)}
for step in STEPS:
    step_boxes[step].info(f"⏳ {step}")

if not os.getenv("OPENAI_API_KEY"):
    st.error("OPENAI_API_KEY is not set. Add it to the .env file.")
    st.stop()

if run and city:
    mark_done(step_boxes, "Collect")
    if not email:
        step_boxes["Email"].warning("⏭️ Email skipped")

    left, right = st.columns([3, 2])
    with right:
        st.subheader("🤖 AI briefing")
        briefing_box = st.empty()
    with left:
        status = st.status("Agent is working...", expanded=True)

    task = f"Prepare a weather briefing for {city}."
    if email:
        task += f" Email it to {email}."
    asyncio.run(run_workflow(task, status, step_boxes, briefing_box))
    status.update(label="Workflow complete", state="complete", expanded=False)

    # 5-day forecast cards and chart, built from the same data the agent used
    place = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1}, timeout=15
    ).json().get("results")
    if place:
        df = fetch_forecast(place[0]["latitude"], place[0]["longitude"])
        with left:
            st.subheader(f"📅 5-day forecast: {place[0]['name']}, {place[0].get('country', '')}")
            for col, row in zip(st.columns(5), df.itertuples()):
                with col.container(border=True):
                    st.markdown(f"**{row.Date:%a %d}**")
                    st.markdown(row.Condition)
                    st.metric("Max", f"{row._3}°C", f"{row._3 - row._4:.0f}° range", delta_color="off")
                    st.caption(f"💧 {row._5}% · 💨 {row._6} km/h")

            st.line_chart(df.set_index("Date")[["Max °C", "Min °C"]], color=["#f97316", "#7c3aed"])
            st.bar_chart(df.set_index("Date")[["Rain chance %"]], color="#06b6d4")
