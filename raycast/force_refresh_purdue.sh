#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Force Refresh Purdue Calendar
# @raycast.mode fullOutput
# @raycast.packageName Purdue Calendar
# @raycast.icon 🏀
# @raycast.description Daily scrape + Google Calendar upsert + score/TV refresh + logs + optional Obsidian summary write.

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Run setup:"
  echo "python3 -m venv .venv"
  echo "source .venv/bin/activate"
  echo "pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate
python scripts/purdue_refresh_from_web.py --config config.yml
