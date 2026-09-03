"""Choosing a client from configuration. The only place a provider is named."""

from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMClient
from app.llm.fake import FakeClient
from app.logging import get_logger

logger = get_logger(__name__)

_client: LLMClient | None = None


def build_client(settings: Settings) -> LLMClient:
    """Construct the configured client.

    Falls back to the fake provider if the real one cannot be constructed, and says so
    loudly. That is the right failure mode here: a missing key should degrade a deployment
    to offline extraction with a warning in the log, rather than refuse to boot and take the
    entire interface down with it.
    """
    if settings.llm_provider == "gemini":
        try:
            from app.llm.gemini import GeminiClient

            client = GeminiClient(settings)
            logger.info(
                "llm.provider_ready",
                provider=client.name,
                extract_model=settings.llm_extract_model,
                query_model=settings.llm_query_model,
            )
            return client
        except Exception as exc:
            logger.error(
                "llm.provider_unavailable_falling_back_to_offline",
                provider="gemini",
                error=type(exc).__name__,
                detail=str(exc)[:300],
            )
            return FakeClient(settings)

    logger.info("llm.provider_ready", provider="fake", mode="fixtures and offline heuristics")
    return FakeClient(settings)


def init_client(settings: Settings) -> LLMClient:
    global _client
    _client = build_client(settings)
    return _client


def get_client() -> LLMClient:
    if _client is None:
        raise RuntimeError("init_client() has not been called")
    return _client


def reset_client() -> None:
    global _client
    _client = None
