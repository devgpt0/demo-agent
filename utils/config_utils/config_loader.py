""" Utility is used to load the enviroment variables from Upstash redis to our project based on profile""" 
import json
from upstash_redis import Redis
from utils.config_utils.env_loader import get_env_var
from dotenv import load_dotenv
from typing import Dict, Optional, Any

redis = Redis(
    url=get_env_var("UPSTASH_CONFIG_REDIS_URL"),
    token=get_env_var("UPSTASH_CONFIG_REDIS_TOKEN")
)

# -------------------------------Load environment variables profile from .env file-------------------------------
load_dotenv()

# -------------------------------Get Env value for the profile -------------------------------
def get_profile_name() -> str:
    profile_name = get_env_var("PROFILE")
    if not profile_name:
        raise ValueError("Missing PROFILE value in .env")
    return profile_name

# -------------------------------Select the Upstash key for the profile -------------------------------
def select_upstash_key(env_name: str) -> str:
    return f"config:env:{env_name}"

# -------------------------------Fetch the correct profile from Upstash-------------------------------
def fetch_config_from_redis(redis_key: str) -> str:
    response = redis.get(redis_key)
    if not response:
        raise ValueError(f"No config found in Redis for key: '{redis_key}'")
    return response

# -------------------------------Parse the JSON received from Upstash-------------------------------
def parse_config_json(response: str, redis_key: str) -> Dict[str, Any]:
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in Redis for key '{redis_key}': {e}")

# -------------------------------Flatten the response JSON from Upstash-------------------------------
def flatten_config(config_json: Dict[str, Any]) -> Dict[str, Any]:
    flat_config = {}
    for group, items in config_json.items():
        if isinstance(items, list):
            for item in items:
                key = item.get("key")
                value = item.get("value")
                if key is not None and value is not None:
                    flat_config[key] = value
    return flat_config

# -------------------------------Use the profile and load env variable from Upstash-------------------------------
def load_config_from_env() -> Dict[str, Any]:
    profile_name = get_profile_name()
    redis_key = select_upstash_key(profile_name)
    raw_config = fetch_config_from_redis(redis_key)
    config_json = parse_config_json(raw_config, redis_key)
    flat_config = flatten_config(config_json)
    flat_config["PROFILE"] = profile_name
    return flat_config

# -------------------------------Get env variable value from Upstash config-------------------------------
def get_config(key: str, default: Optional[str] = None, required: bool = True) -> Optional[str]:
    config = load_config_from_env()
    value = config.get(key, default)

    if required and value is None:
        raise ValueError(f"Missing required config key: {key}")

    return value
