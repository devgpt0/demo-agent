import asyncio
from typing import Optional
from utils.config_utils.env_loader import get_env_var
from utils.config_utils.config_loader import get_config
from utils.monitoring_utils.logging import get_logger
from livekit.plugins import openai, google
import httpx
import openai as openai_client
from abc import ABC, abstractmethod

logger = get_logger("LLM-FACTORY")

# Environment to LLM mapping
ENV_LLM_MAP = {
    "prod": "azure-openai",
    "test": "azure-openai",
    "dev": "azure-openai",
    "client": "openai",
    "local": "openai"
}

class LLMStrategy(ABC):
    @abstractmethod
    async def create(self) -> Optional[object]:
        pass

class OpenAIStrategy(LLMStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("OPEN_AI_API_KEY")
        if not api_key:
            logger.error("Missing API key for openai")
            return None
        params = {
            "temperature": 0.3,
            "timeout": httpx.Timeout(connect=15.0, read=45.0, write=10.0, pool=20.0),
            "client": openai_client.AsyncClient(
                api_key=api_key,
                max_retries=3,
                timeout=httpx.Timeout(connect=15.0, read=45.0, write=10.0, pool=20.0),
                http_client=httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=10000, max_keepalive_connections=2000),
                    follow_redirects=True,
                ),
            ),
            "max_completion_tokens": 150,
        }
        logger.debug("Instantiating openai LLM")
        return openai.LLM(api_key=api_key, model="gpt-4o-mini", **params)

class OpenAIRealtimeStrategy(LLMStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("OPEN_AI_API_KEY")
        if not api_key:
            logger.error("Missing API key for openai-realtime")
            return None
        params = {
            "temperature": 0.1,
            "timeout": httpx.Timeout(connect=15.0, read=45.0, write=10.0, pool=20.0),
            "client": openai_client.AsyncClient(
                api_key=api_key,
                max_retries=3,
                timeout=httpx.Timeout(connect=15.0, read=45.0, write=10.0, pool=20.0),
                http_client=httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=10000, max_keepalive_connections=2000),
                    follow_redirects=True,
                ),
            ),
            "max_completion_tokens": 150,
        }
        logger.debug("Instantiating openai-realtime LLM")
        return openai.LLM(api_key=api_key, model="gpt-4o", **params)

class GoogleStrategy(LLMStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("GOOGLE_AGENT_API_KEY")
        if not api_key:
            logger.error("Missing API key for google")
            return None
        params = {"temperature": 0.3}
        logger.debug("Instantiating google LLM")
        return google.LLM(api_key=api_key, model="gemini-2.5-flash", **params)

class AzureOpenAIStrategy(LLMStrategy):
    async def create(self) -> Optional[object]:
        api_key = get_config("AZURE_OPENAI_API_KEY")
        if not api_key:
            logger.error("Missing API key for azure-openai")
            return None
        params = {
            "azure_endpoint": "https://test-aceint.openai.azure.com/",
            "azure_deployment": "gpt-4o-mini",
            "api_version": "2024-12-01-preview"
        }
        logger.debug("Instantiating azure-openai LLM")
        return openai.LLM.with_azure(api_key=api_key, model="gpt-4o-mini", **params)

async def get_llm() -> Optional[object]:
    env = get_env_var("ENV", default="dev").lower()
    selected_llm = ENV_LLM_MAP.get(env, "openai")
    logger.debug(f"Environment: {env}, Selected LLM: {selected_llm}")

    strategies = {
        "openai": OpenAIStrategy(),
        "openai-realtime": OpenAIRealtimeStrategy(),
        "google": GoogleStrategy(),
        "azure-openai": AzureOpenAIStrategy()
    }

    # Try selected strategy
    strategy = strategies.get(selected_llm)
    if not strategy:
        logger.error(f"No strategy found for LLM: {selected_llm}")
        raise ValueError(f"No strategy found for LLM: {selected_llm}")

    logger.info(f"Attempting to instantiate LLM with strategy: {selected_llm}")
    llm = await strategy.create()
    if llm:
        logger.info(f"Successfully instantiated LLM: {selected_llm}")
        return llm

    # Fallback to azure-openai
    if selected_llm != "azure-openai":
        logger.warning(f"Selected LLM {selected_llm} failed, falling back to azure-openai")
        fallback_strategy = strategies["azure-openai"]
        llm = await fallback_strategy.create()
        if llm:
            logger.info("Successfully instantiated fallback azure-openai LLM")
            return llm

    logger.error("No valid LLM configuration found")
    raise ValueError("No valid LLM configuration found")
