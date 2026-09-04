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

    ``LLM_PROVIDER=gemini`` that cannot be constructed is a **hard failure**, not a
    fall back to the offline provider. This reverses the original behaviour here, and
    decision D26 records why: the fake provider synthesises values from label-and-value
    heuristics, and those values flow into the table wearing the same confidence tiers and
    provenance links as real extraction. An operator who set a key and mistyped it would get
    a running system quietly producing heuristic data it presents as model output, in a
    product whose entire claim is that every value on screen can be trusted and traced. A
    server that refuses to boot is a five-minute problem; a server silently serving
    heuristics as extraction is a credibility problem nobody notices until the demo.

    The offline provider stays fully supported — it is simply reached by asking for it,
    with ``LLM_PROVIDER=fake``, which is still the default (decision D13).
    """
    if settings.llm_provider == "gemini":
        from app.llm.gemini import GeminiClient

        client = GeminiClient(settings)
        logger.info(
            "llm.provider_ready",
            provider=client.name,
            extract_model=settings.llm_extract_model,
            query_model=settings.llm_query_model,
            embed_model=settings.llm_embed_model,
        )
        return client

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
