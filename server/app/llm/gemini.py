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

Verified WITH a key on September 5, 2026 (decision D62): a structured extraction call
returns a schema-valid ``OpenExtraction`` through ``app.llm.jsonschema``, which closes
review finding 8.7; embeddings return one vector per input at the requested width; and a
chat answer streams. The model identifiers in ``config.py`` were changed in the same pass,
because the 2.5 identifiers the plan named are no longer callable by a new key: the
provider answers them with 404 and a pointer to the 3.x line.

Still not verified: extraction quality across the whole sample corpus, which is a judgement
call rather than a check, and the Pro tier, which this key's plan does not include at all.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.errors import LLMInvalidOutput, LLMUnavailable, NotConfigured
from app.llm.base import CallKind, EmbedTask, LLMRequest, LLMResponse, Usage, Vector
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

RETRY_DELAY_PATTERNS: tuple[str, ...] = (
    r"retry in ([0-9]+(?:\.[0-9]+)?)s",
    r"retrydelay['\"]?[:=]\s*['\"]?([0-9]+(?:\.[0-9]+)?)s",
)
"""The two spellings Gemini uses to say how long to wait: the sentence in the message, and
the ``retryDelay`` in the error details."""

MAX_BACKOFF_SECONDS = 45.0
"""Longest a single attempt will wait, whoever asked for it. A waiting request is holding a
worker slot, so an unbounded wait is a stalled pipeline rather than a patient one."""

TERMINAL_MARKERS: tuple[str, ...] = ("limit: 0",)
"""Substrings that override ``RETRYABLE_MARKERS``.

One case, learned from a real key. A model the current plan does not carry at all answers
with 429 RESOURCE_EXHAUSTED, which reads exactly like being rate limited, but the body says
``limit: 0``. That is a permanent state, not a spike: retrying it three times with backoff
delays the same failure and then reports "try again shortly" about something that will never
succeed. Recognising it turns a confusing intermittent-looking failure into one sentence
naming the cause."""


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
            else self._settings.llm_fast_model
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
            thinking_config=self._thinking_for(request.kind),
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
                await self._backoff(attempt, exc)
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

    async def embed(
        self, texts: Sequence[str], *, task: EmbedTask = "similarity"
    ) -> list[Vector | None]:
        """Embed passages, questions, or field labels. Decisions D24, D36, D63.

        Never returns ``None`` entries: Gemini embeds whatever it is given. The optional
        element type exists for ``FakeClient``, which has no vector for an unrecorded label.
        A failure here is a real failure and is raised, not swallowed into a fallback.

        Two things are asked of the provider that the plan did not specify, both settled by
        measurement against a real key on September 5, 2026:

        * **A task type**, from ``task``. Retrieval is asymmetric, and saying which side of
          the pair a text is improves the ranking at no cost.
        * **An output width**, from ``llm_embed_dimensions``. The default 3072 is four
          times the storage and four times the per-question arithmetic for no gain a corpus
          this size can use.

        Vectors narrower than the model's native width come back un-normalised, which the
        provider documents, so they are normalised here. ``cosine`` would normalise anyway;
        doing it once at write time means every stored vector is a unit vector and a plain
        dot product over them is valid.

        Retries share ``structured``'s policy and its reasoning: transport and capacity
        failures are worth another attempt, a rejected request is not.
        """
        if not texts:
            return []

        from google.genai import types

        model = self._settings.llm_embed_model
        config = types.EmbedContentConfig(
            task_type=_TASK_TYPES[task],
            output_dimensionality=self._settings.llm_embed_dimensions,
        )
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
                        config=config,
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
                await self._backoff(attempt, exc)
                continue

            vectors: list[Vector | None] = [
                _unit(embedding.values) if embedding.values else None
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
                task=task,
                dimensions=self._settings.llm_embed_dimensions,
                count=len(vectors),
                attempts=attempt,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return vectors

        raise LLMUnavailable(  # pragma: no cover - the loop always returns or raises
            "The model could not be reached."
        )

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream a text answer. Decision D44.

        No retry loop, unlike ``structured``. Once the first delta has reached the user's
        screen, silently restarting the call would rewrite text they have already read. A
        mid-stream failure is surfaced instead, and the partial answer is persisted as
        failed, which is honest about what happened.
        """
        from google.genai import types

        model = self.model_for(request.kind)
        config = types.GenerateContentConfig(
            temperature=request.temperature,
            system_instruction=request.system,
            thinking_config=self._thinking_for(request.kind),
        )
        started = time.perf_counter()
        first_token_ms: float | None = None
        pieces = 0

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=model, contents=request.prompt, config=config
            )
            async for chunk in stream:
                text = getattr(chunk, "text", None)
                if not text:
                    continue
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - started) * 1000
                pieces += 1
                yield text
        except Exception as exc:
            logger.warning(
                "llm.stream_failed", kind=request.kind.value, error=type(exc).__name__
            )
            raise LLMUnavailable(
                _readable_transport_error(exc), error_type=type(exc).__name__
            ) from exc

        logger.info(
            "llm.stream_completed",
            kind=request.kind.value,
            model=model,
            pieces=pieces,
            # Logged because requirement FR-26 sets a three second target for it, and a
            # target nobody measures is a wish.
            first_token_ms=round(first_token_ms, 1) if first_token_ms else None,
            total_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    def _thinking_for(self, kind: CallKind) -> Any | None:
        """Reasoning effort for one call kind, or ``None`` to leave the model's default.

        Only the calls a user waits on are turned down. Extraction and schema inference
        keep the default, because their cost is paid once per document by a background
        worker and their errors are baked into the table. See decision D62 and the timings
        in ``Settings.llm_fast_thinking_level``.
        """
        level = self._settings.llm_fast_thinking_level
        if level is None or kind.needs_strong_model:
            return None
        from google.genai import types

        return types.ThinkingConfig(thinking_level=level)

    async def _backoff(self, attempt: int, exc: Exception | None = None) -> None:
        """Wait before the next attempt.

        The provider's own hint wins when it gives one. A rate limit on a per-minute quota
        answers "Please retry in 29.8s", and an exponential backoff topping out at eight
        seconds simply spends all three attempts inside the window that is still closed,
        turning a delay into a failure. Honouring the hint is the difference between a slow
        document and a failed one on a free-tier key.

        Without a hint it is exponential and deterministic, so a test can reason about the
        timing. The cap exists because a request holds a worker slot while it waits.
        """
        hinted = _retry_delay_seconds(exc) if exc is not None else None
        if hinted is not None:
            logger.info("llm.backoff_hinted", attempt=attempt, seconds=round(hinted, 1))
            await asyncio.sleep(min(MAX_BACKOFF_SECONDS, hinted))
            return
        await asyncio.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))


_TASK_TYPES: dict[EmbedTask, str] = {
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
    "similarity": "SEMANTIC_SIMILARITY",
}
"""The provider's names for ``EmbedTask``. The only place they appear."""


def _retry_delay_seconds(exc: Exception) -> float | None:
    """The delay the provider asked for, in seconds, if it named one.

    Both spellings seen from Gemini are matched: the human sentence "Please retry in
    29.784742322s" and the structured ``retryDelay: '30s'`` in the error details. A hint
    beyond the cap is treated as no hint, because waiting ten minutes inside a request is
    not a retry, it is a hang.
    """
    text = str(exc)
    for pattern in RETRY_DELAY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            seconds = float(match.group(1))
            return seconds if 0 < seconds <= MAX_BACKOFF_SECONDS else None
    return None


def _unit(values: Sequence[float]) -> Vector:
    """``values`` scaled to length one. A zero vector is returned unchanged."""
    vector = list(values)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    if any(marker in text for marker in TERMINAL_MARKERS):
        return False
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
        # Worth being specific: a model identifier can stop working without anybody
        # touching the configuration. Gemini 2.5 became uncallable for new keys exactly
        # this way, and the generic wording sent us looking for a typo that was not there.
        return (
            "The model provider does not offer the configured model to this key. It may "
            "have been retired. Check LLM_EXTRACT_MODEL, LLM_FAST_MODEL and "
            "LLM_EMBED_MODEL against the provider's current model list. Provider said: "
            f"{_provider_detail(exc)}"
        )
    if any(marker in text for marker in TERMINAL_MARKERS):
        return (
            "The configured model is not included in this API key's plan, so retrying "
            "will not help. Choose a model the plan covers, or upgrade the key. Provider "
            f"said: {_provider_detail(exc)}"
        )
    if "429" in text or "resource_exhausted" in text or "rate limit" in text:
        return "We are being rate limited by the model provider. Please try again shortly."
    return "We could not reach the model provider. Please try again shortly."


def _provider_detail(exc: Exception, limit: int = 200) -> str:
    """The provider's own sentence, trimmed. Included in the messages where the cause is
    outside our control, because paraphrasing it loses the one detail an operator needs."""
    return " ".join(str(exc).split())[:limit]


def _usage_from(response: Any, *, model: str, attempts: int) -> Usage:
    metadata = getattr(response, "usage_metadata", None)
    return Usage(
        input_tokens=getattr(metadata, "prompt_token_count", None),
        output_tokens=getattr(metadata, "candidates_token_count", None),
        attempts=attempts,
        model=model,
        provider="gemini",
    )
