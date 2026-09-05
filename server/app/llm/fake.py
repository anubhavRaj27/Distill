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

import asyncio
import difflib
import json
import time
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.domain.document import ParsedDocument
from app.domain.fields import FieldSpec, fold_label_for_similarity
from app.errors import LLMInvalidOutput, LLMUnavailable
from app.llm.base import CallKind, EmbedTask, LLMRequest, LLMResponse, Usage, Vector
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
        self._embeddings: dict[str, Vector] | None = None
        self._synthesisers: dict[CallKind, Synthesiser] = {
            CallKind.OPEN_EXTRACT: _synthesise_open_extraction,
            CallKind.GUIDED_EXTRACT: _synthesise_guided_extraction,
            CallKind.CHAT_PLAN: _synthesise_chat_plan,
            CallKind.SUGGEST_QUESTIONS: _synthesise_suggestions,
            CallKind.PLAN_DASHBOARD: _synthesise_dashboard,
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

    async def embed(
        self, texts: Sequence[str], *, task: EmbedTask = "similarity"
    ) -> list[Vector | None]:
        """Replay recorded vectors. Decision D24.

        ``task`` is accepted to satisfy the protocol and deliberately ignored: a recording
        is one vector per label, and keying recordings by task as well would multiply the
        fixture corpus by three to encode a distinction no fixture can honour.

        Every recorded label lives in one JSON object at ``{fixture_dir}/embed/labels.json``
        (``{label: [floats]}``) rather than a file per label, because these are keyed by a
        short field label rather than a document hash, and there are a few dozen of them for
        the whole sample corpus.

        A label with no recorded vector returns ``None`` rather than a synthesised one. A
        made-up vector would score a confident-looking cosine against every other field,
        which is worse than no signal: the caller would auto-apply on noise. ``None`` sends
        the caller back to string similarity alone, which produces more proposal cards and
        fewer auto-applies — the safe direction.
        """
        if not texts:
            return []
        recorded = self._recorded_embeddings()
        vectors = [recorded.get(_normalise_label(text)) for text in texts]
        missing = sum(1 for vector in vectors if vector is None)
        if missing:
            logger.info(
                "llm.embed_unrecorded_labels",
                missing=missing,
                total=len(texts),
                detail="scored on string similarity alone; record vectors to change this",
            )
        return vectors

    def _recorded_embeddings(self) -> dict[str, Vector]:
        """Load and cache the recorded vectors. Missing file is normal, not an error."""
        if self._embeddings is None:
            path = self._fixture_dir / "embed" / "labels.json"
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                self._embeddings = {
                    _normalise_label(label): [float(component) for component in vector]
                    for label, vector in payload.items()
                }
            else:
                self._embeddings = {}
        return self._embeddings

    # -- streamed text (decision D44) -----------------------------------

    STREAM_FIXTURE_DIR = "chat_answer"
    WORDS_PER_PIECE = 3
    PIECE_DELAY_SECONDS = 0.015

    async def stream_text(self, request: LLMRequest) -> AsyncIterator[str]:
        """Yield a recorded or synthesised answer in word-sized pieces.

        Chunked and slightly delayed on purpose. A fake that returned the whole answer in
        one piece would let a client's streaming path pass tests it has never actually
        exercised: no partial markers spanning deltas, no placeholder split across a
        boundary, no incremental rendering. Those are precisely the cases
        ``app.chat.stream`` exists to handle, so the fake has to produce them.
        """
        recorded = self._replay_text(request)
        answer = recorded if recorded is not None else _synthesise_answer(request)

        words = answer.split(" ")
        for start in range(0, len(words), self.WORDS_PER_PIECE):
            piece = " ".join(words[start : start + self.WORDS_PER_PIECE])
            # A trailing space keeps the reassembled text identical to the original.
            yield piece if start + self.WORDS_PER_PIECE >= len(words) else piece + " "
            if self.PIECE_DELAY_SECONDS:
                await asyncio.sleep(self.PIECE_DELAY_SECONDS)

    def _replay_text(self, request: LLMRequest) -> str | None:
        path = self._fixture_dir / self.STREAM_FIXTURE_DIR / f"{request.fixture_key}.txt"
        if not path.is_file():
            return None
        logger.info("llm.replayed_stream_fixture", fixture=path.name)
        return path.read_text(encoding="utf-8")

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


# The fuzzy label fold now lives in the domain layer, so that this provider and
# ``app.schema.similarity`` score labels identically rather than drifting apart. Kept as a
# module-level alias because this file refers to it in several places and the short name
# reads better at the call sites.
_normalise_label = fold_label_for_similarity


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


def _synthesise_answer(request: LLMRequest) -> str:
    """Compose a plausible offline answer from the retrieved passages. Decision D13.

    Not a stub string. It deliberately produces the two constructs the real answer format
    uses, because they are the ones the pipeline has to get right:

    * ``[^chunk:<id>]`` citation markers, so ``app.chat.stream``'s marker resolution runs,
      citation numbering happens, and the client receives real ``citation`` events pointing
      at real word spans
    * ``{{result.<path>}}`` placeholders when a visual was evaluated, so the substitution
      path runs and the number the user sees is the server's, not this function's
      (decision D46)

    The prose itself is quoted from the passages rather than invented, which keeps the
    offline mode honest: every claim it makes is genuinely in the documents, and every
    figure comes from the evaluated result.
    """
    question = str(request.context.get("question") or "").strip()
    passages = request.context.get("passages") or []
    result = request.context.get("result")

    if not isinstance(passages, list) or not passages:
        searched = request.context.get("document_count")
        scope = f" across {searched} documents" if searched else ""
        return (
            f"I could not find anything{scope} that answers that. "
            f"Nothing in the indexed passages mentions it."
        )

    sentences: list[str] = []
    for passage in passages[:2]:
        if not isinstance(passage, dict):
            continue
        chunk_id = passage.get("chunk_id")
        text = " ".join(str(passage.get("text", "")).split())
        if not chunk_id or not text:
            continue
        excerpt = text[:180].rstrip(" ,;:.")
        sentences.append(f"{excerpt} [^chunk:{chunk_id}].")

    if not sentences:
        return "The retrieved passages do not contain enough detail to answer that."

    opening = f"Looking at the documents for {question!r}: " if question else ""
    body = " ".join(sentences)

    figure = ""
    if isinstance(result, dict):
        rows = result.get("rows") or []
        if isinstance(rows, list) and rows:
            # Reference the computed value by PATH, never by retyping it. This is the whole
            # point of decision D46, and the offline provider has to honour it too or the
            # substitution path would never run outside a live call.
            figure = " The chart above puts the leading figure at {{result.rows.0.value}}."
        elif result.get("total") is not None:
            figure = " The chart above shows a total of {{result.total}}."

    return f"{opening}{body}{figure}"


# Words that signal a question wants a number rather than a sentence. Used only by the
# offline planner; a real model reads the question properly.
_QUANTITATIVE_HINTS = (
    "total", "sum", "how much", "how many", "count", "average", "avg", "most",
    "largest", "highest", "lowest", "per ", " by ", "breakdown", "spend",
)
_MISSING_HINTS = ("missing", "without", "no ", "lack", "absent")


def _synthesise_chat_plan(request: LLMRequest) -> BaseModel:
    """Decide answerability and a visual with no model call. Decision D13.

    Crude by design, and it does the one thing that matters: it emits a **query
    specification** rather than numbers, so the whole decision D37 path (evaluate, build a
    surface, bind by path, substitute placeholders in prose) runs offline exactly as it does
    with a key. A stub that returned no visual would leave that path untested and
    undemonstrable.
    """
    from app.chat.answer import ChatPlan
    from app.domain.chat import VisualKind
    from app.domain.fields import FieldSpec, FieldType, fold_label_for_similarity
    from app.insights.queryspec import DataQuery, Filter, Visual

    question = str(request.context.get("question") or "")
    lowered = question.lower()
    passages = request.context.get("passages") or []
    raw_schema = request.context.get("schema") or []
    fields = [
        entry if isinstance(entry, FieldSpec) else FieldSpec.model_validate(entry)
        for entry in raw_schema
        if isinstance(entry, (dict, FieldSpec))
    ]

    if not passages:
        return ChatPlan(
            answerable=False,
            not_answerable_reason=(
                "Nothing in the indexed passages relates to that question."
            ),
            visual=None,
        )

    if not fields or not any(hint in lowered for hint in _QUANTITATIVE_HINTS):
        return ChatPlan(answerable=True, visual=None)

    question_words = set(fold_label_for_similarity(question).split())

    def mentioned(field: FieldSpec) -> bool:
        label_words = set(fold_label_for_similarity(field.label).split())
        return bool(label_words & question_words)

    numeric = [f for f in fields if f.type in (FieldType.CURRENCY, FieldType.NUMBER)]
    # A field the question actually names beats one it does not, and money beats a count.
    measure = next(
        (f for f in numeric if mentioned(f) and f.type is FieldType.CURRENCY),
        next((f for f in numeric if mentioned(f)), None),
    ) or next((f for f in numeric if f.type is FieldType.CURRENCY), None)

    groupable = [
        f for f in fields if f.type in (FieldType.STRING, FieldType.ENUM, FieldType.DATE)
    ]
    group = next((f for f in groupable if mentioned(f)), None)

    # "how many X are missing Y" is a count with a presence filter, not a sum.
    if any(hint in lowered for hint in _MISSING_HINTS):
        target = next((f for f in fields if mentioned(f)), None)
        if target is not None:
            return ChatPlan(
                answerable=True,
                visual=Visual(
                    kind=VisualKind.METRIC,
                    title=f"Documents with no {target.label}",
                    query=DataQuery(
                        aggregate="count",
                        filters=[Filter(field=target.key, op="missing")],
                    ),
                ),
            )

    if measure is None:
        return ChatPlan(
            answerable=True,
            visual=Visual(
                kind=VisualKind.BAR if group else VisualKind.METRIC,
                title=f"Documents by {group.label}" if group else "Documents",
                query=DataQuery(aggregate="count", group_by=group.key if group else None),
            ),
        )

    return ChatPlan(
        answerable=True,
        visual=Visual(
            kind=VisualKind.BAR if group else VisualKind.METRIC,
            title=(
                f"{measure.label} by {group.label}"
                if group
                # "Total Total Due" reads as a bug. A label that already starts with the
                # word does not need it prefixed.
                else (
                    measure.label
                    if measure.label.lower().startswith("total")
                    else f"Total {measure.label}"
                )
            ),
            query=DataQuery(
                aggregate="sum",
                measure_field=measure.key,
                group_by=group.key if group else None,
            ),
            unit_hint=measure.currency_default,
        ),
    )


def _total_phrase(label: str) -> str:
    """"Total Total Due" reads as a bug, so a label already saying "total" keeps it."""
    lowered = label.lower()
    return lowered if lowered.startswith("total") else f"total {lowered}"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _synthesise_dashboard(request: LLMRequest) -> BaseModel:
    """Propose dashboard panels from the statistics, with no model call. Decision D13.

    Deliberately proposes a VARIED set rather than repeating one shape, because the point
    of the offline path is to exercise the real one: a plan of six metrics would never
    reach the bar, line, or table branches of the builder, nor most of the vetting rules.

    It also proposes only what the statistics support, which is the same instruction the
    real prompt gives. That matters for the demo: a panel the server then drops is a wasted
    slot, so the offline planner should not be systematically worse at this than a model.
    """
    from app.domain.chat import VisualKind
    from app.insights.dashboard import DashboardPlan, Panel
    from app.insights.queryspec import DataQuery, Visual

    stats = request.context.get("stats") or []
    document_count = int(request.context.get("document_count") or 0)
    if not isinstance(stats, list) or not stats:
        return DashboardPlan(panels=[])

    def entries(**criteria: object) -> list[dict]:
        found = [
            entry
            for entry in stats
            if isinstance(entry, dict)
            and all(entry.get(key) == value for key, value in criteria.items())
        ]
        return sorted(found, key=lambda entry: -float(entry.get("coverage") or 0))

    money = entries(type="currency")
    groupable = [
        entry
        for entry in stats
        if isinstance(entry, dict)
        and entry.get("groupable")
        and entry.get("type") in ("string", "enum")
    ]
    # Prefer a field whose values actually REPEAT: that is what a category is, and what
    # makes a bar chart a comparison rather than a list. Falls back to any groupable field
    # when none repeats, which is the normal state of a very small corpus and not worth
    # refusing to draw anything over.
    repeating = [
        entry
        for entry in groupable
        if int(entry.get("distinct") or 0) < int(entry.get("present") or 0)
    ]
    groupable = repeating or groupable
    groupable.sort(key=lambda entry: -float(entry.get("coverage") or 0))
    dates = entries(type="date")

    panels: list[Panel] = []

    # Lead with the figure that characterises the whole collection.
    panels.append(
        Panel(
            visual=Visual(
                kind=VisualKind.METRIC,
                title="Documents in this collection",
                query=DataQuery(aggregate="count"),
            ),
            rationale=f"There are {document_count} documents, the denominator for everything else.",
        )
    )

    if money:
        top = money[0]
        code = (top.get("currencies") or [None])[0]
        panels.append(
            Panel(
                visual=Visual(
                    kind=VisualKind.METRIC,
                    title=_total_phrase(str(top["label"])).capitalize(),
                    query=DataQuery(aggregate="sum", measure_field=str(top["key"])),
                    unit_hint=code,
                ),
                rationale=(
                    f"{top['label']} is present in {float(top['coverage']):.0%} of "
                    f"documents, so the total is meaningful."
                ),
            )
        )
        if groupable:
            group = groupable[0]
            panels.append(
                Panel(
                    visual=Visual(
                        kind=VisualKind.BAR,
                        title=f"{top['label']} by {group['label'].lower()}",
                        query=DataQuery(
                            aggregate="sum",
                            measure_field=str(top["key"]),
                            group_by=str(group["key"]),
                        ),
                        unit_hint=code,
                    ),
                    rationale=(
                        f"{group['label']} has {group['distinct']} distinct values, few "
                        f"enough to compare side by side."
                    ),
                )
            )

    if groupable:
        group = groupable[-1] if len(groupable) > 1 else groupable[0]
        panels.append(
            Panel(
                visual=Visual(
                    kind=VisualKind.BAR,
                    title=f"Documents by {group['label'].lower()}",
                    query=DataQuery(aggregate="count", group_by=str(group["key"])),
                ),
                rationale=(
                    f"{group['label']} splits the collection into {group['distinct']} groups."
                ),
            )
        )

    if dates:
        date_field = dates[0]
        panels.append(
            Panel(
                visual=Visual(
                    kind=VisualKind.LINE,
                    title=f"Documents by month of {date_field['label'].lower()}",
                    query=DataQuery(
                        aggregate="count", group_by=str(date_field["key"]), bucket="month"
                    ),
                ),
                rationale=(
                    f"{date_field['label']} is present in "
                    f"{float(date_field['coverage']):.0%} of documents, enough for a trend."
                ),
            )
        )

    # A field almost nothing filled in is worth surfacing as a gap rather than a chart.
    sparse = [
        entry
        for entry in stats
        if isinstance(entry, dict) and 0 < float(entry.get("coverage") or 0) < 0.6
    ]
    if sparse:
        gap = sparse[0]
        panels.append(
            Panel(
                visual=Visual(
                    kind=VisualKind.METRIC,
                    title=f"Documents with no {str(gap['label']).lower()}",
                    query=DataQuery(
                        aggregate="count",
                        filters=[{"field": str(gap["key"]), "op": "missing"}],  # type: ignore[list-item]
                    ),
                ),
                rationale=(
                    f"Only {float(gap['coverage']):.0%} of documents have "
                    f"{_article(str(gap['label']))} {str(gap['label']).lower()}, "
                    f"which is worth knowing."
                ),
            )
        )

    return DashboardPlan(panels=panels)


def _synthesise_suggestions(request: LLMRequest) -> BaseModel:
    """Three suggested questions built from the schema, with no model call."""
    from app.chat.suggestions import SuggestedQuestions
    from app.domain.fields import FieldSpec, FieldType

    raw_schema = request.context.get("schema") or []
    fields = [
        entry if isinstance(entry, FieldSpec) else FieldSpec.model_validate(entry)
        for entry in raw_schema
        if isinstance(entry, (dict, FieldSpec))
    ]
    money = next((f for f in fields if f.type is FieldType.CURRENCY), None)
    party = next(
        (
            f
            for f in fields
            if f.type is FieldType.STRING
            and any(word in f.key for word in ("vendor", "supplier", "party", "name"))
        ),
        next((f for f in fields if f.type is FieldType.STRING), None),
    )
    other = next((f for f in fields if f.type is FieldType.STRING and f is not party), None)

    questions: list[str] = []
    if money and party:
        questions.append(
            f"What is the {_total_phrase(money.label)} by {party.label.lower()}?"
        )
    elif money:
        questions.append(f"What is the {_total_phrase(money.label)}?")
    if other:
        label = other.label.lower()
        questions.append(f"Which documents are missing {_article(label)} {label}?")
    if party:
        questions.append(f"Which {party.label.lower()} appears most often?")

    fallback = [
        "What do these documents have in common?",
        "Which document has the largest amount?",
        "What dates do these documents cover?",
    ]
    while len(questions) < 3:
        questions.append(fallback[len(questions) % len(fallback)])
    return SuggestedQuestions(questions=questions[:3])


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
