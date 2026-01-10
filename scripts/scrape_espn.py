from __future__ import annotations
import re
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def scrape_espn_schedule(url: str) -> List[Dict]:
    html = requests.get(url, timeout=25, headers={"User-Agent":"purdue-calendar-bot/1.0"}).text
    soup = BeautifulSoup(html, "html.parser")

    games: List[Dict] = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 2:
                continue
            cells = [_clean(td.get_text(" ", strip=True)) for td in tds]
            if not cells or cells[0].lower().startswith("date"):
                continue

            # Date parse (handles 'Sat, Nov 28' style)
            try:
                dt = dtparser.parse(cells[0], fuzzy=True)
            except Exception:
                continue

            opponent = cells[1]
            tv = ""
            result = ""
            time = ""

            # Look for time, W/L score, and TV tokens in remaining cells
            for c in cells[2:]:
                # Check for game time (e.g., "2:00 PM", "10:00 AM", "TBD")
                time_match = re.search(r"^(\d{1,2}:\d{2}\s*(?:AM|PM))$", c, re.I)
                if time_match:
                    time = time_match.group(1).upper()
                # Check for W/L result
                if re.search(r"\b[WL]\b\s*\d+[-–]\d+", c):
                    result = c.replace("–", "-")
                # Check for TV network
                if re.search(r"\b(ESPN|FOX|CBS|BTN|FS1|FS2|NBC|Peacock)\b", c, re.I):
                    tv = c

            games.append({
                "date": dt.strftime("%Y-%m-%d"),
                "time": time,
                "opponent": opponent,
                "location": "",
                "tv": tv,
                "result": result
            })

    # Deduplicate by (date, opponent)
    seen = set()
    out = []
    for g in games:
        key = (g["date"], g["opponent"])
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out
