#!/bin/bash
set -euo pipefail

PLIST_SRC="$(cd "$(dirname "$0")/.." && pwd)/config/com.bartlettlabs.purdue.calendar.refresh.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.bartlettlabs.purdue.calendar.refresh.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs/purdue-calendar"

cp "$PLIST_SRC" "$PLIST_DST"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "Installed LaunchAgent:"
echo "  $PLIST_DST"
echo "Runs daily at 6:15 AM local time and at login."
echo "Logs: ~/Library/Logs/purdue-calendar/"
