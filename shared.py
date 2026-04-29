import os
import math
import random
import asyncio
import tempfile
import datetime
from zoneinfo import ZoneInfo
import discord
from openai import AsyncOpenAI
from gtts import gTTS
from database import load_economy, save_economy, log_roast, get_weekly_recap

# ── Bot reference ─────────────────────────────────────────────────────────────
_bot = None

def set_bot(b):
    global _bot
    _bot = b

groq_client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

TARGET_NAME = os.getenv("TARGET_NAME", "Donovan")
TARGET_USERNAMES = {u.strip().lower() for u in os.getenv("TARGET_USERNAMES", "itsrebrand,streamerweiner").split(",") if u.strip()}
TARGET_STOCK_TICKER = os.getenv("TARGET_STOCK_TICKER", TARGET_NAME.upper()[:8])

def _t(s: str, guild_id=None) -> str:
    if guild_id:
        t = get_guild_target(guild_id)
        name, ticker = t["name"], t["ticker"]
    else:
        name, ticker = TARGET_NAME, TARGET_STOCK_TICKER
    return (s.replace("Donovan", name)
             .replace("DONOVAN", ticker)
             .replace("donovan", name.lower()))

MILESTONES = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
DONOVAN_USERNAMES = TARGET_USERNAMES
ROAST_CHANNEL_ID = int(os.getenv("ROAST_CHANNEL_ID", 0))
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", 0))
INSURANCE_COST_PER_MINUTE = 10
MAX_INSURANCE_MINUTES = 30

tts_enabled = True
tts_queue = asyncio.Queue()
trial_active = False
guess_game_active = False
trivia_active = False
trivia_recent = {}
trivia_recent_answers = {}
trivia_recent_cats = {}
guessroast_active = False
highlow_games = {}
blackjack_games = {}
sports_trivia_active = {}

_admin_server_started = False

VOTE_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
VOTE_CANDIDATE_LIMIT = 9

SHOP_ITEMS = {
    "shame_bell":        {"name": "Shame Bell",        "cost": 50,  "description": "Next roast comes with a 🔔 SHAME 🔔 announcement"},
    "snitch":            {"name": "Snitch",             "cost": 75,  "description": "Next roast also gets DMed directly to Donovan"},
    "slow_clap":         {"name": "Slow Clap",          "cost": 75,  "description": "HateBot reacts to Donovan's next message with a series of 👏 emojis"},
    "receipt":           {"name": "Receipt",            "cost": 80,  "description": "HateBot digs up and quotes one of his old messages alongside the roast"},
    "laugh_track":       {"name": "Laugh Track",        "cost": 90,  "description": "Next roast is followed by 😂 spam from the HateBot"},
    "double_roast":      {"name": "Double Roast",       "cost": 100, "description": "Your next @mention fires TWO roasts back to back"},
    "triple_roast":      {"name": "Triple Roast",       "cost": 125, "description": "Next roast fires THREE times in a row"},
    "anonymous":         {"name": "Anonymous",          "cost": 150, "description": "Next roast is delivered as an anonymous tip"},
    "spotlight":         {"name": "Spotlight",          "cost": 175, "description": "Next roast pings @here so nobody misses it"},
    "mega_roast":        {"name": "Mega Roast",         "cost": 200, "description": "Your next @mention also triggers an extra savage bonus roast"},
    "press_release":     {"name": "Press Release",      "cost": 225, "description": "HateBot a fake formal press release announcing his latest L"},
    "hall_of_shame":     {"name": "Hall of Shame",      "cost": 250, "description": "Next roast gets pinned in the channel permanently"},
    "breaking_news":     {"name": "Breaking News",      "cost": 250, "description": "HateBot posts a fake breaking news alert about him"},
    "intervention":      {"name": "Intervention",       "cost": 275, "description": "HateBot @everyone and announces a formal server intervention for his behavior"},
    "scorched_earth":    {"name": "Scorched Earth",     "cost": 300, "description": "HateBot Generates 3 different unique roasts back to back"},
    "bounty_boost":      {"name": "Bounty Boost",       "cost": 350, "description": "Your next bounty claim pays out double"},
    "exile":             {"name": "Exile",              "cost": 400, "description": "Timeouts Donovan in the server for 60 seconds"},
    "lore_drop":         {"name": "Lore Drop",          "cost": 400, "description": "HateBot generates a full absurd origin story for why Donovan is the way he is"},
    "nuclear":           {"name": "Nuclear",            "cost": 500, "description": "Maximum Hatebot roast + forces TTS even if it's off"},
    "eulogy":            {"name": "Eulogy",             "cost": 150, "description": "HateBot delivers a dramatic funeral eulogy for Donovan's dignity, as if it has already passed away"},
    "wanted_poster":     {"name": "Wanted Poster",      "cost": 175, "description": "HateBot generates a fake FBI wanted poster describing Donovan's crimes against the server"},
    "therapy_session":   {"name": "Therapy Session",    "cost": 200, "description": "HateBot roleplays as Donovan's therapist and reads his 'case notes' aloud in the channel"},
    "cease_and_desist":  {"name": "Cease & Desist",     "cost": 225, "description": "HateBot drafts a formal legal letter demanding Donovan stop being himself immediately"},
    "linkedin_post":     {"name": "LinkedIn Post",      "cost": 250, "description": "HateBot writes a cringe corporate LinkedIn post from Donovan's perspective hyping up his latest L as a 'growth opportunity'"},
    "documentary":       {"name": "Documentary",        "cost": 325, "description": "HateBot generates a Ken Burns-style documentary narration about a recent Donovan moment, complete with dramatic pauses"},
    "legacy_mode":       {"name": "Legacy Mode",        "cost": 450, "description": "HateBot compiles Donovan's greatest hits — his worst moments from server history — into one devastating highlight reel recap"},
    "motivational_poster":{"name": "Motivational Poster","cost": 200,"description": "HateBot generates a fake inspirational quote attributed to Donovan paired with the most embarrassing context possible"},
    "autopsy_report":    {"name": "Autopsy Report",     "cost": 225, "description": "HateBot produces a clinical medical examiner's report on the cause of death of Donovan's credibility"},
    "wikipedia_page":    {"name": "Wikipedia Page",     "cost": 325, "description": "HateBot generates a fake Wikipedia article about Donovan complete with a controversies section"},
    "parole_hearing":    {"name": "Parole Hearing",     "cost": 350, "description": "HateBot conducts a formal parole board hearing to determine whether Donovan has earned the right to be taken seriously again — verdict always denied"},
    "dossier":           {"name": "Dossier",            "cost": 400, "description": "HateBot compiles and presents a full classified intelligence briefing on Donovan, his known associates, and his pattern of behavior"},
    "state_of_the_union":{"name": "State of the Union", "cost": 475, "description": "HateBot delivers a presidential address formally assessing the ongoing Donovan situation, its impact on national morale, and the administration's response plan"},
}

SLOT_SYMBOLS = ["🍋", "🍒", "🍇", "💎", "🎰", "7️⃣"]
SLOT_PAYOUTS = {("7️⃣", "7️⃣", "7️⃣"): 50, ("💎", "💎", "💎"): 25, ("🎰", "🎰", "🎰"): 15}
CARD_SUITS = ["♠", "♥", "♦", "♣"]
CARD_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

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



SERVER_ROAST_MILESTONES = {100: 50, 250: 75, 500: 100, 1000: 200, 2500: 300, 5000: 500}
DONOVAN_STOCK_BASE = 100.0
USER_STOCK_BASE = 10.0

MARKET_STOCKS = {
    "DONOVAN": {"name": "Donovan Holdings Inc.",   "base_price": 100.0, "shares_outstanding": 10000, "shortable": True, "volatility": 2.0, "mean_reversion": 0.03,  "daily_volume": 2000},
    "RUST":    {"name": "Rust Lang Corp",           "base_price": 42.0,  "shares_outstanding": 5000,  "shortable": True, "volatility": 2.5, "mean_reversion": 0.02,  "daily_volume": 800,  "dividend_rate": 0.005},
    "BIGMAC":  {"name": "McBigMac Enterprises",    "base_price": 5.99,  "shares_outstanding": 5000,  "shortable": True, "volatility": 1.2, "mean_reversion": 0.05,  "daily_volume": 3000, "dividend_rate": 0.010},
    "TORTA":   {"name": "Torta Brothers LLC",      "base_price": 12.50, "shares_outstanding": 5000,  "shortable": True, "volatility": 1.5, "mean_reversion": 0.04,  "daily_volume": 1500, "dividend_rate": 0.008},
    "TRUMP":   {"name": "Trump Media & Golf Co.",  "base_price": 75.0,  "shares_outstanding": 5000,  "shortable": True, "volatility": 3.5, "mean_reversion": 0.015, "daily_volume": 2500},
    "COCAINE": {"name": "Cartel Pharmaceuticals",  "base_price": 420.0, "shares_outstanding": 2000,  "shortable": True, "volatility": 5.0, "mean_reversion": 0.01,  "daily_volume": 400},
    "TBELL":   {"name": "Taco Bell Enterprises",   "base_price": 29.99, "shares_outstanding": 8000,  "shortable": True, "volatility": 3.0, "mean_reversion": 0.03,  "daily_volume": 2000},
    "OHIO":    {"name": "Ohio Ventures LLC",        "base_price": 69.0,  "shares_outstanding": 4200,  "shortable": True, "volatility": 8.0, "mean_reversion": 0.005, "daily_volume": 1000},
    "FLORIDA": {"name": "Florida Man Holdings",    "base_price": 55.0,  "shares_outstanding": 3500,  "shortable": True, "volatility": 6.0, "mean_reversion": 0.01,  "daily_volume": 1200},
    "YEEZY":   {"name": "Ye Industries",           "base_price": 88.0,  "shares_outstanding": 1000,  "shortable": True, "volatility": 9.0, "mean_reversion": 0.005, "daily_volume": 200},
    "WENDY":   {"name": "Wendy's Corp",            "base_price": 38.0,  "shares_outstanding": 6000,  "shortable": True, "volatility": 2.8, "mean_reversion": 0.04,  "daily_volume": 1800, "dividend_rate": 0.007},
}

_TARGET_STOCK_DEFAULTS = {
    "shares_outstanding": 5000, "shortable": True, "volatility": 3.0,
    "mean_reversion": 0.03, "daily_volume": 1500, "base_price": 50.0,
}

_ANALYST_QUOTES = [
    "Jim Cramer says **BUY BUY BUY**", "WSB calls it a **rug pull** 🚨",
    "Goldman Sachs upgrades to **STRONG BUY**", "Warren Buffett is reportedly **confused**",
    "Cathie Wood adds to ARK position", "Analysts raise price target to **the moon** 🌕",
    "Short sellers are **crying**", "SEC opens investigation",
    "Options market implying **total chaos**", "Cramer says **SELL** — so probably buy",
    "JP Morgan downgrades to **SELL**", "Retail investors **going all in**",
    "Hedge funds **exiting positions**", "Insider trading **heavily suspected**",
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


# ── Raw template snapshots (re-applied when update_target() swaps the target) ─
_SHOP_ITEMS_TMPL        = {k: {**v} for k, v in SHOP_ITEMS.items()}
_SENTENCES_TMPL         = list(SENTENCES)
_MONDAY_ROASTS_TMPL     = list(MONDAY_ROASTS)
_FRIDAY_ROASTS_TMPL     = list(FRIDAY_ROASTS)
_RUST_ROASTS_TMPL       = list(RUST_ROASTS)
_WOW_ROASTS_TMPL        = list(WOW_ROASTS)
_ROASTS_DIRECT_TMPL     = list(DONOVAN_ROASTS_DIRECT)
_GENERAL_ROASTS_TMPL    = list(GENERAL_ROASTS)
_TRIVIA_TMPL            = [dict(q) for q in TRIVIA_QUESTIONS]
_QUOTES_TMPL            = [dict(q) for q in QUOTES]
_STOCK_NEWS_TARGET_TMPL = [dict(item) for item in _STOCK_NEWS.get("DONOVAN", [])]

SYSTEM_PROMPT = _t(_SYSTEM_PROMPT_TMPL)
DONOVAN_ARGUE_PROMPT = _t(_ARGUE_PROMPT_TMPL)


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
    for guild in _bot.guilds:
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
    _apply_price_event(eco["market"][TARGET_STOCK_TICKER], eco["market"][TARGET_STOCK_TICKER]["price"] - drop)
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
                # Reconcile ATH/ATL with full price_history in case history predates ATH tracking
                ph = eco["market"][ticker].get("price_history", [])
                if ph:
                    eco["market"][ticker]["all_time_high"] = max(eco["market"][ticker]["all_time_high"], max(ph))
                    eco["market"][ticker]["all_time_low"]  = min(eco["market"][ticker]["all_time_low"],  min(ph))
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
    _apply_price_event(eco["market"][ticker], old * (1 + impact_pct / 100))
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
            ch = _bot.get_channel(ch_id)
            if ch:
                result.append((int(gid_str), ch))
                seen_guild_ids.add(int(gid_str))

    # For every guild the bot is in that hasn't run !setup, fall back to a
    # suitable channel so events reach all servers, not just configured ones.
    for guild in _bot.guilds:
        if guild.id in seen_guild_ids:
            continue
        # Prefer the env-var channel if it belongs to this guild
        if ROAST_CHANNEL_ID:
            ch = _bot.get_channel(ROAST_CHANNEL_ID)
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
    "animals and wildlife",
    "famous inventions",
    "world records",
    "language and linguistics",
    "economics and business",
    "architecture and landmarks",
    "famous crimes and mysteries",
    "television sitcoms",
    "80s and 90s culture",
    "board games and card games",
    "famous speeches and quotes",
    "medical science",
    "cars and transportation",
    "awards and achievements",
    "internet and social media",
]


async def generate_trivia_question(used_topics=None, used_categories=None, used_answers=None):
    import re
    # Avoid repeating recent categories
    available = [c for c in TRIVIA_CATEGORIES if not used_categories or c not in used_categories]
    category = random.choice(available or TRIVIA_CATEGORIES)
    # Pass recent answers (compact) rather than full question text — more effective dedup
    avoid_answers = (
        f"\nDo NOT use any of these answers or subjects (already used recently): {', '.join(used_answers[-20:])}."
        if used_answers else ""
    )
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
                        "- AVOID the single most obvious or overused question for this category "
                        "(e.g. not 'Who painted the Mona Lisa' for art, not 'What language did Brendan Eich create' for tech). "
                        "Pick something more interesting and varied.\n"
                        f"{avoid_answers}\n"
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
        channel = _bot.get_channel(vc_id)
        if channel and getattr(channel, "guild", None) and channel.guild.id == gid:
            return channel
        print(f"[WARN] Ignoring configured voice channel {vc_id} for guild {gid}; channel missing or cross-guild.")
    if VOICE_CHANNEL_ID:
        channel = _bot.get_channel(VOICE_CHANNEL_ID)
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
            guild = _bot.get_guild(guild_id)
            if not guild:
                continue

            if voice_channel_id:
                channel = _bot.get_channel(voice_channel_id) or await _bot.fetch_channel(voice_channel_id)
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
    _apply_price_event(eco["market"][roasted_ticker], old * (1 + drop_pct / 100))
    eco["market"][roasted_ticker]["last_updated"] = now_iso
    moves[roasted_ticker] = (old, eco["market"][roasted_ticker]["price"], drop_pct, roasted_tgt["name"])

    for tgt in eco.get("guild_targets", {}).values():
        ticker = (tgt.get("ticker") or "").upper()
        if not ticker or ticker == roasted_ticker or ticker not in eco["market"]:
            continue
        old = eco["market"][ticker]["price"]
        _apply_price_event(eco["market"][ticker], old * (1 + boost_pct / 100))
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
        ch = _bot.get_channel(legacy["channel_id"])
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

        channel = _bot.get_channel(vote_data["channel_id"])
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


def _fix_news_item(item):
    fixed = {"headline": _t(item["headline"]), "impact": item["impact"]}
    if "linked" in item:
        fixed["linked"] = [
            (TARGET_STOCK_TICKER if tk == "DONOVAN" else tk, imp)
            for tk, imp in item["linked"]
        ]
    return fixed

_STOCK_NEWS[TARGET_STOCK_TICKER] = [_fix_news_item(i) for i in _STOCK_NEWS.pop("DONOVAN")]

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
    "animals and wildlife",
    "famous inventions",
    "world records",
    "language and linguistics",
    "economics and business",
    "architecture and landmarks",
    "famous crimes and mysteries",
    "television sitcoms",
    "80s and 90s culture",
    "board games and card games",
    "famous speeches and quotes",
    "medical science",
    "cars and transportation",
    "awards and achievements",
    "internet and social media",
]

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

def _apply_price_event(mdata, new_price):
    """Update market entry for an event-driven price change (news, rumor, roast impact).
    Keeps ATH/ATL and price_history in sync so !stocktrend reflects spikes immediately."""
    new_price = max(round(new_price, 2), 0.01)
    mdata["prev_price"] = mdata.get("price", new_price)
    mdata["price"] = new_price
    mdata["all_time_high"] = max(mdata.get("all_time_high", new_price), new_price)
    mdata["all_time_low"] = min(mdata.get("all_time_low", new_price), new_price)
    mdata["price_history"] = (mdata.get("price_history", [new_price]) + [new_price])[-49:]


def _sparkline(prices):
    """Convert a list of prices into an 8-level unicode sparkline string."""
    if len(prices) < 2:
        return "—"
    lo, hi = min(prices), max(prices)
    blocks = "▁▂▃▄▅▆▇█"
    if hi == lo:
        return blocks[3] * len(prices)
    return "".join(blocks[round((p - lo) / (hi - lo) * 7)] for p in prices)


