#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple
import yaml
from filelock import FileLock, Timeout

from scripts.utils import expanduser_path, ensure_dir, now_local, iso_ts, load_json, save_json, safe_print, slug
from scripts.scrape_espn import scrape_espn_schedule
from scripts.gcal import get_service, get_or_create_calendar, list_events_window, upsert_event

def stable_id(date_iso: str, opponent: str, phase: str) -> str:
    return f"{date_iso}-{slug(opponent)}-{slug(phase)}"

def parse_season(season: str) -> Tuple[int, int]:
    """Parse season string like '2025-2026' into (start_year, end_year)."""
    match = re.match(r"(\d{4})-(\d{4})", season)
    if match:
        return int(match.group(1)), int(match.group(2))
    raise ValueError(f"Invalid season format: {season}")

def get_time_window(cfg: dict) -> Tuple[str, str]:
    """Get time_min and time_max, auto-calculating from season if not specified."""
    gcal = cfg.get("google_calendar", {})
    if gcal.get("time_min") and gcal.get("time_max"):
        return gcal["time_min"], gcal["time_max"]

    # Auto-calculate from season
    start_year, end_year = parse_season(cfg["season"])
    time_min = f"{start_year}-10-01T00:00:00"
    time_max = f"{end_year}-04-30T00:00:00"
    return time_min, time_max

def calculate_record(games: List[dict], up_to_date: str) -> Tuple[int, int]:
    """Calculate W-L record for games up to (and including) a given date."""
    wins = 0
    losses = 0
    for g in games:
        if g["date"] > up_to_date:
            continue
        result = g.get("result", "")
        if result.startswith("W"):
            wins += 1
        elif result.startswith("L"):
            losses += 1
    return wins, losses

def build_event_body(game: dict, reminders_minutes: List[int], record: Tuple[int, int] | None = None) -> dict:
    date_iso = game["date"]
    title_base = f"Purdue vs {game['opponent']}"

    # Include result and record in title for completed games
    if game.get("result"):
        if record and (record[0] > 0 or record[1] > 0):
            title = f"{title_base} — {game['result']} ({record[0]}-{record[1]})"
        else:
            title = f"{title_base} — {game['result']}"
    else:
        title = title_base

    desc_lines = []
    if game.get("tv"):
        desc_lines.append(f"TV: {game['tv']}")
    if game.get("result"):
        desc_lines.append(f"Result: {game['result']}")
        if record and (record[0] > 0 or record[1] > 0):
            desc_lines.append(f"Record: {record[0]}-{record[1]}")
    if game.get("notes"):
        desc_lines.append(game["notes"])
    description = "\n".join(desc_lines).strip()

    return {
        "summary": title,
        "description": description,
        "location": game.get("location", "") or "",
        "start": {"date": date_iso},
        "end": {"date": date_iso},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method":"popup","minutes": int(m)} for m in reminders_minutes]
        },
    }

def diff_game(old: dict, new: dict) -> Dict:
    changes = {}
    for k in ["opponent", "location", "tv", "result", "date", "phase"]:
        if (old.get(k, "") or "") != (new.get(k, "") or ""):
            changes[k] = {"from": old.get(k, ""), "to": new.get(k, "")}
    return changes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    tz = cfg["timezone"]
    log_dir = expanduser_path(cfg["logging"]["log_dir"])
    lock_file = expanduser_path(cfg["logging"]["lock_file"])
    ensure_dir(log_dir)

    lock = FileLock(str(lock_file))
    try:
        lock.acquire(timeout=2)
    except Timeout:
        safe_print("Another refresh is already running. Exiting.")
        return

    started = now_local(tz)
    warnings = []
    errors = 0

    data_path = Path("data/schedule.json")
    data = load_json(data_path)
    games_old = data.get("games", [])

    # Pull latest schedule/results from ESPN (best-effort)
    games_new = games_old
    try:
        espn_games = scrape_espn_schedule(cfg["sources"]["espn"], season=cfg.get("season"))

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

        placeholders = [g for g in games_old if g.get("phase") in ("big_ten_tournament", "ncaa_tournament", "placeholder")]
        games_new = merged_regular + placeholders

    except Exception as e:
        warnings.append(f"ESPN scrape failed: {e}")

    # Compute stable IDs
    for g in games_new:
        g["phase"] = g.get("phase") or "regular"
        g["stable_id"] = stable_id(g["date"], g["opponent"], g["phase"])

    # Diff
    old_by_id = {g.get("stable_id", ""): g for g in games_old if g.get("stable_id")}
    changed = []
    unchanged = 0
    for g in games_new:
        sid = g["stable_id"]
        if sid in old_by_id:
            d = diff_game(old_by_id[sid], g)
            if d:
                changed.append({"stable_id": sid, "date": g["date"], "opponent": g["opponent"], "changes": d})
            else:
                unchanged += 1

    # Save updated data
    data["games"] = games_new
    data["generated_at"] = iso_ts(now_local(tz))
    save_json(data_path, data)

    created = updated = 0
    try:
        cred = Path(cfg["google_calendar"]["credentials_path"])
        token = Path(cfg["google_calendar"]["token_path"])
        service = get_service(cred, token)
        cal_id = get_or_create_calendar(service, cfg["google_calendar"]["calendar_name"])

        time_min, time_max = get_time_window(cfg)
        events = list_events_window(service, cal_id, time_min, time_max)
        existing_by_stable = {}
        for ev in events:
            ep = (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}
            sid = ep.get("stable_id")
            if sid:
                existing_by_stable[sid] = ev

        reminders = cfg["notifications"]["reminders_minutes"]
        # Sort games by date for accurate record calculation
        sorted_games = sorted(games_new, key=lambda x: x["date"])
        for g in sorted_games:
            record = calculate_record(sorted_games, g["date"]) if g.get("result") else None
            body = build_event_body(g, reminders, record)
            result = upsert_event(service, cal_id, g["stable_id"], body, existing_by_stable)
            if result == "created":
                created += 1
            else:
                updated += 1

    except Exception as e:
        errors += 1
        warnings.append(f"Google Calendar update failed: {e}")

    finished = now_local(tz)
    status = "ok" if errors == 0 else "error"

    # Calculate current record for run data
    sorted_for_record = sorted(games_new, key=lambda x: x["date"])
    wins, losses = calculate_record(sorted_for_record, "9999-12-31")

    run = {
        "started_at": iso_ts(started),
        "finished_at": iso_ts(finished),
        "status": status,
        "record": f"{wins}-{losses}",
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
        "changed_games": changed[:200],
        "warnings": warnings,
        "log_dir": str(log_dir),
    }

    stamp = finished.strftime("%Y-%m-%d_%H%M%S")
    json_path = log_dir / f"run-{stamp}.json"
    md_path = log_dir / f"run-{stamp}.md"
    latest_json = log_dir / "run-latest.json"
    latest_md = log_dir / "run-latest.md"

    json_path.write_text(json.dumps(run, indent=2))
    latest_json.write_text(json.dumps(run, indent=2))

    # Calculate current season record
    sorted_games = sorted(games_new, key=lambda x: x["date"])
    total_wins, total_losses = calculate_record(sorted_games, "9999-12-31")

    lines = []
    lines.append(f"# Purdue Calendar Refresh — {run['status'].upper()}")
    lines.append(f"**Season Record: {total_wins}-{total_losses}**")
    lines.append("")
    lines.append(f"- Started: {run['started_at']}")
    lines.append(f"- Finished: {run['finished_at']}")
    lines.append(f"- Created: {created}")
    lines.append(f"- Updated: {updated}")
    lines.append(f"- Unchanged: {unchanged}")
    lines.append(f"- Errors: {errors}")

    # Prominently show schedule changes
    if changed:
        lines.append("")
        lines.append("## ⚠️ SCHEDULE CHANGES DETECTED")
        for item in changed[:50]:
            ch = ", ".join([f"{k}: {v['from']} → {v['to']}" for k, v in item["changes"].items()])
            lines.append(f"- **{item['date']}** vs {item['opponent']}: {ch}")
    else:
        lines.append("")
        lines.append("## Schedule Changes")
        lines.append("- No changes detected")

    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")

    # Show upcoming games
    today = finished.strftime("%Y-%m-%d")
    upcoming = [g for g in sorted_games if g["date"] >= today and not g.get("result")][:5]
    if upcoming:
        lines.append("")
        lines.append("## Upcoming Games")
        for g in upcoming:
            tv_info = f" ({g['tv']})" if g.get("tv") else ""
            lines.append(f"- **{g['date']}**: vs {g['opponent']}{tv_info}")

    md = "\n".join(lines)
    md_path.write_text(md)
    latest_md.write_text(md)

    # Optional Obsidian write of the latest summary
    try:
        obs = cfg.get("obsidian", {})
        if obs.get("enabled") and obs.get("vault_path"):
            vault = Path(obs["vault_path"]).expanduser()
            out_file = vault / obs["output_file"]
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(md)
    except Exception as e:
        warnings.append(f"Obsidian write failed: {e}")

    safe_print(md)
    safe_print("")
    safe_print(f"Log JSON: {json_path}")
    safe_print(f"Log MD:   {md_path}")

    lock.release()

if __name__ == "__main__":
    main()
