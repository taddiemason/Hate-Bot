#!/usr/bin/env bash
set -e

echo "Pulling latest..."
git pull origin Main

echo "Stopping running bot (if any)..."
pkill -f bot.py || true
