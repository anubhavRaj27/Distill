"""Gemini access, through the google-genai software development kit.

DELIBERATE DEVIATION FROM implementation.md SECTION 2.2 (decision D20)
-----------------------------------------------------------------------
The implementation document chose Instructor as the structured-output layer, for retries on
malformed output and for provider independence. This module calls ``google-genai`` directly
instead, and hand-rolls the retry loop.

The reason is specific rather than a preference. Instructor takes a pydantic model and
converts it to a provider schema with its own converter. That would bypass
``app.llm.jsonschema``, which exists precisely because Gemini accepts a narrow schema subset
and which is verified by tests that need no API key (review finding 8.7). Handing schema
conversion to a library would put the one risk that cannot be tested without a key back into
an untested path, in exchange for about forty lines of retry logic.

Provider independence, Instructor's other benefit, is already provided by the ``LLMClient``
protocol in ``app.llm.base``, which is the boundary the rest of the application talks to.

Instructor has therefore been removed from the dependency manifest, because an unused
dependency is a false statement about what the project needs.

WHAT IS AND IS NOT VERIFIED
---------------------------
Verified without a key: the schema conversion, the prompt assembly, the retry decision
logic, and the error classification, all through ``FakeClient`` and the unit suite.

NOT verified: that a real Gemini call returns what this expects, and that the configured
model identifiers exist. Both need a key. This is the recorded gap in decision D13, and it
is why ``FakeClient`` is the default provider rather than a fallback.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.errors import LLMInvalidOutput, LLMUnavailable, NotConfigured
from app.llm.base import CallKind, LLMRequest, LLMResponse, Usage, Vector
from app.llm.fake import write_fixture
from app.llm.jsonschema import to_provider_schema
from app.logging import get_logger

logger = get_logger(__name__)

RETRYABLE_MARKERS: tuple[str, ...] = (
    "429",
    "resource_exhausted",
    "rate limit",
    "deadline",
    "timeout",
    "unavailable",
    "503",
    "500",
    "internal error",
    "connection",
)
"""Substrings marking a transport or capacity failure, which is worth retrying, as opposed
to a bad request or an invalid key, which is not. Retrying a 400 wastes the user's time
three times over and then reports the same thing."""


class GeminiClient:
    """Structured-output calls against Gemini."""

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise NotConfigured(
                "GEMINI_API_KEY is not set. Leave LLM_PROVIDER as 'fake' to run the full "
                "pipeline against recorded fixtures and offline heuristics instead."
            )
        from google import genai

        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @property
    def name(self) -> str:
        return "gemini"

    def model_for(self, kind: CallKind) -> str:
        """The model tier for a call kind. See decision D13."""
        return (
            self._settings.llm_extract_model
            if kind.needs_strong_model
            else self._settings.llm_query_model
        )

    async def structured(self, request: LLMRequest) -> LLMResponse[BaseModel]:
        from google.genai import types

        model = self.model_for(request.kind)
        schema = to_provider_schema(request.response_model.model_json_schema())

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=request.temperature,
            system_instruction=request.system,
        )

        started = time.perf_counter()
        prompt = request.prompt
        last_error: Exception | None = None

        for attempt in range(1, self._settings.llm_max_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model, contents=prompt, config=config
                    ),
                    timeout=self._settings.llm_timeout_seconds,
                )
            except TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "llm.timeout", kind=request.kind.value, attempt=attempt, model=model
                )
                if attempt >= self._settings.llm_max_attempts:
                    raise LLMUnavailable(
                        "The model did not respond in time. This usually clears up on a "
                        "retry.",
                        attempts=attempt,
                    ) from exc
                await self._backoff(attempt)
                continue
            except Exception as exc:
                last_error = exc
                if not _is_retryable(exc) or attempt >= self._settings.llm_max_attempts:
                    raise LLMUnavailable(
                        _readable_transport_error(exc),
                        attempts=attempt,
                        error_type=type(exc).__name__,
                    ) from exc
                logger.warning(
                    "llm.transport_error",
                    kind=request.kind.value,
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                await self._backoff(attempt)
                continue

            text = (response.text or "").strip()
            try:
                value = request.response_model.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "llm.invalid_output",
                    kind=request.kind.value,
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                if attempt >= self._settings.llm_max_attempts:
                    raise LLMInvalidOutput(
                        "The model returned a response we could not read, three times "
                        "running. This document has been marked as failed so the rest of "
                        "your collection is unaffected.",
                        attempts=attempt,
                    ) from exc
                # Feed the validation error back in. Naming the specific problem is far
                # more effective than simply asking again, which tends to reproduce it.
                prompt = (
                    f"{request.prompt}\n\n"
                    f"Your previous response could not be parsed. The error was:\n"
                    f"{str(exc)[:800]}\n\n"
                    f"Return only valid JSON matching the required schema."
                )
                continue

            usage = _usage_from(response, model=model, attempts=attempt)
            usage.latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "llm.completed",
                kind=request.kind.value,
                model=model,
                attempts=attempt,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                latency_ms=round(usage.latency_ms, 1),
            )

            if self._settings.llm_record:
                # Capture the interaction so the fake can replay it, which is how the
                # deterministic end-to-end test gets real data (decision D13).
                write_fixture(
                    self._settings.llm_fixture_dir
                    / request.kind.value
                    / f"{request.fixture_key}.json",
                    value,
                )

            return LLMResponse(value=value, usage=usage)

        raise LLMUnavailable(  # pragma: no cover - the loop always returns or raises
            "The model could not be reached.", error_type=type(last_error).__name__
        )

    async def embed(self, texts: Sequence[str]) -> list[Vector | None]:
        """Embed field labels for drift matching. Decision D24.

        Never returns ``None`` entries: Gemini embeds whatever it is given. The optional
        element type exists for ``FakeClient``, which has no vector for an unrecorded label.
        A failure here is a real failure and is raised, not swallowed into a fallback.

        Retries share ``structured``'s policy and its reasoning: transport and capacity
        failures are worth another attempt, a rejected request is not.
        """
        if not texts:
            return []

        model = self._settings.llm_embed_model
        started = time.perf_counter()

        for attempt in range(1, self._settings.llm_max_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    # `contents` is invariant in the software development kit's signature,
                    # so a plain list[str] is rejected even though every element is a
                    # permitted type. Narrow ignore rather than a cast, which would switch
                    # off checking for the whole call.
                    self._client.aio.models.embed_content(
                        model=model,
                        contents=list(texts),  # type: ignore[arg-type]
                    ),
                    timeout=self._settings.llm_timeout_seconds,
                )
            except TimeoutError as exc:
                logger.warning("llm.embed_timeout", attempt=attempt, model=model)
                if attempt >= self._settings.llm_max_attempts:
                    raise LLMUnavailable(
                        "The model did not respond in time. This usually clears up on a "
                        "retry.",
                        attempts=attempt,
                    ) from exc
                await self._backoff(attempt)
                continue
            except Exception as exc:
                if not _is_retryable(exc) or attempt >= self._settings.llm_max_attempts:
                    raise LLMUnavailable(
                        _readable_transport_error(exc),
                        attempts=attempt,
                        error_type=type(exc).__name__,
                    ) from exc
                logger.warning(
                    "llm.embed_transport_error", attempt=attempt, error=type(exc).__name__
                )
                await self._backoff(attempt)
                continue

            vectors: list[Vector | None] = [
                list(embedding.values) if embedding.values else None
                for embedding in (response.embeddings or [])
            ]
            if len(vectors) != len(texts):
                # A short response would silently misalign labels with vectors, and a
                # misaligned vector is worse than no vector: it would produce confident
                # similarity scores for the wrong pair of fields.
                raise LLMInvalidOutput(
                    f"The embedding provider returned {len(vectors)} vectors for "
                    f"{len(texts)} inputs.",
                    attempts=attempt,
                )

            logger.info(
                "llm.embed_completed",
                model=model,
                count=len(vectors),
                attempts=attempt,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return vectors

        raise LLMUnavailable(  # pragma: no cover - the loop always returns or raises
            "The model could not be reached."
        )

    async def _backoff(self, attempt: int) -> None:
        """Exponential backoff. Deterministic, so a test can reason about the timing."""
        await asyncio.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in RETRYABLE_MARKERS)


def _readable_transport_error(exc: Exception) -> str:
    """A message for the user, not a library string."""
    text = f"{type(exc).__name__} {exc}".lower()
    if "api key" in text or "permission" in text or "401" in text or "403" in text:
        return (
            "The model provider rejected our credentials. Check that GEMINI_API_KEY is "
            "set correctly on the server."
        )
    if "not found" in text or "404" in text:
        return (
            "The configured model does not exist. Check LLM_EXTRACT_MODEL and "
            "LLM_QUERY_MODEL against the provider's current model list."
        )
    if "429" in text or "resource_exhausted" in text or "rate limit" in text:
        return "We are being rate limited by the model provider. Please try again shortly."
    return "We could not reach the model provider. Please try again shortly."


def _usage_from(response: Any, *, model: str, attempts: int) -> Usage:
    metadata = getattr(response, "usage_metadata", None)
    return Usage(
        input_tokens=getattr(metadata, "prompt_token_count", None),
        output_tokens=getattr(metadata, "candidates_token_count", None),
        attempts=attempts,
        model=model,
        provider="gemini",
    )
