"""The fake provider: replay a recorded response, or synthesise one offline.

See ``app.llm.base`` for why this is a first-class implementation rather than a test double,
and decision D13 for the reasoning. In short: no key exists yet, the end-to-end test has to
be deterministic, and a reviewer with no key should still see the product work.

Resolution order for every call:

1. **Replay.** If ``{fixture_dir}/{kind}/{fixture_key}.json`` exists, it is validated into
   the request's response model and returned. This is the deterministic path the test suite
   and the Playwright demo script use.
2. **Synthesise.** Otherwise a deterministic answer is derived from the request's context,
   using the heuristics in ``app.llm.heuristics``. Modest confidence values, evidence quotes
   taken verbatim from the parsed page, so grounding genuinely runs.

A call kind with no synthesiser raises ``LLMUnavailable`` with a message that says which
fixture is missing and what to do about it, rather than returning an empty result that would
look like a document with nothing in it.
"""

from __future__ import annotations

import difflib
import json
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.domain.document import ParsedDocument
from app.domain.fields import FieldSpec
from app.errors import LLMInvalidOutput, LLMUnavailable
from app.llm.base import CallKind, LLMRequest, LLMResponse, Usage
from app.llm.contracts import ExtractedField, GuidedExtraction, OpenExtraction
from app.llm.heuristics import extract_offline
from app.logging import get_logger

logger = get_logger(__name__)

LABEL_MATCH_THRESHOLD = 0.72
"""Similarity above which an offline-extracted label is considered to BE a schema field.
Below it, the value becomes an extra field and therefore a drift candidate, which is the
safer direction to err: proposing a mapping the user can accept in one click beats silently
filing a value under the wrong column."""

Synthesiser = Callable[[LLMRequest], BaseModel]


class FakeClient:
    """Deterministic model responses with no network and no key."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fixture_dir = settings.llm_fixture_dir
        self._synthesisers: dict[CallKind, Synthesiser] = {
            CallKind.OPEN_EXTRACT: _synthesise_open_extraction,
            CallKind.GUIDED_EXTRACT: _synthesise_guided_extraction,
        }

    @property
    def name(self) -> str:
        return "fake"

    def register(self, kind: CallKind, synthesiser: Synthesiser) -> None:
        """Add or replace a synthesiser. Used as later phases add call kinds."""
        self._synthesisers[kind] = synthesiser

    def fixture_path(self, kind: CallKind, fixture_key: str) -> Path:
        return self._fixture_dir / kind.value / f"{fixture_key}.json"

    async def structured(self, request: LLMRequest) -> LLMResponse[BaseModel]:
        started = time.perf_counter()

        replayed = self._replay(request)
        if replayed is not None:
            return LLMResponse(
                value=replayed,
                usage=Usage(
                    latency_ms=(time.perf_counter() - started) * 1000,
                    model="fixture",
                    provider=self.name,
                ),
            )

        synthesiser = self._synthesisers.get(request.kind)
        if synthesiser is None:
            raise LLMUnavailable(
                f"There is no recorded answer for this {request.kind.value} request, and "
                f"no offline fallback for it. Either set GEMINI_API_KEY to make real "
                f"calls, or record a fixture at "
                f"{self.fixture_path(request.kind, request.fixture_key)}.",
                call_kind=request.kind.value,
                fixture_key=request.fixture_key,
            )

        value = synthesiser(request)
        logger.info(
            "llm.synthesised_offline",
            kind=request.kind.value,
            fixture_key=request.fixture_key,
        )
        return LLMResponse(
            value=value,
            usage=Usage(
                latency_ms=(time.perf_counter() - started) * 1000,
                model="offline-heuristic",
                provider=self.name,
            ),
        )

    def _replay(self, request: LLMRequest) -> BaseModel | None:
        path = self.fixture_path(request.kind, request.fixture_key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = request.response_model.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            # A corrupt fixture is a broken test, not a model failure, so it says exactly
            # which file to look at.
            raise LLMInvalidOutput(
                f"The recorded response at {path} does not match "
                f"{request.response_model.__name__}. Re-record it or delete it.",
                fixture=str(path),
            ) from exc
        logger.info("llm.replayed_fixture", kind=request.kind.value, fixture=path.name)
        return value


# ---------------------------------------------------------------------------
# Synthesisers
# ---------------------------------------------------------------------------


def _document_from(request: LLMRequest) -> ParsedDocument:
    document = request.context.get("document")
    if isinstance(document, ParsedDocument):
        return document
    if isinstance(document, dict):
        return ParsedDocument.model_validate(document)
    raise LLMUnavailable(
        "The offline provider needs the parsed document in the request context.",
        call_kind=request.kind.value,
    )


def _schema_from(request: LLMRequest) -> list[FieldSpec]:
    fields = request.context.get("schema") or []
    if not isinstance(fields, list):
        return []
    return [
        field if isinstance(field, FieldSpec) else FieldSpec.model_validate(field)
        for field in fields
    ]


def _synthesise_open_extraction(request: LLMRequest) -> OpenExtraction:
    return extract_offline(_document_from(request))


def _normalise_label(text: str) -> str:
    """Fold a label for comparison: lowercase, no punctuation, no filler words.

    Dropping "no", "number", "total", and "amount" is what lets ``Invoice No`` match
    ``invoice_number`` and ``Amount`` match ``total_due``, which is the whole point: those
    are the same field written differently, and recognising that is the unification problem.
    """
    lowered = "".join(character if character.isalnum() else " " for character in text.lower())
    # "date" is NOT filler, deliberately. It carries meaning, unlike "no" and "number":
    # stripping it collapsed "Issue Date" to "issue" and "Date" to nothing, so a
    # spreadsheet column called "Date" scored badly against an "Issue Date" field for the
    # wrong reason. It now scores below the threshold on its own merits and becomes a
    # drift proposal the user decides, which is what product principle 3 asks for.
    filler = {"no", "num", "number", "id", "ref", "reference", "the", "of"}
    words = [word for word in lowered.split() if word not in filler]
    return " ".join(words) or lowered.strip()


def _best_match(field: FieldSpec, candidates: list[ExtractedField]) -> ExtractedField | None:
    """Find the extracted value that corresponds to ``field``, if any.

    Tried in order of how much evidence each kind of match carries: an exact key match, a
    key already recorded as an alias of this field, then label similarity. The alias check
    matters because it is how a mapping the user has ALREADY approved keeps working on the
    next document, rather than being re-proposed every time.
    """
    for candidate in candidates:
        if candidate.key == field.key:
            return candidate

    aliases = {alias.lower() for alias in field.source_keys}
    for candidate in candidates:
        if candidate.key.lower() in aliases:
            return candidate

    target = _normalise_label(field.label or field.key)
    best: ExtractedField | None = None
    best_score = 0.0
    for candidate in candidates:
        score = difflib.SequenceMatcher(
            None, target, _normalise_label(candidate.label or candidate.key)
        ).ratio()
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= LABEL_MATCH_THRESHOLD else None


def _synthesise_guided_extraction(request: LLMRequest) -> GuidedExtraction:
    """Fill the current schema from the offline extraction, and flag what did not fit.

    The leftovers become ``extra_fields``, which is exactly what drift detection consumes.
    So the offline mode produces genuine schema drift proposals rather than pretending every
    document fits, which is the behaviour the product is actually about.
    """
    document = _document_from(request)
    schema = _schema_from(request)
    found = extract_offline(document).fields

    values: list[ExtractedField] = []
    consumed: set[int] = set()

    for field in schema:
        available = [
            candidate
            for index, candidate in enumerate(found)
            if index not in consumed
        ]
        match = _best_match(field, available)
        if match is None:
            # Absent, not failed. Requirement: the model returns null rather than guessing.
            values.append(
                ExtractedField(
                    key=field.key,
                    label=field.label,
                    value_text=None,
                    value_type=field.type,
                    page_index=0,
                    confidence=0.4,
                    reasoning=(
                        f"Offline heuristic: no value resembling {field.label!r} was found "
                        f"in this document."
                    ),
                )
            )
            continue

        consumed.add(found.index(match))
        values.append(
            match.model_copy(
                update={
                    "key": field.key,
                    "label": field.label,
                    # The SCHEMA decides the type, not the document. A field the user
                    # agreed is a currency stays a currency even if this document wrote it
                    # in a way the heuristic would have called a plain number.
                    "value_type": field.type,
                }
            )
        )

    extra = [
        candidate for index, candidate in enumerate(found) if index not in consumed
    ]
    return GuidedExtraction(values=values, extra_fields=extra)


def _serialise_for_fixture(value: BaseModel) -> str:
    return json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def write_fixture(path: Path, value: BaseModel) -> None:
    """Persist a response so the fake can replay it. Used by record mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialise_for_fixture(value), encoding="utf-8")


def fixture_key_for_document(
    content_hash: str, kind: CallKind, schema_version: int | None = None
) -> str:
    """A replay key that survives prompt edits. Review finding 8.6.

    Built from WHAT is being processed, never from the prompt text. Editing a prompt leaves
    the suite green; changing the document or the schema correctly invalidates the fixture.
    """
    suffix = f"-v{schema_version}" if schema_version is not None else ""
    return f"{content_hash[:16]}-{kind.value}{suffix}"
