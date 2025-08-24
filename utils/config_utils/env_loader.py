"""Utiltiy to get environmet variables from .env file"""
import os
import logging
from typing import Optional
from dotenv import load_dotenv

# Set up a logger for the utility
logger = logging.getLogger("env-loader")
logger.setLevel(logging.INFO)

# Load environment variables from a .env file
load_dotenv()

# ---------------------------Method to set envrioment variabe from .env file---------------
def get_env_var(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    """Retrieve an environment variable with optional requirement and default value."""
    value = os.getenv(name, default)
    if required and value is None:
        logger.error(f"Environment variable '{name}' is missing.")
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value