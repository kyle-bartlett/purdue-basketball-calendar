# Purdue Men’s Basketball Calendar (Direct Google Calendar API)

This project creates/updates a dedicated Google Calendar daily with Purdue MBB games, including win/loss and score when available.

## Install (Mac)

1) Create folder:
   ~/purdue-basketball-calendar

2) Copy this pack’s contents into that folder.

3) Setup:
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

4) Google Calendar OAuth (one-time):
   - Enable Google Calendar API in Google Cloud
   - Create OAuth Client ID: Desktop App
   - Download the OAuth JSON into this repo as `credentials.json`

5) Initial run:
   source .venv/bin/activate
   python scripts/purdue_to_gcal.py --config config.yml

## Daily Auto Refresh (macOS)
./scripts/install_launchd.sh

## Raycast
Add the `raycast/` folder as a Script Commands directory.
