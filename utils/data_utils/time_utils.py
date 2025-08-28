from typing import Union, Optional
import re
from datetime import datetime, date
from dateutil import parser


def parse_time_str(value: Optional[str]) -> Optional[str]:
    """
    Parse and normalize appointment time into 'HH:MM AM/PM' format.
    Accepts variations like:
        - '3 am'
        - '03:00 pm'
        - '11:30Am'
    Returns None if invalid.
    """
    if not value:
        return None

    v = value.strip().upper().replace(" ", "")

    try:
        # Try "HH:MMAM/PM"
        parsed_time = datetime.strptime(v, "%I:%M%p")
    except ValueError:
        try:
            # Try "HAM/PM"
            parsed_time = datetime.strptime(v, "%I%p")
        except ValueError:
            return None  

    return parsed_time.strftime("%I:%M %p")


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