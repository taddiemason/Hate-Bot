import os
import json
import math
import random
import asyncio
import tempfile
import datetime
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from openai import AsyncOpenAI
from gtts import gTTS

load_dotenv()

TARGET_NAME = os.getenv("TARGET_NAME", "Donovan")
TARGET_USERNAMES = {u.strip().lower() for u in os.getenv("TARGET_USERNAMES", "itsrebrand,streamerweiner").split(",") if u.strip()}
TARGET_STOCK_TICKER = os.getenv("TARGET_STOCK_TICKER", TARGET_NAME.upper()[:8])

def _t(s: str) -> str:
    """Replace default target placeholders with configured TARGET_NAME."""
    return (s.replace("Donovan", TARGET_NAME)
             .replace("DONOVAN", TARGET_STOCK_TICKER)
             .replace("donovan", TARGET_NAME.lower()))

import aiohttp.web
from web_admin import create_web_app, ADMIN_PASSWORD

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)
groq_client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

COUNTER_FILE = "roast_count.json"
ROAST_LOG_FILE = "roast_log.json"
ECONOMY_FILE = "economy.json"
MILESTONES = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
DONOVAN_USERNAMES = TARGET_USERNAMES
ROAST_CHANNEL_ID = int(os.getenv("ROAST_CHANNEL_ID", 0))
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", 0))
INSURANCE_COST_PER_MINUTE = 10
MAX_INSURANCE_MINUTES = 30
