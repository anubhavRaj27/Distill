"""The Large Language Model boundary. See decision D13.

Everything that talks to a model goes through ``LLMClient``, and there are two
implementations: ``GeminiClient`` for real calls, and ``FakeClient`` which needs no key and
no network.

WHY THE FAKE IS A FIRST-CLASS IMPLEMENTATION, NOT A TEST DOUBLE
---------------------------------------------------------------
Three separate needs are met by one thing.

1. No Gemini key exists yet and the provider is explicitly not finalised, so the pipeline
   had to be buildable and demonstrable without one.
2. Section 9 of implementation.md requires the end-to-end test to be deterministic, which
   means a recorded fixture rather than a live call.
3. A reviewer cloning this repository with no key should still see the product work.

So the fake replays recorded interactions when it has them, and otherwise **synthesises a
deterministic extraction from the document's own text** using label-and-value heuristics.
That second mode matters more than it sounds: because the synthesised evidence quotes are
taken verbatim from the parsed page, grounding genuinely succeeds and provenance highlights
are real, not stubbed. The offline mode exercises the trust machinery rather than bypassing
it. Its confidence values are deliberately modest, so tiers land in medium and low, which is
an honest report of what a heuristic deserves.

FIXTURE KEYS ARE CONTENT-BASED, NOT PROMPT-BASED
-------------------------------------------------
Review finding 8.6. Keying recorded responses on a hash of the prompt would invalidate every
fixture on every prompt edit, and prompt tuning is the single most frequent change this
project will make. Keys are therefore built from the document content hash, the call kind,
and the schema version, so editing a prompt leaves the suite green while changing what a
document IS correctly forces a fixture update.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class CallKind(StrEnum):
    """What a model call is for. Selects the model tier, the prompt, and the fixture folder."""

    OPEN_EXTRACT = "open_extract"
    GUIDED_EXTRACT = "guided_extract"
    PROPOSE_SCHEMA = "propose_schema"
    MAP_DRIFT = "map_drift"
    NL2SQL = "nl2sql"
    SUGGEST_QUESTIONS = "suggest_questions"

    @property
    def needs_strong_model(self) -> bool:
        """Whether this call gets the Pro tier rather than Flash. See decision D13.

        Extraction and schema inference are where the hard sub-problem lives and where an
        error is expensive to detect, so they get the stronger model. Query translation is
        short, tightly constrained, and immediately verifiable by whether the SQL runs, so
        it gets the faster one and the user feels the difference.
        """
        return self in (
            CallKind.OPEN_EXTRACT,
            CallKind.GUIDED_EXTRACT,
            CallKind.PROPOSE_SCHEMA,
            CallKind.MAP_DRIFT,
        )


@dataclass
class Usage:
    """Token counts and latency for one call. Logged per call, for cost visibility."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float = 0.0
    attempts: int = 1
    model: str = ""
    provider: str = ""


@dataclass
class LLMRequest:
    """One structured-output request."""

    kind: CallKind
    prompt: str
    response_model: type[BaseModel]

    fixture_key: str
    """Stable identity for replay. Content-derived, never prompt-derived. See above."""

    system: str | None = None
    temperature: float = 0.0
    """Zero by default. Extraction is not a creative task, and a stable temperature makes
    a disagreement between two runs meaningful rather than noise."""

    context: dict[str, object] = field(default_factory=dict)
    """Whatever the fake needs in order to synthesise a plausible answer offline: the parsed
    page text, the current schema, the question. Ignored by the real client."""


@dataclass
class LLMResponse[ModelT: BaseModel]:
    value: ModelT
    usage: Usage


class LLMClient(Protocol):
    """What the rest of the application is allowed to know about model access."""

    @property
    def name(self) -> str:
        """Provider name, for logging and the health route."""
        ...

    async def structured(self, request: LLMRequest) -> LLMResponse[BaseModel]:
        """Run ``request`` and return an instance of its response model.

        Implementations retry on validation failure up to the configured attempt limit and
        then raise ``LLMInvalidOutput``. They raise ``LLMUnavailable`` for transport and
        rate-limit failures, so the worker can distinguish "retry later" from "this
        document cannot be processed".
        """
        ...
