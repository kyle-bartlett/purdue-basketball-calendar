#!/usr/bin/env python3
"""
CI-safe script to update schedule.json from ESPN.
Does not require Google Calendar credentials - just scrapes and updates the data file.
Designed to run in GitHub Actions and commit changes back to the repo.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import yaml

from scripts.scrape_espn import scrape_espn_schedule


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def stable_id(date_iso: str, opponent: str, phase: str) -> str:
    return f"{date_iso}-{slug(opponent)}-{slug(phase)}"


def calculate_record(games: List[dict], up_to_date: str) -> Tuple[int, int]:
    """Calculate W-L record for games up to (and including) a given date."""
    wins = losses = 0
    for g in games:
        if g["date"] > up_to_date:
            continue
        result = g.get("result", "")
        if result.startswith("W"):
            wins += 1
        elif result.startswith("L"):
            losses += 1
    return wins, losses


def diff_game(old: dict, new: dict) -> dict:
    changes = {}
    for k in ["opponent", "location", "tv", "result", "date", "phase"]:
        if (old.get(k, "") or "") != (new.get(k, "") or ""):
            changes[k] = {"from": old.get(k, ""), "to": new.get(k, "")}
    return changes


def main():
    ap = argparse.ArgumentParser(description="Update schedule.json from ESPN (CI-safe)")
    ap.add_argument("--config", default="config.yml")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    tz_name = cfg["timezone"]

    data_path = Path("data/schedule.json")
    data = json.loads(data_path.read_text()) if data_path.exists() else {"games": []}
    games_old = data.get("games", [])

    # Pull latest schedule/results from ESPN
    print(f"Scraping ESPN schedule for {cfg['season']}...")
    try:
        espn_games = scrape_espn_schedule(cfg["sources"]["espn"], season=cfg.get("season"))
        print(f"  Found {len(espn_games)} games from ESPN")
    except Exception as e:
        print(f"ERROR: ESPN scrape failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Merge ESPN data with existing data
    existing_regular = {(g["date"], g["opponent"]): g for g in games_old if g.get("phase", "regular") == "regular"}
    merged_regular = []
    for eg in espn_games:
        key = (eg["date"], eg["opponent"])
        g = existing_regular.get(key, {
            "date": eg["date"],
            "opponent": eg["opponent"],
            "location": "",
            "phase": "regular",
            "tv": "",
            "result": "",
            "notes": ""
        })
        if eg.get("tv"):
            g["tv"] = eg["tv"]
        if eg.get("result"):
            g["result"] = eg["result"]
        merged_regular.append(g)

    # Keep tournament placeholders
    placeholders = [g for g in games_old if g.get("phase") in ("big_ten_tournament", "ncaa_tournament", "placeholder")]
    games_new = merged_regular + placeholders

    # Compute stable IDs
    for g in games_new:
        g["phase"] = g.get("phase") or "regular"
        g["stable_id"] = stable_id(g["date"], g["opponent"], g["phase"])

    # Calculate changes
    old_by_id = {g.get("stable_id", ""): g for g in games_old if g.get("stable_id")}
    changed = []
    for g in games_new:
        sid = g["stable_id"]
        if sid in old_by_id:
            d = diff_game(old_by_id[sid], g)
            if d:
                changed.append({"date": g["date"], "opponent": g["opponent"], "changes": d})

    # Save updated data
    now_utc = datetime.now(timezone.utc).isoformat()
    data["games"] = games_new
    data["generated_at"] = now_utc
    data_path.write_text(json.dumps(data, indent=2) + "\n")

    # Calculate and display record
    sorted_games = sorted(games_new, key=lambda x: x["date"])
    wins, losses = calculate_record(sorted_games, "9999-12-31")

    print(f"\n{'='*50}")
    print(f"Season Record: {wins}-{losses}")
    print(f"Total games: {len(games_new)}")
    print(f"{'='*50}")

    if changed:
        print(f"\n⚠️  SCHEDULE CHANGES DETECTED ({len(changed)}):")
        for item in changed[:20]:
            ch = ", ".join([f"{k}: {v['from']} → {v['to']}" for k, v in item["changes"].items()])
            print(f"  • {item['date']} vs {item['opponent']}: {ch}")
        if len(changed) > 20:
            print(f"  ... and {len(changed) - 20} more changes")
    else:
        print("\nNo schedule changes detected.")

    # Show next 5 upcoming games
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [g for g in sorted_games if g["date"] >= today and not g.get("result")][:5]
    if upcoming:
        print("\nUpcoming games:")
        for g in upcoming:
            tv = f" ({g['tv']})" if g.get("tv") else ""
            print(f"  • {g['date']}: vs {g['opponent']}{tv}")

    print(f"\nUpdated {data_path}")


if __name__ == "__main__":
    main()
