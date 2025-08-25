from datetime import datetime
from typing import Optional, Union
from dateutil import parser


def parse_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Safely parse strings into datetime using python-dateutil.
    - Returns datetime if parsed
    - Returns None if value is None or invalid
    - Returns value if already datetime
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    try:
        return parser.parse(value)
    except Exception:
        return None


def format_datetime(value: Union[str, datetime, None]) -> Optional[str]:
    """
    Format datetime or string into ISO format for storage.
    - If datetime -> isoformat
    - If string -> return as-is
    - If None -> None
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    return str(value)