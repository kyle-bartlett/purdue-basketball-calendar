#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import yaml

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--out", default="exports/Purdue_MBB_Schedule.md")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    data = json.loads(Path("data/schedule.json").read_text())
    games = data.get("games", [])

    lines = []
    lines.append(f"# Purdue Men’s Basketball {cfg['season']}")
    lines.append("")
    lines.append("| Date | Opponent | Phase | TV | Result | Location |")
    lines.append("|---|---|---|---|---|---|")
    for g in games:
        lines.append(f"| {g.get('date','')} | {g.get('opponent','')} | {g.get('phase','')} | {g.get('tv','')} | {g.get('result','')} | {g.get('location','')} |")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))

if __name__ == "__main__":
    main()
