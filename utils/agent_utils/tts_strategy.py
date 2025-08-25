import asyncio
import json
from typing import Optional
from utils.config_utils.env_loader import get_env_var
from utils.config_utils.config_loader import get_config
from utils.monitoring_utils.logging import get_logger
from livekit.plugins import aws, google, openai, deepgram ,elevenlabs
from abc import ABC, abstractmethod

logger = get_logger("TTS-FACTORY")

# Environment to TTS mapping
ENV_TTS_MAP = {
    "prod": "aws",
    "test": "aws",
    "dev": "aws",
    "client": "aws",
    "local": "aws"
}

class TTSStrategy(ABC):
    @abstractmethod
    async def create(self) -> Optional[object]:
        pass

class ElevenLabsStrategy(TTSStrategy):
    async def create(self) ->Optional[object]:
        api_key = get_config("ELEVEN_LABS_API_KEY")
        voice_id=get_config("ElEVEN_LABS_VOICE_ID")
        model="eleven_multilingual_v2"
        if not (api_key and voice_id):
            logger.error("Missing ElevenLabs credentials or voice id")
            return None
        
        logger.debug("Instanting elevenlabs TTS")
        
        return elevenlabs.TTS(api_key=api_key,voice_id=voice_id, model=model)
        
class AWSStrategy(TTSStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("AWS_ACCESS_KEY_ID")
        api_secret = get_config("AWS_SECRET_ACCESS_KEY")
        region = get_config("AWS_REGION")
        if not (api_key and api_secret and region):
            logger.error("Missing AWS credentials or region")
            return None
        params = {
            "voice": "Matthew",
            "speech_engine": "standard",
            "language": "en-US",
        }
        logger.debug("Instantiating aws TTS")
        return aws.TTS(api_key=api_key, api_secret=api_secret, region=region, **params)

class GoogleStrategy(TTSStrategy):
    async def create(self) -> Optional[object]:
        creds = json.loads(get_config("GOOGLE_SA_JSON"))
        if not creds:
            logger.error("Missing Google credentials")
            return None
        params = {
            "language": "en-US"
        }
        logger.debug("Instantiating google TTS")
        return google.TTS(credentials_info=creds, **params)

class DeepgramStrategy(TTSStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("DEEPGRAM_API_KEY")
        if not api_key:
            logger.error("Missing Deepgram API key")
            return None
        params = {
            "model": "aura-2-athena-en",
        }
        logger.debug("Instantiating deepgram TTS")
        return deepgram.TTS(api_key=api_key, **params)

async def get_tts() -> Optional[object]:
    env = get_env_var("ENV", default="dev").lower()
    selected_tts = ENV_TTS_MAP.get(env, "aws")
    logger.debug(f"Environment: {env}, Selected TTS: {selected_tts}")

    strategies = {
        "aws": AWSStrategy(),
        "google": GoogleStrategy(),
        "deepgram": DeepgramStrategy(),
        "elevenlabs":ElevenLabsStrategy()
    }

    # Try selected strategy
    strategy = strategies.get(selected_tts)
    if not strategy:
        logger.error(f"No strategy found for TTS: {selected_tts}")
        raise ValueError(f"No strategy found for TTS: {selected_tts}")

    logger.info(f"Attempting to instantiate TTS with strategy: {selected_tts}")
    tts = await strategy.create()
    if tts:
        logger.info(f"Successfully instantiated TTS: {selected_tts}")
        return tts

    # Fallback to aws
    if selected_tts != "aws":
        logger.warning(f"Selected TTS {selected_tts} failed, falling back to aws")
        fallback_strategy = strategies["aws"]
        tts = await fallback_strategy.create()
        if tts:
            logger.info("Successfully instantiated fallback aws TTS")
            return tts

    logger.error("No valid TTS configuration found")
    raise ValueError("No valid TTS configuration found")


