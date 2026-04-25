#!/usr/bin/env bash
# setup.sh — First-time install and .env configuration for Hate Bot
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
info() { echo -e "${CYAN}→${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*" >&2; }
hr()   { echo -e "${DIM}────────────────────────────────────────────────────${RESET}"; }

ask() {
    # ask <varname> <prompt> [default]
    local var="$1" prompt="$2" default="${3:-}"
    local hint=""
    [[ -n "$default" ]] && hint=" ${DIM}[${default}]${RESET}"
    while true; do
        printf "${BOLD}%s${RESET}%b: " "$prompt" "$hint"
        read -r input
        input="${input:-$default}"
        if [[ -n "$input" ]]; then
            printf -v "$var" '%s' "$input"
            return
        fi
        warn "This field is required."
    done
}

ask_optional() {
    # ask_optional <varname> <prompt> [default]
    local var="$1" prompt="$2" default="${3:-}"
    local hint=""
    [[ -n "$default" ]] && hint=" ${DIM}[${default}]${RESET}"
    printf "${BOLD}%s${RESET}%b: " "$prompt" "$hint"
    read -r input
    printf -v "$var" '%s' "${input:-$default}"
}

ask_secret() {
    # ask_secret <varname> <prompt>
    local var="$1" prompt="$2"
    while true; do
        printf "${BOLD}%s${RESET}: " "$prompt"
        read -rs input
        echo
        if [[ -n "$input" ]]; then
            printf -v "$var" '%s' "$input"
            return
        fi
        warn "This field is required."
    done
}

# ── Header ────────────────────────────────────────────────────────────────────
clear
echo
echo -e "${BOLD}${CYAN}  Hate Bot — Setup${RESET}"
echo -e "${DIM}  First-time install and configuration${RESET}"
echo
hr

# ── Guard: already set up? ────────────────────────────────────────────────────
if [[ -f .env ]]; then
    echo
    warn ".env already exists."
    printf "Overwrite it and reconfigure? ${DIM}[y/N]${RESET}: "
    read -r confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        info "Skipping .env setup. Running dependency install only..."
        SKIP_ENV=1
    else
        SKIP_ENV=0
    fi
else
    SKIP_ENV=0
fi

# ── Python check ──────────────────────────────────────────────────────────────
echo
info "Checking Python version..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c 'import sys; print(sys.version_info[:2])')
        major=$("$cmd" -c 'import sys; print(sys.version_info[0])')
        minor=$("$cmd" -c 'import sys; print(sys.version_info[1])')
        if [[ "$major" -ge 3 && "$minor" -ge 8 ]]; then
            PYTHON="$cmd"
            ok "Found $("$cmd" --version)"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python 3.8 or higher is required but was not found."
    echo "  Install it from https://www.python.org/downloads/ and re-run this script."
    exit 1
fi

# ── System dependencies ───────────────────────────────────────────────────────
echo
info "Checking system dependencies..."

if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg found ($(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3))"
else
    warn "ffmpeg not found — required for voice/TTS."
    printf "Install it now? ${DIM}[Y/n]${RESET}: "
    read -r do_ffmpeg
    if [[ ! "$do_ffmpeg" =~ ^[Nn]$ ]]; then
        if command -v apt &>/dev/null; then
            sudo apt update -qq && sudo apt install -y ffmpeg
        elif command -v brew &>/dev/null; then
            brew install ffmpeg
        else
            err "Could not auto-install ffmpeg. Install it manually: https://ffmpeg.org/download.html"
        fi
        command -v ffmpeg &>/dev/null && ok "ffmpeg installed." || err "ffmpeg still not found — TTS will not work."
    else
        warn "Skipping ffmpeg. Voice/TTS features will not work without it."
    fi
fi

# ── Virtual environment ───────────────────────────────────────────────────────
echo
info "Setting up virtual environment..."

if [[ -f venv/bin/activate ]]; then
    ok "venv already exists, skipping creation."
else
    if [[ -d venv ]]; then
        warn "venv/ directory exists but is incomplete — recreating it."
        rm -rf venv
    fi
    "$PYTHON" -m venv venv
    ok "Created venv/"
fi

# Activate
# shellcheck disable=SC1091
source venv/bin/activate
ok "Activated venv"

# ── Dependencies ──────────────────────────────────────────────────────────────
echo
info "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencies installed"

# ── .env configuration ────────────────────────────────────────────────────────
if [[ "$SKIP_ENV" -eq 0 ]]; then
    echo
    hr
    echo
    echo -e "${BOLD}Now let's configure the bot.${RESET}"
    echo -e "${DIM}Press Enter to accept a default shown in [brackets].${RESET}"
    echo

    # ── Discord token ──────────────────────────────────────────────────────
    echo -e "${CYAN}── Discord Bot Token ─────────────────────────────────────${RESET}"
    echo -e "${DIM}  Get this from: discord.com/developers/applications → your app → Bot → Reset Token${RESET}"
    echo
    ask DISCORD_TOKEN "Bot token"
    echo

    # ── Groq API key ───────────────────────────────────────────────────────
    echo -e "${CYAN}── Groq API Key ──────────────────────────────────────────${RESET}"
    echo -e "${DIM}  Free tier available at: console.groq.com${RESET}"
    echo
    ask GROQ_API_KEY "Groq API key"
    echo

    # ── Target configuration ───────────────────────────────────────────────
    echo -e "${CYAN}── Who should the bot roast? ─────────────────────────────${RESET}"
    echo -e "${DIM}  TARGET_NAME    — display name used in roasts and messages${RESET}"
    echo -e "${DIM}  TARGET_USERNAMES — their Discord username(s), comma-separated${RESET}"
    echo -e "${DIM}                    (lowercase, no # number — found in their profile)${RESET}"
    echo -e "${DIM}  TARGET_STOCK_TICKER — ticker on the in-bot stock market${RESET}"
    echo
    ask TARGET_NAME       "Target's name (e.g. Alex)"
    ask TARGET_USERNAMES  "Target's Discord username(s) (e.g. alexaccount,alexalt)"

    # Derive default ticker from name: uppercase, max 8 chars, letters only
    default_ticker=$(echo "$TARGET_NAME" | tr '[:lower:]' '[:upper:]' | tr -dc 'A-Z' | cut -c1-8)
    ask TARGET_STOCK_TICKER "Stock ticker for target" "$default_ticker"
    echo

    # ── Channel IDs ────────────────────────────────────────────────────────
    echo -e "${CYAN}── Discord Channel IDs ───────────────────────────────────${RESET}"
    echo -e "${DIM}  Enable Developer Mode (Settings → Advanced) then right-click a channel → Copy Channel ID${RESET}"
    echo
    ask          ROAST_CHANNEL_ID  "Roast channel ID (where roasts are posted)"
    ask_optional VOICE_CHANNEL_ID  "Voice channel ID for TTS (leave blank to skip)" ""
    echo

    # ── Admin dashboard ────────────────────────────────────────────────────
    echo -e "${CYAN}── Admin Dashboard ───────────────────────────────────────${RESET}"
    echo -e "${DIM}  Password for the web dashboard at http://localhost:47832${RESET}"
    echo
    ask_secret ADMIN_PASSWORD "Admin dashboard password"
    echo

    # ── Write .env ─────────────────────────────────────────────────────────
    hr
    echo
    info "Writing .env..."

    cat > .env <<EOF
# ── Required ──────────────────────────────────────────────────────────────────
DISCORD_TOKEN=${DISCORD_TOKEN}
GROQ_API_KEY=${GROQ_API_KEY}

# ── Target Configuration ──────────────────────────────────────────────────────
TARGET_NAME=${TARGET_NAME}
TARGET_USERNAMES=${TARGET_USERNAMES}
TARGET_STOCK_TICKER=${TARGET_STOCK_TICKER}

# ── Channel / Server ──────────────────────────────────────────────────────────
ROAST_CHANNEL_ID=${ROAST_CHANNEL_ID}
VOICE_CHANNEL_ID=${VOICE_CHANNEL_ID}

# ── Admin Dashboard ───────────────────────────────────────────────────────────
ADMIN_PASSWORD=${ADMIN_PASSWORD}
EOF

    chmod 600 .env
    ok ".env written (permissions set to 600)"
fi

# ── Optional systemd setup ────────────────────────────────────────────────────
echo
hr
echo
printf "Set up a systemd service to run the bot on startup? ${DIM}[y/N]${RESET}: "
read -r do_systemd

if [[ "$do_systemd" =~ ^[Yy]$ ]]; then
    BOT_DIR="$(pwd)"
    BOT_USER="$(whoami)"
    SERVICE_FILE="/etc/systemd/system/hatebot.service"

    SERVICE_CONTENT="[Unit]
Description=Hate Bot
After=network.target

[Service]
User=${BOT_USER}
WorkingDirectory=${BOT_DIR}
EnvironmentFile=${BOT_DIR}/.env
ExecStart=${BOT_DIR}/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"

    echo
    info "Writing ${SERVICE_FILE}..."
    echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable hatebot
    ok "Service installed and enabled"
    echo
    info "Start it now with:  ${BOLD}sudo systemctl start hatebot${RESET}"
    info "View logs with:     ${BOLD}sudo journalctl -u hatebot -f${RESET}"
else
    echo
    info "Skipping systemd setup."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo
hr
echo
echo -e "${GREEN}${BOLD}Setup complete!${RESET}"
echo
echo -e "  Start the bot:   ${BOLD}source venv/bin/activate && python bot.py${RESET}"
echo -e "  Admin dashboard: ${BOLD}http://localhost:47832${RESET}"
echo
