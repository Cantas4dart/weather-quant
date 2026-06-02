#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/weather-terminal}"
PYTHON="${PYTHON:-python3.12}"

sudo apt-get update
sudo apt-get install -y "$PYTHON" "$PYTHON-venv" git build-essential
sudo mkdir -p "$APP_DIR"
sudo chown "$USER":"$USER" "$APP_DIR"

cd "$APP_DIR"
"$PYTHON" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
mkdir -p data logs

echo "Copy .env.example to .env, edit secrets, then install deploy/weather-terminal.service."

