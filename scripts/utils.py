import json
import os
import re
from pathlib import Path
from datetime import datetime
import pytz

def expanduser_path(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def slug(s: str) -> str:
    s = normalize_ws(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def now_local(tz_name: str) -> datetime:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz)

def iso_ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")

def load_json(path: Path) -> dict:
    return json.loads(path.read_text())

def save_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2))

def safe_print(s: str) -> None:
    print(s, flush=True)
