from datetime import datetime
from typing import Optional
import json

from models.prospect import Prospect
from utils.monitoring_utils.logging import get_logger
from utils.config_utils.db_config import redis 

logger = get_logger("prospect-repo")


def parse_datetime(value: str) -> Optional[datetime]:
    if not value or value.lower() == "null":
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None



#Save prospect
def save_prospect_to_db(prospect: Prospect) -> None:
    key = f"prospect:{prospect.id}"
    data = prospect.to_dict()

    safe_data = {
        k: ("" if v is None or v == "null" else str(v)) for k, v in data.items()
    }
    redis.hset(key, values=safe_data)



#Get Prospect
async def get_prospect_from_db(prospect_id: str) -> Optional[Prospect]:
    key = f"prospect:{prospect_id}"
    data = redis.hgetall(key)

    if not data:
        return None

    decoded = data  # async client already returns str values

    try:
        return Prospect(
            id=prospect_id,
            first_name=decoded.get("first_name") or None,
            last_name=decoded.get("last_name") or None,
            phone=decoded.get("phone", ""),
            timezone=decoded.get("timezone") or None,
            status=decoded.get("status", "new"),
            objections=json.loads(decoded.get("objections") or "[]"),
            responses=json.loads(decoded.get("responses") or "[]"),
            appointment_date=parse_datetime(decoded.get("appointment_date")),
            appointment_slot=decoded.get("appointment_slot") or None,
            email=decoded.get("email") or None,
            created_at=parse_datetime(decoded.get("created_at")) or datetime.utcnow(),
            updated_at=parse_datetime(decoded.get("updated_at")) or datetime.utcnow(),
        )
    except Exception as e:
        import logging
        logging.error(f"Error mapping prospect {prospect_id}: {e}")
        return None

