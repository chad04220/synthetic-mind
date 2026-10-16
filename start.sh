#!/usr/bin/env bash
# Synthetic Mind launcher for Linux/macOS. The first run creates a virtual environment; the
# requirements are installed again whenever requirements.txt changes.
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
if ! cmp -s requirements.txt .venv/requirements.installed; then
  pip install --upgrade pip
  pip install -r requirements.txt
  cp requirements.txt .venv/requirements.installed
fi
exec python run.py "$@"
