"""Utilty to connect to databases(Upstash) from where our agents fetch interview session data,coding-questions,company-prompts and so on"""
from upstash_redis import Redis
import os
from dotenv import load_dotenv
from utils.config_utils.config_loader import get_config 

# Create Redis client using REST credentials
redis = Redis(
    url=get_config("UPSTASH_REDIS_URL"),
    token=get_config("UPSTASH_REDIS_TOKEN")
)
