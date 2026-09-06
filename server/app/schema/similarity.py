"""How alike are two fields, and is the answer obvious enough to act on unasked.

This module implements **decision D18**. Decision D27 owns the *policy* (when the user is
interrupted); this owns the *signal* (how similarity is measured and when it is
unambiguous).

TWO SIGNALS, COMBINED WITH OR, NOT AND AND NOT AVERAGED
--------------------------------------------------------
String similarity and embedding similarity fail on disjoint cases, which is the whole reason
they are combined with OR:

* string similarity catches formatting and typo variants (``Invoice No`` versus
  ``invoice_number``) that an embedding call would be wasted on
* embeddings catch semantic renames (``Supplier`` versus ``vendor_name``, which scores about
  0.2 on string) that string matching cannot see at all

Averaging them would destroy the signal: a true synonym scores near zero on string and high
on embedding, and the blend lands it in the ambiguous band where it needs a card. A strict
AND could never auto-map a synonym, since a synonym fails the string test by definition.

THE MARGIN RULE IS WHAT KEEPS OR FROM BEING RECKLESS
-----------------------------------------------------
A high absolute score is not evidence of an unambiguous match when a second field scores
nearly as high. ``Supplier`` at 0.96 against ``vendor_name`` and 0.94 against
``supplier_id`` is a genuine judgment call, and the margin test routes it to a human instead
of a coin flip. Same instinct as decision D5: the useful question is rarely "how confident
is the score", it is "is there a competing answer".

NOVELTY INVERTS THE COMBINATOR, DELIBERATELY
---------------------------------------------
Declaring a field *new* is a claim about the **absence** of a match, so both signals must
agree that nothing resembles it. If either sees a resemblance, it is not clearly novel and
the user decides.

This is also why a **missing** embedding blocks auto-add rather than being ignored. String
similarity alone cannot support a claim of novelty: a semantic rename scores about 0.2 on
string, so with no vector it would look "clearly novel" and be auto-added as a duplicate
column, which is exactly the silent wrong outcome decision D27 says to avoid. With no
vector the field goes to a card. Recorded fixtures are what keep the offline path behaving
like the online one (decision D11).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz

from app.domain.fields import FieldSpec, FieldType, fold_label
from app.llm.base import Vector

# ---------------------------------------------------------------------------
# Raw signals
# ---------------------------------------------------------------------------


def cosine(left: Vector, right: Vector) -> float:
    """Cosine similarity, clamped to ``[0, 1]``.

    Clamped rather than allowed negative: a negative cosine and a zero cosine both mean
    "unrelated" for this purpose, and letting negatives through would make an
    ``average``-style comparison of scores misleading. Mismatched dimensions return 0.0
    rather than raising, because that means two different embedding models were used and
    the honest answer is "no usable signal", which routes to a card.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def string_similarity(left: str, right: str) -> float:
    """Label similarity in ``[0, 1]``, on the case-and-separator-folded forms.

    ``token_sort_ratio`` rather than a plain ratio, so that ``Due Total`` and ``Total Due``
    are recognised as the same label. Word order in a field label carries no meaning.

    USES ``fold_label``, NOT ``fold_label_for_similarity``, AND THAT IS LOAD-BEARING.
    The filler-word fold drops "id", "number", and "reference", which is useful for the
    loose matching the offline provider does but is actively wrong here. It scores
    ``Supplier`` against ``Supplier ID`` at **1.00**, because both fold to "supplier", and
    at 1.00 this function would clear the 0.90 auto-map bar and silently merge a company
    name into an identifier column. Those are different fields.

    That pair is, almost word for word, decision D18's own example of a case that must go to
    a human. With the case-and-separator fold it scores 0.84, lands below the bar, and asks.

    The division of labour this restores is exactly the one D18 describes: string
    similarity catches **formatting and typo** variants, and embeddings catch **meaning**.
    ``Invoice No`` against ``invoice_number`` scores 0.75 here and is therefore a card
    unless the embedding signal recognises it, which is the correct route for a difference
    that is semantic rather than typographic.
    """
    # Underscores become spaces before scoring. ``fold_label`` joins with underscores,
    # which is right for an identifier but makes the whole label a SINGLE token, and
    # ``token_sort_ratio`` splits on whitespace. Without this, token sorting never happens
    # and the function silently degrades to a plain character ratio, so "Due Total" and
    # "Total Due" would score about 0.5 instead of 1.0.
    folded_left = fold_label(left).replace("_", " ")
    folded_right = fold_label(right).replace("_", " ")
    if not folded_left or not folded_right:
        return 0.0
    return float(fuzz.token_sort_ratio(folded_left, folded_right)) / 100.0


def types_compatible(incoming: FieldType, target: FieldSpec) -> bool:
    """Whether a value of ``incoming`` type can land in ``target`` without losing meaning.

    Deliberately strict, because this gates auto-mapping and the cost of being wrong is
    asymmetric: refusing produces a proposal card the user resolves in one click, while
    accepting wrongly commingles two fields' values under one column and unpicking that
    means knowing which source key produced each value (decision D27).

    So only two things are compatible:

    * the same type
    * a bare number into a currency field **that already has a default code**, because that
      is the one case where the conversion is fully defined

    Notably refused, though each is superficially tempting:

    * anything into a string field. Stringification always "works", which would make a
      string field a magnet that swallows dates and amounts and silently destroys their
      queryability.
    * currency into number. Drops the currency code, which is part of the value.
    * a string into an enum. Whether it is compatible depends on the actual value being one
      of the permitted ones, which is not knowable while matching schemas.
    """
    if incoming is target.type:
        return True
    if incoming is FieldType.NUMBER and target.type is FieldType.CURRENCY:
        return target.currency_default is not None
    return False


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """Decision D18's four numbers.

    A dataclass rather than reading ``Settings`` directly, so this module stays pure and
    unit-testable at any threshold without touching the environment. Callers build one from
    configuration with ``Thresholds.from_settings``.
    """

    string_auto_map: float = 0.90
    embedding_auto_map: float = 0.88
    """MEASURED against gemini-embedding-001 on September 5, 2026. Was 0.95, a guess made
    with no key.

    Twelve synonym pairs a person would merge and twelve unrelated pairs a person would not
    were embedded and scored. The classes separate cleanly, but not where 0.95 assumed:
    unrelated pairs top out at **0.827** (`Payment Terms` versus `Currency`) and synonyms
    run from 0.822 (`Bill To` versus `Customer`) to 0.982 (`Invoice Number` versus
    `Invoice No`). This model's cosines are compressed into a narrow band near the top,
    which is normal for a modern embedding model and fatal to a threshold picked by
    intuition: at 0.95 only two of the twelve synonyms mapped, so drift auto-mapping
    effectively did not exist and a corpus writing "Invoice Total" in one document and
    "Total Amount" in another produced two columns for one fact.

    0.88 sits above every unrelated pair observed with more than five points of headroom,
    and catches nine of twelve synonyms. The three it misses are the genuinely arguable
    ones, and they fall through to asking, which is the direction D18 chose."""

    margin: float = 0.05
    """Kept at D18's value. It is a margin between the best and second-best candidate
    rather than an absolute score, so the compression of this model's scale does not shift
    it: in the measured set, a true synonym beat the runner-up by 0.08 or more, except
    between two total-shaped fields where the ambiguity is real and asking is correct."""

    novelty_ceiling_string: float = 0.65
    """Measured against the fixture corpus. See decision D18.

    The highest string similarity between two genuinely DIFFERENT field labels in the
    corpus is 0.59 (``Currency`` versus ``Reference``), so 0.65 sits just above the observed
    noise floor. Decision D18's original 0.30 made this test unpassable: unrelated pairs
    routinely exceed it, so no field was ever "clearly novel" and the auto-add zone was
    unreachable in practice.
    """

    novelty_ceiling_embedding: float = 0.80
    """MEASURED September 5, 2026, in the same pass as ``embedding_auto_map``. Was 0.30,
    the one number the code said a key would unblock.

    The prediction attached to 0.30 was right in direction and short by half: unrelated
    business labels score **0.764 to 0.827** under gemini-embedding-001, not 0.4 to 0.7. So
    0.30 was not merely strict, it was unreachable — no field's best match ever fell below
    it, which means "clearly novel" never fired and the auto-add path was dead code that
    every test passed.

    0.80 sits just under the observed floor for unrelated pairs, so a field whose best match
    is below it genuinely resembles nothing in the schema. The band between 0.80 and
    ``embedding_auto_map`` is the ask zone, which is where an honest uncertainty belongs."""

    @classmethod
    def from_settings(cls, settings: object) -> Thresholds:
        return cls(
            string_auto_map=float(getattr(settings, "drift_string_auto_map", 0.90)),
            embedding_auto_map=float(getattr(settings, "drift_embedding_auto_map", 0.95)),
            margin=float(getattr(settings, "drift_auto_map_margin", 0.05)),
            novelty_ceiling_string=float(
                getattr(settings, "drift_novelty_ceiling_string", 0.65)
            ),
            novelty_ceiling_embedding=float(
                getattr(settings, "drift_novelty_ceiling_embedding", 0.30)
            ),
        )


# ---------------------------------------------------------------------------
# Scoring one candidate pair
# ---------------------------------------------------------------------------


class Signal(StrEnum):
    """Which evidence fired for a candidate. Reported so a card can explain itself."""

    EXACT = "exact"
    ALIAS = "alias"
    STRING = "string"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class FieldSignals:
    """Every signal for one (incoming field, existing field) pair."""

    field_key: str
    field_label: str
    exact: bool
    alias: bool
    string_score: float
    embedding_score: float | None
    type_compatible: bool
    fired: frozenset[Signal] = field(default_factory=frozenset)

    @property
    def headline(self) -> float:
        """The single number to rank candidates by, and to show a user.

        An exact or alias match is reported as 1.0 because it is a certainty rather than a
        score. Otherwise the stronger of the two signals, since they are evidence of
        different things and the stronger one is what would justify a match.
        """
        if self.exact or self.alias:
            return 1.0
        return max(self.string_score, self.embedding_score or 0.0)

    @property
    def resembles(self) -> bool:
        """Whether this pair shows ANY resemblance, for the novelty test."""
        return self.headline > 0.0


def score_pair(
    *,
    incoming_key: str,
    incoming_label: str,
    incoming_type: FieldType,
    incoming_vector: Vector | None,
    existing: FieldSpec,
    existing_vector: Vector | None,
    thresholds: Thresholds,
) -> FieldSignals:
    """Score one incoming field against one existing field."""
    folded_incoming = fold_label(incoming_key or incoming_label)
    folded_incoming_label = fold_label(incoming_label or incoming_key)

    # Normalized-exact: the same field, written differently. Costs no embedding call.
    exact = folded_incoming in {fold_label(existing.key), fold_label(existing.label)} or (
        folded_incoming_label in {fold_label(existing.key), fold_label(existing.label)}
    )

    # A mapping the user already approved, recorded in source_keys. Honouring this is what
    # stops the same rename being re-proposed on every subsequent document.
    aliases = {fold_label(alias) for alias in existing.source_keys}
    alias = not exact and (folded_incoming in aliases or folded_incoming_label in aliases)

    string_score = max(
        string_similarity(incoming_label or incoming_key, existing.label),
        string_similarity(incoming_key or incoming_label, existing.key),
    )

    embedding_score: float | None = None
    if incoming_vector is not None and existing_vector is not None:
        embedding_score = cosine(incoming_vector, existing_vector)

    fired: set[Signal] = set()
    if exact:
        fired.add(Signal.EXACT)
    if alias:
        fired.add(Signal.ALIAS)
    if string_score >= thresholds.string_auto_map:
        fired.add(Signal.STRING)
    if embedding_score is not None and embedding_score >= thresholds.embedding_auto_map:
        fired.add(Signal.EMBEDDING)

    return FieldSignals(
        field_key=existing.key,
        field_label=existing.label,
        exact=exact,
        alias=alias,
        string_score=string_score,
        embedding_score=embedding_score,
        type_compatible=types_compatible(incoming_type, existing),
        fired=frozenset(fired),
    )


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


class Outcome(StrEnum):
    """What decision D27's policy says to do with an incoming field."""

    AUTO_MAP = "auto_map"
    AUTO_ADD = "auto_add"
    ASK = "ask"


class AskReason(StrEnum):
    """WHY a case needs a human. Different callers act on these differently.

    Collapsing them into a bare ``ASK`` was a real defect: the initial-schema proposer
    treated "we could not confirm novelty because there are no vectors" as though it were
    "two fields genuinely compete", and produced a merge question for every field in the
    batch, pairing things like ``vendor`` with ``invoice_no``. Those are not judgment calls,
    they are the best of a bad lot, and asking about them is worse than useless.

    * ``COMPETING_CANDIDATES`` two fields are both plausible. A genuine judgment call, and
      the case decision D18's margin rule exists for.
    * ``BORDERLINE`` one candidate resembles the field, but not enough to act on.
    * ``TYPE_MISMATCH`` the names line up but the types do not.
    * ``UNCONFIRMED_NOVELTY`` nothing resembles it, but with no embedding we cannot be sure
      it is not a semantic rename. Meaningful when matching a document against an
      established schema, where a wrong auto-add creates a duplicate column. NOT meaningful
      when unifying a first batch, where every observation becomes a field anyway.
    """

    COMPETING_CANDIDATES = "competing_candidates"
    BORDERLINE = "borderline"
    TYPE_MISMATCH = "type_mismatch"
    UNCONFIRMED_NOVELTY = "unconfirmed_novelty"


@dataclass(frozen=True)
class Verdict:
    """The decision, the field it points at, and why. The reason is user-facing."""

    outcome: Outcome
    target_key: str | None
    reason: str
    ranked: list[FieldSignals] = field(default_factory=list)
    ask_reason: AskReason | None = None
    """Set if and only if ``outcome`` is ``ASK``. Lets a caller act on WHY, not just that."""

    @property
    def best(self) -> FieldSignals | None:
        return self.ranked[0] if self.ranked else None


def _margin_holds(
    best: FieldSignals, runner_up: FieldSignals | None, thresholds: Thresholds
) -> tuple[bool, Signal | None]:
    """Whether ``best`` beats ``runner_up`` decisively on a signal that actually fired.

    Checked per signal rather than on the headline number, because the headline can be
    carried by a different signal than the one that qualified the match. It is enough for
    ONE firing signal to clear the margin: if the string signal fired and beats the runner
    up decisively, an unrelated dense cosine on a second field should not veto that.
    """
    if runner_up is None:
        # Nothing else to be confused with.
        return True, next(iter(sorted(best.fired)), None)

    for signal in sorted(best.fired):
        if signal in (Signal.EXACT, Signal.ALIAS):
            # A certainty is ambiguous only if something else is also a certainty. Two
            # fields claiming the same alias is a schema the user needs to fix, not one to
            # guess about.
            if not (runner_up.exact or runner_up.alias):
                return True, signal
            continue
        if signal is Signal.STRING:
            if best.string_score - runner_up.string_score >= thresholds.margin:
                return True, signal
            continue
        if signal is Signal.EMBEDDING:
            best_embedding = best.embedding_score or 0.0
            runner_embedding = runner_up.embedding_score or 0.0
            if best_embedding - runner_embedding >= thresholds.margin:
                return True, signal
    return False, None


def classify(
    *,
    incoming_key: str,
    incoming_label: str,
    incoming_type: FieldType,
    schema: list[FieldSpec],
    incoming_vector: Vector | None = None,
    schema_vectors: dict[str, Vector | None] | None = None,
    thresholds: Thresholds | None = None,
) -> Verdict:
    """Decide whether an incoming field auto-maps, auto-adds, or needs the user.

    Implements decision D18's gates on top of decision D27's three zones. Never raises: an
    undecidable case is an ``ASK``, which is always a safe answer.
    """
    thresholds = thresholds or Thresholds()
    vectors = schema_vectors or {}

    if not schema:
        return Verdict(
            outcome=Outcome.AUTO_ADD,
            target_key=None,
            reason="The schema has no fields yet, so there is nothing this could conflict with.",
        )

    ranked = sorted(
        (
            score_pair(
                incoming_key=incoming_key,
                incoming_label=incoming_label,
                incoming_type=incoming_type,
                incoming_vector=incoming_vector,
                existing=existing,
                existing_vector=vectors.get(existing.key),
                thresholds=thresholds,
            )
            for existing in schema
        ),
        key=lambda signals: signals.headline,
        reverse=True,
    )

    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    # -- zone 1: unambiguous match -> auto-map ---------------------------
    if best.fired:
        decisive, signal = _margin_holds(best, runner_up, thresholds)
        if decisive and best.type_compatible:
            return Verdict(
                outcome=Outcome.AUTO_MAP,
                target_key=best.field_key,
                reason=_auto_map_reason(best, signal),
                ranked=ranked,
            )
        if not best.type_compatible:
            return Verdict(
                outcome=Outcome.ASK,
                target_key=None,
                reason=(
                    f"{incoming_label or incoming_key!r} looks like your "
                    f"{best.field_label!r}, but the types do not line up: this document "
                    f"has a {incoming_type.value} and that field holds "
                    f"{_type_phrase(best, schema)}."
                ),
                ranked=ranked,
                ask_reason=AskReason.TYPE_MISMATCH,
            )
        return Verdict(
            outcome=Outcome.ASK,
            target_key=None,
            reason=(
                f"{incoming_label or incoming_key!r} could be your {best.field_label!r} "
                f"({best.headline:.0%}), but {runner_up.field_label!r} is nearly as close "
                f"({runner_up.headline:.0%}), so this is a judgement call."
                if runner_up is not None
                else f"{incoming_label or incoming_key!r} is a borderline match."
            ),
            ranked=ranked,
            ask_reason=(
                AskReason.COMPETING_CANDIDATES if runner_up is not None else AskReason.BORDERLINE
            ),
        )

    # -- zone 2: clearly novel -> auto-add -------------------------------
    # Both signals must agree nothing resembles it. A MISSING embedding is not agreement:
    # see the module docstring.
    embeddings_available = all(signals.embedding_score is not None for signals in ranked)
    # Each signal is tested against ITS OWN ceiling. Comparing a character ratio and a
    # cosine to one shared number treats them as the same scale, which they are not:
    # measured on the fixture corpus, unrelated label pairs reach 0.59 on the string
    # signal, so a single 0.30 ceiling made this branch unreachable. See decision D18.
    below_ceiling = all(
        signals.string_score < thresholds.novelty_ceiling_string
        and (signals.embedding_score or 0.0) < thresholds.novelty_ceiling_embedding
        for signals in ranked
    )
    if below_ceiling and embeddings_available:
        return Verdict(
            outcome=Outcome.AUTO_ADD,
            target_key=None,
            reason=(
                f"Nothing in your schema resembles {incoming_label or incoming_key!r} "
                f"(closest was {best.field_label!r} at {best.headline:.0%}), so it was "
                f"added as a new field."
            ),
            ranked=ranked,
        )

    # -- zone 3: everything in between -> ask ----------------------------
    if below_ceiling and not embeddings_available:
        return Verdict(
            outcome=Outcome.ASK,
            target_key=None,
            reason=(
                f"{incoming_label or incoming_key!r} does not obviously match any existing "
                f"field, but we could not check it for a meaning-based match, so we would "
                f"rather ask than risk adding a duplicate column."
            ),
            ranked=ranked,
            ask_reason=AskReason.UNCONFIRMED_NOVELTY,
        )

    return Verdict(
        outcome=Outcome.ASK,
        target_key=None,
        reason=(
            f"{incoming_label or incoming_key!r} partly resembles your {best.field_label!r} "
            f"({best.headline:.0%}), which is neither close enough to map automatically nor "
            f"distant enough to treat as a new field."
        ),
        ranked=ranked,
        ask_reason=AskReason.BORDERLINE,
    )


def _auto_map_reason(best: FieldSignals, signal: Signal | None) -> str:
    if best.exact:
        return f"Same field name as your {best.field_label!r}, ignoring case and separators."
    if best.alias:
        return f"You have already mapped this name onto {best.field_label!r}."
    if signal is Signal.EMBEDDING:
        return (
            f"Means the same thing as your {best.field_label!r} "
            f"({(best.embedding_score or 0.0):.0%} match on meaning)."
        )
    return f"Name matches your {best.field_label!r} closely ({best.string_score:.0%})."


def _type_phrase(best: FieldSignals, schema: list[FieldSpec]) -> str:
    for existing in schema:
        if existing.key == best.field_key:
            return existing.type.value
    return "a different type"
