from typing import Union, Optional
from datetime import datetime, date,timedelta
from dateutil import parser


def parse_date(value: Union[str, date, datetime, None]) -> Optional[date]:
    """
    Safely parse strings into `date`.
    - Returns `date` if parsed successfully
    - Returns None if value is None or invalid
    - If already a `date` -> return as-is
    - If datetime -> extract date
    """
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value  # already a date

    if isinstance(value, datetime):
        return value.date()

    try:
        return parser.parse(value).date()
    except Exception:
        return None



def parse_datetime(value: str) -> Optional[datetime]:
    if not value or value.lower() == "null":
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None
    
    
    

def format_date(value: Union[str, date, datetime, None]) -> Optional[str]:
    """
    Format date/datetime/string into DD/MM/YYYY format.
    - If `date` or `datetime` -> format as DD/MM/YYYY
    - If string -> try to parse, then format
    - If None -> None
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    try:
        parsed = parser.parse(value).date()
        return parsed.strftime("%d/%m/%Y")
    except Exception:
        return None


def format_datetime(value: Union[str, datetime, None]) -> Optional[str]: 
    """ Format datetime or string into ISO format for storage. - If datetime -> isoformat - If string -> return as-is - If None -> None """ 
    if value is None: 
        return None 
    
    if isinstance(value, datetime): 
        return value.isoformat() 
    
    return str(value)

def get_next_two_dates():
    today = datetime.now()
    # skip today, start from tomorrow
    first_date = today + timedelta(days=1)
    second_date = today + timedelta(days=3)  # space them apart
    
    # format nicely: "Tuesday, September 2nd"
    def format_date(d):
        return d.strftime("%A, %B %d").replace(" 0", " ")
    
    return format_date(first_date), format_date(second_date)


