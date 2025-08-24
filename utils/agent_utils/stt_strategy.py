import asyncio
import json
from typing import Optional
from utils.config_utils.env_loader import get_env_var
from utils.config_utils.config_loader import get_config
from utils.monitoring_utils.logging import get_logger
from livekit.plugins import openai, google, deepgram
from abc import ABC, abstractmethod

logger = get_logger("STT-FACTORY")

# Environment to STT mapping
ENV_STT_MAP = {
    "prod": "deepgram-3",
    "test": "deepgram-3",
    "dev": "deepgram-2",
    "client": "deepgram-3",
    "local": "deepgram-3"
}

class STTStrategy(ABC):
    @abstractmethod
    async def create(self) -> Optional[object]:
        pass

class Deepgram3Strategy(STTStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("DEEPGRAM_API_KEY")
        if not api_key:
            logger.error("Missing API key for deepgram-3")
            return None
        params = {
            "model": "nova-3",
            "language": "en-IN",
            "smart_format": True,
            "interim_results": False,
        }
        logger.debug("Instantiating deepgram-3 STT")
        return deepgram.STT(api_key=api_key, **params)

class GoogleStrategy(STTStrategy):
    async def create(self) -> Optional[object]:
        creds = json.loads(get_config("GOOGLE_SA_JSON"))
        if not creds:
            logger.error("Missing Google credentials")
            return None
        params = {
            "model": "latest_long",
            "languages": "en-IN",
            "interim_results": False,
            "detect_language": False,
            "punctuate": True,
            "spoken_punctuation": False,
            "min_confidence_threshold": 0.7,
        }
        logger.debug("Instantiating google STT")
        return google.STT(credentials_info=creds, **params)

class OpenAIStrategy(STTStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("OPEN_AI_API_KEY")
        if not api_key:
            logger.error("Missing API key for openai")
            return None
        params = {
            "use_realtime": True,
            "language": "en",
            "detect_language": False
        }
        logger.debug("Instantiating openai STT")
        return openai.STT(api_key=api_key, model="gpt-4o-transcribe", **params)

class Deepgram2Strategy(STTStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("DEEPGRAM_API_KEY")
        if not api_key:
            logger.error("Missing API key for deepgram-2")
            return None
        params = {
            "model": "nova-2",
            "language": "en-IN",
            "smart_format": True,
            "interim_results": False,
        }
        logger.debug("Instantiating deepgram-2 STT")
        return deepgram.STT(api_key=api_key, **params)

async def get_stt() -> Optional[object]:
    env = get_env_var("ENV", default="dev").lower()
    selected_stt = ENV_STT_MAP.get(env, "deepgram-3")
    logger.debug(f"Environment: {env}, Selected STT: {selected_stt}")

    strategies = {
        "deepgram-3": Deepgram3Strategy(),
        "google": GoogleStrategy(),
        "openai": OpenAIStrategy(),
        "deepgram-2": Deepgram2Strategy()
    }

    # Try selected strategy
    strategy = strategies.get(selected_stt)
    if not strategy:
        logger.error(f"No strategy found for STT: {selected_stt}")
        raise ValueError(f"No strategy found for STT: {selected_stt}")

    logger.info(f"Attempting to instantiate STT with strategy: {selected_stt}")
    stt = await strategy.create()
    if stt:
        logger.info(f"Successfully instantiated STT: {selected_stt}")
        return stt

    # Fallback to deepgram-3
    if selected_stt != "deepgram-3":
        logger.warning(f"Selected STT {selected_stt} failed, falling back to deepgram-3")
        fallback_strategy = strategies["deepgram-3"]
        stt = await fallback_strategy.create()
        if stt:
            logger.info("Successfully instantiated fallback deepgram-3 STT")
            return stt

    logger.error("No valid STT configuration found")
    raise ValueError("No valid STT configuration found")
