# prospect_repository.py
from datetime import datetime
from typing import Optional
import json

from models.prospect import Prospect
from utils.monitoring_utils.logging import get_logger
from utils.config_utils.db_config import redis 
from utils.data_utils.date_utils import parse_date, parse_datetime
from utils.data_utils.time_utils import parse_time_str

logger = get_logger("prospect-repo")


def save_prospect_to_db(prospect: Prospect) -> None:
    key = f"prospect:{prospect.id}"
    data = prospect.to_dict()

    safe_data = {
        k: ("" if v is None or v == "null" else str(v)) for k, v in data.items()
    }
    redis.hset(key, values=safe_data)




# Get prospect
def get_prospect_from_db(prospect_id: str) -> Optional[Prospect]:
    key = f"prospect:{prospect_id}"
    data = redis.hgetall(key)

    if not data:
        return None

    try:
        return Prospect(
            id=prospect_id,
            first_name=data.get("first_name") or None,
            last_name=data.get("last_name") or None,
            phone=data.get("phone", ""),
            timezone=data.get("timezone") or None,
            status=data.get("status", "new"),
            objections=json.loads(data.get("objections") or "[]"),
            responses=json.loads(data.get("responses") or "[]"),
            appointment_date=parse_date(data.get("appointment_date")),
            appointment_time=parse_time_str(data.get("appointment_time")) or None,
            email=data.get("email") or None,
            created_at=parse_datetime(data.get("created_at")) or datetime.utcnow(),
            updated_at=parse_datetime(data.get("updated_at")) or datetime.utcnow(),
        )
    except Exception as e:
        logger.error(f"Error mapping prospect {prospect_id}: {e}")
        return None
