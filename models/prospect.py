import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import datetime, date 
from utils.data_utils.date_utils import format_datetime,format_date
from utils.data_utils.time_utils import format_time_str





@dataclass
class Prospect:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: str = ""  
    timezone: Optional[str] = None
    status: str = "new"  

    objections: List[str] = field(default_factory=list)
    responses: List[str] = field(default_factory=list)

    appointment_date: Optional[date] = None
    appointment_time: Optional[str] = None
    email: Optional[str] = None

    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self):
        d = asdict(self)
        d["appointment_date"] = format_date(self.appointment_date)
        d["appointment_time"] = format_time_str(self.appointment_time)
        d["created_at"] = format_datetime(self.created_at)
        d["updated_at"] = format_datetime(self.updated_at)
        return d

