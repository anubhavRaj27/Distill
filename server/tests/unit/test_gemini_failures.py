"""How the Gemini adapter reads a failure. No API key needed, and no network.

Everything here was learned from a real key on September 5, 2026, and every case is one
that a plausible-looking implementation gets wrong in a way nobody notices until a demo:
a permanent failure retried three times, or a per-minute quota retried three times inside
the same minute. See decision D42.
"""

from __future__ import annotations

import pytest
from app.llm.gemini import (
    MAX_BACKOFF_SECONDS,
    _is_retryable,
    _readable_transport_error,
    _retry_delay_seconds,
    _unit,
)

QUOTA_EXHAUSTED = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota. * Quota exceeded for metric: generate_content_free_tier_requests, "
    "limit: 0, model: gemini-3.1-pro. Please retry in 29.784742322s.'}}"
)
RATE_LIMITED = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota, limit: 10, model: gemini-3.6-flash. Please retry in 12s.'}}"
)
RETIRED_MODEL = (
    "404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model models/gemini-2.5-pro "
    "is no longer available to new users.'}}"
)


def test_a_quota_of_zero_is_permanent_not_a_rate_limit() -> None:
    """The 429 that will never clear. It is spelled exactly like the one that will, and
    the only thing separating them is `limit: 0`."""
    assert _is_retryable(Exception(QUOTA_EXHAUSTED)) is False
    message = _readable_transport_error(Exception(QUOTA_EXHAUSTED))
    assert "plan" in message and "retrying will not help" in message


def test_an_ordinary_rate_limit_is_still_retried() -> None:
    assert _is_retryable(Exception(RATE_LIMITED)) is True


def test_a_retired_model_names_itself() -> None:
    """A model identifier can stop working without anyone touching the configuration, so
    the message carries the provider's own sentence rather than a paraphrase."""
    message = _readable_transport_error(Exception(RETIRED_MODEL))
    assert "gemini-2.5-pro" in message
    assert "LLM_EXTRACT_MODEL" in message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please retry in 29.784742322s.", 29.784742322),
        ("{'retryDelay': '30s'}", 30.0),
        ("retryDelay: 7s", 7.0),
        ("some unrelated failure", None),
        ("Please retry in 900s", None),  # beyond the cap is not a hint, it is a hang
        ("Please retry in 0s", None),
    ],
)
def test_the_providers_own_retry_delay_is_read(text: str, expected: float | None) -> None:
    """Backoff tops out at eight seconds. A per-minute quota asks for thirty. Ignoring the
    hint spends every attempt inside the window that is still closed."""
    assert _retry_delay_seconds(Exception(text)) == expected


def test_a_hint_can_never_exceed_the_cap() -> None:
    delay = _retry_delay_seconds(Exception(f"Please retry in {MAX_BACKOFF_SECONDS - 1}s"))
    assert delay is not None and delay <= MAX_BACKOFF_SECONDS


def test_vectors_are_normalised_to_unit_length() -> None:
    """Widths below the model's native 3072 come back un-normalised, which the provider
    documents. Normalising once at write time keeps every stored vector comparable."""
    vector = _unit([3.0, 4.0])
    assert vector == pytest.approx([0.6, 0.8])
    assert _unit([0.0, 0.0]) == [0.0, 0.0]
