from __future__ import annotations
from typing import Dict, List
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_service(credentials_path: Path, token_path: Path):
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def get_or_create_calendar(service, calendar_name: str) -> str:
    page_token = None
    while True:
        cal_list = service.calendarList().list(pageToken=page_token).execute()
        for item in cal_list.get("items", []):
            if item.get("summary") == calendar_name:
                return item["id"]
        page_token = cal_list.get("nextPageToken")
        if not page_token:
            break
    created = service.calendars().insert(body={"summary": calendar_name}).execute()
    return created["id"]

def list_events_window(service, calendar_id: str, time_min: str, time_max: str) -> List[dict]:
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events

def upsert_event(service, calendar_id: str, stable_id: str, body: dict, existing_by_stable: Dict[str, dict]) -> str:
    ep = body.get("extendedProperties", {}) or {}
    priv = ep.get("private", {}) or {}
    priv["stable_id"] = stable_id
    ep["private"] = priv
    body["extendedProperties"] = ep

    if stable_id in existing_by_stable:
        event_id = existing_by_stable[stable_id]["id"]
        service.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()
        return "updated"
    service.events().insert(calendarId=calendar_id, body=body).execute()
    return "created"
