#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List
import yaml
from filelock import FileLock, Timeout

from scripts.utils import expanduser_path, ensure_dir, now_local, iso_ts, load_json, save_json, safe_print, slug
from scripts.scrape_espn import scrape_espn_schedule
from scripts.gcal import get_service, get_or_create_calendar, list_events_window, upsert_event

def stable_id(date_iso: str, opponent: str, phase: str) -> str:
    return f"{date_iso}-{slug(opponent)}-{slug(phase)}"

def build_event_body(game: dict, reminders_minutes: List[int], target_tz_name: str = "America/New_York") -> dict:
    date_iso = game["date"]
    game_time = game.get("time", "")
    title_base = f"Purdue vs {game['opponent']}"
    title = f"{title_base} — {game['result']}" if game.get("result") else title_base

    desc_lines = []
    if game.get("tv"):
        desc_lines.append(f"TV: {game['tv']}")
    if game.get("result"):
        desc_lines.append(f"Result: {game['result']}")
    if game.get("link"):
        label = "Recap" if game.get("result") else "Game Center"
        desc_lines.append(f"{label}: {game['link']}")
    if game.get("notes"):
        desc_lines.append(game["notes"])
    description = "\n".join(desc_lines).strip()

    # If we have a game time, create a timed event; otherwise all-day
    if game_time and game_time != "TBD":
        try:
            import pytz
            # Parse time like "2:00 PM" or "10:00 AM" (Assume source is ALWAYS Eastern Time for Purdue/ESPN)
            source_tz = pytz.timezone("America/New_York")
            target_tz = pytz.timezone(target_tz_name)
            
            # Create naive datetime from scraped date + time
            naive_dt = datetime.strptime(f"{date_iso} {game_time}", "%Y-%m-%d %I:%M %p")
            
            # Localize to Eastern Time
            et_dt = source_tz.localize(naive_dt)
            
            # Convert to Target Timezone (e.g. Central)
            local_dt = et_dt.astimezone(target_tz)
            
            # Games are typically ~2.5 hours
            end_dt = local_dt + timedelta(hours=2, minutes=30)

            start_end = {
                "start": {"dateTime": local_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": target_tz_name, "date": None},
                "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": target_tz_name, "date": None},
            }
        except ValueError:
            # Fallback to all-day if time parsing fails
            start_end = {
                "start": {"date": date_iso, "dateTime": None, "timeZone": None},
                "end": {"date": date_iso, "dateTime": None, "timeZone": None},
            }
    else:
        start_end = {
            "start": {"date": date_iso, "dateTime": None, "timeZone": None},
            "end": {"date": date_iso, "dateTime": None, "timeZone": None},
        }

    return {
        "summary": title,
        "description": description,
        "location": game.get("location", "") or "",
        **start_end,
        "reminders": {
            "useDefault": False,
            "overrides": [{"method":"popup","minutes": int(m)} for m in reminders_minutes]
        },
    }

def diff_game(old: dict, new: dict) -> Dict:
    changes = {}
    for k in ["opponent", "location", "tv", "result", "date", "phase", "time", "link"]:
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
        espn_games = scrape_espn_schedule(cfg["sources"]["espn"])

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
                "time": "",
                "result": "",
                "notes": ""
            })
            if eg.get("tv"):
                g["tv"] = eg["tv"]
            if eg.get("time"):
                g["time"] = eg["time"]
            if eg.get("result"):
                g["result"] = eg["result"]
            if eg.get("link"):
                g["link"] = eg["link"]
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

        events = list_events_window(service, cal_id, cfg["google_calendar"]["time_min"], cfg["google_calendar"]["time_max"])
        existing_by_stable = {}
        for ev in events:
            ep = (ev.get("extendedProperties", {}) or {}).get("private", {}) or {}
            sid = ep.get("stable_id")
            if sid:
                existing_by_stable[sid] = ev

        reminders = cfg["notifications"]["reminders_minutes"]
        for g in games_new:
            try:
                body = build_event_body(g, reminders, tz)
                result = upsert_event(service, cal_id, g["stable_id"], body, existing_by_stable)
                if result == "created":
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                errors += 1
                warnings.append(f"Failed to update game {g['date']} vs {g['opponent']}: {e}")
                # safe_print(f"DEBUG: Failed body for {g['opponent']}: {json.dumps(body, indent=2)}")

    except Exception as e:
        errors += 1
        warnings.append(f"Google Calendar setup failed: {e}")

    finished = now_local(tz)
    status = "ok" if errors == 0 else "error"

    run = {
        "started_at": iso_ts(started),
        "finished_at": iso_ts(finished),
        "status": status,
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

    lines = []
    lines.append(f"# Purdue Calendar Refresh — {run['status'].upper()}")
    lines.append(f"- Started: {run['started_at']}")
    lines.append(f"- Finished: {run['finished_at']}")
    lines.append(f"- Created: {created}")
    lines.append(f"- Updated: {updated}")
    lines.append(f"- Unchanged: {unchanged}")
    lines.append(f"- Errors: {errors}")
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
    lines.append("")
    lines.append("## Changed games (this run)")
    if not changed:
        lines.append("- None")
    else:
        for item in changed[:50]:
            ch = ", ".join([f"{k}: {v['from']} → {v['to']}" for k, v in item["changes"].items()])
            lines.append(f"- {item['date']} vs {item['opponent']}: {ch}")

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
