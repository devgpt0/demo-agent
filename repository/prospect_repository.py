from datetime import datetime
from typing import Optional, Dict, Any
import json

from models.prospect import Prospect
from utils.monitoring_utils.logging import get_logger
from utils.config_utils.db_config import redis

logger = get_logger("prospect-repo")


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value or value.lower() == "null":
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as e:
        logger.warning(f"Invalid datetime format '{value}': {e}")
        return None


# ------------------------
# Get Prospect
# ------------------------
async def get_prospect_from_db(prospect_id: str) -> Optional[Prospect]:
    """
    Fetch a prospect from Redis hash and map it to Prospect model.
    """
    key = f"prospect:{prospect_id}"
    data: Dict[str, Any] = redis.hgetall(key)

    if not data:
        logger.info(f"No prospect found in Redis for key={key}")
        return None

    try:
        return Prospect(
            id=prospect_id,
            first_name=data.get("first_name") or None,
            last_name=data.get("last_name") or None,
            phone=data.get("phone") or "",
            timezone=data.get("timezone") or None,
            status=data.get("status", "new"),
            objections=json.loads(data.get("objections") or "[]"),
            responses=json.loads(data.get("responses") or "[]"),
            appointment_date=parse_datetime(data.get("appointment_date")),
            appointment_slot=data.get("appointment_slot") or None,
            email=data.get("email") or None,
            created_at=parse_datetime(data.get("created_at")) or datetime.utcnow(),
            updated_at=parse_datetime(data.get("updated_at")) or datetime.utcnow(),
        )
    except Exception as e:
        logger.error(f"Error mapping prospect {prospect_id}: {e}")
        return None


# ------------------------
# Update Prospect
# ------------------------
async def update_prospect_in_db(prospect: Prospect) -> None:
    """
    Save Prospect back into Redis hash.
    Arrays are JSON-encoded for storage.
    """
    key = f"prospect:{prospect.id}"
    now = datetime.utcnow().isoformat()

    fields = {
        "first_name": prospect.first_name or "",
        "last_name": prospect.last_name or "",
        "phone": prospect.phone or "",
        "timezone": prospect.timezone or "",
        "status": prospect.status or "new",
        "objections": json.dumps(prospect.objections or []),
        "responses": json.dumps(prospect.responses or []),
        "appointment_date": (
            prospect.appointment_date.isoformat() if prospect.appointment_date else ""
        ),
        "appointment_slot": prospect.appointment_slot or "",
        "email": prospect.email or "",
        "created_at": (
            prospect.created_at.isoformat() if prospect.created_at else now
        ),
        "updated_at": now,
    }

    try:
        redis.hset(key, mapping=fields)
        logger.info(f"Updated prospect {prospect.id} in Redis")
    except Exception as e:
        logger.error(f"Failed to update prospect {prospect.id} in Redis: {e}")
