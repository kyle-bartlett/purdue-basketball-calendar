from __future__ import annotations
import re
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _parse_season(season: str) -> tuple[int, int]:
    """Parse season string like '2025-2026' into (start_year, end_year)."""
    match = re.match(r"(\d{4})-(\d{4})", season)
    if match:
        return int(match.group(1)), int(match.group(2))
    raise ValueError(f"Invalid season format: {season}")

def _assign_year(month: int, start_year: int, end_year: int) -> int:
    """Assign correct year based on month for a college basketball season.

    Oct-Dec games belong to start_year, Jan-Apr games belong to end_year.
    """
    if month >= 10:  # Oct, Nov, Dec
        return start_year
    else:  # Jan-Sep (realistically Jan-Apr for basketball)
        return end_year

def scrape_espn_schedule(url: str, season: Optional[str] = None) -> List[Dict]:
    html = requests.get(url, timeout=25, headers={"User-Agent":"purdue-calendar-bot/1.0"}).text
    soup = BeautifulSoup(html, "html.parser")

    # Parse season for year assignment
    start_year, end_year = None, None
    if season:
        start_year, end_year = _parse_season(season)

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

            # Fix year based on season context
            if start_year and end_year:
                correct_year = _assign_year(dt.month, start_year, end_year)
                dt = dt.replace(year=correct_year)

            opponent = cells[1]
            tv = ""
            result = ""

            # Look for W/L score and TV tokens in remaining cells
            for c in cells[2:]:
                if re.search(r"\b[WL]\b\s*\d+[-–]\d+", c):
                    result = c.replace("–", "-")
                if re.search(r"\b(ESPN[2U]?|ABC|FOX|CBS|CBSSN|BTN|FS[12]|NBC|Peacock|TBS|TNT|truTV|MAX)\b", c, re.I):
                    tv = c

            games.append({
                "date": dt.strftime("%Y-%m-%d"),
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
