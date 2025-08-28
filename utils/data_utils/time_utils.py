from typing import Union, Optional
import re
from datetime import datetime, date
from dateutil import parser


def parse_time_str(value: Optional[str]) -> Optional[str]:
    """
    Parse and normalize appointment time into 24-hour 'HH:MM' format.
    Supports:
        - '3 am'
        - '03:00 pm'
        - '11:30Am'
        - '14:00' (24-hour format)
    Returns None if invalid.
    """
    if not value:
        return None

    v = value.strip().upper().replace(" ", "")

    for fmt in ["%I:%M%p", "%I%p", "%H:%M"]:  # try 12h+AM/PM and 24h
        try:
            parsed_time = datetime.strptime(v, fmt)
            return parsed_time.strftime("%H:%M")  # always save in 24-hour format
        except ValueError:
            continue

    return None

def format_time_str(t: Optional[str]) -> Optional[str]:
    """Ensure time is displayed as 'HH:MM AM/PM'."""
    if not t:
        return None
    try:
        parsed_time = datetime.strptime(t.strip().upper(), "%I:%M %p")
        return parsed_time.strftime("%I:%M %p")
    except Exception:
        return t



def human_time(t: Optional[str]) -> Optional[str]:
    """
    Convert normalized time string '05:00 AM' -> '5AM'
    """
    if not t:
        return None
    try:
        parsed = datetime.strptime(t.strip().upper(), "%I:%M %p")
        return parsed.strftime("%-I%p")  
    except ValueError:
        return None