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

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class CallKind(StrEnum):
    """What a model call is for. Selects the model tier, the prompt, and the fixture folder.

    v2 removed ``NL2SQL`` with the feature it served (decision D35) and added the three
    calls the chat and dashboard need. There are now exactly two streamed-text callers and
    the rest are structured.
    """

    OPEN_EXTRACT = "open_extract"
    GUIDED_EXTRACT = "guided_extract"
    PROPOSE_SCHEMA = "propose_schema"
    MAP_DRIFT = "map_drift"

    CHAT_PLAN = "chat_plan"
    """Structured. Decides whether the question is answerable and whether a visual helps,
    and if so emits a `Visual` holding a query specification. It never emits numbers
    (decision D37)."""

    CHAT_ANSWER = "chat_answer"
    """Streamed text. Writes the prose, citing passages with markers and referring to
    computed figures by placeholder (decisions D45, D46)."""

    PLAN_DASHBOARD = "plan_dashboard"
    """Structured. Proposes dashboard panels from field statistics (decision D40)."""

    SUGGEST_QUESTIONS = "suggest_questions"

    @property
    def needs_strong_model(self) -> bool:
        """Whether this call gets the Pro tier rather than Flash. See decision D13.

        True only for extraction and schema inference. Those are the accuracy-critical
        calls, they run once per document rather than once per interaction, and an error in
        them is expensive to detect later because it is baked into the table.

        Everything the user waits on synchronously runs on Flash. Chat is the clearest
        case: requirement FR-26 asks for a first prose token within three seconds, and that
        target is a product decision about how the answer feels, not a cost saving.
        """
        return self in (
            CallKind.OPEN_EXTRACT,
            CallKind.GUIDED_EXTRACT,
            CallKind.PROPOSE_SCHEMA,
            CallKind.MAP_DRIFT,
        )

    @property
    def is_streamed(self) -> bool:
        """Whether this call is served by ``stream_text`` rather than ``structured``."""
        return self is CallKind.CHAT_ANSWER


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


type Vector = list[float]
"""One embedding. Compared with cosine similarity in ``app.schema.drift``."""


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

    def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream a text answer as deltas. Decision D44.

        Returns an async iterator rather than being an async generator itself, so that a
        caller can hold the iterator without having started the request, and so that
        ``FakeClient`` can return a pre-recorded sequence without pretending to be a
        coroutine.

        Deltas are raw model output: markers and placeholders are still in the text.
        Resolving them is ``app.chat.stream``'s job, deliberately kept out of the provider
        so that both providers stay dumb about the answer format.

        Raises ``LLMUnavailable`` for transport failures, like every other call. A failure
        part way through a stream is still a failure: the caller persists the partial answer
        with ``status = failed`` rather than presenting a truncated answer as complete.
        """
        ...

    async def embed(self, texts: Sequence[str]) -> list[Vector | None]:
        """Embed ``texts`` for schema drift matching. Decision D24.

        Returns one entry per input, in order. An entry is ``None`` when this provider has
        no vector for that text, which is **not** an error and not a production degradation
        path: against Gemini every text gets a vector, and a genuine transport failure
        raises ``LLMUnavailable`` like any other call. ``None`` exists for ``FakeClient``,
        which replays recorded vectors and has none for a label it has never seen — the
        no-key and test case D13 covers.

        A caller that receives ``None`` scores that pair on string similarity alone, which
        yields more proposal cards and fewer auto-applies. The direction of that degradation
        is deliberate: toward asking the user, never toward a silent wrong merge.
        """
        ...
