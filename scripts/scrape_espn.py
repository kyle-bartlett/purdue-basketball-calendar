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
            
            # Extract text for basic parsing
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
            game_link = ""

            # Look for time, W/L score, TV tokens, and LINKS in remaining cells
            # We iterate through the tds (skipping first two: Date, Opponent) matching the cells
            for i, td in enumerate(tds[2:], start=2):
                text = cells[i]
                
                # Check for game time (e.g., "2:00 PM", "10:00 AM", "TBD")
                time_match = re.search(r"^(\d{1,2}:\d{2}\s*(?:AM|PM))$", text, re.I)
                if time_match:
                    time = time_match.group(1).upper()
                    # If this cell has a link, it's the game preview/tickets
                    link_tag = td.find("a", href=True)
                    if link_tag and "gameId" in link_tag["href"]:
                         game_link = link_tag["href"]

                # Check for W/L result
                if re.search(r"\b[WL]\b\s*\d+[-–]\d+", text):
                    result = text.replace("–", "-")
                    # If this cell has a link, it's the recap
                    link_tag = td.find("a", href=True)
                    if link_tag and "gameId" in link_tag["href"]:
                         game_link = link_tag["href"]

                # Check for TV network
                if re.search(r"\b(ESPN|FOX|CBS|BTN|FS1|FS2|NBC|Peacock)\b", text, re.I):
                    tv = text

            # Normalize link
            if game_link and not game_link.startswith("http"):
                game_link = f"https://www.espn.com{game_link}"

            games.append({
                "date": dt.strftime("%Y-%m-%d"),
                "time": time,
                "opponent": opponent,
                "location": "",
                "tv": tv,
                "result": result,
                "link": game_link
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
