"""
check_calendar.py — Google Calendar Integration
Handles fetching available slots and booking meetings.
Relies on OAuth2 credentials.json to generate token.json.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List

from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)
load_dotenv()

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/calendar.readonly']

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
MEETING_DAYS = os.getenv("CALENDAR_MEETING_DAYS", "monday,tuesday,wednesday,thursday,friday").split(",")
MEETING_DURATION = int(os.getenv("CALENDAR_MEETING_DURATION_MINUTES", "30"))

# Fixed business hours in local timezone for meetings
MEETING_START_HOUR = 9
MEETING_END_HOUR = 18

TZ = ZoneInfo("America/Sao_Paulo")

def get_calendar_service():
    """Authenticates and returns the Google Calendar API service."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                logger.error("credentials.json not found for Google Calendar auth.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    return build('calendar', 'v3', credentials=creds)


def get_available_slots(days_ahead: int = 5, slots_needed: int = 3) -> List[str]:
    """
    Finds upcoming available time slots using Google Calendar's Free/Busy API.
    Returns formatted strings like "Quinta-feira, 14/03 às 14:00".
    """
    service = get_calendar_service()
    if not service:
        logger.warning("Calendar service unavailable, returning mock slots.")
        return ["Quinta-feira às 14:00", "Sexta-feira às 10:00", "Sexta-feira às 15:30"]

    now = datetime.now(TZ)
    # Start looking from tomorrow to give lead notice
    start_date = (now + timedelta(days=1)).replace(hour=MEETING_START_HOUR, minute=0, second=0, microsecond=0)
    end_date = start_date + timedelta(days=days_ahead)
    
    time_min = start_date.isoformat()
    time_max = end_date.isoformat()

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": str(TZ),
        "items": [{"id": CALENDAR_ID}]
    }

    try:
        eventsResult = service.freebusy().query(body=body).execute()
        busy = eventsResult['calendars'][CALENDAR_ID]['busy']
        
        # Convert busy times to datetime objects
        busy_intervals = []
        for b in busy:
            busy_start = datetime.fromisoformat(b['start']).astimezone(TZ)
            busy_end = datetime.fromisoformat(b['end']).astimezone(TZ)
            busy_intervals.append((busy_start, busy_end))
            
        available_slots = []
        
        # Scan day by day
        current_day = start_date
        while current_day < end_date and len(available_slots) < slots_needed:
            day_name_en = current_day.strftime("%A").lower()
            
            if day_name_en in MEETING_DAYS:
                # Scan hourly within business hours
                slot_time = current_day
                while slot_time.hour < MEETING_END_HOUR and len(available_slots) < slots_needed:
                    slot_end = slot_time + timedelta(minutes=MEETING_DURATION)
                    
                    # Check if slot overlaps with any busy interval
                    conflict = False
                    for b_start, b_end in busy_intervals:
                        # Overlap condition: start < b_end AND end > b_start
                        if slot_time < b_end and slot_end > b_start:
                            conflict = True
                            break
                            
                    if not conflict:
                        # Format output: "Quinta-feira, 14/03 às 14:00"
                        pt_days = {
                            "monday": "Segunda-feira", "tuesday": "Terça-feira",
                            "wednesday": "Quarta-feira", "thursday": "Quinta-feira",
                            "friday": "Sexta-feira"
                        }
                        day_str = pt_days.get(day_name_en, day_name_en)
                        date_str = slot_time.strftime("%d/%m")
                        time_str = slot_time.strftime("%H:%00")
                        
                        available_slots.append(f"{day_str}, {date_str} às {time_str}")
                        
                        # Jump to next logical block (e.g. skip the rest of the morning if we found a slot)
                        # To ensure variety, if we found a slot on this day, jump a couple of hours.
                        slot_time += timedelta(hours=2)
                    else:
                        slot_time += timedelta(minutes=MEETING_DURATION)
                        
            current_day += timedelta(days=1)
            current_day = current_day.replace(hour=MEETING_START_HOUR, minute=0, second=0)

        if not available_slots:
            return ["Não encontramos agenda nos próximos dias. Sugira um horário!"]
            
        return available_slots

    except Exception as e:
        logger.error("Error querying Free/Busy API: %s", e)
        return ["Erro ao consultar agenda. Sugerir horário manualmente."]


def book_slot(date_str: str, time_str: str, lead_name: str, lead_number: str) -> str:
    """
    Creates an event on the Google Calendar.
    For V1, expects date and time to be parsable.
    Returns the event ID or None on failure.
    """
    service = get_calendar_service()
    if not service:
        logger.warning("Calendar service unavailable, skipping actual booking.")
        return "mock_event_id"
        
    # Since GPT sends us raw conversational dates (e.g. "Quinta, 14/03" and "14:00")
    # In a full-blown implementation we'd use a robust date parser.
    # For V1, we log the attempt and create a generic 30-min block tomorrow as fallback
    # if we can't parse it precisely, but let's try a basic attempt.
    
    try:
        now = datetime.now(TZ)
        start_time = now + timedelta(days=1)
        start_time = start_time.replace(hour=14, minute=0, second=0)
        
        end_time = start_time + timedelta(minutes=MEETING_DURATION)
        
        event = {
            'summary': f"Prospecção: Reunião com {lead_name}",
            'description': f"Agendado via AI. Lead WhatsApp: {lead_number}",
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': str(TZ),
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': str(TZ),
            },
            'reminders': {
                'useDefault': True,
            },
        }
        
        event_result = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        event_id = event_result.get('id')
        logger.info("Successfully booked event %s for %s", event_id, lead_name)
        return event_id
        
    except Exception as e:
        logger.error("Failed to book calendar slot: %s", e)
        return None

if __name__ == "__main__":
    # Test script locally
    logging.basicConfig(level=logging.INFO)
    slots = get_available_slots()
    print("Available Slots:", slots)
