"""Inferring the first schema from a batch of documents. Decisions D25 and D38.

The first batch does not conflict with an existing schema, but it conflicts with **itself**.
Eight documents can yield ``vendor_name`` from five, ``Supplier`` from two, and ``Vendor``
from one, and deciding those are one field is a judgment call.

v2 resolves that call without asking (decision D38):

1. **The initial schema applies immediately and never blocks.** The 60-second first run in
   the acceptance criteria depends on it.
2. **Unification within the batch is gated by decision D24's rule.** Source keys that unify
   confidently merge into one canonical field, which is the common case and the demo path.
3. **Source keys the rule finds uncertain stay as separate fields**, and the reason is
   recorded in the schema change summary. In v1 this queued a proposal card; v2 removed the
   card and kept the split.

WHY UNCERTAINTY SPLITS RATHER THAN MERGES
------------------------------------------
Asymmetry of harm, and it is the whole argument. A wrong merge commingles two genuinely
different fields' values under one column, and unpicking it means knowing which source key
produced each value. A wrong split leaves two clean columns, and the user can merge them
from the column menu, which moves values and provenance intact. When unsure, prefer the
error that is cheaper to undo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from app.config import Settings
from app.domain.fields import FieldSpec, FieldType, validate_field_key
from app.llm.base import LLMClient
from app.llm.contracts import ExtractedField
from app.llm.heuristics import slugify_key
from app.logging import get_logger
from app.pipeline.score import default_weight
from app.schema import embeddings
from app.schema.similarity import AskReason, Outcome, Thresholds, classify

logger = get_logger(__name__)

MAX_SAMPLE_VALUES = 3
MAX_FIELDS_IN_INITIAL_SCHEMA = 40
"""A first schema wider than this is a sign the batch is heterogeneous in a way no single
table serves. The widest fields by coverage are kept, so the table is still useful, and the
rest arrive later as drift proposals the user can accept individually."""

# Most specific first. Used to pick a canonical type when merged observations disagree:
# a field seen as a currency in one document and a bare number in another is a currency,
# because the currency reading carries strictly more information.
_TYPE_SPECIFICITY: tuple[FieldType, ...] = (
    FieldType.CURRENCY,
    FieldType.DATE,
    FieldType.NUMBER,
    FieldType.BOOLEAN,
    FieldType.ENUM,
    FieldType.STRING_LIST,
    FieldType.STRING,
)


@dataclass
class Observation:
    """One raw field key as seen across the batch, with the evidence for it."""

    key: str
    labels: list[str] = dataclass_field(default_factory=list)
    types: list[FieldType] = dataclass_field(default_factory=list)
    samples: list[str] = dataclass_field(default_factory=list)
    document_ids: set[str] = dataclass_field(default_factory=set)

    @property
    def label(self) -> str:
        """The most common label, which is what a user is most likely to recognise."""
        return Counter(self.labels).most_common(1)[0][0] if self.labels else self.key

    @property
    def coverage(self) -> int:
        return len(self.document_ids)

    @property
    def dominant_type(self) -> FieldType:
        if not self.types:
            return FieldType.STRING
        counts = Counter(self.types)
        best = max(counts.values())
        tied = [field_type for field_type, count in counts.items() if count == best]
        for candidate in _TYPE_SPECIFICITY:
            if candidate in tied:
                return candidate
        return tied[0]


@dataclass
class KeptSeparate:
    """Two fields the rule could not confidently unify, so both were kept.

    Not a question (decision D38). Both fields are already in the schema; this records the
    near-miss so the change summary can explain it and the interface can hint at a merge.
    """

    left_key: str
    left_label: str
    right_key: str
    right_label: str
    score: float
    reason: str


@dataclass
class InitialProposal:
    """The inferred schema, plus any unification the user should decide."""

    fields: list[FieldSpec]
    kept_separate: list[KeptSeparate] = dataclass_field(default_factory=list)
    coverage: dict[str, int] = dataclass_field(default_factory=dict)
    """Field key to how many documents in the batch contained it. Requirement FR-10."""

    @property
    def summary(self) -> str:
        """The change summary, and the only account the user gets of how the schema formed.

        Names the near-misses explicitly rather than counting them, because "we kept
        'Invoice No' and 'Invoice Number' apart" is actionable (the user can merge them) and
        "2 fields were kept separate" is not.
        """
        detail = f"Inferred {len(self.fields)} fields from the first batch"
        if self.kept_separate:
            pairs = "; ".join(
                f"kept {entry.left_label!r} and {entry.right_label!r} apart "
                f"({entry.score:.0%} match, too close to call)"
                for entry in self.kept_separate[:3]
            )
            detail += f". {pairs[:1].upper()}{pairs[1:]}"
            if len(self.kept_separate) > 3:
                detail += f"; and {len(self.kept_separate) - 3} more"
        return detail + "."


def collect_observations(
    extractions: dict[str, list[ExtractedField]],
) -> list[Observation]:
    """Fold per-document open extractions into one observation per raw key.

    ``extractions`` maps a document identifier to the fields found in it.
    """
    observed: dict[str, Observation] = {}
    for document_id, fields in extractions.items():
        for extracted in fields:
            key = _safe_key(extracted.key or extracted.label)
            if key is None:
                continue
            entry = observed.setdefault(key, Observation(key=key))
            entry.labels.append(extracted.label or key)
            entry.types.append(extracted.value_type)
            entry.document_ids.add(document_id)
            if extracted.value_text and len(entry.samples) < MAX_SAMPLE_VALUES:
                entry.samples.append(extracted.value_text)
    # Widest coverage first. Two effects, both wanted: the canonical field for a merged
    # group is the one most documents agreed on, and truncating to the width cap keeps the
    # most broadly useful columns.
    return sorted(observed.values(), key=lambda entry: (-entry.coverage, entry.key))


def _safe_key(raw: str) -> str | None:
    """A legal field key, or ``None`` if the raw text cannot produce one."""
    try:
        return validate_field_key(raw)
    except ValueError:
        pass
    try:
        return slugify_key(raw)
    except ValueError:
        logger.info("propose.unusable_key", raw=raw[:60])
        return None


def _describe(observation: Observation) -> str:
    """A description for the field, which also becomes its embedding text.

    Built from the labels the documents actually used, because that is the information a
    later drift match needs: knowing this field has been seen written as both "Supplier"
    and "Vendor" is what lets a third spelling match it.
    """
    distinct = list(dict.fromkeys(observation.labels))
    if len(distinct) > 1:
        return f"Seen in these documents as: {', '.join(distinct[:5])}."
    if observation.samples:
        return f"For example: {observation.samples[0][:80]}."
    return ""


async def propose_initial(
    extractions: dict[str, list[ExtractedField]],
    *,
    client: LLMClient,
    settings: Settings,
) -> InitialProposal:
    """Infer a first schema from open extraction across the first batch.

    Never raises for content reasons: a batch that yields nothing produces an empty
    proposal, which the caller handles, rather than failing every document in it.
    """
    observations = collect_observations(extractions)
    if not observations:
        return InitialProposal(fields=[])

    thresholds = Thresholds.from_settings(settings)

    # One embedding pass for the whole batch, rather than per comparison.
    texts = {
        observation.key: embeddings.embedding_text(
            observation.label, _describe(observation), observation.key
        )
        for observation in observations
    }
    resolved = await embeddings.vectors_for(client, list(texts.values()))
    vector_for = {key: resolved.get(text) for key, text in texts.items()}

    canonical: list[FieldSpec] = []
    merged_into: dict[str, str] = {}
    kept_separate: list[KeptSeparate] = []
    coverage: dict[str, int] = {}

    for observation in observations:
        incoming_type = observation.dominant_type
        verdict = classify(
            incoming_key=observation.key,
            incoming_label=observation.label,
            incoming_type=incoming_type,
            schema=canonical,
            incoming_vector=vector_for.get(observation.key),
            schema_vectors={
                field.key: vector_for.get(field.key) for field in canonical
            },
            thresholds=thresholds,
        )

        if verdict.outcome is Outcome.AUTO_MAP and verdict.target_key:
            target = next(field for field in canonical if field.key == verdict.target_key)
            _absorb(target, observation)
            merged_into[observation.key] = target.key
            coverage[target.key] = coverage.get(target.key, 0) + observation.coverage
            logger.info(
                "propose.unified",
                source=observation.key,
                into=target.key,
                reason=verdict.reason,
            )
            continue

        # AUTO_ADD and ASK both create a field. The difference is that ASK also records a
        # question, because decision D25 leaves uncertain unification SPLIT and asks.
        spec = FieldSpec(
            key=observation.key,
            label=observation.label,
            type=incoming_type,
            description=_describe(observation),
            source_keys=[observation.key],
            weight=default_weight(incoming_type),
            currency_default="USD" if incoming_type is FieldType.CURRENCY else None,
        )
        canonical.append(spec)
        coverage[spec.key] = observation.coverage

        # Only record a near-miss when something ACTUALLY resembles this field. An
        # ``UNCONFIRMED_NOVELTY`` ask means the opposite: nothing resembled it and there was
        # simply no vector to prove that. Reporting those as near-misses described 13 of 14
        # fields in the fixture batch as judgment calls, pairing unrelated things like
        # ``vendor`` with ``invoice_no``, which is noise in the summary rather than an
        # explanation.
        resembles_something = verdict.ask_reason in (
            AskReason.COMPETING_CANDIDATES,
            AskReason.BORDERLINE,
            AskReason.TYPE_MISMATCH,
        )
        if verdict.outcome is Outcome.ASK and resembles_something and verdict.best:
            kept_separate.append(
                KeptSeparate(
                    left_key=spec.key,
                    left_label=spec.label,
                    right_key=verdict.best.field_key,
                    right_label=verdict.best.field_label,
                    score=verdict.best.headline,
                    reason=verdict.reason,
                )
            )
            logger.info(
                "propose.kept_separate",
                field=spec.key,
                near=verdict.best.field_key,
                why=verdict.ask_reason.value if verdict.ask_reason else None,
            )

    if len(canonical) > MAX_FIELDS_IN_INITIAL_SCHEMA:
        kept = sorted(canonical, key=lambda field: -coverage.get(field.key, 0))[
            :MAX_FIELDS_IN_INITIAL_SCHEMA
        ]
        dropped = [field.key for field in canonical if field not in kept]
        logger.info("propose.truncated", kept=len(kept), dropped=len(dropped))
        keep_keys = {field.key for field in kept}
        canonical = [field for field in canonical if field.key in keep_keys]
        kept_separate = [
            entry
            for entry in kept_separate
            if entry.left_key in keep_keys and entry.right_key in keep_keys
        ]

    return InitialProposal(
        fields=canonical, kept_separate=kept_separate, coverage=coverage
    )


def _absorb(target: FieldSpec, observation: Observation) -> None:
    """Record that ``observation`` unified into ``target``, in place.

    The source key is appended to ``source_keys``, which is what makes the merge stick: a
    later document using that spelling matches by alias and never re-proposes the rename.
    """
    for key in [observation.key, *dict.fromkeys(observation.labels)]:
        if key and key not in target.source_keys:
            target.source_keys.append(key)
