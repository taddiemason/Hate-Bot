# Hate Bot

A customizable Discord bot that roasts anyone you point it at every time they get @mentioned.

---

## Customization

The bot targets whoever you configure — not just Donovan. Set these three variables in your `.env` and the bot will roast, shame, and economically devastate the right person:

| Variable | What it does | Example |
|---|---|---|
| `TARGET_NAME` | Name used in all roasts and messages | `Alex` |
| `TARGET_USERNAMES` | Comma-separated Discord **usernames** (not display names) of the target | `alexaccount,alexalt` |
| `TARGET_STOCK_TICKER` | Stock ticker for the target on the in-bot market | `ALEX` |

Everything — shop item descriptions, scheduled Monday/Friday roasts, the LLM system prompt, the stock market, game quotes, weekly recap messages — automatically uses your configured name.

---

## Multiserver Setup

The bot supports multiple Discord servers from a single instance. Each server gets its own hate target and roast channel — the economy (coins, stocks, trivia wins) is shared across all servers since Discord user IDs are globally unique.

### Quick start for a new server

Once the bot is running and in your server, run these two commands as an admin:

```
!setup
```
Registers the current channel as the roast channel for your server. Scheduled roasts, weekly recaps, market news, and vote announcements will all post here.

```
!settarget <display_name> <discord_username> [ticker]
```
Sets who the bot hates on your server. Example:
```
!settarget Alex alexaccount ALEX
```

That's it. The bot will now roast `Alex` in your server independently of any other server's target.

### How it works

| Scope | Behaviour |
|---|---|
| **Target** | Per-server — each server has its own name, username(s), and stock ticker |
| **Roast channel** | Per-server — set with `!setup` |
| **Economy** (coins, balances, portfolios) | Shared — user IDs are unique across Discord |
| **Trivia leaderboard** | Shared |
| **Stock market** | Global — prices are the same on every server |
| **Weekly vote** | Per-server — the vote updates that server's target only |

### First server (`.env`-based)

If you only have one server, you don't need `!setup` or `!settarget`. The bot falls back to the env vars (`TARGET_NAME`, `TARGET_USERNAMES`, `ROAST_CHANNEL_ID`) the same as before. Per-server config only kicks in once a `!setup` or `!settarget` is run for that guild.

### Useful admin commands

| Command | What it does |
|---|---|
| `!setup` | Register current channel as this server's roast channel |
| `!settarget <name> <username> [ticker]` | Set/change the hate target for this server |
| `!currenttarget` | Show who the bot is currently targeting on this server |
| `!startvote` | Manually open a weekly hate vote in the current channel |
| `!tallyvote` | Manually close and tally the current vote |

---

## Prerequisites

- Python 3.8 or higher
- A Discord account
- A server where you have admin permissions

---

## Step 1 — Create the Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and give it a name
3. In the left sidebar, click **Bot**
4. Click **Add Bot** → **Yes, do it!**
5. Under the bot's username, click **Reset Token** and copy the token — you'll need this later
6. Scroll down to **Privileged Gateway Intents** and enable:
   - **Message Content Intent**
   - **Server Members Intent**
   - **Presence Intent**
7. Click **Save Changes**

---

## Step 2 — Invite the Bot to Your Server

1. In the left sidebar, click **OAuth2** → **URL Generator**
2. Under **Scopes**, check `bot`
3. Under **Bot Permissions**, check:
   - `Send Messages`
   - `Read Message History`
   - `View Channels`
   - `Connect` / `Speak` (for voice/TTS features)
   - `Moderate Members` (for the `!exile` shop item)
4. Copy the generated URL and open it in your browser
5. Select your server and click **Authorize**

---

## Step 3 — Install and Configure

Clone the repository and run the setup script:

```bash
git clone https://github.com/taddiemason/Hate-Bot.git
cd Hate-Bot
bash setup.sh
```

The script will:
1. Check your Python version (3.8+ required)
2. Create a virtual environment and install dependencies
3. Walk you through every `.env` setting interactively
4. Offer to install a systemd service so the bot starts on boot

**You'll be prompted for:**
- Your Discord bot token (from Step 1)
- Your Groq API key ([free at console.groq.com](https://console.groq.com))
- Who to roast — their name, Discord username(s), and stock ticker
- Which channel to post roasts in
- An admin dashboard password

### Manual setup (Windows or if you prefer)

```bash
python -m venv venv
venv\Scripts\activate      # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit .env with your values
```

**How to get a Groq API key:** Sign up at [console.groq.com](https://console.groq.com) — the free tier is more than enough.

**How to find Discord usernames:** Click a user's profile in Discord. The username is the lowercase handle without any `#` number (e.g., `alexaccount`). This is different from their display name.

**How to find Channel IDs:** Enable Developer Mode in Discord Settings → Advanced, then right-click any channel and choose **Copy Channel ID**.

---

## Step 5 — Run the Bot

```bash
python bot.py
```

You should see output like:

```
Logged in as HateBot#1234 (ID: 123456789)
```

The bot is now live. @mention it in any channel and it will respond with a roast targeting your configured user.

---

## Admin Panel

When the bot starts it also launches a local web dashboard at:

```
http://localhost:47832
```

> If port 47832 is in use the bot will try 47833, 47834 … up to 47841. Check the terminal for the actual port.

### Pages

| Page | What it shows |
|---|---|
| `/` | Economy overview — users, coins, shop rotation, stock prices |
| `/economy` | Full leaderboard with coin balances and portfolio values |
| `/shop` | Current shop rotation with time until refresh + force-reset button |
| `/stocks` | All stock prices, short interest, manual price override |
| `/user/<id>` | Individual user — cash, portfolio, shorts, inventory |
| `/messages` | Send a message to any channel (optional TTS) |

---

## Keeping the Bot Running 24/7

### Option A — systemd (Linux)

Create `/etc/systemd/system/hatebot.service`:

```ini
[Unit]
Description=Hate Bot
After=network.target

[Service]
User=YOUR_LINUX_USER
WorkingDirectory=/path/to/Hate-Bot
EnvironmentFile=/path/to/Hate-Bot/.env
ExecStart=/path/to/Hate-Bot/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable hatebot
sudo systemctl start hatebot
```

### Option B — screen (quick)

```bash
screen -S hatebot
python bot.py
# Ctrl+A then D to detach
```

---

## Updating the Bot

### Via Discord command

```
!update
```

Pulls the latest code and restarts automatically.

### Manually

```bash
git pull
pip install -r requirements.txt
pkill -f bot.py
python bot.py
```

---

## Troubleshooting

**Bot sends duplicate replies** — two instances are running. Kill them all with `pkill -f bot.py` then start one.

**Target not detected in voice** — make sure `TARGET_USERNAMES` matches their Discord username exactly (lowercase, no `#number`).

**Roasts still say "Donovan"** — check that `TARGET_NAME` is set in your `.env` and the bot was restarted after the change.

---

## File Overview

| File | Purpose |
|---|---|
| `bot.py` | Main bot logic |
| `web_admin.py` | Admin dashboard web server |
| `setup.sh` | Interactive first-time install and `.env` configurator |
| `update.sh` | Pulls latest code and restarts (used by `!update` command) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Configuration template |
| `.gitignore` | Prevents `.env` from being committed |
