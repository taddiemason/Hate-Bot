#!/usr/bin/env bash
set -e

echo "Pulling latest..."
git pull origin Main

pkill -f bot.py

source venv/bin/activate
python bot.py
