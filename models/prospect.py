import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import datetime


@dataclass
class Prospect:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: str = ""  # required
    timezone: Optional[str] = None
    status: str = "new"  # new, in_progress, booked, lost

    # Objection / Conversation tracking
    objections: List[str] = field(default_factory=list)
    responses: List[str] = field(default_factory=list)

    # Appointment details
    appointment_date: Optional[datetime] = None
    appointment_slot: Optional[str] = None  # "morning"/"afternoon"
    email: Optional[str] = None

    # System metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self):
        """Convert to JSON-serializable dict"""
        d = asdict(self)
        d["appointment_date"] = (
            self.appointment_date.isoformat() if self.appointment_date else None
        )
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        return d
