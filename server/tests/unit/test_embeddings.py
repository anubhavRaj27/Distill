"""The embedding half of the drift signal. Decision D18.

Drift matching scores a candidate field against the existing schema with two independent
signals, and this suite covers the one that needs a provider. The important behaviour is
not "vectors come back", it is what happens when they do **not**: an unrecorded label must
produce ``None`` rather than a plausible-looking vector, because a synthesised vector would
score a confident cosine against every field and the caller would auto-apply on noise.
``None`` sends the caller back to string similarity, which produces more proposal cards and
fewer auto-applies — failing toward asking the user.
"""

from __future__ import annotations

import json

import pytest
from app.config import Settings
from app.llm.base import LLMClient
from app.llm.fake import FakeClient
from app.llm.registry import build_client
from pydantic import ValidationError


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(llm_provider="fake", llm_fixture_dir=tmp_path)


def _record(settings: Settings, labels: dict[str, list[float]]) -> None:
    path = settings.llm_fixture_dir / "embed" / "labels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels), encoding="utf-8")


async def test_an_unrecorded_label_returns_none_rather_than_an_invented_vector(
    settings: Settings,
) -> None:
    """The whole point. A made-up vector would be worse than no vector at all."""
    client = FakeClient(settings)

    assert await client.embed(["vendor_name"]) == [None]


async def test_recorded_vectors_are_replayed(settings: Settings) -> None:
    _record(settings, {"vendor_name": [0.1, 0.2, 0.3]})
    client = FakeClient(settings)

    assert await client.embed(["vendor_name"]) == [[0.1, 0.2, 0.3]]


async def test_results_are_positional_so_a_partial_recording_stays_aligned(
    settings: Settings,
) -> None:
    """A misaligned vector is worse than a missing one: it would score the wrong pair."""
    _record(settings, {"vendor_name": [1.0, 0.0]})
    client = FakeClient(settings)

    assert await client.embed(["unknown_a", "vendor_name", "unknown_b"]) == [
        None,
        [1.0, 0.0],
        None,
    ]


async def test_labels_match_regardless_of_case_and_separators(settings: Settings) -> None:
    """Recording every casing of a label would be a fixture maintenance trap."""
    _record(settings, {"vendor_name": [0.5]})
    client = FakeClient(settings)

    assert await client.embed(["Vendor Name"]) == [[0.5]]


async def test_an_empty_request_does_no_work(settings: Settings) -> None:
    client = FakeClient(settings)

    assert await client.embed([]) == []


async def test_a_missing_fixture_file_is_normal_not_an_error(settings: Settings) -> None:
    """A fresh clone has no recordings and must still start."""
    client = FakeClient(settings)

    assert await client.embed(["anything"]) == [None]


def test_the_fake_provider_satisfies_the_client_protocol(settings: Settings) -> None:
    """``embed`` was added to ``LLMClient`` after both implementations existed."""
    client: LLMClient = FakeClient(settings)

    assert hasattr(client, "embed")


def test_a_missing_key_is_refused_before_a_client_is_ever_built() -> None:
    """The common misconfiguration never reaches the registry: ``Settings`` rejects it."""
    with pytest.raises(ValidationError) as caught:
        Settings(llm_provider="gemini", gemini_api_key=None)

    assert "GEMINI_API_KEY" in str(caught.value)


def test_an_unconstructable_gemini_client_fails_loudly(monkeypatch) -> None:
    """With a key present, ``Settings`` is satisfied and construction is the
    next thing that can fail — a broken software development kit import, or a client
    constructor that throws. That used to fall back to the offline provider, which is the
    failure mode this refuses to have: heuristic values reach the table wearing the same
    confidence tiers and provenance links as real extraction, so nobody notices until the
    numbers are wrong."""
    settings = Settings(llm_provider="gemini", gemini_api_key="present-but-unusable")

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("the provider could not be constructed")

    monkeypatch.setattr("app.llm.gemini.GeminiClient.__init__", _explode)

    with pytest.raises(RuntimeError, match="could not be constructed"):
        build_client(settings)
