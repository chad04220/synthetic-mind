#!/usr/bin/env bash
# Synthetic Mind launcher for Linux/macOS. The first run creates a virtual environment.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi
exec python run.py "$@"
