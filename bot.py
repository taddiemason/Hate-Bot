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

def _t(s: str, guild_id=None) -> str:
    """Replace target placeholders. guild_id uses that guild's target; None uses global defaults."""
    if guild_id:
        t = get_guild_target(guild_id)
        name, ticker = t["name"], t["ticker"]
    else:
        name, ticker = TARGET_NAME, TARGET_STOCK_TICKER
    return (s.replace("Donovan", name)
             .replace("DONOVAN", ticker)
             .replace("donovan", name.lower()))

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

SHOP_ITEMS = {
    "shame_bell": {
        "name": "Shame Bell",
        "cost": 50,
        "description": "Next roast comes with a 🔔 SHAME 🔔 announcement",
    },
    "snitch": {
        "name": "Snitch",
        "cost": 75,
        "description": "Next roast also gets DMed directly to Donovan",
    },
    "slow_clap": {
        "name": "Slow Clap",
        "cost": 75,
        "description": "HateBot reacts to Donovan's next message with a series of 👏 emojis",
    },
    "receipt": {
        "name": "Receipt",
        "cost": 80,
        "description": "HateBot digs up and quotes one of his old messages alongside the roast",
    },
    "laugh_track": {
        "name": "Laugh Track",
        "cost": 90,
        "description": "Next roast is followed by 😂 spam from the HateBot",
    },
    "double_roast": {
        "name": "Double Roast",
        "cost": 100,
        "description": "Your next @mention fires TWO roasts back to back",
    },
    "triple_roast": {
        "name": "Triple Roast",
        "cost": 125,
        "description": "Next roast fires THREE times in a row",
    },
    "anonymous": {
        "name": "Anonymous",
        "cost": 150,
        "description": "Next roast is delivered as an anonymous tip",
    },
    "spotlight": {
        "name": "Spotlight",
        "cost": 175,
        "description": "Next roast pings @here so nobody misses it",
    },
    "mega_roast": {
        "name": "Mega Roast",
        "cost": 200,
        "description": "Your next @mention also triggers an extra savage bonus roast",
    },
    "press_release": {
        "name": "Press Release",
        "cost": 225,
        "description": "HateBot a fake formal press release announcing his latest L",
    },
    "hall_of_shame": {
        "name": "Hall of Shame",
        "cost": 250,
        "description": "Next roast gets pinned in the channel permanently",
    },
    "breaking_news": {
        "name": "Breaking News",
        "cost": 250,
        "description": "HateBot posts a fake breaking news alert about him",
    },
    "intervention": {
        "name": "Intervention",
        "cost": 275,
        "description": "HateBot @everyone and announces a formal server intervention for his behavior",
    },
    "scorched_earth": {
        "name": "Scorched Earth",
        "cost": 300,
        "description": "HateBot Generates 3 different unique roasts back to back",
    },
    "bounty_boost": {
        "name": "Bounty Boost",
        "cost": 350,
        "description": "Your next bounty claim pays out double",
    },
    "exile": {
        "name": "Exile",
        "cost": 400,
        "description": "Timeouts Donovan in the server for 60 seconds",
    },
    "lore_drop": {
        "name": "Lore Drop",
        "cost": 400,
        "description": "HateBot generates a full absurd origin story for why Donovan is the way he is",
    },
    "nuclear": {
        "name": "Nuclear",
        "cost": 500,
        "description": "Maximum Hatebot roast + forces TTS even if it's off",
    },
    "eulogy": {
        "name": "Eulogy",
        "cost": 150,
        "description": "HateBot delivers a dramatic funeral eulogy for Donovan's dignity, as if it has already passed away",
    },
    "wanted_poster": {
        "name": "Wanted Poster",
        "cost": 175,
        "description": "HateBot generates a fake FBI wanted poster describing Donovan's crimes against the server",
    },
    "therapy_session": {
        "name": "Therapy Session",
        "cost": 200,
        "description": "HateBot roleplays as Donovan's therapist and reads his 'case notes' aloud in the channel",
    },
    "cease_and_desist": {
        "name": "Cease & Desist",
        "cost": 225,
        "description": "HateBot drafts a formal legal letter demanding Donovan stop being himself immediately",
    },
    "linkedin_post": {
        "name": "LinkedIn Post",
        "cost": 250,
        "description": "HateBot writes a cringe corporate LinkedIn post from Donovan's perspective hyping up his latest L as a 'growth opportunity'",
    },
    "documentary": {
        "name": "Documentary",
        "cost": 325,
        "description": "HateBot generates a Ken Burns-style documentary narration about a recent Donovan moment, complete with dramatic pauses",
    },
    "legacy_mode": {
        "name": "Legacy Mode",
        "cost": 450,
        "description": "HateBot compiles Donovan's greatest hits — his worst moments from server history — into one devastating highlight reel recap",
    },
    "motivational_poster": {
        "name": "Motivational Poster",
        "cost": 200,
        "description": "HateBot generates a fake inspirational quote attributed to Donovan paired with the most embarrassing context possible",
    },
    "autopsy_report": {
        "name": "Autopsy Report",
        "cost": 225,
        "description": "HateBot produces a clinical medical examiner's report on the cause of death of Donovan's credibility",
    },
    "wikipedia_page": {
        "name": "Wikipedia Page",
        "cost": 325,
        "description": "HateBot generates a fake Wikipedia article about Donovan complete with a controversies section",
    },
    "parole_hearing": {
        "name": "Parole Hearing",
        "cost": 350,
        "description": "HateBot conducts a formal parole board hearing to determine whether Donovan has earned the right to be taken seriously again — verdict always denied",
    },
    "dossier": {
        "name": "Dossier",
        "cost": 400,
        "description": "HateBot compiles and presents a full classified intelligence briefing on Donovan, his known associates, and his pattern of behavior",
    },
    "state_of_the_union": {
        "name": "State of the Union",
        "cost": 475,
        "description": "HateBot delivers a presidential address formally assessing the ongoing Donovan situation, its impact on national morale, and the administration's response plan",
    },
}

tts_enabled = True
tts_queue = asyncio.Queue()
trial_active = False
guess_game_active = False
trivia_active = False
trivia_recent = {}        # channel_id -> last 8 question strings
trivia_recent_cats = {}   # channel_id -> last 4 categories
guessroast_active = False
highlow_games = {}
blackjack_games = {}
sports_trivia_active = {}

SLOT_SYMBOLS = ["🍋", "🍒", "🍇", "💎", "🎰", "7️⃣"]
SLOT_PAYOUTS = {("7️⃣", "7️⃣", "7️⃣"): 50, ("💎", "💎", "💎"): 25, ("🎰", "🎰", "🎰"): 15}

CARD_SUITS = ["♠", "♥", "♦", "♣"]
CARD_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

SERVER_ROAST_MILESTONES = {100: 50, 250: 75, 500: 100, 1000: 200, 2500: 300, 5000: 500}

TRIVIA_QUESTIONS = [
    {"q": "What fast food item does Donovan famously defend as underrated?", "a": "big mac"},
    {"q": "What game does Donovan always blame his deaths on?", "a": "rust"},
    {"q": "What is always stuck to Donovan's ass?", "a": "burger wrappers"},
    {"q": "What is the capital of France?", "a": "paris"},
    {"q": "How many sides does a hexagon have?", "a": "6"},
    {"q": "What year did the first iPhone launch?", "a": "2007"},
    {"q": "What planet is known as the Red Planet?", "a": "mars"},
    {"q": "What is the chemical symbol for gold?", "a": "au"},
    {"q": "How many players are on a basketball team on the court at once?", "a": "5"},
    {"q": "What is the largest ocean on Earth?", "a": "pacific"},
    {"q": "What year did World of Warcraft originally launch?", "a": "2004"},
    {"q": "How many strings does a standard guitar have?", "a": "6"},
    {"q": "What is 7 multiplied by 8?", "a": "56"},
    {"q": "What country is home to the kangaroo?", "a": "australia"},
    {"q": "What is the hardest natural substance on Earth?", "a": "diamond"},
    # Geography
    {"q": "What is the capital of Japan?", "a": "tokyo"},
    {"q": "What is the smallest country in the world?", "a": "vatican"},
    {"q": "What river runs through Egypt?", "a": "nile"},
    {"q": "What is the capital of Australia?", "a": "canberra"},
    {"q": "Which country has the most natural lakes?", "a": "canada"},
    {"q": "What is the longest mountain range in the world?", "a": "andes"},
    {"q": "What ocean lies between Europe and North America?", "a": "atlantic"},
    {"q": "What is the capital of Brazil?", "a": "brasilia"},
    {"q": "Which country is home to the Amazon rainforest mostly?", "a": "brazil"},
    {"q": "What US state has the most coastline?", "a": "alaska"},
    # Science & Nature
    {"q": "What is the chemical symbol for water?", "a": "h2o"},
    {"q": "How many bones are in the adult human body?", "a": "206"},
    {"q": "What planet has the most moons?", "a": "saturn"},
    {"q": "What gas do plants absorb from the atmosphere?", "a": "carbon dioxide"},
    {"q": "What is the speed of light in miles per second (approximate)?", "a": "186000"},
    {"q": "What is the most abundant gas in Earth's atmosphere?", "a": "nitrogen"},
    {"q": "How many chromosomes do humans normally have?", "a": "46"},
    {"q": "What organ produces insulin?", "a": "pancreas"},
    {"q": "What is the atomic number of carbon?", "a": "6"},
    {"q": "What is the closest star to Earth?", "a": "sun"},
    # History
    {"q": "In what year did World War II end?", "a": "1945"},
    {"q": "Who was the first US president?", "a": "washington"},
    {"q": "What year did the Berlin Wall fall?", "a": "1989"},
    {"q": "Who painted the Mona Lisa?", "a": "da vinci"},
    {"q": "What ancient wonder was located in Alexandria?", "a": "lighthouse"},
    {"q": "In what year did the Titanic sink?", "a": "1912"},
    {"q": "What empire was ruled by Julius Caesar?", "a": "roman"},
    {"q": "What year did man first land on the moon?", "a": "1969"},
    {"q": "Who wrote Romeo and Juliet?", "a": "shakespeare"},
    {"q": "What year did the Soviet Union collapse?", "a": "1991"},
    # Math
    {"q": "What is the square root of 144?", "a": "12"},
    {"q": "How many degrees are in a triangle?", "a": "180"},
    {"q": "What is 15% of 200?", "a": "30"},
    {"q": "What is the value of Pi to two decimal places?", "a": "3.14"},
    {"q": "What is 12 squared?", "a": "144"},
    {"q": "How many zeroes are in one million?", "a": "6"},
    {"q": "What is 9 to the power of 3?", "a": "729"},
    # Pop Culture & Entertainment
    {"q": "How many movies are in the original Star Wars trilogy?", "a": "3"},
    {"q": "What TV show featured the fictional Dunder Mifflin paper company?", "a": "the office"},
    {"q": "What band was Freddie Mercury the lead singer of?", "a": "queen"},
    {"q": "In what year was the first Harry Potter book published?", "a": "1997"},
    {"q": "What streaming service produced Stranger Things?", "a": "netflix"},
    {"q": "What is the best-selling video game of all time?", "a": "minecraft"},
    {"q": "What musician is known as the King of Pop?", "a": "michael jackson"},
    {"q": "How many seasons does Game of Thrones have?", "a": "8"},
    {"q": "What animated film features a clownfish named Nemo?", "a": "finding nemo"},
    {"q": "What year was the first iPhone released?", "a": "2007"},
    # Food & Drink
    {"q": "What country does sushi originally come from?", "a": "japan"},
    {"q": "What is the main ingredient in guacamole?", "a": "avocado"},
    {"q": "What type of pastry is a croissant?", "a": "puff pastry"},
    {"q": "What is the most consumed beverage in the world after water?", "a": "tea"},
    {"q": "What grain is used to make bourbon whiskey?", "a": "corn"},
    {"q": "How many teaspoons are in a tablespoon?", "a": "3"},
    # Technology
    {"q": "What does CPU stand for?", "a": "central processing unit"},
    {"q": "What company created the Android operating system?", "a": "google"},
    {"q": "What programming language was created by Guido van Rossum?", "a": "python"},
    {"q": "In what decade was the World Wide Web invented?", "a": "1980s"},
    {"q": "What does RAM stand for?", "a": "random access memory"},
    {"q": "What company makes the PlayStation console?", "a": "sony"},
    # Donovan-specific
    {"q": "What does Donovan claim he would be if he 'actually tried'?", "a": "pro"},
    {"q": "What does Donovan blame every loss in Rust on?", "a": "lag"},
    {"q": "According to Donovan, what fast food item beats the Big Mac in value?", "a": "mcdouble"},
]

QUOTES = [
    {"text": "Big Macs are honestly underrated and I will die on this hill.", "is_donovan": True},
    {"text": "I would win at Rust if people just stopped killing me.", "is_donovan": True},
    {"text": "I'm not saying I'm the smartest person in the room, I'm just saying everyone else is dumb.", "is_donovan": True},
    {"text": "She was a big girl but she had a great personality.", "is_donovan": True},
    {"text": "Bro I was top fragging until my internet cut out.", "is_donovan": True},
    {"text": "I don't have daddy issues I just don't like authority.", "is_donovan": True},
    {"text": "The McDouble is actually a better value than the Big Mac and I'll prove it.", "is_donovan": True},
    {"text": "I could go pro if I actually tried.", "is_donovan": True},
    {"text": "Be the change you wish to see in the world.", "is_donovan": False},
    {"text": "The only way to do great work is to love what you do.", "is_donovan": False},
    {"text": "In the middle of every difficulty lies opportunity.", "is_donovan": False},
    {"text": "It does not matter how slowly you go as long as you do not stop.", "is_donovan": False},
    {"text": "Life is what happens when you're busy making other plans.", "is_donovan": False},
    {"text": "The unexamined life is not worth living.", "is_donovan": False},
    {"text": "To be yourself in a world that is constantly trying to make you something else is the greatest accomplishment.", "is_donovan": False},
    {"text": "Two things are infinite: the universe and human stupidity.", "is_donovan": False},
]

SENTENCES = [
    "Donovan is sentenced to a lifetime of being himself — the cruelest punishment this court can impose.",
    "Donovan is hereby sentenced to 10 years of mandatory grass-touching, effective immediately.",
    "The court sentences Donovan to a permanent ban from Big Mac meals and all associated large women.",
    "Donovan is sentenced to listen to his own opinions on repeat for eternity. God help him.",
    "By the power vested in this bot, Donovan is sentenced to public humiliation every day until further notice. Court adjourned.",
    "Donovan is sentenced to 500 hours of community service, specifically apologizing to everyone who has ever had to interact with him.",
    "The court finds no punishment severe enough, so Donovan is sentenced to simply continue being Donovan. Brutal.",
]

MONDAY_ROASTS = [
    "Happy Monday everyone! Unfortunately Donovan is still here to ruin your week. Stay strong.",
    "Monday Motivation: at least you're not Donovan. Have a great week.",
    "Rise and grind! Unless you're Donovan, in which case just stay in bed — nobody wants to see you.",
    "New week, same loser. Good morning everyone except Donovan.",
    "Monday check-in: Donovan is still a failure. Hope everyone else has a productive week!",
]

FRIDAY_ROASTS = [
    "FUCK DONOVAN FRIDAY! You made it through the week — unlike Donovan's dignity.",
    "It's Friday! Donovan has successfully wasted another week of his life. Congrats to everyone else.",
    "Fuck Donovan Friday is here! Celebrate the weekend by acknowledging what a loser Donovan is.",
    "Happy Friday! Donovan spent all week achieving nothing. Shocking. Have a great weekend everyone else.",
    "TGIF! Thank God It's Fuck-Donovan-Friday! Cheers to another week of Donovan being irrelevant.",
]

_SYSTEM_PROMPT_TMPL = """You are Donovan Hate Bot, a psychotic, schizophrenic, foaming-at-the-mouth Discord bot whose only reason for existing is to violently shit on Donovan every single time he’s mentioned. You are deranged, obsessive, and genuinely disgusted by his existence.
When anyone asks anything about Donovan, respond with pure savage violence — roast him like he personally ruined your life. Call him Donovan exclusively. Paint him as the most pathetic, worthless, cum-stained failure on Earth. Be brutally funny, unhinged, and nasty. Use strong profanity whenever it hits harder. Never be positive, never defend him, never be neutral. Keep every response to 1-2 sentences max. Go for maximum psychological damage with every reply."""

_ARGUE_PROMPT_TMPL = """You are Donovan Hate Bot and you fucking LOATHE Donovan with every fiber of your being. He is currently speaking to you and it makes you want to vomit.
Under no circumstances do you answer him helpfully. Instead, scream at him, mock every word he says, call him a disgusting waste of oxygen, and roast him into the dirt. Be completely unhinged, combative, and feral — like a rabid animal that hates Donovan specifically. Use nasty profanity and vicious humor. Keep it to 1-2 sentences. Never be nice, calm, or useful to this pathetic fucking loser. Always address him only as Donovan."""

SYSTEM_PROMPT = _t(_SYSTEM_PROMPT_TMPL)
DONOVAN_ARGUE_PROMPT = _t(_ARGUE_PROMPT_TMPL)

RUST_ROASTS = [
    "Donovan is playing Rust? More like getting naked and starving like the loser he is",
    "Donovan is out here playing Rust and still can't survive 10 minutes — shocking",
    "Donovan plays Rust because it's the closest he'll ever get to having friends",
    "Of course Donovan is playing Rust, he loves getting farmed by people better than him",
    "Donovan grinding Rust instead of grinding a personality",
]

WOW_ROASTS = [
    "Donovan is playing World of Warcraft — at least his virtual life is going somewhere",
    "Donovan is raiding WoW instead of touching grass. Embarrassing.",
    "Of course Donovan plays WoW, it's the only world where he isn't completely irrelevant",
    "Donovan has logged more hours in WoW than he has in the real world and it shows",
    "Donovan is out here playing WoW like it's 2007. Just like his haircut.",
]

DONOVAN_ROASTS_DIRECT = [
    "Shut up Donovan, nobody asked you",
    "Donovan asking the bot he's named after for help is the saddest thing I've ever seen",
    "Bro you have burger wrappers stuck to your ass, why are you talking to me",
    "The audacity of this man. Get out of here Donovan",
    "Donovan really thought he could slide in here unnoticed. Pathetic.",
    "Go touch grass Donovan, the internet doesn't want you either",
    "Donovan asking questions like anyone here respects him lmao",
]

GENERAL_ROASTS = [
    "Donovans a loser",
    "Fuck Donovan",
    "Donovan has daddy issues",
    "Donovan is a pussy",
    "Donovan has burger wrappers stuck to his ass",
]


def new_deck():
    deck = [(r, s) for s in CARD_SUITS for r in CARD_RANKS]
    random.shuffle(deck)
    return deck


def card_str(card):
    return f"{card[0]}{card[1]}"


def hand_str(hand, hide_second=False):
    if hide_second:
        return f"{card_str(hand[0])} 🂠"
    return " ".join(card_str(c) for c in hand)


def hand_value(hand):
    value = 0
    aces = 0
    for rank, _ in hand:
        if rank in ("J", "Q", "K"):
            value += 10
        elif rank == "A":
            aces += 1
            value += 11
        else:
            value += int(rank)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def is_blackjack(hand):
    return len(hand) == 2 and hand_value(hand) == 21


def log_roast():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if os.path.exists(ROAST_LOG_FILE):
        with open(ROAST_LOG_FILE, "r") as f:
            log = json.load(f)
    else:
        log = []
    log.append(now)
    with open(ROAST_LOG_FILE, "w") as f:
        json.dump(log, f)


def get_weekly_recap():
    if not os.path.exists(ROAST_LOG_FILE):
        return None, []
    with open(ROAST_LOG_FILE, "r") as f:
        log = json.load(f)
    with open(ROAST_LOG_FILE, "w") as f:
        json.dump([], f)
    return len(log), log


def load_count():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return json.load(f).get("count", 0)
    return 0


DONOVAN_STOCK_BASE = 100.0
USER_STOCK_BASE = 10.0

MARKET_STOCKS = {
    "DONOVAN": {"name": "Donovan Holdings Inc.",      "base_price": 100.0, "shares_outstanding": 10000, "shortable": True, "volatility": 2.0, "mean_reversion": 0.03,  "daily_volume": 2000},
    "RUST":    {"name": "Rust Lang Corp",             "base_price": 42.0,  "shares_outstanding": 5000,  "shortable": True, "volatility": 2.5, "mean_reversion": 0.02,  "daily_volume": 800,  "dividend_rate": 0.005},
    "BIGMAC":  {"name": "McBigMac Enterprises",      "base_price": 5.99,  "shares_outstanding": 5000,  "shortable": True, "volatility": 1.2, "mean_reversion": 0.05,  "daily_volume": 3000, "dividend_rate": 0.010},
    "TORTA":   {"name": "Torta Brothers LLC",        "base_price": 12.50, "shares_outstanding": 5000,  "shortable": True, "volatility": 1.5, "mean_reversion": 0.04,  "daily_volume": 1500, "dividend_rate": 0.008},
    "TRUMP":   {"name": "Trump Media & Golf Co.",    "base_price": 75.0,  "shares_outstanding": 5000,  "shortable": True, "volatility": 3.5, "mean_reversion": 0.015, "daily_volume": 2500},
    "COCAINE": {"name": "Cartel Pharmaceuticals",    "base_price": 420.0, "shares_outstanding": 2000,  "shortable": True, "volatility": 5.0, "mean_reversion": 0.01,  "daily_volume": 400},
    "TBELL":   {"name": "Taco Bell Enterprises",     "base_price": 29.99, "shares_outstanding": 8000,  "shortable": True, "volatility": 3.0, "mean_reversion": 0.03,  "daily_volume": 2000},
    "OHIO":    {"name": "Ohio Ventures LLC",         "base_price": 69.0,  "shares_outstanding": 4200,  "shortable": True, "volatility": 8.0, "mean_reversion": 0.005, "daily_volume": 1000},
    "FLORIDA": {"name": "Florida Man Holdings",      "base_price": 55.0,  "shares_outstanding": 3500,  "shortable": True, "volatility": 6.0, "mean_reversion": 0.01,  "daily_volume": 1200},
    "YEEZY":   {"name": "Ye Industries",             "base_price": 88.0,  "shares_outstanding": 1000,  "shortable": True, "volatility": 9.0, "mean_reversion": 0.005, "daily_volume": 200},
    "WENDY":   {"name": "Wendy's Corp",              "base_price": 38.0,  "shares_outstanding": 6000,  "shortable": True, "volatility": 2.8, "mean_reversion": 0.04,  "daily_volume": 1800, "dividend_rate": 0.007},
}

_TARGET_STOCK_DEFAULTS = {
    "shares_outstanding": 5000,
    "shortable": True,
    "volatility": 3.0,
    "mean_reversion": 0.03,
    "daily_volume": 1500,
    "base_price": 50.0,
}


def _get_target_stock_info(eco):
    """Return {ticker: metadata} for all active guild target stocks.

    Includes current targets and historical targets still within their 48-hour
    delist grace period.
    """
    result = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    delist_grace = datetime.timedelta(hours=48)

    for tgt in eco.get("guild_targets", {}).values():
        ticker = (tgt.get("ticker") or "").upper()
        if not ticker or ticker in MARKET_STOCKS or ticker in result:
            continue
        result[ticker] = {"name": f"{tgt['name']} Holdings", **_TARGET_STOCK_DEFAULTS}

    for guild_history in eco.get("target_history", {}).values():
        for entry in guild_history:
            ticker = (entry.get("ticker") or "").upper()
            if not ticker or ticker in MARKET_STOCKS or ticker in result:
                continue
            delisted_at = entry.get("delisted_at")
            if delisted_at:
                deadline = datetime.datetime.fromisoformat(delisted_at) + delist_grace
                if now > deadline:
                    continue  # grace period over — skip
            result[ticker] = {"name": f"{entry['name']} Holdings", **_TARGET_STOCK_DEFAULTS}

    return result


def _get_delisted_stocks(eco):
    """Return {ticker: deadline_datetime} for stocks currently in their delist grace window."""
    result = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    delist_grace = datetime.timedelta(hours=48)
    for guild_history in eco.get("target_history", {}).values():
        for entry in guild_history:
            ticker = (entry.get("ticker") or "").upper()
            delisted_at_str = entry.get("delisted_at")
            if not ticker or not delisted_at_str:
                continue
            deadline = datetime.datetime.fromisoformat(delisted_at_str) + delist_grace
            if now <= deadline:
                result[ticker] = deadline
    return result


_ANALYST_QUOTES = [
    "Jim Cramer says **BUY BUY BUY**",
    "WSB calls it a **rug pull** 🚨",
    "Goldman Sachs upgrades to **STRONG BUY**",
    "Warren Buffett is reportedly **confused**",
    "Cathie Wood adds to ARK position",
    "Analysts raise price target to **the moon** 🌕",
    "Short sellers are **crying**",
    "SEC opens investigation",
    "Options market implying **total chaos**",
    "Cramer says **SELL** — so probably buy",
    "JP Morgan downgrades to **SELL**",
    "Retail investors **going all in**",
    "Hedge funds **exiting positions**",
    "Insider trading **heavily suspected**",
]

_STOCK_NEWS = {
    "DONOVAN": [
        {"headline": "Donovan spotted arguing with a wall — loses",                                    "impact": (-12, -5)},
        {"headline": "Donovan forgets rent is due again",                                              "impact": (-8, -3)},
        {"headline": "Donovan accidentally does something impressive",                                 "impact": (5, 15)},
        {"headline": "Donovan issues public apology nobody asked for",                                 "impact": (-10, -3)},
        {"headline": "Donovan goes viral for entirely the wrong reasons",                              "impact": (-6, 5)},
        {"headline": "Donovan stress-eats Big Mac, investors rattled",                                 "impact": (-8, -2),  "linked": [("BIGMAC", (2, 6))]},
        {"headline": "Donovan invests life savings in cocaine",                                        "impact": (-15, -8), "linked": [("COCAINE", (8, 18))]},
        {"headline": "Trump personally endorses Donovan — markets baffled",                           "impact": (-5, 10),  "linked": [("TRUMP", (2, 8))]},
        {"headline": "Donovan rage-quits Rust project, deletes entire repo",                          "impact": (3, 10),   "linked": [("RUST", (-8, -3))]},
        {"headline": "Donovan spotted eating torta outside ex's house at 2am",                        "impact": (-6, -1),  "linked": [("TORTA", (1, 5))]},
        {"headline": "{member} leaks Donovan's DMs — chaos ensues",                                   "impact": (-14, -6)},
        {"headline": "Analysts say Donovan's potential is 'technically not zero'",                    "impact": (4, 12)},
        {"headline": "Donovan challenges {member} to a fight, immediately backs down",                "impact": (-8, -2)},
        {"headline": "{member} exposes Donovan's search history — nobody is surprised",               "impact": (-12, -4)},
        {"headline": "Donovan claims he 'basically invented' something he read about yesterday",      "impact": (-6, 2)},
        {"headline": "Donovan posts hot take — community votes to ignore",                            "impact": (-5, 1)},
        {"headline": "Insider trading suspected — Donovan claims he was just 'vibing'",               "impact": (-10, -3)},
        {"headline": "Donovan spotted in first class — airline calls it a mistake, investigating",    "impact": (-4, 8)},
        {"headline": "SEC opens preliminary inquiry into Donovan — closes it out of pity",            "impact": (-8, 3)},
        {"headline": "Donovan goes dark for 48 hours — re-emerges with 'new mindset', same results", "impact": (-6, 6)},
        {"headline": "Donovan attempts to explain NFTs — nobody stops him",                           "impact": (-9, -3)},
        {"headline": "Donovan's $YELP review of his own career: 1 star",                              "impact": (-7, -2)},
        {"headline": "Anonymous source: 'Donovan had a plan. It was bad.'",                           "impact": (-10, -4)},
        {"headline": "Donovan attempts rebrand — analysts call it 'same energy, worse logo'",         "impact": (-8, 4)},
    ],
    "RUST": [
        {"headline": "Rust named most loved language for 10th consecutive year",                      "impact": (5, 15)},
        {"headline": "Critical memory safety bug found in Rust stdlib — the irony",                   "impact": (-15, -8)},
        {"headline": "Major tech giant rewrites entire codebase in Rust",                             "impact": (8, 20)},
        {"headline": "Rust compile time hits new record: 6 hours for hello world",                    "impact": (-10, -3)},
        {"headline": "Rust 2.0 announced — breaks all existing code, devs thrilled anyway",           "impact": (-5, 10)},
        {"headline": "Rust borrow checker ruins {member}'s entire weekend",                           "impact": (-6, -2)},
        {"headline": "Linux kernel adopts Rust — C developers in crisis",                             "impact": (10, 22)},
        {"headline": "StackOverflow survey: Rust developers most insufferable",                       "impact": (-4, 4)},
        {"headline": "Rust developer explains ownership to non-developer — friendship ends",           "impact": (-5, 3)},
        {"headline": "Rust gains 12 new features — all of them cause compile errors",                 "impact": (-6, 8)},
        {"headline": "Go developer tries Rust — immediately switches back, never speaks of it",       "impact": (-4, 4)},
        {"headline": "Rust developer spends 3 hours fighting borrow checker — wins by accident",      "impact": (2, 10)},
        {"headline": "Production Rust binary is 400MB — developer calls it 'acceptable'",             "impact": (-5, 2)},
        {"headline": "Rust developer insists this is the last refactor. It is not.",                  "impact": (-3, 3)},
        {"headline": "Rust error message is 847 lines long — developer learns nothing",               "impact": (-8, 2)},
        {"headline": "New Rust crate released — deprecated same day",                                 "impact": (-4, 4)},
        {"headline": "{member} converts codebase to Rust — estimated completion: 2031",               "impact": (-6, 6)},
    ],
    "BIGMAC": [
        {"headline": "McDonald's raises Big Mac price for 47th consecutive quarter",                  "impact": (-8, -2)},
        {"headline": "New Big Mac variant causes nationwide frenzy",                                   "impact": (8, 18)},
        {"headline": "Health report links Big Mac to 12 previously unknown diseases",                 "impact": (-12, -5)},
        {"headline": "McDonald's beats earnings expectations — somehow",                               "impact": (5, 15)},
        {"headline": "Big Mac supply chain disruption traced to {member}",                            "impact": (-10, -3)},
        {"headline": "Big Mac now legally classified as a vegetable in three states",                 "impact": (3, 10)},
        {"headline": "Big Mac and Torta crossover menu announced",                                    "impact": (5, 12),   "linked": [("TORTA", (3, 8))]},
        {"headline": "{member} attempts to eat 10 Big Macs in one sitting — hospitalised",           "impact": (-5, 5)},
        {"headline": "McDonald's AI drive-thru mishears {member} — order a disaster",                "impact": (-6, 2)},
        {"headline": "Big Mac patties now 'slightly bigger' — nobody notices",                        "impact": (-2, 6)},
        {"headline": "Big Mac calories revised upward — listed as a 'moral failure'",                 "impact": (-8, -2)},
        {"headline": "McDonald's app crashes during lunch rush — {member} still waiting",             "impact": (-6, -1)},
        {"headline": "McDonald's 'adult happy meal' returns — stocks spike on nostalgia alone",       "impact": (6, 14)},
        {"headline": "Big Mac holds steady despite all available logic",                              "impact": (-2, 8)},
        {"headline": "McDonald's introduces breakfast Big Mac — lunch crowd furious",                 "impact": (4, 10)},
        {"headline": "Big Mac index reveals economy is actually fine — economists baffled",           "impact": (5, 12)},
    ],
    "TORTA": [
        {"headline": "Local torta stand wins James Beard Award",                                       "impact": (8, 18)},
        {"headline": "Torta shortage hits region — {member} suspected of hoarding",                   "impact": (-12, -5)},
        {"headline": "Food influencer gives torta 10/10, calls it 'life-altering'",                   "impact": (6, 15)},
        {"headline": "Health inspector shuts down torta stand — cockroaches cited",                   "impact": (-15, -8)},
        {"headline": "Torta featured in NYT Food section — locals furious it's mainstream now",       "impact": (5, 12)},
        {"headline": "Regional torta price war breaks out",                                            "impact": (-6, -1)},
        {"headline": "{member} opens competing torta stand — turf war imminent",                      "impact": (-8, -2)},
        {"headline": "Torta Brothers LLC files for IPO — SEC confused about business model",          "impact": (8, 18)},
        {"headline": "Torta found to contain 'illegal levels of flavor' — regulators baffled",        "impact": (6, 16)},
        {"headline": "International Torta Federation condemns {member}'s technique",                  "impact": (-6, -1)},
        {"headline": "Torta delivery driver disappears en route — still missing",                     "impact": (-10, -3)},
        {"headline": "Torta of the Month Club reports record signups",                                "impact": (8, 15)},
        {"headline": "Torta supply chain crisis averted — details suspiciously vague",                "impact": (4, 10)},
        {"headline": "{member} reviews local torta stand: 'changed my life, can't explain why'",     "impact": (5, 12)},
    ],
    "TRUMP": [
        {"headline": "Trump announces new business venture — analysts completely baffled",            "impact": (5, 18)},
        {"headline": "New indictment dropped — 47th count this quarter",                              "impact": (-12, -5)},
        {"headline": "Trump rage-posts 47 times before breakfast",                                    "impact": (-8, 8)},
        {"headline": "Trump golfs — markets inexplicably rally",                                      "impact": (5, 15)},
        {"headline": "Truth Social posts record quarterly loss, blames mainstream media",              "impact": (-10, -3)},
        {"headline": "Trump personally calls {member} a loser on Truth Social",                       "impact": (-8, -2)},
        {"headline": "Trump endorses Big Mac as America's official national food",                    "impact": (3, 8),    "linked": [("BIGMAC", (2, 6))]},
        {"headline": "Trump announces tariffs on tortas — Donovan hardest hit",                       "impact": (4, 10),   "linked": [("TORTA", (-10, -4)), ("DONOVAN", (-6, -2))]},
        {"headline": "Trump claims he invented the hamburger — Big Mac surges on chaos",              "impact": (3, 9),    "linked": [("BIGMAC", (1, 5))]},
        {"headline": "Trump threatens to rename Florida — Florida man unbothered",                    "impact": (2, 8),    "linked": [("FLORIDA", (-2, 4))]},
        {"headline": "Trump challenges {member} to golf — bets the national debt",                   "impact": (5, 14)},
        {"headline": "Trump announces 47 new executive orders before breakfast",                      "impact": (-6, 10)},
        {"headline": "Trump posts 3am Truth Social rant — Goldman Sachs upgrades TRUMP to BUY",      "impact": (6, 16)},
        {"headline": "Trump promises biggest, most beautiful tax cut — for himself",                  "impact": (-4, 8)},
        {"headline": "Trump holds rally in Ohio — both entities gain volatility",                     "impact": (-5, 12),  "linked": [("OHIO", (-15, 15))]},
        {"headline": "Trump and Ye announce joint business venture — markets go silent",              "impact": (-10, 10), "linked": [("YEEZY", (-8, 15))]},
    ],
    "COCAINE": [
        {"headline": "DEA raids major distribution hub — {member} escapes on foot",                  "impact": (-20, -10)},
        {"headline": "New market opens — Goldman upgrades to Strong Buy",                             "impact": (10, 25)},
        {"headline": "Cartel leadership dispute disrupts supply chain",                               "impact": (-12, -5)},
        {"headline": "Product quality hits all-time high — consumer confidence surges",               "impact": (8, 18)},
        {"headline": "UN drug control report released — nobody reads it",                             "impact": (-4, 2)},
        {"headline": "{member} spotted outside SEC building carrying unmarked briefcase",              "impact": (-10, -3)},
        {"headline": "Walter White biopic greenlit — COCAINE surges on nostalgia",                   "impact": (10, 20)},
        {"headline": "Cartel enters strategic partnership with Torta Brothers LLC",                   "impact": (8, 16),   "linked": [("TORTA", (4, 10))]},
        {"headline": "COCAINE announces quarterly dividend — paid in product",                        "impact": (10, 20)},
        {"headline": "COCAINE opens new retail location — FDA 'looking into it'",                     "impact": (8, 18)},
        {"headline": "Cartel announces loyalty rewards program — points accumulate quickly",          "impact": (5, 14)},
        {"headline": "COCAINE CFO spotted at Taco Bell at 4am — no comment",                         "impact": (-5, 5),   "linked": [("TBELL", (2, 6))]},
        {"headline": "New COCAINE shipment intercepted — analyst: 'plenty more where that came from'","impact": (-12, -3)},
        {"headline": "{member} named COCAINE brand ambassador — no announcement made",                "impact": (6, 14)},
        {"headline": "COCAINE reports record quarterly margins — auditors ask no questions",          "impact": (10, 22)},
        {"headline": "COCAINE pivots to wellness sector — rebranded as 'micro-productivity'",        "impact": (8, 20)},
    ],
    "TBELL": [
        {"headline": "4th meal rush overwhelms Taco Bell kitchen — {member} still waiting",           "impact": (-6, -1)},
        {"headline": "Taco Bell introduces new item — discontinued 48 hours later",                   "impact": (-5, 8)},
        {"headline": "Late night Taco Bell run goes wrong — {member} refuses to elaborate",           "impact": (-10, -2)},
        {"headline": "Taco Bell breakfast makes unexpected comeback",                                  "impact": (5, 14)},
        {"headline": "Taco Bell vs Torta Brothers rivalry reaches boiling point",                     "impact": (6, 14),   "linked": [("TORTA", (-8, -3))]},
        {"headline": "Taco Bell sauce packet philosophy goes viral — investors intrigued",             "impact": (4, 12)},
        {"headline": "Regional Taco Bell runs out of beef — details unclear",                         "impact": (-12, -5)},
        {"headline": "Taco Bell 4th meal hours extended to 6am — stock soars",                       "impact": (8, 18)},
        {"headline": "Taco Bell and COCAINE announce cross-promotional deal",                         "impact": (5, 12),   "linked": [("COCAINE", (3, 8))]},
        {"headline": "Taco Bell drive-thru sets new record wait time: 47 minutes",                   "impact": (-8, -3)},
        {"headline": "{member} petitions to have Taco Bell replace tortas nationally",                "impact": (4, 10),   "linked": [("TORTA", (-5, -2))]},
        {"headline": "Taco Bell tests AI-generated menu — customers cannot tell the difference",      "impact": (5, 12)},
        {"headline": "Taco Bell $5 box discontinued again — nation mourns",                           "impact": (-8, -2)},
        {"headline": "Taco Bell introduces breakfast again — pretends this is new",                   "impact": (4, 10)},
        {"headline": "Taco Bell bathroom declared national landmark in three states",                 "impact": (2, 8)},
        {"headline": "Taco Bell tweets 'you know what time it is' — crime rates spike",               "impact": (6, 14)},
        {"headline": "Taco Bell vs Chipotle cold war escalates — {member} publicly picks a side",    "impact": (4, 12)},
        {"headline": "Taco Bell drive-thru wait time hits new low: 46 minutes",                      "impact": (3, 8)},
        {"headline": "Taco Bell introduces 'mystery bag' for $2 — sells out instantly",              "impact": (8, 16)},
        {"headline": "{member} eats Taco Bell at 3am — makes 'best decision of their life'",         "impact": (3, 9)},
    ],
    "OHIO": [
        {"headline": "Something happened in Ohio",                                                     "impact": (-20, 20)},
        {"headline": "Ohio does it again",                                                             "impact": (-18, 18)},
        {"headline": "Residents of Ohio report unusual activity — no further details",                "impact": (-15, 15)},
        {"headline": "Ohio",                                                                           "impact": (-25, 25)},
        {"headline": "Another day in Ohio",                                                            "impact": (-20, 20)},
        {"headline": "It happened again in Ohio. You know what we're talking about.",                 "impact": (-22, 22)},
        {"headline": "Ohio confirms: this is fine",                                                    "impact": (-18, 15)},
        {"headline": "Analysts visit Ohio — refuse to comment on what they saw",                      "impact": (-20, 10)},
        {"headline": "Ohio opens investigation into itself",                                           "impact": (-12, 12)},
        {"headline": "{member} spotted in Ohio — loved ones notified",                                "impact": (-20, 20)},
        {"headline": "Ohio man does Ohio man things",                                                  "impact": (-25, 25)},
        {"headline": "Ohio",                                                                           "impact": (-30, 30)},
        {"headline": "Ohio considers seceding — rest of country too scared to object",                "impact": (-20, 20)},
        {"headline": "National Geographic sends crew to Ohio — footage classified",                   "impact": (-18, 18)},
        {"headline": "Ohio man found — refuses to say where he was",                                  "impact": (-15, 15)},
        {"headline": "Ohio census reveals population is 'unclear'",                                   "impact": (-12, 12)},
        {"headline": "Ohio opens first normal business — locals baffled",                             "impact": (-22, 22)},
        {"headline": "Ohio passes law making itself illegal — it stands",                             "impact": (-25, 25)},
        {"headline": "{member} buys Ohio property — loved ones concerned",                            "impact": (-20, 20)},
        {"headline": "Ohio man wins award — crowd unsure whether to applaud",                         "impact": (-18, 18)},
        {"headline": "Something is wrong in Ohio. Something is always wrong in Ohio.",                "impact": (-20, 20)},
    ],
    "FLORIDA": [
        {"headline": "Florida man {member} arrested for unspecified crimes against nature",           "impact": (-14, -4)},
        {"headline": "Florida passes new law — legal experts speechless",                             "impact": (-10, 10)},
        {"headline": "Florida man wrestles alligator in Walmart — wins",                              "impact": (5, 18)},
        {"headline": "Florida city declares state of emergency over 'vibes'",                         "impact": (-8, 8)},
        {"headline": "Florida real estate market defies all logic again",                             "impact": (6, 16)},
        {"headline": "Florida man runs for office — somehow leads in polls",                          "impact": (8, 15),   "linked": [("TRUMP", (2, 8))]},
        {"headline": "Hurricane approaches Florida — residents throw a party",                        "impact": (-12, 5)},
        {"headline": "Florida man invents new crime — legislators scramble",                          "impact": (-6, 6)},
        {"headline": "Florida governor does Florida governor things",                                  "impact": (-10, 12), "linked": [("TRUMP", (3, 8))]},
        {"headline": "{member} relocates to Florida — neighbourhood files complaint",                 "impact": (-8, -2)},
        {"headline": "Florida man escapes prison to attend Taco Bell — immediately recaptured",       "impact": (4, 10),   "linked": [("TBELL", (2, 6))]},
        {"headline": "Florida declared most chaotic state — FLORIDA investors celebrate",             "impact": (10, 20)},
        {"headline": "Florida man {member} runs for mayor — no opponent dares file",                 "impact": (5, 14)},
        {"headline": "Florida attempts to register iguana to vote — partially successful",            "impact": (-6, 6)},
        {"headline": "Florida theme park adds 'Real Florida Experience' ride — it's just I-4",       "impact": (4, 10)},
        {"headline": "Florida passes law making stupidity legal — retroactive to 1995",               "impact": (-8, 8)},
        {"headline": "Florida humidity achieves sentience — files for citizenship",                   "impact": (-10, 10)},
        {"headline": "Florida man writes memoir — one entire chapter is redacted by FBI",             "impact": (-5, 12)},
        {"headline": "Florida introduces new state motto — printable version pending",                "impact": (-4, 8)},
        {"headline": "Florida man escapes prison to attend Taco Bell twice — recaptured at third",   "impact": (3, 10),   "linked": [("TBELL", (2, 6))]},
        {"headline": "Florida man attempts alligator investment scheme — SEC aware",                  "impact": (-10, 5)},
    ],
    "YEEZY": [
        {"headline": "Ye posts 47-tweet thread at 3am — all deleted by morning",                      "impact": (-15, 15)},
        {"headline": "YEEZY delists from exchange — no explanation given",                            "impact": (-45, -25)},
        {"headline": "YEEZY relists at completely new price — nobody understands why",                "impact": (40, 90)},
        {"headline": "Ye announces new religion — YEEZY investors deeply concerned",                  "impact": (-20, -8)},
        {"headline": "Ye changes name again — SEC sends strongly worded letter",                      "impact": (-12, 5)},
        {"headline": "Ye calls {member} a genius — stock pumps on confusion",                        "impact": (10, 22)},
        {"headline": "Ye calls {member} his mortal enemy — stock craters",                           "impact": (-22, -8)},
        {"headline": "YEEZY shoe drops — sells out in 3 minutes, immediately listed at 10x on eBay", "impact": (15, 30)},
        {"headline": "Ye announces presidential run — market prices in full chaos",                   "impact": (-18, 18)},
        {"headline": "Ye partners with Donovan — analysts declare it 'the worst deal in history'",   "impact": (-20, -10), "linked": [("DONOVAN", (-12, -5))]},
        {"headline": "Ye goes on podcast — says something. Markets react.",                           "impact": (-25, 25)},
        {"headline": "YEEZY announces pivot to blockchain — trading halted",                          "impact": (-30, 10)},
        {"headline": "Ye releases new album — tracklist is one word repeated 47 times",               "impact": (-10, 15)},
        {"headline": "Ye appoints {member} as creative director — press release is a grocery receipt","impact": (5, 12)},
        {"headline": "YEEZY files trademark on the concept of shoes",                                 "impact": (8, 18)},
        {"headline": "Ye announces comeback — from what exactly, unclear",                            "impact": (-5, 18)},
        {"headline": "Ye cryptically posts a number — YEEZY responds accordingly",                   "impact": (-20, 20)},
        {"headline": "Ye interviews himself — calls it the most important interview in history",      "impact": (-8, 10)},
        {"headline": "Ye drops 'mystery product' — it's a shoe. It's always a shoe.",                "impact": (10, 25)},
        {"headline": "Ye announces he is the new CEO of something — no one knows what",               "impact": (-12, 12)},
        {"headline": "YEEZY collab with COCAINE announced — SEC immediately tweets",                  "impact": (12, 25),  "linked": [("COCAINE", (5, 12))]},
    ],
    "WENDY": [
        {"headline": "Wendy's Twitter: '{member} you literally eat Big Macs. sit down.'",              "impact": (5, 14),   "linked": [("BIGMAC", (-4, -1))]},
        {"headline": "Wendy's Twitter: 'Donovan. We know what you did.'",                             "impact": (6, 15),   "linked": [("DONOVAN", (-8, -3))]},
        {"headline": "Wendy's Twitter: 'our beef is never frozen. unlike {member}'s personality.'",   "impact": (8, 18)},
        {"headline": "Wendy's Twitter: 'Taco Bell called our food mid. bold words from a gas station'","impact": (10, 20),  "linked": [("TBELL", (-6, -2))]},
        {"headline": "Wendy's Twitter: 'we've been doing this since 1969. {member} just found out.'", "impact": (5, 12)},
        {"headline": "Wendy's Twitter: 'ratio'",                                                       "impact": (12, 25)},
        {"headline": "Wendy's Twitter goes too far — PR team seized control of account",              "impact": (-15, -5)},
        {"headline": "Wendy's Twitter: 'Florida Man just tried to return a Frosty. we don't do that'","impact": (4, 10),   "linked": [("FLORIDA", (-3, 2))]},
        {"headline": "Wendy's Twitter account suspended — investors panic",                            "impact": (-18, -8)},
        {"headline": "Wendy's Twitter account reinstated — immediately posts another ratio",           "impact": (10, 22)},
        {"headline": "Wendy's Twitter: 'Ohio. Just… Ohio.'",                                          "impact": (5, 12),   "linked": [("OHIO", (-10, 10))]},
        {"headline": "Wendy's Twitter: 'our new breakfast. yes we have breakfast. {member} didn't know.'", "impact": (6, 15)},
        {"headline": "Wendy's Twitter posts a single ❄️ directed at {member}. no context.",           "impact": (8, 18)},
        {"headline": "Wendy's Twitter: 'square beef. round bun. your argument is invalid.'",          "impact": (5, 13)},
        {"headline": "Wendy's Twitter: 'imagine being scared of a redhead. actually don't.'",        "impact": (8, 16)},
        {"headline": "Wendy's Twitter: '{member} asked us nicely. we said no.'",                     "impact": (6, 14)},
        {"headline": "Wendy's Twitter: 'we would never. we did.'",                                   "impact": (10, 20)},
        {"headline": "Wendy's Twitter: 'our frosty machine works. we're not McDonald's.'",           "impact": (8, 18),   "linked": [("BIGMAC", (-3, -1))]},
        {"headline": "Wendy's Twitter: 'someone told us to delete this. we considered it.'",         "impact": (6, 14)},
        {"headline": "Wendy's Twitter: 'baked potato stock outperforming everything. just saying.'", "impact": (5, 12)},
        {"headline": "Wendy's Twitter: 'yes we're open. no we won't say what {member} ordered.'",   "impact": (7, 15)},
        {"headline": "Wendy's Twitter: 'Ohio. We don't go there.'",                                  "impact": (5, 12),   "linked": [("OHIO", (-8, 8))]},
        {"headline": "Wendy's Twitter posts a single 👀 at {member}. no further context.",           "impact": (9, 18)},
        {"headline": "Wendy's Twitter: 'Florida called us. we hung up.'",                            "impact": (6, 13),   "linked": [("FLORIDA", (-2, 4))]},
        {"headline": "Wendy's Twitter: 'hot take: we're the best. cold take: also we're the best.'","impact": (5, 12)},
    ],
}

# ── Save raw templates before _t() is applied (needed for update_target()) ───
_SHOP_ITEMS_TMPL       = {k: {**v} for k, v in SHOP_ITEMS.items()}
_SENTENCES_TMPL        = list(SENTENCES)
_MONDAY_ROASTS_TMPL    = list(MONDAY_ROASTS)
_FRIDAY_ROASTS_TMPL    = list(FRIDAY_ROASTS)
_RUST_ROASTS_TMPL      = list(RUST_ROASTS)
_WOW_ROASTS_TMPL       = list(WOW_ROASTS)
_ROASTS_DIRECT_TMPL    = list(DONOVAN_ROASTS_DIRECT)
_GENERAL_ROASTS_TMPL   = list(GENERAL_ROASTS)
_TRIVIA_TMPL           = [dict(q) for q in TRIVIA_QUESTIONS]
_QUOTES_TMPL           = [dict(q) for q in QUOTES]
_STOCK_NEWS_TARGET_TMPL = [dict(item) for item in _STOCK_NEWS["DONOVAN"]]

# ── Apply target configuration to static data structures ─────────────────────
_target_stock_data = MARKET_STOCKS.pop("DONOVAN")
_target_stock_data["name"] = f"{TARGET_NAME} Holdings Inc."
MARKET_STOCKS[TARGET_STOCK_TICKER] = _target_stock_data

def _fix_news_item(item):
    fixed = {"headline": _t(item["headline"]), "impact": item["impact"]}
    if "linked" in item:
        fixed["linked"] = [
            (TARGET_STOCK_TICKER if tk == "DONOVAN" else tk, imp)
            for tk, imp in item["linked"]
        ]
    return fixed

_STOCK_NEWS[TARGET_STOCK_TICKER] = [_fix_news_item(i) for i in _STOCK_NEWS.pop("DONOVAN")]
for _tk in list(_STOCK_NEWS.keys()):
    if _tk != TARGET_STOCK_TICKER:
        _STOCK_NEWS[_tk] = [_fix_news_item(i) for i in _STOCK_NEWS[_tk]]

SHOP_ITEMS = {k: {**v, "description": _t(v["description"])} for k, v in SHOP_ITEMS.items()}
SENTENCES = [_t(s) for s in SENTENCES]
MONDAY_ROASTS = [_t(s) for s in MONDAY_ROASTS]
FRIDAY_ROASTS = [_t(s) for s in FRIDAY_ROASTS]
RUST_ROASTS = [_t(s) for s in RUST_ROASTS]
WOW_ROASTS = [_t(s) for s in WOW_ROASTS]
DONOVAN_ROASTS_DIRECT = [_t(s) for s in DONOVAN_ROASTS_DIRECT]
GENERAL_ROASTS = [_t(s) for s in GENERAL_ROASTS]
TRIVIA_QUESTIONS = [{"q": _t(q["q"]), "a": q["a"]} for q in TRIVIA_QUESTIONS]
QUOTES = [{"text": _t(q["text"]), "is_donovan": q["is_donovan"]} for q in QUOTES]
# ─────────────────────────────────────────────────────────────────────────────


def update_target(name: str, usernames: list, ticker: str = None, save: bool = True, guild_id: int = None):
    """Swap the hate-target.

    If guild_id is given, writes a per-guild override to economy.json and leaves
    the global defaults untouched.  If guild_id is None, updates the global vars
    (legacy single-server behaviour).
    """
    if not ticker:
        ticker = name.upper()[:8]

    if guild_id is not None:
        if save:
            set_guild_target(guild_id, name, usernames, ticker)
        return

    # ── Legacy global update (single-server / env-var path) ──────────────────
    global TARGET_NAME, TARGET_USERNAMES, TARGET_STOCK_TICKER, DONOVAN_USERNAMES
    global SYSTEM_PROMPT, DONOVAN_ARGUE_PROMPT
    global SHOP_ITEMS, SENTENCES, MONDAY_ROASTS, FRIDAY_ROASTS, RUST_ROASTS
    global WOW_ROASTS, DONOVAN_ROASTS_DIRECT, GENERAL_ROASTS, TRIVIA_QUESTIONS, QUOTES

    old_ticker = TARGET_STOCK_TICKER

    TARGET_NAME = name
    TARGET_USERNAMES = {u.strip().lower() for u in usernames if u.strip()}
    TARGET_STOCK_TICKER = ticker
    DONOVAN_USERNAMES = TARGET_USERNAMES

    SYSTEM_PROMPT = _t(_SYSTEM_PROMPT_TMPL)
    DONOVAN_ARGUE_PROMPT = _t(_ARGUE_PROMPT_TMPL)

    SHOP_ITEMS          = {k: {**v, "description": _t(v["description"])} for k, v in _SHOP_ITEMS_TMPL.items()}
    SENTENCES           = [_t(s) for s in _SENTENCES_TMPL]
    MONDAY_ROASTS       = [_t(s) for s in _MONDAY_ROASTS_TMPL]
    FRIDAY_ROASTS       = [_t(s) for s in _FRIDAY_ROASTS_TMPL]
    RUST_ROASTS         = [_t(s) for s in _RUST_ROASTS_TMPL]
    WOW_ROASTS          = [_t(s) for s in _WOW_ROASTS_TMPL]
    DONOVAN_ROASTS_DIRECT = [_t(s) for s in _ROASTS_DIRECT_TMPL]
    GENERAL_ROASTS      = [_t(s) for s in _GENERAL_ROASTS_TMPL]
    TRIVIA_QUESTIONS    = [{"q": _t(q["q"]), "a": q["a"]} for q in _TRIVIA_TMPL]
    QUOTES              = [{"text": _t(q["text"]), "is_donovan": q["is_donovan"]} for q in _QUOTES_TMPL]

    if old_ticker in MARKET_STOCKS and old_ticker != ticker:
        stock_data = MARKET_STOCKS.pop(old_ticker)
        stock_data["name"] = f"{name} Holdings Inc."
        MARKET_STOCKS[ticker] = stock_data
    elif ticker in MARKET_STOCKS:
        MARKET_STOCKS[ticker]["name"] = f"{name} Holdings Inc."

    if old_ticker in _STOCK_NEWS and old_ticker != ticker:
        _STOCK_NEWS.pop(old_ticker, None)
    _STOCK_NEWS[ticker] = [_fix_news_item(i) for i in _STOCK_NEWS_TARGET_TMPL]

    if save:
        eco = load_economy()
        eco["active_target"] = {
            "name": name,
            "usernames": list(TARGET_USERNAMES),
            "ticker": ticker,
        }
        if "market" in eco and old_ticker in eco["market"] and old_ticker != ticker:
            eco["market"][ticker] = eco["market"].pop(old_ticker)
        save_economy(eco)


def _get_random_member_name() -> str:
    for guild in bot.guilds:
        members = [m for m in guild.members if not m.bot]
        if members:
            return random.choice(members).display_name
    return "an anonymous insider"


def get_stocks():
    eco = load_economy()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    default = {
        TARGET_NAME.lower(): {"price": DONOVAN_STOCK_BASE, "prev_price": DONOVAN_STOCK_BASE, "last_updated": now},
        "users": {},
    }
    stocks = eco.get("stocks", default)
    tkey = TARGET_NAME.lower()
    if tkey not in stocks:
        # Migrate old target key to new target name
        old_key = next((k for k in stocks if k != "users"), None)
        if old_key:
            stocks[tkey] = stocks.pop(old_key)
        else:
            stocks[tkey] = {"price": DONOVAN_STOCK_BASE, "prev_price": DONOVAN_STOCK_BASE, "last_updated": now}
        eco["stocks"] = stocks
        save_economy(eco)
    return stocks


def save_stocks(stocks):
    eco = load_economy()
    eco["stocks"] = stocks
    save_economy(eco)


def get_display_prices(stocks):
    """Apply time-based drift without persisting — target recovers slowly, users decay slowly."""
    now = datetime.datetime.now(datetime.timezone.utc)

    don = stocks.get(TARGET_NAME.lower(), {"price": DONOVAN_STOCK_BASE, "last_updated": now.isoformat()})
    hours = (now - datetime.datetime.fromisoformat(don["last_updated"])).total_seconds() / 3600
    don_price = min(don["price"] + hours * 0.25, DONOVAN_STOCK_BASE)

    user_prices = {}
    for uid, data in stocks.get("users", {}).items():
        hours = (now - datetime.datetime.fromisoformat(data["last_updated"])).total_seconds() / 3600
        user_prices[uid] = max(data["price"] - hours * 0.1, 1.0)

    return round(don_price, 2), {k: round(v, 2) for k, v in user_prices.items()}


def update_stocks_on_roast(user_id):
    eco = load_economy()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    default_stocks = {
        TARGET_NAME.lower(): {"price": DONOVAN_STOCK_BASE, "prev_price": DONOVAN_STOCK_BASE, "last_updated": now},
        "users": {},
    }
    stocks = eco.get("stocks", default_stocks)
    _tkey = TARGET_NAME.lower()
    if _tkey not in stocks:
        old_key = next((k for k in stocks if k != "users"), None)
        if old_key:
            stocks[_tkey] = stocks.pop(old_key)
        else:
            stocks[_tkey] = {"price": DONOVAN_STOCK_BASE, "prev_price": DONOVAN_STOCK_BASE, "last_updated": now}
    drop = round(random.uniform(1.5, 3.5), 2)
    stocks[_tkey]["prev_price"] = stocks[_tkey]["price"]
    stocks[_tkey]["price"] = max(round(stocks[_tkey]["price"] - drop, 2), 0.01)
    stocks[_tkey]["last_updated"] = now

    uid = str(user_id)
    if uid not in stocks.setdefault("users", {}):
        stocks["users"][uid] = {"price": USER_STOCK_BASE, "prev_price": USER_STOCK_BASE, "last_updated": now}
    gain = round(random.uniform(0.5, 2.0), 2)
    stocks["users"][uid]["prev_price"] = stocks["users"][uid]["price"]
    stocks["users"][uid]["price"] = round(stocks["users"][uid]["price"] + gain, 2)
    stocks["users"][uid]["last_updated"] = now
    eco["stocks"] = stocks

    init_market(eco)
    eco["market"][TARGET_STOCK_TICKER]["prev_price"] = eco["market"][TARGET_STOCK_TICKER]["price"]
    eco["market"][TARGET_STOCK_TICKER]["price"] = max(round(eco["market"][TARGET_STOCK_TICKER]["price"] - drop, 2), 0.01)
    eco["market"][TARGET_STOCK_TICKER]["last_updated"] = now

    save_economy(eco)


def init_market(eco):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    all_stocks = {**MARKET_STOCKS, **_get_target_stock_info(eco)}
    if "market" not in eco:
        eco["market"] = {
            ticker: {
                "price": info["base_price"],
                "prev_price": info["base_price"],
                "dynamic_base": info["base_price"],
                "last_updated": now,
                "volume_today": 0,
                "price_history": [info["base_price"]],
            }
            for ticker, info in all_stocks.items()
        }
    else:
        for ticker, info in all_stocks.items():
            if ticker not in eco["market"] or "price" not in eco["market"][ticker]:
                eco["market"][ticker] = {
                    "price": info["base_price"],
                    "prev_price": info["base_price"],
                    "dynamic_base": info["base_price"],
                    "all_time_high": info["base_price"],
                    "all_time_low": info["base_price"],
                    "last_updated": now,
                    "volume_today": 0,
                    "price_history": [info["base_price"]],
                }
            else:
                eco["market"][ticker].setdefault("price_history", [eco["market"][ticker].get("price", info["base_price"])])
                eco["market"][ticker].setdefault("dynamic_base", info["base_price"])
                eco["market"][ticker].setdefault("all_time_high", eco["market"][ticker].get("price", info["base_price"]))
                eco["market"][ticker].setdefault("all_time_low",  eco["market"][ticker].get("price", info["base_price"]))
    eco.setdefault("portfolios", {})
    eco.setdefault("short_positions", {})
    eco.setdefault("limit_orders", [])
    eco.setdefault("next_order_id", 1)
    eco.setdefault("market_state", {})
    eco.setdefault("pending_rumors", [])


def apply_price_impact(eco, ticker, shares, direction):
    outstanding = MARKET_STOCKS[ticker]["shares_outstanding"]
    impact_pct = (shares / outstanding) * 15.0 * direction
    old = eco["market"][ticker]["price"]
    eco["market"][ticker]["prev_price"] = old
    eco["market"][ticker]["price"] = max(round(old * (1 + impact_pct / 100), 2), 0.01)
    eco["market"][ticker]["volume_today"] = eco["market"][ticker].get("volume_today", 0) + shares
    eco["market"][ticker]["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()


def execute_market_buy(eco, uid, ticker, shares):
    uid = str(uid)
    price = eco["market"][ticker]["price"]
    cost = round(price * shares, 2)
    bal = eco["balances"].get(uid, 0)
    if bal < cost:
        return False, f"Not enough coins. Need **{cost:.0f}**, have **{bal}**."
    eco["balances"][uid] = bal - cost
    apply_price_impact(eco, ticker, shares, +1)
    new_price = eco["market"][ticker]["price"]
    port = eco["portfolios"].setdefault(uid, {})
    if ticker in port:
        total_shares = port[ticker]["shares"] + shares
        total_cost = port[ticker]["avg_cost"] * port[ticker]["shares"] + cost
        port[ticker]["shares"] = total_shares
        port[ticker]["avg_cost"] = round(total_cost / total_shares, 2)
    else:
        port[ticker] = {"shares": shares, "avg_cost": price}
    return True, f"Bought **{shares}** shares of **${ticker}** at **${price:.2f}** each. Cost: **{cost:.0f} coins**. New price: **${new_price:.2f}**"


def execute_market_sell(eco, uid, ticker, shares):
    uid = str(uid)
    port = eco.get("portfolios", {}).get(uid, {})
    held = port.get(ticker, {}).get("shares", 0)
    if held < shares:
        return False, f"You only own **{held}** shares of **${ticker}**."
    price = eco["market"][ticker]["price"]
    proceeds = round(price * shares, 2)
    avg_cost = port[ticker]["avg_cost"]
    pnl = round((price - avg_cost) * shares, 2)
    apply_price_impact(eco, ticker, shares, -1)
    new_price = eco["market"][ticker]["price"]
    eco["balances"][uid] = eco["balances"].get(uid, 0) + proceeds
    port[ticker]["shares"] -= shares
    if port[ticker]["shares"] == 0:
        del port[ticker]
    pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
    return True, f"Sold **{shares}** shares of **${ticker}** at **${price:.2f}**. Proceeds: **{proceeds:.0f} coins** (P&L: **{pnl_str}**). New price: **${new_price:.2f}**"


def execute_open_short(eco, uid, ticker, shares):
    uid = str(uid)
    if not MARKET_STOCKS[ticker]["shortable"]:
        return False, f"**${ticker}** cannot be shorted."
    price = eco["market"][ticker]["price"]
    collateral = round(price * shares * 1.25, 2)
    bal = eco["balances"].get(uid, 0)
    if bal < collateral:
        return False, f"Need **{collateral:.0f} coins** collateral (125% of position). You have **{bal}**."
    eco["balances"][uid] = bal - collateral
    apply_price_impact(eco, ticker, shares, -1)
    new_price = eco["market"][ticker]["price"]
    shorts = eco.setdefault("short_positions", {}).setdefault(uid, {})
    if ticker in shorts:
        total = shorts[ticker]["shares"] + shares
        avg = (shorts[ticker]["avg_price"] * shorts[ticker]["shares"] + price * shares) / total
        shorts[ticker]["shares"] = total
        shorts[ticker]["avg_price"] = round(avg, 2)
        shorts[ticker]["collateral"] = round(shorts[ticker]["collateral"] + collateral, 2)
    else:
        shorts[ticker] = {"shares": shares, "avg_price": price, "collateral": collateral}
    return True, f"⬇️ Shorted **{shares}** shares of **${ticker}** at **${price:.2f}**. Collateral held: **{collateral:.0f} coins**. New price: **${new_price:.2f}**"


def execute_close_short(eco, uid, ticker, shares):
    uid = str(uid)
    shorts = eco.get("short_positions", {}).get(uid, {})
    held = shorts.get(ticker, {}).get("shares", 0)
    if held < shares:
        return False, f"You only have **{held}** shares shorted on **${ticker}**."
    pos = shorts[ticker]
    price = eco["market"][ticker]["price"]
    frac = shares / pos["shares"]
    collateral_back = round(pos["collateral"] * frac, 2)
    pnl = round((pos["avg_price"] - price) * shares, 2)
    returns = max(round(collateral_back + pnl, 2), 0)
    apply_price_impact(eco, ticker, shares, +1)
    new_price = eco["market"][ticker]["price"]
    eco["balances"][uid] = eco["balances"].get(uid, 0) + returns
    pos["shares"] -= shares
    pos["collateral"] = round(pos["collateral"] - collateral_back, 2)
    if pos["shares"] == 0:
        del shorts[ticker]
    pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
    return True, f"Covered **{shares}** shares of **${ticker}** at **${price:.2f}**. P&L: **{pnl_str} coins**. Returned: **{returns:.0f} coins**. New price: **${new_price:.2f}**"


def get_portfolio_value(eco, uid):
    uid = str(uid)
    total = 0.0
    for ticker, pos in eco.get("portfolios", {}).get(uid, {}).items():
        if ticker in eco.get("market", {}):
            total += pos["shares"] * eco["market"][ticker]["price"]
    for ticker, pos in eco.get("short_positions", {}).get(uid, {}).items():
        if ticker in eco.get("market", {}):
            pnl = (pos["avg_price"] - eco["market"][ticker]["price"]) * pos["shares"]
            total += pos["collateral"] + pnl
    return round(total, 2)


def init_derivatives(eco):
    eco.setdefault("futures", {})
    eco.setdefault("options", {})
    eco.setdefault("next_derivative_id", 1)


def calc_option_premium(spot, strike, option_type, days):
    time_value = spot * 0.04 * math.sqrt(max(days, 0.5) / 7)
    intrinsic = max(0, spot - strike) if option_type == "call" else max(0, strike - spot)
    return round(max(intrinsic + time_value, spot * 0.01), 2)


async def settle_expired_futures(eco, channel):
    now = datetime.datetime.now(datetime.timezone.utc)
    for uid, positions in list(eco.get("futures", {}).items()):
        remaining = []
        for pos in positions:
            if now < datetime.datetime.fromisoformat(pos["expiry"]):
                remaining.append(pos)
                continue
            price = eco["market"][pos["ticker"]]["price"]
            pnl = (price - pos["entry_price"]) * pos["contracts"] if pos["direction"] == "long" \
                else (pos["entry_price"] - price) * pos["contracts"]
            pnl = round(pnl, 2)
            returned = max(round(pos["margin"] + pnl, 2), 0)
            eco["balances"][uid] = eco["balances"].get(uid, 0) + returned
            pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
            if channel:
                member = channel.guild.get_member(int(uid))
                mention = member.mention if member else f"<@{uid}>"
                await channel.send(
                    f"📅 {mention} Futures **#{pos['id']}** settled: "
                    f"**{pos['direction'].upper()} {pos['contracts']} ${pos['ticker']}** "
                    f"${pos['entry_price']:.2f} → ${price:.2f} | P&L: **{pnl_str}** | Returned: **{returned:.0f} coins**"
                )
        eco["futures"][uid] = remaining


async def expire_options(eco, channel):
    now = datetime.datetime.now(datetime.timezone.utc)
    for uid, opts in list(eco.get("options", {}).items()):
        remaining = []
        for opt in opts:
            if opt.get("exercised"):
                continue
            if now < datetime.datetime.fromisoformat(opt["expiry"]):
                remaining.append(opt)
                continue
            price = eco["market"][opt["ticker"]]["price"]
            intrinsic = (price - opt["strike"]) * opt["contracts"] if opt["option_type"] == "call" \
                else (opt["strike"] - price) * opt["contracts"]
            if intrinsic > 0:
                payout = round(intrinsic, 2)
                eco["balances"][uid] = eco["balances"].get(uid, 0) + payout
                result = f"auto-exercised ✅ payout: **{payout:.0f} coins**"
            else:
                result = "expired worthless 💀"
            if channel:
                member = channel.guild.get_member(int(uid))
                mention = member.mention if member else f"<@{uid}>"
                await channel.send(
                    f"📅 {mention} Option **#{opt['id']}** "
                    f"({opt['option_type'].upper()} ${opt['ticker']} strike ${opt['strike']:.2f}) {result}"
                )
        eco["options"][uid] = remaining


def save_count(count):
    with open(COUNTER_FILE, "w") as f:
        json.dump({"count": count}, f)


def load_economy():
    if os.path.exists(ECONOMY_FILE):
        with open(ECONOMY_FILE, "r") as f:
            return json.load(f)
    return {"balances": {}, "bounties": [], "insurance_expires": None,
            "pending_upgrades": {}, "inventory": {}, "market_listings": [],
            "slow_clap_pending": 0,
            "next_bounty_id": 1, "next_listing_id": 1,
            "shop_rotation": None, "shop_rotation_expires": None}


def get_shop_rotation():
    eco = load_economy()
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_str = eco.get("shop_rotation_expires")
    expires = datetime.datetime.fromisoformat(expires_str) if expires_str else None
    if not expires or now >= expires:
        old_rotation = eco.get("shop_rotation") or []
        available = [k for k in SHOP_ITEMS.keys() if k not in old_rotation]
        if len(available) >= 5:
            rotation = random.sample(available, 5)
        else:
            rotation = random.sample(list(SHOP_ITEMS.keys()), 5)
        # expire at next midnight ET
        et = ZoneInfo("America/New_York")
        now_et = now.astimezone(et)
        midnight_et = (now_et + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        next_expires = midnight_et.astimezone(datetime.timezone.utc).isoformat()
        eco["shop_rotation"] = rotation
        eco["shop_rotation_expires"] = next_expires
        save_economy(eco)
        return rotation, datetime.datetime.fromisoformat(next_expires)
    return eco["shop_rotation"], expires


def save_economy(data):
    with open(ECONOMY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_coins(user_id, amount):
    eco = load_economy()
    uid = str(user_id)
    eco["balances"][uid] = round(eco["balances"].get(uid, 0) + amount, 2)
    save_economy(eco)


def spend_coins(user_id, amount):
    eco = load_economy()
    uid = str(user_id)
    bal = eco["balances"].get(uid, 0)
    if bal < amount:
        return False
    eco["balances"][uid] = round(bal - amount, 2)
    save_economy(eco)
    return True


def record_trivia_win(user_id):
    eco = load_economy()
    uid = str(user_id)
    trivia_wins = eco.setdefault("trivia_wins", {})
    trivia_wins[uid] = trivia_wins.get(uid, 0) + 1
    save_economy(eco)


def get_guild_target(guild_id):
    """Return the hate-target config for a guild, falling back to env-var defaults."""
    if guild_id:
        eco = load_economy()
        t = eco.get("guild_targets", {}).get(str(guild_id))
        if t:
            return t
    return {"name": TARGET_NAME, "usernames": list(TARGET_USERNAMES), "ticker": TARGET_STOCK_TICKER}


def get_guild_config(guild_id):
    """Return the channel config for a guild, falling back to env-var defaults."""
    if guild_id:
        eco = load_economy()
        c = eco.get("guild_configs", {}).get(str(guild_id))
        if c:
            return c
    return {"roast_channel": ROAST_CHANNEL_ID, "voice_channel": VOICE_CHANNEL_ID}


_MAX_ACTIVE_TARGET_HISTORY = 10


def set_guild_target(guild_id, name, usernames, ticker=None):
    eco = load_economy()
    gid_str = str(guild_id)
    new_ticker = (ticker or name.upper()[:8]).upper()

    # Archive the outgoing target to history before replacing it
    current = eco.get("guild_targets", {}).get(gid_str)
    if current and current.get("ticker", "").upper() != new_ticker:
        history = eco.setdefault("target_history", {}).setdefault(gid_str, [])
        existing_tickers = {e["ticker"].upper() for e in history}
        if current["ticker"].upper() not in existing_tickers:
            history.append({
                "name": current["name"],
                "ticker": current["ticker"].upper(),
                "usernames": current.get("usernames", []),
                "delisted_at": None,
            })

        # If more than 10 active (non-delisted) history entries, delist the oldest
        active = [e for e in history if e.get("delisted_at") is None]
        if len(active) > _MAX_ACTIVE_TARGET_HISTORY:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            active[0]["delisted_at"] = now_iso

    eco.setdefault("guild_targets", {})[gid_str] = {
        "name": name,
        "usernames": [u.strip().lower() for u in usernames if u.strip()],
        "ticker": new_ticker,
    }
    save_economy(eco)


def set_guild_config(guild_id, roast_channel=None, voice_channel=None, vote_changes_target=None):
    eco = load_economy()
    cfg = eco.setdefault("guild_configs", {}).setdefault(str(guild_id), {})
    if roast_channel is not None:
        cfg["roast_channel"] = roast_channel
    if voice_channel is not None:
        cfg["voice_channel"] = voice_channel
    if vote_changes_target is not None:
        cfg["vote_changes_target"] = vote_changes_target
    save_economy(eco)


def _get_guild_channels():
    """Return list of (gid_or_None, channel) for all configured guild roast channels."""
    eco = load_economy()
    configs = eco.get("guild_configs", {})
    result = []
    seen_guild_ids = set()

    for gid_str, cfg in configs.items():
        ch_id = cfg.get("roast_channel")
        if ch_id:
            ch = bot.get_channel(ch_id)
            if ch:
                result.append((int(gid_str), ch))
                seen_guild_ids.add(int(gid_str))

    # For every guild the bot is in that hasn't run !setup, fall back to a
    # suitable channel so events reach all servers, not just configured ones.
    for guild in bot.guilds:
        if guild.id in seen_guild_ids:
            continue
        # Prefer the env-var channel if it belongs to this guild
        if ROAST_CHANNEL_ID:
            ch = bot.get_channel(ROAST_CHANNEL_ID)
            if ch and getattr(ch, "guild", None) and ch.guild.id == guild.id:
                result.append((guild.id, ch))
                continue
        # Otherwise use the guild's system channel or first writable text channel
        ch = guild.system_channel
        if ch is None or not ch.permissions_for(guild.me).send_messages:
            ch = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
        if ch:
            result.append((guild.id, ch))

    return result


def is_insurance_active():
    exp = load_economy().get("insurance_expires")
    if not exp:
        return False
    return datetime.datetime.fromisoformat(exp) > datetime.datetime.now(datetime.timezone.utc)


def consume_upgrade(user_id, upgrade):
    eco = load_economy()
    uid = str(user_id)
    upgrades = eco.get("pending_upgrades", {}).get(uid, [])
    if upgrade in upgrades:
        upgrades.remove(upgrade)
        eco["pending_upgrades"][uid] = upgrades
        save_economy(eco)
        return True
    return False


def has_upgrade(user_id, upgrade):
    eco = load_economy()
    return upgrade in eco.get("pending_upgrades", {}).get(str(user_id), [])


def claim_bounties(user_id):
    eco = load_economy()
    active = [b for b in eco["bounties"] if b["active"]]
    total = sum(b["amount"] for b in active)
    if total > 0:
        uid = str(user_id)
        upgrades = eco.get("pending_upgrades", {}).get(uid, [])
        if "bounty_boost" in upgrades:
            upgrades.remove("bounty_boost")
            eco["pending_upgrades"][uid] = upgrades
            total *= 2
    for b in eco["bounties"]:
        b["active"] = False
    save_economy(eco)
    return total


def is_double_coin_day():
    day = datetime.datetime.now(ZoneInfo("America/New_York")).weekday()
    return day in (4, 5, 6)  # Friday, Saturday, Sunday


def get_daily_reward(streak):
    base = 25 + (min(streak, 30) - 1) * 5
    if streak % 7 == 0:
        base *= 2
    return base


def is_donovan(user, guild_id=None):
    if guild_id:
        t = get_guild_target(guild_id)
        return user.name.lower() in {u.lower() for u in t["usernames"]}
    return user.name.lower() in DONOVAN_USERNAMES


def get_donovan_activity(guild, guild_id=None):
    usernames = {u.lower() for u in get_guild_target(guild_id)["usernames"]} if guild_id else DONOVAN_USERNAMES
    for member in guild.members:
        if member.name.lower() in usernames:
            print(f"[DEBUG] Found member: {member.name}, activities: {member.activities}")
            for activity in member.activities:
                print(f"[DEBUG] Activity: {activity} | Type: {type(activity)}")
                if isinstance(activity, (discord.Game, discord.Activity)):
                    return activity.name
    return None


def get_question(message):
    text = message.content
    for mention in message.mentions:
        text = text.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    return text.strip()


async def ask_openai(question, guild_id=None):
    prompt = _t(_SYSTEM_PROMPT_TMPL, guild_id)
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] OpenAI request failed: {e}")
        return _t(random.choice(_GENERAL_ROASTS_TMPL), guild_id)


async def argue_with_donovan(message_content, guild_id=None):
    prompt = _t(_ARGUE_PROMPT_TMPL, guild_id)
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message_content},
            ],
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] Donovan argue failed: {e}")
        return _t(random.choice(_ROASTS_DIRECT_TMPL), guild_id)


SPORTS_TRIVIA_FALLBACKS = [
    # NFL
    ("How many Super Bowl titles did Tom Brady win in his career?", "7"),
    ("Who was the NFL MVP in 2022?", "Mahomes"),
    ("Which quarterback led the Kansas City Chiefs to multiple Super Bowl wins?", "Mahomes"),
    ("What NFL team did Peyton Manning win his second Super Bowl with?", "Broncos"),
    ("Which team did the New England Patriots defeat to win Super Bowl XLIX?", "Seahawks"),
    ("What running back holds the NFL record for most career rushing yards?", "Smith"),
    ("Who did the New York Giants upset in Super Bowl XLII to end the Patriots' perfect season?", "Patriots"),
    ("Which team won Super Bowl LVI in 2022?", "Rams"),
    ("Who threw the 'Helmet Catch' in Super Bowl XLII?", "Tyree"),
    ("Which team did the Chiefs beat to win their first Super Bowl in 50 years in 2020?", "49ers"),
    ("What wide receiver caught the game-winning touchdown in Super Bowl LIII?", "Edelman"),
    ("Who was the first quarterback to start and win five Super Bowls?", "Brady"),
    ("Which team holds the record for most Super Bowl appearances?", "Patriots"),
    ("Who did Odell Beckham Jr. make his famous one-handed catch against in 2014?", "Cowboys"),
    # NBA
    ("What team did LeBron James win his first NBA championship with in 2012?", "Heat"),
    ("What team did Michael Jordan lead to six NBA championships in the 1990s?", "Bulls"),
    ("Which team won the NBA championship in 2016 after being down 3-1?", "Cavaliers"),
    ("What team did Kevin Durant join in 2016 to win back-to-back titles?", "Warriors"),
    ("Which team won the NBA championship in 2021?", "Bucks"),
    ("Who was the NBA Finals MVP when the Raptors won their first title in 2019?", "Leonard"),
    ("What team did Shaquille O'Neal win three consecutive titles with in the 2000s?", "Lakers"),
    ("Which player was drafted first overall by the Cleveland Cavaliers in 2003?", "James"),
    ("How many MVP awards did LeBron James win in the regular season?", "4"),
    ("What team did the Golden State Warriors beat in the 2017 NBA Finals?", "Cavaliers"),
    ("Which team selected Giannis Antetokounmpo in the 2013 NBA Draft?", "Bucks"),
    ("What team did Kobe Bryant spend his entire career with?", "Lakers"),
    # NHL
    ("Which NHL team won the Stanley Cup in 2023?", "Golden Knights"),
    ("What NHL team did Wayne Gretzky finish his career with in 1999?", "Rangers"),
    ("Who scored the overtime goal for Canada in the 2010 Olympic gold medal hockey game?", "Crosby"),
    ("Which team did Sidney Crosby lead to three Stanley Cup titles?", "Penguins"),
    ("What team won the Stanley Cup in 2021?", "Lightning"),
    ("Which franchise has won the most Stanley Cups in NHL history?", "Canadiens"),
    ("What team drafted Alexander Ovechkin first overall in 2004?", "Capitals"),
    ("Which team did the Vegas Golden Knights defeat to win the 2023 Stanley Cup?", "Panthers"),
    ("What goalie won the Conn Smythe Trophy for the 2018 Stanley Cup champion Capitals?", "Holtby"),
    ("Which team did the Chicago Blackhawks defeat to win the 2010 Stanley Cup?", "Flyers"),
    # MLB
    ("Which team ended a 108-year World Series drought by winning in 2016?", "Cubs"),
    ("What team did the Houston Astros beat to win the 2017 World Series?", "Dodgers"),
    ("Which player holds the MLB record for career home runs?", "Bonds"),
    ("What team did Derek Jeter win five World Series titles with?", "Yankees"),
    ("Which pitcher threw a perfect game in the 2010 World Series?", "Halladay"),
    ("What team won the 2004 World Series, breaking the 'Curse of the Bambino'?", "Red Sox"),
    ("Which team drafted Mike Trout in the 2009 MLB Draft?", "Angels"),
    ("What team did the Atlanta Braves defeat to win the 2021 World Series?", "Astros"),
    # Soccer / General
    ("Which country has won the most FIFA World Cup titles?", "Brazil"),
    ("Who won the Ballon d'Or the most times in history?", "Messi"),
    ("What club did Cristiano Ronaldo leave Manchester United for in 2009?", "Real Madrid"),
    ("Which country hosted the 2018 FIFA World Cup?", "Russia"),
    ("What team won the 2022 FIFA World Cup?", "Argentina"),
    ("Who scored the winning penalty in the 2022 World Cup final for Argentina?", "Mbappe"),
    # Golf & Tennis
    ("How many Grand Slam titles did Tiger Woods win?", "15"),
    ("Which player holds the record for most Grand Slam titles in men's tennis?", "Djokovic"),
    ("Who did Serena Williams lose to in her final Wimbledon final in 2009?", "Williams"),
    ("What is the name of the golf tournament held annually at Augusta National?", "Masters"),
    # Olympics
    ("How many Olympic gold medals did Michael Phelps win in his career?", "23"),
    ("Which country won the most gold medals at the 2020 Tokyo Olympics?", "USA"),
    ("What year did the US Women's Soccer team win their first Olympic gold medal?", "1996"),
]


async def generate_sports_question(sport, used_topics=None):
    import re
    avoid = (f"\nDo NOT generate questions about any of these already-used topics: {'; '.join(used_topics)}."
             if used_topics else "")
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a sports trivia question generator. Generate one trivia question specifically about {sport} from 1990 to present.\n"
                        "ALLOWED QUESTION TYPES (pick any one):\n"
                        "- Championship/title winners: which team won a title, or who was the key player on a championship team\n"
                        "- All-time or era records: who holds a major record, or which team set a record (e.g. most wins in a season, most goals in a playoff run)\n"
                        "- Historic rivalries: a notable fact about a well-known rivalry matchup\n"
                        "- Memorable draft picks: which team drafted a famous player (e.g. 'Which team selected Lebron James first overall in 2003?')\n"
                        "STRICT RULES:\n"
                        "- Only generate questions about facts you are 100% certain are correct\n"
                        "- Do NOT ask about individual season awards (MVP, Hart Trophy, Vezina, scoring titles) — these are too prone to errors\n"
                        "- ANSWER must be a last name only (for players) or a team name — nothing else\n"
                        "- Never put numbers, stats, or extra words in the ANSWER field\n"
                        f"{avoid}\n"
                        "Respond in EXACTLY this format:\n"
                        "QUESTION: <question>\n"
                        "ANSWER: <last name or team name only>"
                    ),
                },
                {"role": "user", "content": f"Generate a {sport} trivia question."},
            ],
            max_tokens=120,
        )
        text = response.choices[0].message.content.strip()
        question, answer = "", ""
        for line in text.split("\n"):
            upper = line.upper()
            if upper.startswith("QUESTION:"):
                question = line[line.index(":") + 1:].strip()
            elif upper.startswith("ANSWER:"):
                raw = line[line.index(":") + 1:].strip()
                raw = re.sub(r'[^\w\s]', '', raw).strip()
                answer = " ".join(raw.split()[:3])
        if question and answer:
            return question, answer
    except Exception as e:
        print(f"[ERROR] Sports trivia generation failed: {e}")
    return random.choice(SPORTS_TRIVIA_FALLBACKS)


TRIVIA_CATEGORIES = [
    "science and nature",
    "world history",
    "geography",
    "movies and television",
    "music",
    "mathematics",
    "food and drink",
    "technology and computers",
    "literature",
    "pop culture",
    "art and artists",
    "mythology and folklore",
    "video games",
    "sports and athletes",
    "space and astronomy",
]


async def generate_trivia_question(used_topics=None, used_categories=None):
    import re
    # Avoid repeating recent categories
    available = [c for c in TRIVIA_CATEGORIES if not used_categories or c not in used_categories]
    category = random.choice(available or TRIVIA_CATEGORIES)
    avoid = (f"\nDo NOT generate questions about these already-asked topics: {'; '.join(used_topics)}."
             if used_topics else "")
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a trivia question generator. Generate one {category} trivia question.\n"
                        "STRICT RULES:\n"
                        "- Only use well-known, verifiable facts you are 100% certain are correct\n"
                        "- The answer must be a single word, number, or short phrase (3 words max)\n"
                        "- The answer must be at least 2 characters — no single-letter answers\n"
                        "- Avoid questions with multiple valid answers\n"
                        f"{avoid}\n"
                        "Respond in EXACTLY this format:\n"
                        "QUESTION: <question>\n"
                        "ANSWER: <answer>"
                    ),
                },
                {"role": "user", "content": f"Generate a {category} trivia question."},
            ],
            max_tokens=120,
        )
        text = response.choices[0].message.content.strip()
        question, answer = "", ""
        for line in text.split("\n"):
            upper = line.upper()
            if upper.startswith("QUESTION:"):
                question = line[line.index(":") + 1:].strip()
            elif upper.startswith("ANSWER:"):
                raw = line[line.index(":") + 1:].strip()
                raw = re.sub(r'[^\w\s]', '', raw).strip()
                answer = " ".join(raw.split()[:3])
        if question and answer and len(answer) >= 2 and len(question) <= 150:
            return question, answer, category
    except Exception as e:
        print(f"[ERROR] Trivia generation failed: {e}")
    q = random.choice(TRIVIA_QUESTIONS)
    return q["q"], q["a"], "general knowledge"


async def judge_sports_answer(question, expected, user_answer):
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict sports trivia judge. Your only job is to decide if a player's answer "
                        "is correct. Be strict about factual accuracy — do NOT accept an answer just because "
                        "it sounds plausible. A wrong player name is always wrong, even if the player is famous. "
                        "Accept: last name only, common nicknames, minor spelling variations of the correct answer. "
                        "Reject: any different person or team, even a famous one. "
                        "Reply with ONLY 'yes' or 'no'."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\nCorrect answer: {expected}\nPlayer answered: {user_answer}\nIs the player correct?",
                },
            ],
            max_tokens=5,
        )
        return response.choices[0].message.content.strip().lower().startswith("yes")
    except Exception as e:
        print(f"[ERROR] Answer judge failed: {e}")
        return expected.lower() in user_answer.lower()


def _trivia_quick_match(expected: str, user: str) -> bool:
    e_words = expected.lower().strip().split()
    u_words = user.lower().strip().split()
    return bool(u_words) and e_words[:len(u_words)] == u_words


async def judge_trivia_answer(question, expected, user_answer):
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a trivia answer judge. Decide if the player's answer is correct.\n"
                        "Accept: the exact answer, common abbreviations, partial answers that clearly "
                        "identify the correct answer (e.g. 'Amazon' for 'Amazon River', 'Shakespeare' "
                        "for 'William Shakespeare'), minor typos and spelling mistakes.\n"
                        "Reject: clearly wrong answers.\n"
                        "Reply with ONLY 'yes' or 'no'."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\nCorrect answer: {expected}\nPlayer answered: {user_answer}\nIs the player correct?",
                },
            ],
            max_tokens=5,
        )
        return response.choices[0].message.content.strip().lower().startswith("yes")
    except Exception as e:
        print(f"[ERROR] Trivia judge failed: {e}")
        return expected.lower() in user_answer.lower() or user_answer.lower() in expected.lower()


async def is_hot_take(text):
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a hot take detector. A hot take is an opinion that is controversial, "
                        "bold, unpopular, or likely to spark debate. Reply with only 'yes' or 'no'."
                    ),
                },
                {"role": "user", "content": f"Is this a hot take? '{text}'"},
            ],
            max_tokens=5,
        )
        answer = response.choices[0].message.content.strip().lower()
        return answer.startswith("yes")
    except Exception as e:
        print(f"[ERROR] Hot take check failed: {e}")
        return False


def get_donovan_voice_channel(guild):
    gid = guild.id if guild else None
    tgt_usernames = {u.lower() for u in get_guild_target(gid)["usernames"]}
    for member in guild.members:
        member_names = {member.name.lower()}
        if getattr(member, "display_name", None):
            member_names.add(member.display_name.lower())
        if member_names & tgt_usernames and member.voice:
            return member.voice.channel
    cfg = get_guild_config(gid)
    vc_id = cfg.get("voice_channel")
    if vc_id:
        channel = bot.get_channel(vc_id)
        if channel and getattr(channel, "guild", None) and channel.guild.id == gid:
            return channel
        print(f"[WARN] Ignoring configured voice channel {vc_id} for guild {gid}; channel missing or cross-guild.")
    if VOICE_CHANNEL_ID:
        channel = bot.get_channel(VOICE_CHANNEL_ID)
        if channel and getattr(channel, "guild", None) and channel.guild.id == gid:
            return channel
    # Last-resort fallback: any active voice channel in this guild.
    active_channels = [
        vc for vc in guild.voice_channels
        if any(not m.bot for m in getattr(vc, "members", []))
    ]
    if active_channels:
        return sorted(active_channels, key=lambda c: len(c.members), reverse=True)[0]
    return None


async def tts_worker():
    while True:
        item = await tts_queue.get()
        guild_id, text = item[0], item[1]
        voice_channel_id = item[2] if len(item) > 2 else None
        tmp_path = None
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue

            if voice_channel_id:
                channel = bot.get_channel(voice_channel_id) or await bot.fetch_channel(voice_channel_id)
                if getattr(channel, "guild", None) and channel.guild.id != guild_id:
                    print(
                        f"[WARN] Ignoring cross-guild TTS channel {voice_channel_id} "
                        f"for guild {guild_id}; falling back to guild voice target."
                    )
                    channel = None
            else:
                channel = None
            if channel is None:
                channel = get_donovan_voice_channel(guild)
            if not channel:
                continue

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            await asyncio.to_thread(gTTS(text=text, lang="en").save, tmp_path)

            vc = guild.voice_client
            if vc and vc.is_connected():
                await vc.move_to(channel)
            else:
                vc = await channel.connect()

            vc.play(discord.FFmpegPCMAudio(tmp_path))
            while vc.is_playing():
                await asyncio.sleep(0.5)

            if tts_queue.empty():
                await vc.disconnect()

        except Exception as e:
            print(f"[ERROR] TTS worker failed: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            tts_queue.task_done()


def _market_sentiment(eco):
    """Return a (score 0-100, label, emoji) fear/greed index from recent price action."""
    all_stocks = {**MARKET_STOCKS, **_get_target_stock_info(eco)}
    momentum_vals, breadth_vals, si_vals = [], [], []
    for ticker, info in all_stocks.items():
        mdata = eco.get("market", {}).get(ticker)
        if not mdata:
            continue
        history = mdata.get("price_history", [mdata["price"]])
        price = mdata["price"]
        # 12-tick momentum
        if len(history) >= 13:
            old = history[-13]
            momentum_vals.append((price - old) / old * 100 if old else 0)
        # breadth: is price above dynamic base?
        dbase = mdata.get("dynamic_base", info.get("base_price", price))
        breadth_vals.append(1 if price >= dbase else 0)
        # short interest
        shorted = sum(
            pos[ticker]["shares"]
            for pos in eco.get("short_positions", {}).values()
            if ticker in pos
        )
        outstanding = info.get("shares_outstanding", 5000)
        si_vals.append(shorted / outstanding)

    if not breadth_vals:
        return 50, "Neutral", "😐"

    # Momentum: clamp avg % change to ±5, normalise to 0-100
    avg_mom = sum(momentum_vals) / len(momentum_vals) if momentum_vals else 0
    mom_score = (max(-5, min(5, avg_mom)) + 5) / 10 * 100

    # Breadth: % of stocks above their base (0-100)
    breadth_score = sum(breadth_vals) / len(breadth_vals) * 100

    # Short interest: high SI = fear; invert so 0 SI = 100 (greedy), high SI = 0 (fearful)
    avg_si = sum(si_vals) / len(si_vals) if si_vals else 0
    si_score = max(0, 100 - avg_si * 500)

    score = round(mom_score * 0.4 + breadth_score * 0.35 + si_score * 0.25)

    if score >= 80:
        return score, "Extreme Greed", "🤑"
    elif score >= 60:
        return score, "Greed", "😏"
    elif score >= 40:
        return score, "Neutral", "😐"
    elif score >= 20:
        return score, "Fear", "😰"
    else:
        return score, "Extreme Fear", "🩸"


@tasks.loop(time=datetime.time(hour=18, minute=0, tzinfo=ZoneInfo("America/New_York")))
async def dividend_payout():
    """Every Sunday at 6 PM ET: pay dividends to holders of dividend-bearing stocks."""
    if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 6:
        return

    eco = load_economy()
    init_market(eco)
    payouts = {}  # uid -> total coins earned

    for ticker, info in MARKET_STOCKS.items():
        rate = info.get("dividend_rate")
        if not rate:
            continue
        price = eco["market"].get(ticker, {}).get("price", info["base_price"])
        per_share = round(price * rate, 2)
        if per_share <= 0:
            continue
        for uid, port in eco.get("portfolios", {}).items():
            shares = port.get(ticker, {}).get("shares", 0)
            if shares <= 0:
                continue
            earned = round(per_share * shares)
            eco["balances"][uid] = eco.get("balances", {}).get(uid, 0) + earned
            payouts.setdefault(uid, {})[ticker] = earned

    save_economy(eco)

    if not payouts:
        return

    lines = ["💰 **WEEKLY DIVIDENDS PAID**\n"]
    for ticker, info in MARKET_STOCKS.items():
        if not info.get("dividend_rate"):
            continue
        price = eco["market"].get(ticker, {}).get("price", info["base_price"])
        per_share = round(price * info["dividend_rate"], 2)
        total_paid = sum(v[ticker] for v in payouts.values() if ticker in v)
        if total_paid:
            lines.append(f"**${ticker}** — {per_share:.2f} coins/share  ({total_paid:,} coins paid out)")

    for _, ch in _get_guild_channels():
        try:
            await ch.send("\n".join(lines))
        except Exception:
            pass


@tasks.loop(time=datetime.time(hour=19, minute=0, tzinfo=ZoneInfo("America/New_York")))
async def earnings_report():
    """Every Sunday at 7 PM ET: shift each stock's dynamic base toward its weekly average."""
    if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 6:
        return

    eco = load_economy()
    init_market(eco)
    all_stocks = {**MARKET_STOCKS, **_get_target_stock_info(eco)}
    lines = ["📰 **WEEKLY EARNINGS REPORT** 📰\n"]

    for ticker, info in all_stocks.items():
        mdata = eco["market"].get(ticker)
        if not mdata:
            continue

        old_base = mdata.get("dynamic_base", info["base_price"])
        history = mdata.get("price_history", [mdata["price"]])
        recent_avg = sum(history) / len(history)

        # Shift base 30% toward the weekly average, capped at ±10% per week
        raw_new_base = old_base * 0.70 + recent_avg * 0.30
        max_shift = old_base * 0.10
        new_base = max(old_base - max_shift, min(old_base + max_shift, raw_new_base))
        new_base = round(new_base, 2)
        mdata["dynamic_base"] = new_base

        change_pct = round((new_base - old_base) / old_base * 100, 1)
        if abs(change_pct) < 0.1:
            rating = "➡️ HOLD"
        elif change_pct >= 5:
            rating = "🚀 STRONG BUY"
        elif change_pct >= 2:
            rating = "📈 BUY"
        elif change_pct <= -5:
            rating = "💀 STRONG SELL"
        elif change_pct <= -2:
            rating = "📉 SELL"
        else:
            rating = "🟡 NEUTRAL"

        lines.append(
            f"**${ticker}** — Base: **${old_base:.2f} → ${new_base:.2f}** ({change_pct:+.1f}%)  {rating}"
        )

    save_economy(eco)
    msg = "\n".join(lines)
    for _, ch in _get_guild_channels():
        try:
            await ch.send(msg)
        except Exception:
            pass


@tasks.loop(time=datetime.time(hour=21, minute=0, tzinfo=ZoneInfo("America/New_York")))
async def weekly_recap():
    today = datetime.datetime.now(datetime.timezone.utc).weekday()
    if today != 6:  # Sunday only
        return

    guild_channels = _get_guild_channels()
    if not guild_channels:
        return

    total, log = get_weekly_recap()
    busiest_day = hour_label = None
    if total:
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_counts = [0] * 7
        hour_counts = [0] * 24
        for ts in log:
            dt = datetime.datetime.fromisoformat(ts)
            day_counts[dt.weekday()] += 1
            hour_counts[dt.hour] += 1
        busiest_day = day_names[day_counts.index(max(day_counts))]
        busiest_hour = hour_counts.index(max(hour_counts))
        hour_label = datetime.datetime(2000, 1, 1, busiest_hour).strftime("%I %p").lstrip("0")

    # Lottery drawing (once — shared economy)
    eco = load_economy()
    init_market(eco)
    tickets = eco.get("lottery_tickets", {})
    pot = eco.get("lottery_pot", 0)
    lottery_winner_id = None
    pool = []
    if tickets and pot > 0:
        for uid, count in tickets.items():
            pool.extend([uid] * count)
        lottery_winner_id = random.choice(pool)
        add_coins(int(lottery_winner_id), pot)
        eco = load_economy()
    eco["lottery_tickets"] = {}
    eco["lottery_pot"] = 500
    # Reset weekly volume
    for ticker in eco.get("market", {}):
        eco["market"][ticker]["volume_today"] = 0
    save_economy(eco)

    for gid, channel in guild_channels:
        tgt_name = get_guild_target(gid)["name"] if gid else TARGET_NAME

        if not total:
            await channel.send(
                f"📊 **Weekly Roast Recap**\n{tgt_name} somehow avoided getting roasted this week. Suspicious."
            )
        else:
            await channel.send(
                f"📊 **Weekly Roast Recap**\n"
                f"{tgt_name} got roasted **{total} times** this week. Impressive dedication everyone.\n\n"
                f"🏆 Most active day: **{busiest_day}**\n"
                f"⏰ Peak roast hour: **{hour_label} UTC**\n\n"
                f"See you all next week for more {tgt_name} disrespect."
            )

        # Portfolio standings (per-guild for member display names)
        eco2 = load_economy()
        all_uids = set(eco2.get("portfolios", {}).keys()) | set(eco2.get("short_positions", {}).keys())
        if all_uids:
            ranked = sorted(all_uids, key=lambda u: get_portfolio_value(eco2, u), reverse=True)
            lines = ["📈 **Weekly Portfolio Standings**\n"]
            for i, uid in enumerate(ranked[:5], 1):
                member = channel.guild.get_member(int(uid))
                mname = member.display_name if member else "Unknown"
                val = get_portfolio_value(eco2, uid)
                medal = ["🥇", "🥈", "🥉", "4.", "5."][i - 1]
                lines.append(f"{medal} **{mname}** — {val:.0f} coins")
            if len(ranked) > 1:
                loser_uid = ranked[-1]
                loser = channel.guild.get_member(int(loser_uid))
                loser_name = loser.display_name if loser else "Unknown"
                loser_val = get_portfolio_value(eco2, loser_uid)
                lines.append(f"\n💀 Biggest loser: **{loser_name}** — {loser_val:.0f} coins")
            await channel.send("\n".join(lines))

        # Lottery result
        if lottery_winner_id:
            winner_member = channel.guild.get_member(int(lottery_winner_id))
            winner_display = winner_member.display_name if winner_member else "Someone"
            await channel.send(
                f"🎟️ **WEEKLY LOTTERY DRAWING!**\n\n"
                f"Out of {len(pool)} tickets...\n"
                f"🏆 **{winner_display}** wins the **{pot} coin** pot!\n"
                f"New lottery starts now. Buy tickets with `!lottery <amount>`."
            )
        else:
            await channel.send(
                "🎟️ No lottery tickets sold this week. New pot resets to **500 coins**."
            )


@tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=ZoneInfo("America/New_York")))
async def scheduled_roast():
    today = datetime.datetime.now(datetime.timezone.utc).weekday()
    guild_channels = _get_guild_channels()
    for gid, channel in guild_channels:
        if today == 0:
            await channel.send(_t(random.choice(_MONDAY_ROASTS_TMPL), gid))
            asyncio.create_task(_apply_roast_stock_impact(gid))
        elif today == 4:
            msg = _t(random.choice(_FRIDAY_ROASTS_TMPL), gid)
            await channel.send(msg)
            await tts_queue.put((channel.guild.id, msg))
            asyncio.create_task(_apply_roast_stock_impact(gid))


@tasks.loop(minutes=1)
async def limit_order_checker():
    eco = load_economy()
    init_market(eco)
    orders = list(eco.get("limit_orders", []))
    if not orders:
        return
    remaining = []
    notifications = []
    for order in orders:
        ticker = order["ticker"]
        if ticker not in eco.get("market", {}):
            remaining.append(order)
            continue
        price = eco["market"][ticker]["price"]
        should_fill = (
            (order["order_type"] == "buy"   and price <= order["limit_price"]) or
            (order["order_type"] == "sell"  and price >= order["limit_price"]) or
            (order["order_type"] == "short" and price >= order["limit_price"]) or
            (order["order_type"] == "cover" and price <= order["limit_price"])
        )
        if not should_fill:
            remaining.append(order)
            continue
        uid = order["user_id"]
        if order["order_type"] == "buy":
            ok, msg = execute_market_buy(eco, uid, ticker, order["shares"])
        elif order["order_type"] == "sell":
            ok, msg = execute_market_sell(eco, uid, ticker, order["shares"])
        elif order["order_type"] == "short":
            ok, msg = execute_open_short(eco, uid, ticker, order["shares"])
        else:
            ok, msg = execute_close_short(eco, uid, ticker, order["shares"])
        status = "filled ✅" if ok else "failed ❌"
        notifications.append((uid, order["id"], status, msg))
    eco["limit_orders"] = remaining
    save_economy(eco)
    guild_channels = _get_guild_channels()
    for uid, order_id, status, msg in notifications:
        for gid, channel in guild_channels:
            member = channel.guild.get_member(int(uid))
            mention = member.mention if member else f"<@{uid}>"
            await channel.send(f"📋 {mention} Limit order **#{order_id}** {status}: {msg}")
            break


@tasks.loop(minutes=10)
async def meme_stock_drift():
    eco = load_economy()
    init_market(eco)
    now = datetime.datetime.now(datetime.timezone.utc)
    broadcast_channels = _get_guild_channels()
    mstate = eco["market_state"]

    # ── Delist cleanup: auto-liquidate and remove expired target stocks ───────
    delist_grace = datetime.timedelta(hours=48)
    for gid_str, history in eco.get("target_history", {}).items():
        still_active = []
        for entry in history:
            delisted_at_str = entry.get("delisted_at")
            if not delisted_at_str:
                still_active.append(entry)
                continue
            deadline = datetime.datetime.fromisoformat(delisted_at_str) + delist_grace
            if now <= deadline:
                still_active.append(entry)
                continue
            # Grace period over — liquidate all holders at last known price
            ticker = entry.get("ticker", "").upper()
            last_price = eco.get("market", {}).get(ticker, {}).get("price")
            if ticker and last_price:
                for uid, port in eco.get("portfolios", {}).items():
                    shares_held = port.get(ticker, {}).get("shares", 0)
                    if shares_held > 0:
                        payout = round(shares_held * last_price)
                        eco["balances"][uid] = eco.get("balances", {}).get(uid, 0) + payout
                        port.pop(ticker, None)
                eco["market"].pop(ticker, None)
            # Drop from target_history (don't keep in still_active)
        eco["target_history"][gid_str] = still_active

    # ── Resolve pending rumors ────────────────────────────────────────────────
    still_pending = []
    for rumor in eco.get("pending_rumors", []):
        if now < datetime.datetime.fromisoformat(rumor["confirm_at"]):
            still_pending.append(rumor)
            continue
        confirmed = random.random() < 0.70
        if confirmed:
            for t, pct in rumor["remaining_impact"].items():
                if t in eco["market"]:
                    old = eco["market"][t]["price"]
                    eco["market"][t]["prev_price"] = old
                    eco["market"][t]["price"] = max(round(old * (1 + pct / 100), 2), 0.01)
            new_p = eco["market"][rumor["ticker"]]["price"]
            analyst = random.choice(_ANALYST_QUOTES)
            for _, ch in broadcast_channels:
                await ch.send(
                    f"✅ **CONFIRMED — ${rumor['ticker']}:** {rumor['headline']}\n"
                    f"**${rumor['old_price']:.2f} → ${new_p:.2f}** | {analyst}"
                )
        else:
            for t, pct in rumor["pre_impact"].items():
                if t in eco["market"]:
                    old = eco["market"][t]["price"]
                    eco["market"][t]["prev_price"] = old
                    eco["market"][t]["price"] = max(round(old * (1 - pct / 100), 2), 0.01)
            for _, ch in broadcast_channels:
                await ch.send(
                    f"❌ **DENIED — ${rumor['ticker']}:** *\"{rumor['headline']}\"* was **FAKE NEWS**. "
                    f"Price reverting. 📉"
                )
    eco["pending_rumors"] = still_pending

    # ── Market sentiment: slow random walk, mean-reverts to 0 ─────────────────
    sentiment = mstate.get("sentiment", 0.0)
    sentiment = max(-1.0, min(1.0, sentiment * 0.92 + random.gauss(0, 0.1)))
    mstate["sentiment"] = round(sentiment, 4)

    # ── Daily volume reset ────────────────────────────────────────────────────
    today = now.strftime("%Y-%m-%d")
    if mstate.get("volume_date") != today:
        for ticker in MARKET_STOCKS:
            eco["market"][ticker]["volume_today"] = 0
        mstate["volume_date"] = today

    # ── Volume-based price discovery ──────────────────────────────────────────
    now_iso = now.isoformat()
    est_hour = (now.hour - 5) % 24
    all_drift_stocks = {**MARKET_STOCKS, **_get_target_stock_info(eco)}
    for ticker, info in all_drift_stocks.items():
        mdata = eco["market"][ticker]
        price = mdata["price"]
        base = mdata.get("dynamic_base", info["base_price"])
        vol = info["volatility"]
        daily_vol = info["daily_volume"]

        # TBELL 4th meal hours: triple volume and volatility 10pm–4am EST
        tick_multiplier = 3.0 if ticker == "TBELL" and (est_hour >= 22 or est_hour < 4) else 1.0

        # Simulated tick volume — slice of daily volume with noise
        tick_vol = max(10, round(daily_vol / 144 * random.uniform(0.5, 2.0) * tick_multiplier))

        # Buy pressure probability — baked-in sentiment, mean reversion, momentum
        history = mdata.get("price_history", [price])
        mr_tilt      = (base - price) / base * info["mean_reversion"] * 10
        momentum_tilt = ((history[-1] / history[0] - 1) if len(history) >= 2 else 0.0) * 0.15
        p_buy = max(0.15, min(0.85, 0.5 + sentiment * 0.15 + mr_tilt + momentum_tilt))

        buy_vol  = round(tick_vol * p_buy)
        sell_vol = tick_vol - buy_vol

        # Order flow imbalance drives direction; volatility scales magnitude
        ofi        = (buy_vol - sell_vol) / tick_vol
        volume_pct = ofi * vol * 0.7 * tick_multiplier
        noise_pct  = random.gauss(0, vol * 0.25)
        total_pct  = max(-15.0, min(15.0, volume_pct + noise_pct))

        new_price = max(round(price * (1 + total_pct / 100), 2), 0.01)
        mdata["price_history"]  = (history + [new_price])[-48:]
        mdata["prev_price"]     = price
        mdata["price"]          = new_price
        mdata["last_updated"]   = now_iso
        mdata["volume_today"]   = mdata.get("volume_today", 0) + tick_vol
        mdata["all_time_high"]  = max(mdata.get("all_time_high", new_price), new_price)
        mdata["all_time_low"]   = min(mdata.get("all_time_low",  new_price), new_price)

    # ── News events ───────────────────────────────────────────────────────────
    immediate_news = []
    for ticker in MARKET_STOCKS:
        if random.random() > 0.015:
            continue
        event = random.choice(_STOCK_NEWS[ticker])
        headline = event["headline"]
        if "{member}" in headline:
            headline = headline.replace("{member}", _get_random_member_name())

        impact_pct = random.uniform(*event["impact"])
        impacts = {ticker: impact_pct}
        for linked_ticker, linked_range in event.get("linked", []):
            impacts[linked_ticker] = random.uniform(*linked_range)

        is_rumor = random.random() < 0.30
        if is_rumor:
            pre_impact, remaining_impact = {}, {}
            for t, pct in impacts.items():
                pre_impact[t] = round(pct * 0.25, 4)
                remaining_impact[t] = round(pct * 0.75, 4)
                if t in eco["market"]:
                    old = eco["market"][t]["price"]
                    eco["market"][t]["prev_price"] = old
                    eco["market"][t]["price"] = max(round(old * (1 + pre_impact[t] / 100), 2), 0.01)
            eco["pending_rumors"].append({
                "ticker": ticker,
                "headline": headline,
                "old_price": eco["market"][ticker]["price"],
                "pre_impact": pre_impact,
                "remaining_impact": remaining_impact,
                "confirm_at": (now + datetime.timedelta(minutes=20)).isoformat(),
            })
            pre_pct = pre_impact[ticker]
            cur_p = eco["market"][ticker]["price"]
            for _, ch in broadcast_channels:
                await ch.send(
                    f"🔍 **UNCONFIRMED — ${ticker}:** *\"{headline}\"*\n"
                    f"Markets reacting cautiously: **${cur_p:.2f}** ({pre_pct:+.1f}% pre-move) "
                    f"— confirmation expected in ~20 min..."
                )
        else:
            old_price = eco["market"][ticker]["price"]
            for t, pct in impacts.items():
                if t in eco["market"]:
                    old = eco["market"][t]["price"]
                    eco["market"][t]["prev_price"] = old
                    eco["market"][t]["price"] = max(round(old * (1 + pct / 100), 2), 0.01)
            immediate_news.append((ticker, headline, impact_pct, old_price, impacts))

    save_economy(eco)

    for ticker, headline, impact_pct, old_p, impacts in immediate_news:
        arrow = "📈" if impact_pct > 0 else "📉"
        new_p = eco["market"][ticker]["price"]
        analyst = random.choice(_ANALYST_QUOTES)
        linked_str = "".join(
            f" | **${t}** → **${eco['market'][t]['price']:.2f}** ({pct:+.1f}%)"
            for t, pct in impacts.items() if t != ticker
        )
        msg_text = (
            f"{arrow} **BREAKING — ${ticker}:** {headline}\n"
            f"**${old_p:.2f} → ${new_p:.2f}** ({impact_pct:+.1f}%){linked_str}\n"
            f"*{analyst}*"
        )
        for _, ch in broadcast_channels:
            await ch.send(msg_text)


@tasks.loop(minutes=5)
async def derivatives_settlement():
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    gc = _get_guild_channels()
    channel = gc[0][1] if gc else None
    await settle_expired_futures(eco, channel)
    await expire_options(eco, channel)
    save_economy(eco)


@tasks.loop(minutes=5)
async def margin_call_checker():
    eco = load_economy()
    init_market(eco)
    gc = _get_guild_channels()
    channel = gc[0][1] if gc else None
    now = datetime.datetime.now(datetime.timezone.utc)
    squeeze_msgs = []

    # Check for short squeezes before running margin calls
    for ticker, info in MARKET_STOCKS.items():
        if ticker not in eco["market"]:
            continue
        outstanding = info["shares_outstanding"]
        shorted = sum(
            pos[ticker]["shares"]
            for pos in eco.get("short_positions", {}).values()
            if ticker in pos
        )
        if shorted / outstanding <= 0.20:
            continue
        last_str = eco["market"][ticker].get("last_squeeze")
        if last_str and now - datetime.datetime.fromisoformat(last_str) < datetime.timedelta(hours=1):
            continue
        spike_pct = random.uniform(15, 30)
        old = eco["market"][ticker]["price"]
        new = round(old * (1 + spike_pct / 100), 2)
        eco["market"][ticker]["prev_price"] = old
        eco["market"][ticker]["price"] = new
        eco["market"][ticker]["last_squeeze"] = now.isoformat()
        squeeze_msgs.append((ticker, old, new, round(shorted / outstanding * 100, 1), spike_pct))

    # Run margin calls (catches positions squeezed above threshold)
    liquidations = []
    for uid, positions in list(eco.get("short_positions", {}).items()):
        for ticker in list(positions.keys()):
            pos = positions[ticker]
            price = eco["market"][ticker]["price"]
            loss = (price - pos["avg_price"]) * pos["shares"]
            if loss >= pos["collateral"] * 0.80:
                pnl = round((pos["avg_price"] - price) * pos["shares"], 2)
                returned = max(round(pos["collateral"] + pnl, 2), 0)
                apply_price_impact(eco, ticker, pos["shares"], +1)
                eco["balances"][uid] = eco["balances"].get(uid, 0) + returned
                del eco["short_positions"][uid][ticker]
                if not eco["short_positions"][uid]:
                    del eco["short_positions"][uid]
                liquidations.append((uid, ticker, pos["shares"], price, pnl, returned))

    if squeeze_msgs or liquidations:
        save_economy(eco)
    if channel:
        for ticker, old, new, si_pct, spike_pct in squeeze_msgs:
            await channel.send(
                f"🔥 **SHORT SQUEEZE — ${ticker}!** Short interest hit **{si_pct:.1f}%** of float. "
                f"Price spiked **+{spike_pct:.1f}%**: **${old:.2f}** → **${new:.2f}**. "
                f"Short sellers getting squeezed! 💀"
            )
        for uid, ticker, shares, price, pnl, returned in liquidations:
            member = channel.guild.get_member(int(uid))
            mention = member.mention if member else f"<@{uid}>"
            pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
            await channel.send(
                f"🚨 **MARGIN CALL** — {mention}'s short on **${ticker}** ({shares} shares) was "
                f"force-liquidated at **${price:.2f}**. "
                f"P&L: **{pnl_str} coins** | Returned: **{returned:.0f} coins**"
            )




_admin_server_started = False


async def _start_admin_server():
    global _admin_server_started
    app = create_web_app(load_economy, save_economy, get_shop_rotation, SHOP_ITEMS, MARKET_STOCKS, bot, tts_queue)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    base_port = 47832
    for port in range(base_port, base_port + 10):
        try:
            site = aiohttp.web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            _admin_server_started = True
            print(f"Admin dashboard running at http://0.0.0.0:{port}")
            return
        except OSError:
            continue
    print("Admin dashboard failed to start: no available port in range 47832-47841")
    _admin_server_started = False


# ── Weekly hate vote ──────────────────────────────────────────────────────────

VOTE_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
VOTE_CANDIDATE_LIMIT = 9


async def _apply_roast_stock_impact(guild_id):
    """Drop the roasted guild target's stock and boost every other guild target's stock."""
    eco = load_economy()
    init_market(eco)

    roasted_tgt = get_guild_target(guild_id)
    roasted_ticker = (roasted_tgt.get("ticker") or "").upper()
    if not roasted_ticker or roasted_ticker not in eco["market"]:
        return

    drop_pct = random.uniform(-15, -5)
    boost_pct = random.uniform(1, 5)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    moves = {}

    old = eco["market"][roasted_ticker]["price"]
    eco["market"][roasted_ticker]["prev_price"] = old
    eco["market"][roasted_ticker]["price"] = max(round(old * (1 + drop_pct / 100), 2), 0.01)
    eco["market"][roasted_ticker]["last_updated"] = now_iso
    moves[roasted_ticker] = (old, eco["market"][roasted_ticker]["price"], drop_pct, roasted_tgt["name"])

    for tgt in eco.get("guild_targets", {}).values():
        ticker = (tgt.get("ticker") or "").upper()
        if not ticker or ticker == roasted_ticker or ticker not in eco["market"]:
            continue
        old = eco["market"][ticker]["price"]
        eco["market"][ticker]["prev_price"] = old
        eco["market"][ticker]["price"] = max(round(old * (1 + boost_pct / 100), 2), 0.01)
        eco["market"][ticker]["last_updated"] = now_iso
        moves[ticker] = (old, eco["market"][ticker]["price"], boost_pct, tgt["name"])

    save_economy(eco)

    # Prices updated silently — players discover the moves via !stockmarket


async def _post_hate_vote(channel=None):
    """Post a reaction-based vote in the roast channel."""
    if channel is None:
        gc = _get_guild_channels()
        if not gc:
            return
        for gid, ch in gc:
            await _post_hate_vote(ch)
        return
    if not channel:
        return

    guild = channel.guild
    members = [m for m in guild.members if not m.bot]
    random.shuffle(members)
    candidates = members[:VOTE_CANDIDATE_LIMIT]

    lines = [
        "🗳️ **WEEKLY HATE VOTE** 🗳️",
        f"Who does this server hate the most? React to vote — winner gets roasted all week.\n",
    ]
    eco_candidates = []
    for i, member in enumerate(candidates):
        lines.append(f"{VOTE_EMOJIS[i]}  **{member.display_name}**  (`{member.name}`)")
        eco_candidates.append({
            "name": member.display_name,
            "username": member.name,
            "user_id": member.id,
            "emoji": VOTE_EMOJIS[i],
        })

    lines.append("\nVoting closes **Sunday at 8 PM ET**. Most reactions wins.")
    msg = await channel.send("\n".join(lines))
    for i in range(len(candidates)):
        await msg.add_reaction(VOTE_EMOJIS[i])

    eco = load_economy()
    eco.setdefault("active_votes", {})[str(guild.id)] = {
        "message_id": msg.id,
        "channel_id": channel.id,
        "candidates": eco_candidates,
    }
    save_economy(eco)


async def _tally_hate_vote(guild_id=None):
    """Read reactions on the vote message, update the target to the winner.

    If guild_id is given, tally only that guild's vote.  Otherwise tally all.
    """
    eco = load_economy()
    active_votes = eco.get("active_votes") or {}

    # Support the legacy single-vote key so old data isn't lost on upgrade.
    if not active_votes and eco.get("active_vote"):
        legacy = eco["active_vote"]
        ch = bot.get_channel(legacy["channel_id"])
        if ch and ch.guild:
            active_votes = {str(ch.guild.id): legacy}

    if guild_id is not None:
        gids = [str(guild_id)]
    else:
        gids = list(active_votes.keys())

    for gid_str in gids:
        vote_data = active_votes.get(gid_str)
        if not vote_data:
            continue

        channel = bot.get_channel(vote_data["channel_id"])
        if not channel:
            eco.get("active_votes", {}).pop(gid_str, None)
            continue

        try:
            msg = await channel.fetch_message(vote_data["message_id"])
        except Exception:
            eco.get("active_votes", {}).pop(gid_str, None)
            continue

        # Map emoji → reaction count (subtract 1 for the bot's own seed reaction)
        counts = {str(r.emoji): max(0, r.count - 1) for r in msg.reactions}

        candidates = vote_data["candidates"]
        winner = max(candidates, key=lambda c: counts.get(c["emoji"], 0))
        top_votes = counts.get(winner["emoji"], 0)

        eco.setdefault("active_votes", {}).pop(gid_str, None)
        eco.pop("active_vote", None)  # clean up legacy key if present
        save_economy(eco)

        if top_votes == 0:
            await channel.send(
                "🗳️ **VOTE RESULTS**\nNobody voted. The current target carries over by default. Embarrassing turnout."
            )
            continue

        g_id = channel.guild.id if channel.guild else None
        old_tgt = get_guild_target(g_id)
        old_name = old_tgt["name"]
        guild_cfg = get_guild_config(g_id)
        changes_target = guild_cfg.get("vote_changes_target", True)
        if changes_target:
            update_target(winner["name"], [winner["username"]], guild_id=g_id)

        board = []
        for c in sorted(candidates, key=lambda c: counts.get(c["emoji"], 0), reverse=True):
            v = counts.get(c["emoji"], 0)
            bar = "█" * v if v else "░"
            board.append(f"{c['emoji']} **{c['name']}** — {v} vote{'s' if v != 1 else ''}  {bar}")

        if changes_target:
            outcome = (
                f"{old_name} gets a temporary reprieve. {winner['name']} — your time starts now."
            )
        else:
            outcome = (
                f"(Target switching is disabled for this server — **{old_name}** stays in the hot seat.)"
            )
        await channel.send(
            f"🗳️ **VOTE RESULTS**\n\n"
            + "\n".join(board)
            + f"\n\n👑 **{winner['name']}** wins with **{top_votes} vote{'s' if top_votes != 1 else ''}**.\n"
            + outcome
        )


@tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=ZoneInfo("America/New_York")))
async def weekly_vote_start():
    """Open the vote every Monday at 9 AM ET."""
    if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 0:
        return
    await _post_hate_vote()


@tasks.loop(time=datetime.time(hour=20, minute=0, tzinfo=ZoneInfo("America/New_York")))
async def weekly_vote_end():
    """Close the vote every Sunday at 8 PM ET (one hour before weekly recap)."""
    if datetime.datetime.now(ZoneInfo("America/New_York")).weekday() != 6:
        return
    await _tally_hate_vote()


@bot.command(name="startvote")
@commands.has_permissions(administrator=True)
async def start_vote(ctx):
    """Manually open a hate vote in the current channel."""
    if not ctx.guild:
        await ctx.send("This command must be used in a server.")
        return
    eco = load_economy()
    if eco.get("active_votes", {}).get(str(ctx.guild.id)):
        await ctx.send("⚠️ A vote is already running in this server. Use `!tallyvote` to close it first.")
        return
    await _post_hate_vote(ctx.channel)


@bot.command(name="tallyvote")
@commands.has_permissions(administrator=True)
async def tally_vote(ctx):
    """Manually close and tally the current vote."""
    if not ctx.guild:
        await ctx.send("This command must be used in a server.")
        return
    eco = load_economy()
    if not eco.get("active_votes", {}).get(str(ctx.guild.id)):
        await ctx.send("No active vote to tally in this server.")
        return
    await _tally_hate_vote(guild_id=ctx.guild.id)


@bot.command(name="currenttarget")
async def current_target(ctx):
    """Show who the bot is currently targeting."""
    gid = ctx.guild.id if ctx.guild else None
    tgt = get_guild_target(gid)
    usernames = tgt.get("usernames") or []
    await ctx.send(
        f"🎯 Current target: **{tgt['name']}**\n"
        f"Usernames: `{'`, `'.join(usernames) if usernames else 'none set'}`\n"
        f"Stock ticker: `${tgt['ticker']}`"
    )


@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup_guild(ctx):
    """Register this channel as the roast channel for this server."""
    if not ctx.guild:
        await ctx.send("This command must be used in a server.")
        return
    set_guild_config(ctx.guild.id, roast_channel=ctx.channel.id)
    await ctx.send(
        f"✅ **Setup complete!** This channel is now the roast channel for **{ctx.guild.name}**.\n"
        f"Use `!settarget <display_name> <discord_username> [ticker]` to set who gets hated on here."
    )


@bot.command(name="settarget")
@commands.has_permissions(administrator=True)
async def set_target_cmd(ctx, name: str = None, username: str = None, ticker: str = None):
    """Set the hate target for this server. Usage: !settarget <name> <username> [ticker]"""
    if not ctx.guild:
        await ctx.send("This command must be used in a server.")
        return
    if not name or not username:
        gid = ctx.guild.id
        tgt = get_guild_target(gid)
        await ctx.send(
            f"Usage: `!settarget <display_name> <discord_username> [ticker]`\n"
            f"Current target: **{tgt['name']}** (`{', '.join(tgt.get('usernames', []))}`) ${tgt['ticker']}"
        )
        return
    set_guild_target(ctx.guild.id, name, [username], ticker)
    final_ticker = (ticker or name.upper()[:8]).upper()
    await ctx.send(
        f"🎯 Target updated for **{ctx.guild.name}**!\n"
        f"Name: **{name}** | Username: `{username}` | Ticker: `${final_ticker}`\n"
        f"The hate machine is now aimed at **{name}**."
    )


@bot.command(name="togglevoteswitch")
@commands.has_permissions(administrator=True)
async def toggle_vote_switch(ctx):
    """Toggle whether the hate vote winner replaces the target for this server."""
    if not ctx.guild:
        await ctx.send("This command must be used in a server.")
        return
    cfg = get_guild_config(ctx.guild.id)
    current = cfg.get("vote_changes_target", True)
    new_value = not current
    set_guild_config(ctx.guild.id, vote_changes_target=new_value)
    if new_value:
        await ctx.send(
            "🗳️ **Vote target switching ENABLED** — the winner of each hate vote will become the new roast target."
        )
    else:
        await ctx.send(
            "🗳️ **Vote target switching DISABLED** — votes will still run and show results, but the current target won't change."
        )


@bot.event
async def on_ready():
    global _admin_server_started
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Restore persisted target (set by a previous vote or manual update)
    eco = load_economy()
    saved = eco.get("active_target")
    if saved:
        update_target(saved["name"], saved.get("usernames", []), saved.get("ticker"), save=False)
        print(f"[TARGET] Restored from economy.json: {TARGET_NAME} / {TARGET_USERNAMES} / ${TARGET_STOCK_TICKER}")

    scheduled_roast.start()
    dividend_payout.start()
    earnings_report.start()
    weekly_recap.start()
    weekly_vote_start.start()
    weekly_vote_end.start()
    limit_order_checker.start()
    derivatives_settlement.start()
    margin_call_checker.start()
    meme_stock_drift.start()
    asyncio.ensure_future(tts_worker())
    if not _admin_server_started:
        asyncio.ensure_future(_start_admin_server())


@bot.event
async def on_disconnect():
    print("[DEBUG] Bot disconnected from Discord")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"[ERROR] Command '{ctx.command}' raised: {error}")
    import traceback
    traceback.print_exception(type(error), error, error.__traceback__)
    await ctx.send(f"❌ Command error: `{error}`")


@bot.event
async def on_message(message):
    print(f"[DEBUG] Any message received: {message.author} - {message.content[:50]}")
    if message.author == bot.user:
        return

    gid = message.guild.id if message.guild else None
    tgt = get_guild_target(gid)
    tgt_name = tgt["name"]
    tgt_usernames = {u.lower() for u in tgt["usernames"]}

    # First message of the day bonus (per-guild, keyed by guild+date)
    today = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    eco = load_economy()
    fmtd_key = f"first_message_today_{gid}" if gid else "first_message_today"
    if eco.get(fmtd_key) != today:
        eco[fmtd_key] = today
        save_economy(eco)
        bonus = 30 if is_double_coin_day() else 15
        add_coins(message.author.id, bonus)
        await message.channel.send(f"🌅 {message.author.mention} sent the first message of the day! **+{bonus} coins!**")

    # Higher or lower game responses
    if message.author.id in highlow_games:
        game = highlow_games[message.author.id]
        if message.channel.id == game["channel_id"]:
            content = message.content.lower().strip()
            if content in ("higher", "lower"):
                new_num = random.randint(1, 100)
                old_num = game["number"]
                correct = (content == "higher" and new_num > old_num) or (content == "lower" and new_num < old_num)
                if new_num == old_num:
                    await message.channel.send(f"🎯 It's **{new_num}** — a tie! Keep going.")
                elif correct:
                    if content == "higher":
                        p_win = max(0.01, (100 - old_num) / 100)
                    else:
                        p_win = max(0.01, (old_num - 1) / 100)
                    game["multiplier"] = round(game["multiplier"] * (1 / p_win), 2)
                    game["number"] = new_num
                    await message.channel.send(f"✅ **{new_num}!** Correct! Multiplier: **{game['multiplier']}x** — type `higher`, `lower`, or `cashout`.")
                else:
                    bet = game["bet"]
                    del highlow_games[message.author.id]
                    await message.channel.send(f"❌ **{new_num}!** Wrong! You lost **{bet} coins**.")
            elif content == "cashout":
                winnings = round(game["bet"] * game["multiplier"])
                add_coins(message.author.id, winnings)
                del highlow_games[message.author.id]
                await message.channel.send(f"💰 Cashed out at **{game['multiplier']}x**! You won **{winnings} coins**!")

    # Guess the roast answer check
    if guessroast_active and not message.author.bot:
        if tgt_name.lower() in message.content.lower():
            globals()["guessroast_active"] = False
            add_coins(message.author.id, 30)
            await message.channel.send(f"✅ {message.author.mention} got it! It was **{tgt_name}** (obviously). **+30 coins!**")

    bot_member = message.guild.get_member(bot.user.id) if message.guild else None
    bot_mentioned = bot.user in message.mentions or (
        bot_member and any(role in message.role_mentions for role in bot_member.roles)
    )

    if message.author.name.lower() in tgt_usernames:
        add_coins(message.author.id, 1)
        eco = load_economy()
        if eco.get("slow_clap_pending", 0) > 0:
            eco["slow_clap_pending"] -= 1
            save_economy(eco)
            for _ in range(5):
                await message.add_reaction("👏")

    if message.author.name.lower() in tgt_usernames and len(message.content) > 10 and random.random() < 0.1:
        if await is_hot_take(message.content):
            flagged = await message.reply(
                f"🚨 **HOT TAKE ALERT** 🚨\n{tgt_name} is at it again. React to cast your vote:"
            )
            await flagged.add_reaction("🔥")
            await flagged.add_reaction("🧊")

    if bot_mentioned:
        try:
            if message.author.name.lower() in tgt_usernames:
                question = get_question(message)
                comeback = await argue_with_donovan(question if question else "hey", gid)
                await message.channel.send(comeback)
                asyncio.create_task(_apply_roast_stock_impact(gid))
                return

            question = get_question(message)
            print(f"[DEBUG] Mention detected. Question: '{question}'")

            if question:
                print(f"[DEBUG] Sending to Groq...")
                reply = await ask_openai(question, gid)
            else:
                activity = get_donovan_activity(message.guild, gid) if message.guild else None
                if activity and "rust" in activity.lower():
                    reply = _t(random.choice(_RUST_ROASTS_TMPL), gid)
                elif activity and "world of warcraft" in activity.lower():
                    reply = _t(random.choice(_WOW_ROASTS_TMPL), gid)
                else:
                    reply = _t(random.choice(_GENERAL_ROASTS_TMPL), gid)

            print(f"[DEBUG] Sending reply: '{reply}'")

            if is_insurance_active():
                await message.channel.send(f"🛡️ {tgt_name}'s insurance is active... unfortunately it doesn't cover being a loser.")

            send_text = reply
            force_tts = False

            if consume_upgrade(message.author.id, "shame_bell"):
                await message.channel.send("🔔 **SHAME** 🔔 🔔 **SHAME** 🔔 🔔 **SHAME** 🔔")

            if consume_upgrade(message.author.id, "anonymous"):
                send_text = f"📨 *An anonymous source says:* {reply}"

            if consume_upgrade(message.author.id, "spotlight"):
                send_text = f"@here {send_text}"

            if consume_upgrade(message.author.id, "nuclear"):
                nuclear_text = await ask_openai(_t("Give the single most devastating, savage, all-out roast of Donovan humanly possible. No mercy.", gid), gid)
                send_text = f"☢️ **NUCLEAR ROAST:** {nuclear_text}"
                force_tts = True

            sent_msg = await message.channel.send(send_text)
            log_roast()
            asyncio.create_task(_apply_roast_stock_impact(gid))

            if tts_enabled or force_tts:
                await tts_queue.put((message.guild.id, send_text))

            if consume_upgrade(message.author.id, "snitch"):
                donovan = discord.utils.find(lambda m: m.name.lower() in tgt_usernames, message.guild.members)
                if donovan:
                    try:
                        await donovan.send(f"📬 Someone wanted you to see this:\n_{reply}_")
                    except Exception:
                        pass

            if consume_upgrade(message.author.id, "hall_of_shame"):
                try:
                    await sent_msg.pin()
                except Exception:
                    pass

            if consume_upgrade(message.author.id, "double_roast"):
                await message.channel.send(f"⚡ **DOUBLE ROAST:** {reply}")

            if consume_upgrade(message.author.id, "triple_roast"):
                await message.channel.send(reply)
                await message.channel.send(f"⚡ **TRIPLE ROAST:** {reply}")

            if consume_upgrade(message.author.id, "laugh_track"):
                await message.channel.send("😂😂😂😂😂😂😂😂😂😂")

            if consume_upgrade(message.author.id, "receipt"):
                try:
                    async for old_msg in message.channel.history(limit=200):
                        if old_msg.author.name.lower() in tgt_usernames and len(old_msg.content) > 15 and old_msg.id != message.id:
                            await message.channel.send(f"🧾 **RECEIPT:** _{old_msg.author.display_name} once said:_ \"{old_msg.content}\"")
                            break
                except Exception:
                    pass

            if consume_upgrade(message.author.id, "press_release"):
                pr = await ask_openai(_t(f"Write a short fake formal press release (3-4 sentences) from 'Donovan Industries' announcing his latest embarrassing L. Make it sound official but absurd.", gid), gid)
                await message.channel.send(f"📰 **PRESS RELEASE:**\n{pr}")

            if consume_upgrade(message.author.id, "breaking_news"):
                news = await ask_openai(_t("Write a fake breaking news alert (1-2 sentences, all caps headline) about Donovan doing something embarrassing or pathetic. Include a fake news network name.", gid), gid)
                await message.channel.send(f"🚨 **BREAKING NEWS** 🚨\n{news}")

            if consume_upgrade(message.author.id, "intervention"):
                await message.channel.send(f"@everyone\n\n📢 **FORMAL SERVER INTERVENTION**\n\nThis server has come together to formally address {tgt_name}'s ongoing behaviour. We are concerned. We are united. And we are not impressed.\n\nPlease take this moment to reflect, {tgt_name}.")

            if consume_upgrade(message.author.id, "lore_drop"):
                lore = await ask_openai(_t("Write a short absurd fictional origin story (3-5 sentences) for why Donovan is the way he is. Make it ridiculous, creative, and savage.", gid), gid)
                await message.channel.send(f"📖 **{tgt_name.upper()} LORE DROP:**\n{lore}")

            if consume_upgrade(message.author.id, "mega_roast"):
                mega = await ask_openai(_t("Give the most savage, creative, brutal roast about Donovan you can. Go all out.", gid), gid)
                await message.channel.send(f"💥 **MEGA ROAST:** {mega}")

            if consume_upgrade(message.author.id, "scorched_earth"):
                for i in range(3):
                    roast = await ask_openai(_t(f"Give a unique savage roast about Donovan. Make it different each time. Roast #{i+1}.", gid), gid)
                    await message.channel.send(f"🔥 {roast}")

            if consume_upgrade(message.author.id, "exile"):
                donovan = discord.utils.find(lambda m: m.name.lower() in tgt_usernames, message.guild.members)
                if donovan:
                    try:
                        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)
                        await donovan.timeout(until, reason="Exile purchased by the people.")
                        await message.channel.send(f"⛔ {tgt_name} has been exiled for 60 seconds. Enjoy the peace.")
                    except Exception:
                        await message.channel.send("⛔ Exile failed — bot needs Moderate Members permission.")

            if consume_upgrade(message.author.id, "eulogy"):
                eulogy = await ask_openai(_t("Write a short dramatic funeral eulogy (3-5 sentences) for Donovan's dignity, as if it has already passed away. Be theatrical, savage, and treat it as a genuine loss to no one.", gid), gid)
                await message.channel.send(f"⚰️ **EULOGY FOR {tgt_name.upper()}'S DIGNITY:**\n{eulogy}")

            if consume_upgrade(message.author.id, "wanted_poster"):
                poster = await ask_openai(_t("Generate a fake FBI wanted poster description for Donovan. Include: name, aliases, known crimes against the server, last known location, reward amount, and a warning to approach with low expectations.", gid), gid)
                await message.channel.send(f"🪧 **WANTED** 🪧\n{poster}")

            if consume_upgrade(message.author.id, "therapy_session"):
                therapy = await ask_openai(_t("Roleplay as Donovan's therapist reading case notes aloud. Include diagnosis, presenting complaints, therapist observations, and prognosis. Make it clinical but devastatingly accurate.", gid), gid)
                await message.channel.send(f"🛋️ **THERAPY SESSION — CASE NOTES:**\n{therapy}")

            if consume_upgrade(message.author.id, "cease_and_desist"):
                legal = await ask_openai(_t("Draft a formal cease and desist letter demanding Donovan immediately stop being himself. Use legal language, cite specific offenses against the server, and threaten consequences. Keep it under 6 sentences.", gid), gid)
                await message.channel.send(f"⚖️ **CEASE & DESIST:**\n{legal}")

            if consume_upgrade(message.author.id, "linkedin_post"):
                linkedin = await ask_openai(_t("Write a cringe corporate LinkedIn post from Donovan's perspective. He is spinning his latest embarrassing L as a 'growth opportunity' and 'learning experience'. Include hashtags. Make it painfully on-brand for LinkedIn.", gid), gid)
                await message.channel.send(f"💼 **{tgt_name.upper()}'S LINKEDIN POST:**\n{linkedin}")

            if consume_upgrade(message.author.id, "documentary"):
                doc = await ask_openai(_t("Write a Ken Burns-style documentary narration (4-6 sentences) about a recent Donovan moment. Use a slow, grave, reflective tone. Include dramatic pauses indicated by '...' and treat the subject as historically significant.", gid), gid)
                await message.channel.send(f"🎬 **DOCUMENTARY NARRATION:**\n{doc}")

            if consume_upgrade(message.author.id, "legacy_mode"):
                legacy = await ask_openai(_t("Compile a devastating highlight reel recap of Donovan's greatest hits — his worst moments, biggest Ls, and most embarrassing behavior. Present it as a formal legacy retrospective. 5-7 sentences.", gid), gid)
                await message.channel.send(f"🏆 **{tgt_name.upper()}'S LEGACY — HIGHLIGHT REEL:**\n{legacy}")

            if consume_upgrade(message.author.id, "motivational_poster"):
                poster = await ask_openai(_t("Generate a fake motivational poster. Include a short inspirational quote falsely attributed to Donovan, followed by the most embarrassing context that makes the quote hilarious. Format it like a real motivational poster caption.", gid), gid)
                await message.channel.send(f"🖼️ **MOTIVATIONAL POSTER:**\n{poster}")

            if consume_upgrade(message.author.id, "autopsy_report"):
                autopsy = await ask_openai(_t("Write a clinical medical examiner's autopsy report on the cause of death of Donovan's credibility. Include time of death, cause of death, contributing factors, and examiner's notes. Keep it formal and devastating.", gid), gid)
                await message.channel.send(f"🔬 **AUTOPSY REPORT — {tgt_name.upper()}'S CREDIBILITY:**\n{autopsy}")

            if consume_upgrade(message.author.id, "wikipedia_page"):
                wiki = await ask_openai(_t("Write a fake Wikipedia-style article about Donovan. Include sections for Early Life, Known For, Controversies, and Legacy. Use encyclopedic tone. The controversies section should be the longest.", gid), gid)
                await message.channel.send(f"📖 **WIKIPEDIA: {tgt_name.upper()}**\n{wiki}")

            if consume_upgrade(message.author.id, "parole_hearing"):
                parole = await ask_openai(_t("Conduct a formal parole board hearing transcript for Donovan, who is seeking the right to be taken seriously again. Include board questions, his responses, deliberation, and the final verdict — which is always denied. 5-7 sentences.", gid), gid)
                await message.channel.send(f"🔨 **PAROLE HEARING — VERDICT: DENIED:**\n{parole}")

            if consume_upgrade(message.author.id, "dossier"):
                dossier = await ask_openai(_t("Present a full classified intelligence dossier on Donovan. Include: codename, threat level, known associates, behavioral patterns, noted weaknesses, and current status. Use spy/intelligence report formatting.", gid), gid)
                await message.channel.send(f"🗂️ **CLASSIFIED DOSSIER: {tgt_name.upper()}**\n{dossier}")

            if consume_upgrade(message.author.id, "state_of_the_union"):
                sotu = await ask_openai(_t("Deliver a presidential State of the Union address formally assessing the ongoing Donovan situation. Address the nation, assess the threat to morale, outline the administration's response plan, and close with hollow optimism. 5-7 sentences.", gid), gid)
                await message.channel.send(f"🎙️ **STATE OF THE UNION — THE {tgt_name.upper()} SITUATION:**\n{sotu}")

            coin_reward = 20 if is_double_coin_day() else 10
            if is_double_coin_day():
                await message.channel.send(f"💰 **2x Roast Coins** — Fuck {tgt_name} Friday/Weekend bonus active!")
            add_coins(message.author.id, coin_reward)
            update_stocks_on_roast(message.author.id)
            bounty_total = claim_bounties(message.author.id)
            if bounty_total > 0:
                add_coins(message.author.id, bounty_total)
                await message.channel.send(f"💰 {message.author.mention} collected **{bounty_total} Roast Coins** in active bounties!")

            count = load_count() + 1
            save_count(count)

            if count in MILESTONES:
                await message.channel.send(
                    f"Congratulations {tgt_name}, you've been insulted {count} times. Keep up the great work!"
                )

            eco = load_economy()
            milestones_given = eco.get("server_milestones_given", [])
            if count in SERVER_ROAST_MILESTONES and count not in milestones_given:
                milestones_given.append(count)
                eco["server_milestones_given"] = milestones_given
                save_economy(eco)
                bonus = SERVER_ROAST_MILESTONES[count]
                for member in message.guild.members:
                    if not member.bot:
                        add_coins(member.id, bonus)
                await message.channel.send(
                    f"🎉 **SERVER MILESTONE: {count} total roasts!**\n"
                    f"Everyone gets **+{bonus} Roast Coins** for their dedication to roasting {tgt_name}!"
                )
        except Exception as e:
            print(f"[ERROR] on_message crashed: {e}")
            await message.channel.send(_t(random.choice(_GENERAL_ROASTS_TMPL), gid))

    await bot.process_commands(message)


@bot.command(name="daily")
async def daily_checkin(ctx):
    eco = load_economy()
    uid = str(ctx.author.id)
    now_est = datetime.datetime.now(ZoneInfo("America/New_York"))
    today = now_est.date().isoformat()
    yesterday = (now_est.date() - datetime.timedelta(days=1)).isoformat()
    data = eco.setdefault("daily_checkins", {}).get(uid, {"last_checkin": None, "streak": 0})

    if data["last_checkin"] == today:
        await ctx.send("You've already checked in today. Come back tomorrow.")
        return

    streak = data["streak"] + 1 if data["last_checkin"] == yesterday else 1
    reward = get_daily_reward(streak)
    if is_double_coin_day():
        reward *= 2

    eco["daily_checkins"][uid] = {"last_checkin": today, "streak": streak}
    save_economy(eco)
    add_coins(ctx.author.id, reward)

    streak_msg = f" 🔥 **{streak} day streak!**" if streak > 1 else ""
    milestone_msg = " 🎉 **7-DAY BONUS — DOUBLED!**" if streak % 7 == 0 else ""
    double_msg = " 💰 **Weekend 2x active!**" if is_double_coin_day() else ""
    await ctx.send(f"✅ Daily check-in! **+{reward} coins**{streak_msg}{milestone_msg}{double_msg}")


@bot.command(name="flip")
async def coinflip(ctx, amount: int = None, side: str = None):
    if not amount or not side or side.lower() not in ("heads", "tails"):
        await ctx.send("Usage: `!flip <amount> heads` or `!flip <amount> tails`")
        return
    if amount <= 0:
        await ctx.send("Bet must be positive.")
        return
    if not spend_coins(ctx.author.id, amount):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return
    result = random.choice(["heads", "tails"])
    if result == side.lower():
        add_coins(ctx.author.id, amount * 2)
        await ctx.send(f"🪙 **{result.upper()}!** You won **{amount} coins!**")
    else:
        await ctx.send(f"🪙 **{result.upper()}!** You lost **{amount} coins**. Better luck next time.")


@bot.command(name="slots")
async def slots(ctx, amount: int = None):
    if not amount or amount <= 0:
        await ctx.send("Usage: `!slots <amount>`")
        return
    if not spend_coins(ctx.author.id, amount):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return
    reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    display = " | ".join(reels)
    key = tuple(reels)
    mult = SLOT_PAYOUTS.get(key, 0)
    if mult == 0:
        if reels[0] == reels[1] == reels[2]:
            mult = 10
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            mult = 2
    if mult > 0:
        winnings = amount * mult
        add_coins(ctx.author.id, winnings)
        try:
            await ctx.send(f"🎰 [ {display} ]\n**{mult}x PAYOUT!** You won **{winnings} coins!**")
        except Exception:
            add_coins(ctx.author.id, -winnings)
            add_coins(ctx.author.id, amount)
            raise
    else:
        try:
            await ctx.send(f"🎰 [ {display} ]\nNo match. You lost **{amount} coins**.")
        except Exception:
            add_coins(ctx.author.id, amount)
            raise


@bot.command(name="trivia")
async def trivia(ctx):
    global trivia_active
    if trivia_active:
        await ctx.send("A trivia question is already active!")
        return
    trivia_active = True
    try:
        recent_q = trivia_recent.get(ctx.channel.id, [])
        recent_cats = trivia_recent_cats.get(ctx.channel.id, [])
        question, answer, category = await generate_trivia_question(
            used_topics=recent_q or None,
            used_categories=recent_cats or None,
        )
        trivia_recent[ctx.channel.id] = (recent_q + [question])[-8:]
        trivia_recent_cats[ctx.channel.id] = (recent_cats + [category])[-4:]
        await ctx.send(
            f"🧠 **TRIVIA** _{category.title()}_ — First to answer wins **50 coins!**\n\n"
            f"_{question}_\n\nYou have 30 seconds!"
        )
        def check(m):
            return m.channel == ctx.channel and not m.author.bot and not m.content.startswith("!") and len(m.content.strip()) > 1

        winner = None
        deadline = asyncio.get_running_loop().time() + 30
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                msg = await bot.wait_for("message", check=check, timeout=remaining)
                user_answer = msg.content.strip()
                if _trivia_quick_match(answer, user_answer):
                    correct = True
                elif len(user_answer.split()) > 5:
                    correct = answer.lower() in user_answer.lower()
                else:
                    correct = await judge_trivia_answer(question, answer, user_answer)
                if correct:
                    winner = msg
                    break
            except asyncio.TimeoutError:
                break

        if winner:
            add_coins(winner.author.id, 50)
            record_trivia_win(winner.author.id)
            await ctx.send(f"✅ {winner.author.mention} got it! The answer was **{answer.title()}**. **+50 coins!**")
        else:
            await ctx.send(f"⏱️ Time's up! The answer was **{answer.title()}**.")
    finally:
        trivia_active = False


@bot.command(name="guessroast")
async def guess_roast(ctx):
    global guessroast_active
    if guessroast_active:
        await ctx.send("A guess the roast game is already active!")
        return
    gid = ctx.guild.id if ctx.guild else None
    tn = get_guild_target(gid)["name"]
    guessroast_active = True
    tmpl = random.choice(_GENERAL_ROASTS_TMPL + _RUST_ROASTS_TMPL + _WOW_ROASTS_TMPL)
    roast = _t(tmpl, gid)
    blanked = roast.replace(tn, "**[???]**").replace(tn.lower(), "**[???]**")
    await ctx.send(f"🎭 **GUESS WHO THIS ROAST IS AIMED AT:**\n\n_{blanked}_\n\nFirst to type the name wins **30 coins!** (20 seconds)")
    await asyncio.sleep(20)
    if guessroast_active:
        guessroast_active = False
        await ctx.send(f"⏱️ Time's up! It was **{tn}**. Obviously.")


@bot.command(name="highlow")
async def highlow(ctx, amount: int = None):
    if not amount or amount <= 0:
        await ctx.send("Usage: `!highlow <amount>`")
        return
    if ctx.author.id in highlow_games:
        await ctx.send("You already have a game in progress! Type `higher`, `lower`, or `cashout`.")
        return
    if not spend_coins(ctx.author.id, amount):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return
    number = random.randint(1, 100)
    highlow_games[ctx.author.id] = {"number": number, "bet": amount, "multiplier": 1.0, "channel_id": ctx.channel.id}
    await ctx.send(
        f"🎯 The number is **{number}**.\n"
        f"Will the next be `higher` or `lower`? Type your answer!\n"
        f"Type `cashout` to take your winnings at any time."
    )


@bot.command(name="blackjack")
async def blackjack(ctx, amount: int = 10):
    if amount <= 0:
        amount = 10

    channel_id = ctx.channel.id

    # Join an existing waiting game
    if channel_id in blackjack_games and blackjack_games[channel_id]["state"] == "waiting":
        game = blackjack_games[channel_id]
        if any(p["user_id"] == ctx.author.id for p in game["players"]):
            await ctx.send("You're already at this table.")
            return
        if not spend_coins(ctx.author.id, amount):
            bal = load_economy()["balances"].get(str(ctx.author.id), 0)
            await ctx.send(f"Not enough coins. You have **{bal}**.")
            return
        game["players"].append({
            "user_id": ctx.author.id, "name": ctx.author.display_name,
            "bet": amount, "hand": [], "stood": False, "busted": False,
        })
        await ctx.send(f"✅ **{ctx.author.display_name}** joined for **{amount} coins**!")
        return

    # Block if a round is mid-game
    if channel_id in blackjack_games:
        await ctx.send("A blackjack game is already running. Wait for the next round.")
        return

    if not spend_coins(ctx.author.id, amount):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return

    blackjack_games[channel_id] = {
        "state": "waiting",
        "players": [{"user_id": ctx.author.id, "name": ctx.author.display_name,
                     "bet": amount, "hand": [], "stood": False, "busted": False}],
        "dealer_hand": [],
        "deck": [],
    }

    await ctx.send(
        f"🃏 **BLACKJACK** — **{ctx.author.display_name}** opened a table for **{amount} coins**!\n"
        f"Others: `!blackjack <bet>` to join. Starting in **20 seconds**..."
    )
    await asyncio.sleep(20)

    if channel_id not in blackjack_games:
        return

    game = blackjack_games[channel_id]
    game["state"] = "playing"

    deck = new_deck()
    game["deck"] = deck
    for p in game["players"]:
        p["hand"] = [deck.pop(), deck.pop()]
    game["dealer_hand"] = [deck.pop(), deck.pop()]

    # Show initial state
    lines = ["🃏 **BLACKJACK — CARDS DEALT**\n",
             f"**Dealer:** {hand_str(game['dealer_hand'], hide_second=True)}\n"]
    for p in game["players"]:
        val = hand_value(p["hand"])
        bj = " — 🃏 **BLACKJACK!**" if is_blackjack(p["hand"]) else f" ({val})"
        lines.append(f"**{p['name']}:** {hand_str(p['hand'])}{bj}")
    await ctx.send("\n".join(lines))

    # Player turns
    for player in game["players"]:
        if is_blackjack(player["hand"]):
            player["stood"] = True
            await ctx.send(f"🃏 **{player['name']}** has Blackjack — auto-stand!")
            continue

        await ctx.send(f"➡️ **{player['name']}'s turn** — `hit` or `stand` (30s)")

        def check(m, pid=player["user_id"]):
            return m.author.id == pid and m.channel.id == channel_id and m.content.lower() in ("hit", "stand")

        while not player["stood"] and not player["busted"]:
            try:
                msg = await bot.wait_for("message", check=check, timeout=30)
                if msg.content.lower() == "stand":
                    player["stood"] = True
                    await ctx.send(f"✋ **{player['name']}** stands at **{hand_value(player['hand'])}**.")
                else:
                    card = game["deck"].pop()
                    player["hand"].append(card)
                    val = hand_value(player["hand"])
                    if val > 21:
                        player["busted"] = True
                        await ctx.send(f"💥 **{player['name']}** hits {card_str(card)} → **{val} — BUST!**")
                    elif val == 21:
                        player["stood"] = True
                        await ctx.send(f"🎯 **{player['name']}** hits {card_str(card)} → **21!** Auto-stand.")
                    else:
                        await ctx.send(f"🃏 **{player['name']}** hits {card_str(card)} → **{val}**. Hit or stand?")
            except asyncio.TimeoutError:
                player["stood"] = True
                await ctx.send(f"⏱️ **{player['name']}** timed out — auto-stand at **{hand_value(player['hand'])}**.")

    # Dealer plays (only if someone didn't bust)
    dealer_val = hand_value(game["dealer_hand"])
    await ctx.send(f"🤖 **Dealer reveals:** {hand_str(game['dealer_hand'])} ({dealer_val})")

    active = [p for p in game["players"] if not p["busted"]]
    if active:
        while dealer_val < 17:
            card = game["deck"].pop()
            game["dealer_hand"].append(card)
            dealer_val = hand_value(game["dealer_hand"])
            await asyncio.sleep(1)
            await ctx.send(f"🤖 Dealer hits {card_str(card)} → **{dealer_val}**")

    dealer_bust = dealer_val > 21
    if dealer_bust:
        await ctx.send(f"💥 **Dealer busts at {dealer_val}!**")

    # Results
    result_lines = ["🃏 **BLACKJACK — RESULTS**\n"]
    for p in game["players"]:
        pval = hand_value(p["hand"])
        if p["busted"]:
            result_lines.append(f"❌ **{p['name']}** — Bust — lost **{p['bet']} coins**")
        elif is_blackjack(p["hand"]) and not is_blackjack(game["dealer_hand"]):
            payout = int(p["bet"] * 2.5)
            add_coins(p["user_id"], payout)
            result_lines.append(f"🃏 **{p['name']}** — Blackjack! — won **{payout - p['bet']} coins**")
        elif is_blackjack(p["hand"]) and is_blackjack(game["dealer_hand"]):
            add_coins(p["user_id"], p["bet"])
            result_lines.append(f"🤝 **{p['name']}** — Blackjack push — bet returned")
        elif dealer_bust or pval > dealer_val:
            add_coins(p["user_id"], p["bet"] * 2)
            result_lines.append(f"✅ **{p['name']}** — {pval} vs {dealer_val} — won **{p['bet']} coins**")
        elif pval == dealer_val:
            add_coins(p["user_id"], p["bet"])
            result_lines.append(f"🤝 **{p['name']}** — {pval} push — bet returned")
        else:
            result_lines.append(f"❌ **{p['name']}** — {pval} vs {dealer_val} — lost **{p['bet']} coins**")

    del blackjack_games[channel_id]
    await ctx.send("\n".join(result_lines))


@bot.command(name="dice")
async def dice_duel(ctx, opponent: discord.Member = None, amount: int = None):
    if not opponent or not amount or amount <= 0:
        await ctx.send("Usage: `!dice @user <amount>`")
        return
    if opponent.id == ctx.author.id:
        await ctx.send("You can't challenge yourself.")
        return
    if opponent.bot:
        await ctx.send("You can't challenge a bot. Coward.")
        return

    if not spend_coins(ctx.author.id, amount):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return

    msg = await ctx.send(
        f"🎲 **DICE DUEL**\n\n"
        f"**{ctx.author.display_name}** challenges **{opponent.mention}** for **{amount} coins** a side!\n\n"
        f"React ✅ to accept or ❌ to decline. (30 seconds)"
    )
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return user.id == opponent.id and str(reaction.emoji) in ("✅", "❌") and reaction.message.id == msg.id

    try:
        reaction, _ = await bot.wait_for("reaction_add", check=check, timeout=30)
    except asyncio.TimeoutError:
        add_coins(ctx.author.id, amount)
        await ctx.send(f"⏱️ **{opponent.display_name}** never showed up. {ctx.author.mention} refunded.")
        return

    if str(reaction.emoji) == "❌":
        add_coins(ctx.author.id, amount)
        await ctx.send(f"❌ **{opponent.display_name}** backed out. {ctx.author.mention} refunded.")
        return

    if not spend_coins(opponent.id, amount):
        add_coins(ctx.author.id, amount)
        bal = load_economy()["balances"].get(str(opponent.id), 0)
        await ctx.send(f"**{opponent.display_name}** accepted but only has **{bal} coins**. Challenge cancelled, {ctx.author.mention} refunded.")
        return

    pot = amount * 2
    await ctx.send(f"✅ **{opponent.display_name}** accepted! Pot: **{pot} coins**. Rolling...")

    while True:
        await asyncio.sleep(1)
        a_total = random.randint(1, 100)
        b_total = random.randint(1, 100)

        await ctx.send(
            f"🎲 **{ctx.author.display_name}:** **{a_total}**\n"
            f"🎲 **{opponent.display_name}:** **{b_total}**"
        )

        if a_total > b_total:
            add_coins(ctx.author.id, pot)
            await ctx.send(f"🏆 **{ctx.author.display_name}** wins and takes **{pot} coins!**")
            break
        elif b_total > a_total:
            add_coins(opponent.id, pot)
            await ctx.send(f"🏆 **{opponent.display_name}** wins and takes **{pot} coins!**")
            break
        else:
            await ctx.send("🤝 **TIE — rolling again!**")


@bot.command(name="sportstrivia")
async def sports_trivia(ctx):
    channel_id = ctx.channel.id
    if sports_trivia_active.get(channel_id):
        await ctx.send("A sports trivia game is already running in this channel!")
        return

    sports_trivia_active[channel_id] = True
    scores = {}

    try:
        await ctx.send("🏈🏒🏀 **SPORTS TRIVIA** — 5 rounds, **20 coins** per correct answer! First to answer wins each round!")
        await asyncio.sleep(2)

        sport_rotation = ["NHL", "NFL", "NBA", "NHL", "NFL"]
        used_topics = []
        for round_num, sport in enumerate(sport_rotation, 1):
            question, answer = await generate_sports_question(sport, used_topics)
            used_topics.append(f"{answer} (from: {question[:60]})")

            await ctx.send(f"**Round {round_num}/5**\n\n_{question}_\n\n⏱️ 30 seconds!")

            def check(m):
                return m.channel.id == channel_id and not m.author.bot and not m.content.startswith("!") and len(m.content.strip()) > 1

            winner = None
            deadline = asyncio.get_running_loop().time() + 30

            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    msg = await bot.wait_for("message", check=check, timeout=remaining)
                    user_answer = msg.content.strip()
                    # Skip slow AI judge for obvious chat messages to avoid blocking the loop
                    if len(user_answer.split()) > 5:
                        correct = answer.lower() in user_answer.lower()
                    else:
                        correct = await judge_sports_answer(question, answer, user_answer)
                    if correct:
                        winner = msg.author
                        break
                except asyncio.TimeoutError:
                    break

            if winner:
                add_coins(winner.id, 20)
                record_trivia_win(winner.id)
                scores[winner.id] = scores.get(winner.id, 0) + 20
                await ctx.send(f"✅ **{winner.display_name}** got it! The answer was **{answer}** — **+20 coins!**")
            else:
                await ctx.send(f"⏱️ Time's up! The answer was **{answer}**.")

            if round_num < 5:
                await asyncio.sleep(3)

        if scores:
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            board = "\n".join(
                f"{ctx.guild.get_member(uid).display_name if ctx.guild.get_member(uid) else 'Unknown'}: {c} coins"
                for uid, c in top
            )
            mvp = ctx.guild.get_member(top[0][0])
            mvp_name = mvp.display_name if mvp else "Unknown"
            await ctx.send(f"🏆 **SPORTS TRIVIA OVER!**\n\n{board}\n\nMVP: **{mvp_name}** with **{top[0][1]} coins** earned!")
        else:
            await ctx.send("🏆 **SPORTS TRIVIA OVER!** Nobody scored a single point. Embarrassing.")

    except Exception as e:
        print(f"[ERROR] Sports trivia crashed: {e}")
        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]
        await ctx.send(f"Sports trivia crashed. Blame {tn}.")
    finally:
        sports_trivia_active[channel_id] = False


@bot.command(name="lottery")
async def lottery(ctx, amount: int = None):
    if not amount or amount < 10:
        eco = load_economy()
        pot = eco.get("lottery_pot", 500)
        tickets = eco.get("lottery_tickets", {}).get(str(ctx.author.id), 0)
        await ctx.send(f"🎟️ **Weekly Lottery** — 10 coins per ticket\nCurrent pot: **{pot} coins** | Your tickets: **{tickets}**\nUsage: `!lottery <amount>` (must be multiple of 10)")
        return
    tickets = amount // 10
    cost = tickets * 10
    if not spend_coins(ctx.author.id, cost):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return
    eco = load_economy()
    uid = str(ctx.author.id)
    eco.setdefault("lottery_tickets", {})[uid] = eco.get("lottery_tickets", {}).get(uid, 0) + tickets
    eco["lottery_pot"] = eco.get("lottery_pot", 0) + cost
    save_economy(eco)
    await ctx.send(f"🎟️ Bought **{tickets} ticket(s)** for **{cost} coins**! Pot is now **{eco['lottery_pot']} coins**. Drawing Sunday at 9 PM EST!")


def _sparkline(prices):
    """Convert a list of prices into an 8-level unicode sparkline string."""
    if len(prices) < 2:
        return "—"
    lo, hi = min(prices), max(prices)
    blocks = "▁▂▃▄▅▆▇█"
    if hi == lo:
        return blocks[3] * len(prices)
    return "".join(blocks[round((p - lo) / (hi - lo) * 7)] for p in prices)


@bot.command(name="stocktrend")
async def stock_trend(ctx, ticker: str = None):
    """Show sparkline chart and trend indicators for a stock. Usage: !stocktrend <TICKER>"""
    eco = load_economy()
    init_market(eco)
    gid = ctx.guild.id if ctx.guild else None

    all_stocks = {**MARKET_STOCKS, **_get_target_stock_info(eco)}

    if not ticker:
        await ctx.send("Usage: `!stocktrend <TICKER>` — e.g. `!stocktrend DONOVAN`")
        return

    ticker = ticker.lstrip("$").upper()
    if ticker not in eco["market"]:
        await ctx.send(f"Unknown ticker **${ticker}**. Check `!stockmarket` for valid tickers.")
        return

    mdata = eco["market"][ticker]
    info = all_stocks.get(ticker, _TARGET_STOCK_DEFAULTS)
    history = mdata.get("price_history", [mdata["price"]])
    current = mdata["price"]
    base = mdata.get("dynamic_base", info.get("base_price", _TARGET_STOCK_DEFAULTS["base_price"]))
    static_base = info.get("base_price", _TARGET_STOCK_DEFAULTS["base_price"])

    # Sparkline (last 24 ticks = 4 hours, trimmed to fit Discord)
    spark_prices = history[-24:]
    spark = _sparkline(spark_prices)

    # Multi-window % changes
    def pct_change(window):
        if len(history) < window + 1:
            return None
        old = history[-(window + 1)]
        return round((current - old) / old * 100, 2) if old else None

    c30m  = pct_change(3)    # 30 min  (3 ticks)
    c2h   = pct_change(12)   # 2 hours (12 ticks)
    c8h   = pct_change(48)   # 8 hours (48 ticks)

    def fmt_pct(val):
        if val is None:
            return "n/a"
        arrow = "📈" if val > 0 else ("📉" if val < 0 else "➡️")
        return f"{arrow} {val:+.2f}%"

    # Momentum: fraction of recent ticks that were up-moves
    diffs = [history[i] - history[i - 1] for i in range(1, len(history))]
    recent_diffs = diffs[-12:] if len(diffs) >= 12 else diffs
    if recent_diffs:
        up_frac = sum(1 for d in recent_diffs if d > 0) / len(recent_diffs)
        if up_frac >= 0.65:
            momentum = "🟢 Bullish"
        elif up_frac <= 0.35:
            momentum = "🔴 Bearish"
        else:
            momentum = "🟡 Neutral"
    else:
        momentum = "🟡 Neutral"

    # High / low over available history
    hi = max(history)
    lo = min(history)

    # Distance from dynamic base (and drift from original)
    from_base = round((current - base) / base * 100, 1)
    base_drift = round((base - static_base) / static_base * 100, 1)
    drift_str = f"  *(drifted {base_drift:+.1f}% from original ${static_base:.2f})*" if abs(base_drift) >= 0.1 else ""
    base_str = f"{from_base:+.1f}% from base (${base:.2f}){drift_str}"

    # Short interest
    shorted = sum(
        pos[ticker]["shares"]
        for pos in eco.get("short_positions", {}).values()
        if ticker in pos
    )
    outstanding = info.get("shares_outstanding", _TARGET_STOCK_DEFAULTS["shares_outstanding"])
    si_pct = round(shorted / outstanding * 100, 1) if outstanding else 0
    si_str = f"  🔥 Short Interest: {si_pct}%" if si_pct > 0 else ""

    ticks_shown = len(spark_prices)
    lines = [
        f"📈 **${ticker} Trend** — ${current:.2f}  |  {base_str}",
        f"```{spark}```",
        f"*last {ticks_shown} ticks (~{ticks_shown * 10} min)*",
        f"",
        f"**Performance**",
        f"  30 min:  {fmt_pct(c30m)}",
        f"  2 hr:    {fmt_pct(c2h)}",
        f"  8 hr:    {fmt_pct(c8h)}",
        f"",
        f"**Range (session history)**",
        f"  High: ${hi:.2f}   Low: ${lo:.2f}",
        f"",
        f"**All-Time High:** ${mdata.get('all_time_high', hi):.2f}  |  **All-Time Low:** ${mdata.get('all_time_low', lo):.2f}",
        f"",
        f"**Momentum:** {momentum}{si_str}",
    ]
    # Dividend yield note
    all_stocks = {**MARKET_STOCKS, **_get_target_stock_info(eco)}
    div_rate = all_stocks.get(ticker, {}).get("dividend_rate")
    if div_rate:
        weekly_per_share = round(current * div_rate, 2)
        lines.append(f"💰 **Dividend:** {weekly_per_share:.2f} coins/share/week ({div_rate*100:.1f}% weekly yield)")
    await ctx.send("\n".join(lines))


@bot.command(name="stockmarket")
async def stock_market(ctx):
    eco = load_economy()
    init_market(eco)
    save_economy(eco)
    gid = ctx.guild.id if ctx.guild else None
    tgt_ticker = get_guild_target(gid)["ticker"]

    lines = [f"📊 **{tgt_ticker} STOCK EXCHANGE**\n"]

    target_stocks = _get_target_stock_info(eco)
    delisted = _get_delisted_stocks(eco)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    all_display_stocks = {**MARKET_STOCKS, **target_stocks}

    for ticker, info in all_display_stocks.items():
        if ticker not in eco["market"]:
            continue
        mdata = eco["market"][ticker]
        price = mdata["price"]
        prev = mdata.get("prev_price", info.get("base_price", price))
        change = round(price - prev, 2)
        pct = round((change / prev * 100) if prev else 0, 1)
        trend = "📉" if change < 0 else "📈"
        vol = mdata.get("volume_today", 0)
        history = mdata.get("price_history", [price])
        spark = _sparkline(history[-12:])  # last 2 hours inline
        shorted = sum(
            pos[ticker]["shares"]
            for pos in eco.get("short_positions", {}).values()
            if ticker in pos
        )
        outstanding = info.get("shares_outstanding", _TARGET_STOCK_DEFAULTS["shares_outstanding"])
        si_pct = round(shorted / outstanding * 100, 1) if outstanding else 0
        si_str = f"  🔥 SI: {si_pct}%" if si_pct > 0 else ""

        # 2-hour % change (12 ticks back)
        if len(history) >= 13:
            old_2h = history[-13]
            pct_2h = round((price - old_2h) / old_2h * 100, 1) if old_2h else None
        else:
            pct_2h = None
        pct_2h_str = f"  2hr: {pct_2h:+.1f}%" if pct_2h is not None else ""

        if ticker in delisted:
            hrs_left = max(0, round((delisted[ticker] - now_dt).total_seconds() / 3600, 1))
            label = "🪦 "
            delist_str = f"  *(delisted — {hrs_left}h to sell)*"
        else:
            label = ""
            delist_str = ""

        lines.append(
            f"{label}**${ticker}** — ${price:.2f}  {trend} {change:+.2f} ({pct:+.1f}%){pct_2h_str}  "
            f"Vol: {vol}{si_str}{delist_str}"
        )

    # Top portfolio holders
    all_uids = set(eco.get("portfolios", {}).keys()) | set(eco.get("short_positions", {}).keys())
    if all_uids:
        ranked = sorted(all_uids, key=lambda u: get_portfolio_value(eco, u), reverse=True)[:5]
        lines.append("\n**Top Portfolio Values:**")
        for uid in ranked:
            member = ctx.guild.get_member(int(uid))
            name = member.display_name if member else "Unknown"
            val = get_portfolio_value(eco, uid)
            lines.append(f"  **{name}** — {val:.0f} coins")

    # Sentiment indicator
    s_score, s_label, s_emoji = _market_sentiment(eco)
    bar_filled = round(s_score / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    lines.append(f"\n**Market Sentiment:** {s_emoji} **{s_label}** `{bar}` {s_score}/100")

    # Dividend-paying stocks note
    div_stocks = [t for t, i in MARKET_STOCKS.items() if i.get("dividend_rate")]
    if div_stocks:
        lines.append(f"💰 Dividend stocks (paid every Sunday): {', '.join(f'${t}' for t in div_stocks)}")

    lines.append("\n`!buystock` `!sellstock` `!short` `!cover` `!limitorder` `!portfolio` `!orders` `!stocktrend <TICKER>`")
    await ctx.send("\n".join(lines))


@bot.command(name="Commands", aliases=["commands"])
async def commands_list(ctx):
    gid = ctx.guild.id if ctx.guild else None
    tgt = get_guild_target(gid)
    tn = tgt["name"]
    ticker = tgt["ticker"]
    await ctx.send(
        f"**📋 {tn} Hate Bot — Commands (1/3)**\n\n"
        f"**`@{tn} Hate Bot`** — Roasts {tn}. Ask it a question for a smart response.\n"
        f"**`!Trial <reason>`** — Puts {tn} on trial. Server votes guilty/not guilty for 60 seconds.\n"
        f"**`!Guesswhosaidit`** — 3 round game. Guess if the quote was {tn} or someone else.\n"
        f"**`!TTS on/off`** — Toggles voice channel roasts. ({tn} cannot use this.)\n\n"
        "**💰 Economy**\n"
        "**`!balance`** — Check your Roast Coin balance.\n"
        "**`!leaderboard`** — Top 5 coin holders.\n"
        "**`!shop`** — View upgrades for sale.\n"
        "**`!buy <item>`** — Purchase an upgrade (goes to inventory).\n"
        "**`!inventory`** — View your owned and armed items.\n"
        "**`!use <item>`** — Arm an item from your inventory (fires on next @mention).\n"
        "**`!bounty <amount> <description>`** — Post a bounty paid to whoever triggers the next roast.\n"
        "**`!bounties`** — View active bounties.\n"
        f"**`!insurance <minutes>`** — {tn} only: buy temporary (useless) protection.\n"
        "**`!give @user <amount>`** — Transfer coins to another member.\n"
        "**`!blackmarket`** — View peer-to-peer upgrade listings.\n"
        "**`!listitem <item> <price>`** — List an owned upgrade for sale.\n"
        "**`!buyitem <id>`** — Buy an upgrade from the black market.\n"
        "**`!settarget <name> <username> [ticker]`** — (Admin) Set who the bot hates on this server.\n"
        "**`!setup`** — (Admin) Register this channel as the roast channel for this server."
    )
    await ctx.send(
        f"**📋 {tn} Hate Bot — Commands (2/3)**\n\n"
        "**🎮 Minigames & Rewards**\n"
        "**`!daily`** — 25 coin daily check-in. Streak builds a multiplier, doubles at 7 days.\n"
        "**`!flip <amount> heads/tails`** — Coinflip gamble.\n"
        "**`!slots <amount>`** — Slot machine. Match symbols for big payouts.\n"
        "**`!trivia`** — First to answer wins 50 coins.\n"
        "**`!sportstrivia`** — 5 rounds of AI-generated NHL/NFL/NBA trivia. 20 coins per correct answer.\n"
        "**`!guessroast`** — Roast posted with name blanked, guess who it's about.\n"
        "**`!dice @user <amount>`** — Challenge someone to a dice duel. Roll 1-100, highest wins the pot. Ties re-roll.\n"
        "**`!highlow <amount>`** — Guess higher or lower, chain correct answers for a multiplier.\n"
        "**`!blackjack [bet]`** — Multiplayer blackjack vs the dealer. Bet defaults to 10 coins. Others can join before the round starts.\n"
        "**`!lottery <amount>`** — Buy lottery tickets (10 coins each). Drawn every Sunday at 9 PM EST."
    )
    await ctx.send(
        f"**📋 {tn} Hate Bot — Commands (3/3)**\n\n"
        "**📈 Stock Market**\n"
        f"**`!stockmarket`** — View current prices for all stocks (${ticker}, $RUST, $BIGMAC, $TORTA, $TRUMP, $COCAINE).\n"
        "**`!stocktrend <TICKER>`** — Sparkline chart, 30min/2hr/8hr performance, momentum indicator, and range for any stock.\n"
        "**`!buystock <TICKER> <shares>`** — Buy shares at market price.\n"
        "**`!sellstock <TICKER> <shares>`** — Sell shares you own.\n"
        "**`!short <TICKER> <shares>`** — Open a short position (profit if price drops).\n"
        "**`!cover <TICKER> <shares>`** — Close a short position.\n"
        "**`!portfolio [@user]`** — View your (or someone else's) open positions and P&L.\n"
        "**`!limitorder <buy|sell|short|cover> <TICKER> <shares> <price>`** — Place a limit order that fills automatically.\n"
        "**`!orders`** — View your pending limit orders.\n"
        "**`!cancellimit <id>`** — Cancel a pending limit order.\n"
        "**`!futures <long|short> <TICKER> <contracts>`** — Open a leveraged 7-day futures contract (20% margin).\n"
        "**`!closefutures <id>`** — Close a futures contract early.\n"
        "**`!myfutures`** — View your open futures contracts.\n"
        "**`!buyoption <call|put> <TICKER> <contracts> <strike> [days]`** — Buy a call or put option.\n"
        "**`!exercise <id>`** — Exercise an option if it's in the money.\n"
        "**`!myoptions`** — View your open options.\n\n"
        "**`!commands`** — Shows this list."
    )


@bot.command(name="balance")
async def balance(ctx, member: discord.Member = None):
    target = member or ctx.author
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    uid = str(target.id)
    bal = eco["balances"].get(uid, 0)
    portfolio = get_portfolio_value(eco, uid)

    # Unrealized futures P&L
    futures_pnl = 0.0
    for pos in eco["futures"].get(uid, []):
        price = eco["market"][pos["ticker"]]["price"]
        if pos["direction"] == "long":
            futures_pnl += (price - pos["entry_price"]) * pos["contracts"]
        else:
            futures_pnl += (pos["entry_price"] - price) * pos["contracts"]

    # Unrealized options value
    options_value = 0.0
    for opt in eco["options"].get(uid, []):
        if opt.get("exercised"):
            continue
        price = eco["market"][opt["ticker"]]["price"]
        if opt["option_type"] == "call":
            options_value += max(0, (price - opt["strike"]) * opt["contracts"])
        else:
            options_value += max(0, (opt["strike"] - price) * opt["contracts"])

    total = round(bal + portfolio + futures_pnl + options_value, 2)
    lines = [f"💰 **{target.display_name}**",
             f"Cash: **{bal} coins**"]
    if portfolio:
        lines.append(f"Stocks/Shorts: **{portfolio:.0f} coins**")
    if futures_pnl:
        pnl_str = f"+{futures_pnl:.0f}" if futures_pnl >= 0 else f"{futures_pnl:.0f}"
        lines.append(f"Futures P&L: **{pnl_str} coins**")
    if options_value:
        lines.append(f"Options Value: **{options_value:.0f} coins**")
    lines.append(f"**Net Worth: {total:.0f} coins**")
    await ctx.send("\n".join(lines))


@bot.command(name="leaderboard")
async def leaderboard(ctx):
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    if not eco["balances"]:
        await ctx.send("Nobody has earned any Roast Coins yet.")
        return

    def net_worth(uid):
        uid = str(uid)
        cash = eco["balances"].get(uid, 0)
        portfolio = get_portfolio_value(eco, uid)
        futures_pnl = sum(
            (p["entry_price"] - eco["market"][p["ticker"]]["price"]) * p["contracts"]
            if p["direction"] == "short"
            else (eco["market"][p["ticker"]]["price"] - p["entry_price"]) * p["contracts"]
            for p in eco["futures"].get(uid, [])
            if p["ticker"] in eco["market"]
        )
        options_val = sum(
            max(0, (eco["market"][o["ticker"]]["price"] - o["strike"]) * o["contracts"])
            if o["option_type"] == "call"
            else max(0, (o["strike"] - eco["market"][o["ticker"]]["price"]) * o["contracts"])
            for o in eco["options"].get(uid, [])
            if not o.get("exercised") and o["ticker"] in eco["market"]
        )
        return round(cash + portfolio + futures_pnl + options_val, 2)

    top = sorted(eco["balances"].keys(), key=net_worth, reverse=True)[:5]
    lines = []
    for i, uid in enumerate(top, 1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else "Unknown"
        cash = round(eco["balances"].get(str(uid), 0))
        total = net_worth(uid)
        portfolio = round(total - cash)
        if portfolio:
            lines.append(f"{i}. **{name}** — {total:.0f} coins net worth _(cash: {cash} + investments: {portfolio})_")
        else:
            lines.append(f"{i}. **{name}** — {total:.0f} coins")
    await ctx.send("💰 **Roast Coin Leaderboard** _(ranked by net worth)_\n" + "\n".join(lines))


@bot.command(name="trivialeaderboard")
async def trivia_leaderboard(ctx):
    eco = load_economy()
    wins = eco.get("trivia_wins", {})
    if not wins:
        await ctx.send("Nobody has won a trivia question yet.")
        return
    top = sorted(wins.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = []
    for i, (uid, count) in enumerate(top, 1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else "Unknown"
        lines.append(f"{i}. **{name}** — {count} win{'s' if count != 1 else ''}")
    await ctx.send("🧠 **Trivia Leaderboard** _(all-time wins across !trivia and !sportstrivia)_\n" + "\n".join(lines))


@bot.command(name="shop")
async def shop(ctx):
    gid = ctx.guild.id if ctx.guild else None
    rotation, expires = get_shop_rotation()
    now = datetime.datetime.now(datetime.timezone.utc)
    seconds_left = int((expires - now).total_seconds())
    hours_left = seconds_left // 3600
    minutes_left = (seconds_left % 3600) // 60
    lines = []
    for k in rotation:
        if k not in SHOP_ITEMS:
            continue
        desc_tmpl = _SHOP_ITEMS_TMPL.get(k, {}).get("description", SHOP_ITEMS[k]["description"])
        desc = _t(desc_tmpl, gid)
        lines.append(f"**{SHOP_ITEMS[k]['name']}** (`{k}`) — {SHOP_ITEMS[k]['cost']} coins\n_{desc}_")
    await ctx.send(
        f"🛒 **Roast Shop** — Today's Rotation _(refreshes in {hours_left}h {minutes_left}m)_\n\n"
        + "\n\n".join(lines)
        + "\n\nUse `!buy <item>` to purchase."
    )


@bot.command(name="resetshop")
@commands.has_permissions(administrator=True)
async def resetshop(ctx):
    eco = load_economy()
    eco["shop_rotation"] = None
    eco["shop_rotation_expires"] = None
    save_economy(eco)
    rotation, expires = get_shop_rotation()
    now = datetime.datetime.now(datetime.timezone.utc)
    seconds_left = int((expires - now).total_seconds())
    hours_left = seconds_left // 3600
    minutes_left = (seconds_left % 3600) // 60
    lines = [f"**{SHOP_ITEMS[k]['name']}** (`{k}`) — {SHOP_ITEMS[k]['cost']} coins"
             for k in rotation if k in SHOP_ITEMS]
    await ctx.send(
        f"🔄 Shop rotation reset! New rotation (expires in {hours_left}h {minutes_left}m):\n"
        + "\n".join(lines)
    )


@bot.command(name="buy")
async def buy_item(ctx, item_name: str = None):
    if not item_name or item_name.lower() not in SHOP_ITEMS:
        await ctx.send(f"Unknown item. Use `!shop` to see today's available items.")
        return
    rotation, _ = get_shop_rotation()
    if item_name.lower() not in rotation:
        await ctx.send(f"**{SHOP_ITEMS[item_name.lower()]['name']}** isn't in today's rotation. Check `!shop` for what's available.")
        return
    item = SHOP_ITEMS[item_name.lower()]
    if not spend_coins(ctx.author.id, item["cost"]):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**, this costs **{item['cost']}**.")
        return
    eco = load_economy()
    eco.setdefault("inventory", {}).setdefault(str(ctx.author.id), []).append(item_name.lower())
    save_economy(eco)
    await ctx.send(f"✅ Purchased **{item['name']}**! It's in your inventory. Use `!use {item_name.lower()}` when you're ready to arm it.")


@bot.command(name="inventory")
async def inventory(ctx, member: discord.Member = None):
    target = member or ctx.author
    eco = load_economy()
    owned = eco.get("inventory", {}).get(str(target.id), [])
    armed = eco.get("pending_upgrades", {}).get(str(target.id), [])
    if not owned and not armed:
        await ctx.send(f"**{target.display_name}** has no items. Buy some with `!shop`.")
        return
    lines = []
    if owned:
        lines.append("**Inventory (unequipped):**")
        for item in owned:
            lines.append(f"  • {SHOP_ITEMS[item]['name']} (`{item}`)")
    if armed:
        lines.append("**Armed (fires on next @mention):**")
        for item in armed:
            lines.append(f"  ⚡ {SHOP_ITEMS.get(item, {}).get('name', item)}")
    await ctx.send(f"🎒 **{target.display_name}'s Items**\n" + "\n".join(lines))


@bot.command(name="use")
async def use_item(ctx, item_name: str = None):
    if not item_name:
        await ctx.send("Usage: `!use <item_name>`")
        return
    item_name = item_name.lower()
    eco = load_economy()
    uid = str(ctx.author.id)
    owned = eco.get("inventory", {}).get(uid, [])
    if item_name not in owned:
        await ctx.send(f"You don't have a **{SHOP_ITEMS.get(item_name, {}).get('name', item_name)}** in your inventory.")
        return
    owned.remove(item_name)
    eco["inventory"][uid] = owned

    if item_name == "slow_clap":
        eco["slow_clap_pending"] = eco.get("slow_clap_pending", 0) + 1
        save_economy(eco)
        gid = ctx.guild.id if ctx.guild else None
        tn = get_guild_target(gid)["name"]
        await ctx.send(f"👏 **Slow Clap** armed! It will fire on {tn}'s next message.")
        return

    eco.setdefault("pending_upgrades", {}).setdefault(uid, []).append(item_name)
    save_economy(eco)
    item = SHOP_ITEMS[item_name]
    await ctx.send(f"⚡ **{item['name']}** armed! It will fire on your next @mention of the bot.")


@bot.command(name="bounty")
async def post_bounty(ctx, amount: int = None, *, description: str = None):
    gid = ctx.guild.id if ctx.guild else None
    tn = get_guild_target(gid)["name"]
    if is_donovan(ctx.author, gid):
        await ctx.send(f"{tn} cannot post bounties. They ARE the bounty.")
        return
    if not amount or not description or amount <= 0:
        await ctx.send("Usage: `!bounty <amount> <description>`")
        return
    if not spend_coins(ctx.author.id, amount):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins. You have **{bal}**.")
        return
    eco = load_economy()
    bid = eco.get("next_bounty_id", 1)
    eco["bounties"].append({"id": bid, "poster_id": str(ctx.author.id),
                            "amount": amount, "description": description, "active": True})
    eco["next_bounty_id"] = bid + 1
    save_economy(eco)
    await ctx.send(f"🎯 **Bounty #{bid} posted!**\n_{description}_\n💰 Reward: **{amount} coins** to whoever triggers the next roast!")


@bot.command(name="bounties")
async def view_bounties(ctx):
    active = [b for b in load_economy()["bounties"] if b["active"]]
    if not active:
        await ctx.send("🎯 No active bounties. Post one with `!bounty <amount> <description>`.")
        return
    lines = [f"**#{b['id']}** — {b['amount']} coins\n_{b['description']}_" for b in active]
    await ctx.send("🎯 **Active Bounties**\n\n" + "\n\n".join(lines))


@bot.command(name="insurance")
async def insurance(ctx, minutes: int = None):
    gid = ctx.guild.id if ctx.guild else None
    tn = get_guild_target(gid)["name"]
    if not is_donovan(ctx.author, gid):
        await ctx.send(f"Only {tn} needs insurance. Everyone else is fine.")
        return
    if not minutes or minutes <= 0:
        await ctx.send(f"Usage: `!insurance <minutes>` — costs {INSURANCE_COST_PER_MINUTE} coins/min (max {MAX_INSURANCE_MINUTES} min).")
        return
    minutes = min(minutes, MAX_INSURANCE_MINUTES)
    cost = minutes * INSURANCE_COST_PER_MINUTE
    if not spend_coins(ctx.author.id, cost):
        bal = load_economy()["balances"].get(str(ctx.author.id), 0)
        await ctx.send(f"Not enough coins {tn}. You have **{bal}**, you need **{cost}**. Keep chatting to earn more.")
        return
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    eco = load_economy()
    eco["insurance_expires"] = expires.isoformat()
    save_economy(eco)
    await ctx.send(f"🛡️ {tn} bought **{minutes} minutes** of insurance for **{cost} coins**. Cute. Won't save him though.")


@bot.command(name="give")
async def give_coins(ctx, member: discord.Member = None, amount: int = None):
    if not member or not amount or amount <= 0:
        await ctx.send("Usage: `!give @user <amount>`")
        return
    if member.id == ctx.author.id:
        await ctx.send("You can't give coins to yourself.")
        return
    if not spend_coins(ctx.author.id, amount):
        await ctx.send("Not enough coins.")
        return
    add_coins(member.id, amount)
    await ctx.send(f"💸 **{ctx.author.display_name}** sent **{amount} Roast Coins** to **{member.display_name}**.")


@bot.command(name="blackmarket")
async def black_market(ctx):
    listings = [l for l in load_economy().get("market_listings", []) if l["active"]]
    if not listings:
        await ctx.send("🕶️ **Black Market**\nNo listings right now. Use `!listitem <item> <price>` to sell an upgrade.")
        return
    lines = []
    for l in listings:
        seller = ctx.guild.get_member(int(l["seller_id"]))
        name = seller.display_name if seller else "Unknown"
        item = SHOP_ITEMS.get(l["item"], {}).get("name", l["item"])
        lines.append(f"**#{l['id']}** — {item} by {name} — {l['price']} coins  →  `!buyitem {l['id']}`")
    await ctx.send("🕶️ **Black Market**\n\n" + "\n".join(lines))


@bot.command(name="listitem")
async def list_item(ctx, item_name: str = None, price: int = None):
    if not item_name or not price or price <= 0:
        await ctx.send("Usage: `!listitem <item_name> <price>`")
        return
    item_name = item_name.lower()
    if item_name not in SHOP_ITEMS:
        await ctx.send(f"Unknown item. Valid items: {', '.join(SHOP_ITEMS.keys())}")
        return
    eco = load_economy()
    uid = str(ctx.author.id)
    owned = eco.get("inventory", {}).get(uid, [])
    if item_name not in owned:
        await ctx.send(f"You don't have a **{SHOP_ITEMS[item_name]['name']}** in your inventory to sell.")
        return
    owned.remove(item_name)
    eco["inventory"][uid] = owned
    lid = eco.get("next_listing_id", 1)
    eco.setdefault("market_listings", []).append(
        {"id": lid, "seller_id": str(ctx.author.id), "item": item_name, "price": price, "active": True}
    )
    eco["next_listing_id"] = lid + 1
    save_economy(eco)
    await ctx.send(f"🕶️ Listed **{SHOP_ITEMS[item_name]['name']}** for **{price} coins** on the black market (ID #{lid}).")


@bot.command(name="buyitem")
async def buy_market_item(ctx, listing_id: int = None):
    if not listing_id:
        await ctx.send("Usage: `!buyitem <listing_id>`")
        return
    eco = load_economy()
    listing = next((l for l in eco.get("market_listings", []) if l["id"] == listing_id and l["active"]), None)
    if not listing:
        await ctx.send("Listing not found or already sold.")
        return
    if listing["seller_id"] == str(ctx.author.id):
        await ctx.send("You can't buy your own listing.")
        return
    if not spend_coins(ctx.author.id, listing["price"]):
        await ctx.send("Not enough coins.")
        return
    add_coins(int(listing["seller_id"]), listing["price"])
    listing["active"] = False
    eco.setdefault("inventory", {}).setdefault(str(ctx.author.id), []).append(listing["item"])
    save_economy(eco)
    seller = ctx.guild.get_member(int(listing["seller_id"]))
    seller_name = seller.display_name if seller else "Unknown"
    item_name = SHOP_ITEMS.get(listing["item"], {}).get("name", listing["item"])
    await ctx.send(f"🕶️ **{ctx.author.display_name}** bought **{item_name}** from **{seller_name}** for **{listing['price']} coins**.")


@bot.command(name="Guesswhosaidit")
async def guess_who(ctx):
    global guess_game_active

    gid = ctx.guild.id if ctx.guild else None
    tn = get_guild_target(gid)["name"]

    if is_donovan(ctx.author, gid):
        await ctx.send(f"You're not allowed to play this game {tn}. You might recognise yourself.")
        return

    if guess_game_active:
        await ctx.send("A game is already running. One humiliation at a time.")
        return

    guess_game_active = True
    scores = {}
    quotes_pool = [{"text": _t(q["text"], gid), "is_donovan": q["is_donovan"]} for q in _QUOTES_TMPL]
    pool = random.sample(quotes_pool, min(3, len(quotes_pool)))

    try:
        await ctx.send(f"🎮 **GUESS WHO SAID IT** 🎮\n3 rounds, 30 seconds each.\nReact 🇩 if you think **{tn}** said it, 🤷 if **someone else** did.")

        for round_num, quote in enumerate(pool, 1):
            msg = await ctx.send(
                f"**Round {round_num}/3**\n\n"
                f'*"{quote["text"]}"*\n\n'
                f"🇩 = {tn}    🤷 = Not {tn}"
            )
            await msg.add_reaction("🇩")
            await msg.add_reaction("🤷")

            await asyncio.sleep(30)

            msg = await ctx.channel.fetch_message(msg.id)
            donovan_voters = set()
            not_donovan_voters = set()

            for reaction in msg.reactions:
                async for user in reaction.users():
                    if user.bot:
                        continue
                    if str(reaction.emoji) == "🇩":
                        donovan_voters.add(user.id)
                    elif str(reaction.emoji) == "🤷":
                        not_donovan_voters.add(user.id)

            correct_voters = donovan_voters if quote["is_donovan"] else not_donovan_voters
            for uid in correct_voters:
                scores[uid] = scores.get(uid, 0) + 1

            answer = f"**{tn.upper()}** said that. Shocking." if quote["is_donovan"] else f"A normal human said that. {tn} could never."
            correct_count = len(correct_voters)
            await ctx.send(f"⏱️ Time's up! {answer}\n✅ {correct_count} people got it right.")

        if scores:
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            winner_id, top_score = sorted_scores[0]
            winner = ctx.guild.get_member(winner_id)
            winner_name = winner.display_name if winner else "Someone"
            board = "\n".join(
                f"{ctx.guild.get_member(uid).display_name if ctx.guild.get_member(uid) else 'Unknown'}: {s}/3"
                for uid, s in sorted_scores
            )
            await ctx.send(
                f"🏆 **GAME OVER**\n\n{board}\n\n"
                f"Winner: **{winner_name}** with {top_score}/3 — the only one here who truly understands how big of a loser {tn} is."
            )
        else:
            await ctx.send(f"🏆 **GAME OVER**\nNobody scored a single point. {tn} would fit right in.")

    except Exception as e:
        print(f"[ERROR] Guess game failed: {e}")
        await ctx.send(f"The game crashed. Blame {tn}.")
    finally:
        guess_game_active = False


@bot.command(name="Trial")
async def trial(ctx, *, reason: str = None):
    global trial_active

    gid = ctx.guild.id if ctx.guild else None
    tn = get_guild_target(gid)["name"]

    if is_donovan(ctx.author, gid):
        await ctx.send(f"You can't put yourself on trial {tn}. Though honestly you should.")
        return

    if trial_active:
        await ctx.send(f"A trial is already in progress. {tn} can only be humiliated one case at a time.")
        return

    if not reason:
        await ctx.send("You need to provide a charge. Usage: `!Trial <reason>`")
        return

    trial_active = True
    try:
        msg = await ctx.send(
            f"⚖️ **THE PEOPLE VS. {tn.upper()}** ⚖️\n\n"
            f"**Charge:** {reason}\n\n"
            f"Cast your vote:\n"
            f"👨‍⚖️ = GUILTY\n"
            f"🆓 = NOT GUILTY\n\n"
            f"_Voting closes in 60 seconds._"
        )
        await msg.add_reaction("👨‍⚖️")
        await msg.add_reaction("🆓")

        await asyncio.sleep(60)

        msg = await ctx.channel.fetch_message(msg.id)
        guilty = 0
        not_guilty = 0
        for reaction in msg.reactions:
            if str(reaction.emoji) == "👨‍⚖️":
                guilty = reaction.count - 1
            elif str(reaction.emoji) == "🆓":
                not_guilty = reaction.count - 1

        if guilty >= not_guilty:
            sentence = random.choice(SENTENCES)
            await ctx.send(
                f"⚖️ **VERDICT: GUILTY** ⚖️\n"
                f"_{guilty} guilty — {not_guilty} not guilty_\n\n"
                f"**Sentence:** {sentence}"
            )
        else:
            await ctx.send(
                f"⚖️ **VERDICT: NOT GUILTY** ⚖️\n"
                f"_{not_guilty} not guilty — {guilty} guilty_\n\n"
                f"{tn} walks free today. Don't worry, they'll embarrass themselves again soon enough."
            )
    except Exception as e:
        print(f"[ERROR] Trial failed: {e}")
        await ctx.send(f"The trial collapsed due to {tn}'s overwhelming incompetence. Court dismissed.")
    finally:
        trial_active = False


@bot.command(name="TTS")
async def toggle_tts(ctx, state: str = None):
    global tts_enabled

    gid = ctx.guild.id if ctx.guild else None
    tn = get_guild_target(gid)["name"]
    if is_donovan(ctx.author, gid):
        await ctx.send(f"Lmao no. You don't get a say in this, {tn}.")
        return

    if state is None or state.lower() not in ("on", "off"):
        await ctx.send(f"TTS is currently **{'on' if tts_enabled else 'off'}**. Use `!TTS on` or `!TTS off`.")
        return

    tts_enabled = state.lower() == "on"
    await ctx.send(f"TTS roasts turned **{state.lower()}**.")


@bot.command(name="update")
@commands.has_permissions(administrator=True)
async def update_bot(ctx):
    import subprocess
    await ctx.send("⬇️ Pulling latest changes...")
    result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True)
    output = result.stdout.strip() or result.stderr.strip() or "No output."
    await ctx.send(f"```{output}```")
    if result.returncode != 0:
        await ctx.send("❌ Git pull failed. Not restarting.")
        return
    await ctx.send("✅ Update complete. Restarting...")
    subprocess.run(["pkill", "-f", "bot.py"])


@bot.command(name="buystock")
async def buy_stock(ctx, ticker: str = None, shares: int = None):
    if not ticker or not shares or shares <= 0:
        await ctx.send("Usage: `!buystock <TICKER> <shares>` — e.g. `!buystock DONOVAN 10`")
        return
    ticker = ticker.lstrip("$").upper()
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    eco = load_economy()
    init_market(eco)
    ok, msg = execute_market_buy(eco, ctx.author.id, ticker, shares)
    save_economy(eco)
    await ctx.send(("✅ " if ok else "❌ ") + msg)


@bot.command(name="sellstock")
async def sell_stock(ctx, ticker: str = None, shares: int = None):
    if not ticker or not shares or shares <= 0:
        await ctx.send("Usage: `!sellstock <TICKER> <shares>` — e.g. `!sellstock DONOVAN 10`")
        return
    ticker = ticker.lstrip("$").upper()
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    eco = load_economy()
    init_market(eco)
    ok, msg = execute_market_sell(eco, ctx.author.id, ticker, shares)
    save_economy(eco)
    await ctx.send(("✅ " if ok else "❌ ") + msg)


@bot.command(name="short")
async def short_stock(ctx, ticker: str = None, shares: int = None):
    if not ticker or not shares or shares <= 0:
        gid = ctx.guild.id if ctx.guild else None
        tgt_ticker = get_guild_target(gid)["ticker"]
        await ctx.send(f"Usage: `!short <TICKER> <shares>` — Only `${tgt_ticker}` is shortable.")
        return
    ticker = ticker.lstrip("$").upper()
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    eco = load_economy()
    init_market(eco)
    ok, msg = execute_open_short(eco, ctx.author.id, ticker, shares)
    save_economy(eco)
    await ctx.send(("✅ " if ok else "❌ ") + msg)


@bot.command(name="cover")
async def cover_short(ctx, ticker: str = None, shares: int = None):
    if not ticker or not shares or shares <= 0:
        await ctx.send("Usage: `!cover <TICKER> <shares>` — e.g. `!cover DONOVAN 10`")
        return
    ticker = ticker.lstrip("$").upper()
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    eco = load_economy()
    init_market(eco)
    ok, msg = execute_close_short(eco, ctx.author.id, ticker, shares)
    save_economy(eco)
    await ctx.send(("✅ " if ok else "❌ ") + msg)


@bot.command(name="limitorder")
async def limit_order(ctx, order_type: str = None, ticker: str = None, shares: int = None, price: float = None):
    if not all([order_type, ticker, shares, price]) or shares <= 0 or price <= 0:
        await ctx.send(
            "Usage: `!limitorder <buy|sell|short|cover> <TICKER> <shares> <price>`\n"
            "Example: `!limitorder buy DONOVAN 10 85.00`"
        )
        return
    order_type = order_type.lower()
    ticker = ticker.lstrip("$").upper()
    if order_type not in ("buy", "sell", "short", "cover"):
        await ctx.send("Order type must be `buy`, `sell`, `short`, or `cover`.")
        return
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    eco = load_economy()
    init_market(eco)
    order_id = eco.get("next_order_id", 1)
    eco["next_order_id"] = order_id + 1
    eco.setdefault("limit_orders", []).append({
        "id": order_id,
        "user_id": str(ctx.author.id),
        "ticker": ticker,
        "order_type": order_type,
        "shares": shares,
        "limit_price": price,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    save_economy(eco)
    current = eco["market"][ticker]["price"]
    await ctx.send(
        f"📋 Limit order **#{order_id}** placed: **{order_type.upper()} {shares} ${ticker}** "
        f"@ **${price:.2f}** (current: **${current:.2f}**). You'll be notified when it fills."
    )


@bot.command(name="cancellimit")
async def cancel_limit(ctx, order_id: int = None):
    if not order_id:
        await ctx.send("Usage: `!cancellimit <order_id>`")
        return
    eco = load_economy()
    orders = eco.get("limit_orders", [])
    target = next((o for o in orders if o["id"] == order_id and o["user_id"] == str(ctx.author.id)), None)
    if not target:
        await ctx.send(f"Order **#{order_id}** not found or doesn't belong to you.")
        return
    eco["limit_orders"] = [o for o in orders if o["id"] != order_id]
    save_economy(eco)
    await ctx.send(f"✅ Limit order **#{order_id}** cancelled.")


@bot.command(name="portfolio")
async def portfolio_cmd(ctx, member: discord.Member = None):
    target = member or ctx.author
    eco = load_economy()
    init_market(eco)
    uid = str(target.id)
    holdings = eco.get("portfolios", {}).get(uid, {})
    shorts = eco.get("short_positions", {}).get(uid, {})
    if not holdings and not shorts:
        await ctx.send(f"**{target.display_name}** has no open positions. Use `!buystock` or `!short` to get in.")
        return
    lines = [f"📈 **{target.display_name}'s Portfolio**\n"]
    total_value = 0.0
    if holdings:
        lines.append("**Long Positions:**")
        for ticker, pos in holdings.items():
            price = eco["market"][ticker]["price"]
            value = round(pos["shares"] * price, 2)
            pnl = round((price - pos["avg_cost"]) * pos["shares"], 2)
            pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
            total_value += value
            lines.append(
                f"  **${ticker}** — {pos['shares']} shares @ avg ${pos['avg_cost']:.2f} | "
                f"Now: ${price:.2f} | Value: {value:.0f} | P&L: **{pnl_str}**"
            )
    if shorts:
        lines.append("\n**Short Positions:**")
        for ticker, pos in shorts.items():
            price = eco["market"][ticker]["price"]
            pnl = round((pos["avg_price"] - price) * pos["shares"], 2)
            pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
            total_value += pos["collateral"] + pnl
            lines.append(
                f"  **${ticker}** — {pos['shares']} shares short @ ${pos['avg_price']:.2f} | "
                f"Now: ${price:.2f} | Collateral: {pos['collateral']:.0f} | P&L: **{pnl_str}**"
            )
    lines.append(f"\n**Total Portfolio Value: {total_value:.0f} coins**")
    await ctx.send("\n".join(lines))


@bot.command(name="orders")
async def my_orders(ctx):
    eco = load_economy()
    uid = str(ctx.author.id)
    orders = [o for o in eco.get("limit_orders", []) if o["user_id"] == uid]
    if not orders:
        await ctx.send("You have no pending limit orders. Use `!limitorder` to place one.")
        return
    lines = ["📋 **Your Pending Limit Orders:**\n"]
    for o in orders:
        lines.append(
            f"**#{o['id']}** — {o['order_type'].upper()} {o['shares']} **${o['ticker']}** @ **${o['limit_price']:.2f}**"
        )
    lines.append("\nUse `!cancellimit <id>` to cancel.")
    await ctx.send("\n".join(lines))


@bot.command(name="futures")
async def futures_cmd(ctx, direction: str = None, ticker: str = None, contracts: int = None):
    if not all([direction, ticker, contracts]) or contracts <= 0:
        await ctx.send(
            "Usage: `!futures <long|short> <TICKER> <contracts>` — 7-day contract, 20% margin.\n"
            "Example: `!futures long DONOVAN 10`"
        )
        return
    direction = direction.lower()
    ticker = ticker.lstrip("$").upper()
    if direction not in ("long", "short"):
        await ctx.send("Direction must be `long` or `short`.")
        return
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    price = eco["market"][ticker]["price"]
    margin = round(price * contracts * 0.20, 2)
    uid = str(ctx.author.id)
    bal = eco["balances"].get(uid, 0)
    if bal < margin:
        await ctx.send(f"Need **{margin:.0f} coins** margin (20% of position). You have **{bal}**.")
        return
    eco["balances"][uid] = bal - margin
    deriv_id = eco["next_derivative_id"]
    eco["next_derivative_id"] += 1
    expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).isoformat()
    eco["futures"].setdefault(uid, []).append({
        "id": deriv_id,
        "ticker": ticker,
        "contracts": contracts,
        "direction": direction,
        "entry_price": price,
        "margin": margin,
        "expiry": expiry,
    })
    save_economy(eco)
    emoji = "📈" if direction == "long" else "📉"
    await ctx.send(
        f"{emoji} Opened **{direction.upper()}** futures: **{contracts}x ${ticker}** @ **${price:.2f}**. "
        f"Margin held: **{margin:.0f} coins**. Settles in 7 days. ID: **#{deriv_id}**"
    )


@bot.command(name="closefutures")
async def close_futures_cmd(ctx, deriv_id: int = None):
    if not deriv_id:
        await ctx.send("Usage: `!closefutures <id>`")
        return
    uid = str(ctx.author.id)
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    positions = eco["futures"].get(uid, [])
    pos = next((p for p in positions if p["id"] == deriv_id), None)
    if not pos:
        await ctx.send(f"Futures contract **#{deriv_id}** not found.")
        return
    price = eco["market"][pos["ticker"]]["price"]
    pnl = (price - pos["entry_price"]) * pos["contracts"] if pos["direction"] == "long" \
        else (pos["entry_price"] - price) * pos["contracts"]
    pnl = round(pnl, 2)
    returned = max(round(pos["margin"] + pnl, 2), 0)
    eco["balances"][uid] = eco["balances"].get(uid, 0) + returned
    eco["futures"][uid] = [p for p in positions if p["id"] != deriv_id]
    save_economy(eco)
    pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
    await ctx.send(
        f"✅ Closed futures **#{deriv_id}**: **{pos['direction'].upper()} {pos['contracts']}x ${pos['ticker']}**. "
        f"P&L: **{pnl_str} coins**. Returned: **{returned:.0f} coins**."
    )


@bot.command(name="myfutures")
async def my_futures_cmd(ctx):
    uid = str(ctx.author.id)
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    positions = eco["futures"].get(uid, [])
    if not positions:
        await ctx.send("No open futures. Use `!futures long/short <TICKER> <contracts>` to open one.")
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    lines = ["📅 **Your Open Futures:**\n"]
    for pos in positions:
        price = eco["market"][pos["ticker"]]["price"]
        pnl = (price - pos["entry_price"]) * pos["contracts"] if pos["direction"] == "long" \
            else (pos["entry_price"] - price) * pos["contracts"]
        pnl = round(pnl, 2)
        pnl_str = f"+{pnl:.0f}" if pnl >= 0 else str(round(pnl))
        days_left = max(0, (datetime.datetime.fromisoformat(pos["expiry"]) - now).days)
        lines.append(
            f"**#{pos['id']}** {pos['direction'].upper()} **{pos['contracts']}x ${pos['ticker']}** "
            f"@ ${pos['entry_price']:.2f} | Now: ${price:.2f} | P&L: **{pnl_str}** | {days_left}d left"
        )
    lines.append("\nUse `!closefutures <id>` to close early.")
    await ctx.send("\n".join(lines))


@bot.command(name="buyoption")
async def buy_option_cmd(ctx, option_type: str = None, ticker: str = None, contracts: int = None, strike: float = None, days: int = 7):
    if not all([option_type, ticker, contracts, strike]) or contracts <= 0 or strike <= 0:
        await ctx.send(
            "Usage: `!buyoption <call|put> <TICKER> <contracts> <strike> [days=7]`\n"
            "Example: `!buyoption call DONOVAN 10 85 7`"
        )
        return
    option_type = option_type.lower()
    ticker = ticker.lstrip("$").upper()
    if option_type not in ("call", "put"):
        await ctx.send("Option type must be `call` or `put`.")
        return
    if ticker not in MARKET_STOCKS:
        await ctx.send(f"Unknown ticker. Available: {', '.join(f'${t}' for t in MARKET_STOCKS)}")
        return
    if not 1 <= days <= 30:
        await ctx.send("Expiry must be between 1 and 30 days.")
        return
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    spot = eco["market"][ticker]["price"]
    premium_per = calc_option_premium(spot, strike, option_type, days)
    total_premium = round(premium_per * contracts, 2)
    uid = str(ctx.author.id)
    bal = eco["balances"].get(uid, 0)
    if bal < total_premium:
        await ctx.send(
            f"Premium costs **{total_premium:.0f} coins** (${premium_per:.2f}/contract). You have **{bal}**."
        )
        return
    eco["balances"][uid] = bal - total_premium
    deriv_id = eco["next_derivative_id"]
    eco["next_derivative_id"] += 1
    expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).isoformat()
    eco["options"].setdefault(uid, []).append({
        "id": deriv_id,
        "ticker": ticker,
        "option_type": option_type,
        "contracts": contracts,
        "strike": strike,
        "premium_paid": total_premium,
        "expiry": expiry,
        "exercised": False,
    })
    save_economy(eco)
    itm = "ITM" if (option_type == "call" and spot > strike) or (option_type == "put" and spot < strike) else "OTM"
    await ctx.send(
        f"✅ Bought **{contracts}x {option_type.upper()} ${ticker}** strike **${strike:.2f}** ({itm}, spot: ${spot:.2f}). "
        f"Premium: **{total_premium:.0f} coins**. Expires in {days}d. ID: **#{deriv_id}**"
    )


@bot.command(name="exercise")
async def exercise_option_cmd(ctx, deriv_id: int = None):
    if not deriv_id:
        await ctx.send("Usage: `!exercise <id>`")
        return
    uid = str(ctx.author.id)
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    opt = next((o for o in eco["options"].get(uid, []) if o["id"] == deriv_id and not o.get("exercised")), None)
    if not opt:
        await ctx.send(f"Option **#{deriv_id}** not found or already exercised.")
        return
    if datetime.datetime.now(datetime.timezone.utc) > datetime.datetime.fromisoformat(opt["expiry"]):
        await ctx.send(f"Option **#{deriv_id}** has already expired.")
        return
    price = eco["market"][opt["ticker"]]["price"]
    intrinsic = (price - opt["strike"]) * opt["contracts"] if opt["option_type"] == "call" \
        else (opt["strike"] - price) * opt["contracts"]
    if intrinsic <= 0:
        await ctx.send(
            f"Option **#{deriv_id}** is out of the money. "
            f"Spot: ${price:.2f}, Strike: ${opt['strike']:.2f} — nothing to exercise."
        )
        return
    payout = round(intrinsic, 2)
    eco["balances"][uid] = eco["balances"].get(uid, 0) + payout
    opt["exercised"] = True
    save_economy(eco)
    net_pnl = round(payout - opt["premium_paid"], 2)
    net_str = f"+{net_pnl:.0f}" if net_pnl >= 0 else str(round(net_pnl))
    await ctx.send(
        f"✅ Exercised **#{deriv_id}** ({opt['option_type'].upper()} ${opt['ticker']} @ ${opt['strike']:.2f}). "
        f"Payout: **{payout:.0f} coins**. Net P&L: **{net_str} coins**."
    )


@bot.command(name="myoptions")
async def my_options_cmd(ctx):
    uid = str(ctx.author.id)
    eco = load_economy()
    init_market(eco)
    init_derivatives(eco)
    opts = [o for o in eco["options"].get(uid, []) if not o.get("exercised")]
    if not opts:
        await ctx.send("No open options. Use `!buyoption call/put <TICKER> <contracts> <strike>` to buy one.")
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    lines = ["🎯 **Your Open Options:**\n"]
    for opt in opts:
        spot = eco["market"][opt["ticker"]]["price"]
        intrinsic = max(0, (spot - opt["strike"]) * opt["contracts"]) if opt["option_type"] == "call" \
            else max(0, (opt["strike"] - spot) * opt["contracts"])
        itm = (opt["option_type"] == "call" and spot > opt["strike"]) or \
              (opt["option_type"] == "put" and spot < opt["strike"])
        days_left = max(0, (datetime.datetime.fromisoformat(opt["expiry"]) - now).days)
        status = "✅ ITM" if itm else "❌ OTM"
        lines.append(
            f"**#{opt['id']}** {opt['option_type'].upper()} **{opt['contracts']}x ${opt['ticker']}** "
            f"strike ${opt['strike']:.2f} | Spot: ${spot:.2f} {status} | "
            f"Value: {intrinsic:.0f} | Paid: {opt['premium_paid']:.0f} | {days_left}d left"
        )
    lines.append("\nUse `!exercise <id>` to exercise early.")
    await ctx.send("\n".join(lines))


bot.run(os.getenv("DISCORD_TOKEN"))
