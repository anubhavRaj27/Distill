"""Label vectors for drift matching, with a cache. Decision D24.

Decision D24 budgets "a label-keyed cache so a schema's labels are not re-embedded once per
document". This is that cache.

Keyed on the **embedding text**, not the field key, so two fields that happen to describe
themselves identically share a vector and a rename does not invalidate one. The cache lives
for the process, which matches the single-process constraint decision D9 already imposes.

The embedding text is the label plus the description rather than the key alone. A key like
``po_no`` carries almost no signal, while "Purchase Order Number, the reference the customer
raised against their own purchase order" carries plenty, and the description is exactly the
field metadata the schema layer already maintains for this purpose.
"""

from __future__ import annotations

from app.domain.fields import FieldSpec
from app.llm.base import LLMClient, Vector
from app.logging import get_logger

logger = get_logger(__name__)

MAX_EMBED_BATCH = 64
"""Labels per request. Keeps a large schema from becoming one oversized call."""

_cache: dict[str, Vector | None] = {}


def embedding_text(label: str, description: str = "", key: str = "") -> str:
    """The text that represents a field to the embedding model.

    **The label alone**, falling back to the key when a field has no label. The
    ``description`` parameter is accepted and deliberately ignored; it is kept in the
    signature because callers naturally have one to hand and because excluding it is a
    decision worth stating at the call site rather than hiding.

    Why not label plus description, which is what decision D24 sketched:

    * **Fixture stability.** This string is the cache key and the recorded-fixture key. Our
      descriptions are generated, and one of them is "For example: Acme Industrial", built
      from a sample value. Including it would change a field's fixture key whenever a
      different document happened to be extracted first, silently invalidating recordings.
    * **Recordability.** Someone recording vectors for the sample corpus has to be able to
      predict the keys. "Vendor" and "Total Due" are predictable; "Vendor. Seen in these
      documents as: Supplier, Vendor." is not.
    * **Signal.** The label is the dominant term anyway, and an earlier version composed
      label and key together, which sent "Vendor. vendor_name" and diluted the vector with
      a restatement of the same word.

    A field's description is still used, by string similarity and by the interface. It is
    only the embedding text that is kept narrow and predictable.
    """
    chosen = label.strip() or key.strip()
    return chosen


def field_embedding_text(field: FieldSpec) -> str:
    return embedding_text(field.label, field.description, field.key)


async def vectors_for(client: LLMClient, texts: list[str]) -> dict[str, Vector | None]:
    """Vectors for ``texts``, using and filling the process cache.

    A ``None`` result is cached like any other. That is deliberate: with the offline
    provider an unrecorded label yields ``None`` every time, and re-asking once per document
    would be pure waste. It also means a genuine transport failure is NOT cached, because
    that raises out of ``client.embed`` rather than returning ``None``.
    """
    wanted = [text for text in dict.fromkeys(texts) if text]
    missing = [text for text in wanted if text not in _cache]

    for start in range(0, len(missing), MAX_EMBED_BATCH):
        batch = missing[start : start + MAX_EMBED_BATCH]
        # "similarity", not "document": neither of two field labels being compared is a
        # query for the other. Decision D63.
        vectors = await client.embed(batch, task="similarity")
        if len(vectors) != len(batch):
            # A provider that returns a different count has broken the positional contract
            # in ``LLMClient.embed``, and a misaligned vector is worse than a missing one
            # because it would score the wrong pair. Discard the whole batch.
            logger.error(
                "embeddings.length_mismatch", requested=len(batch), returned=len(vectors)
            )
            for text in batch:
                _cache[text] = None
            continue
        for text, vector in zip(batch, vectors, strict=True):
            _cache[text] = vector

    resolved = {text: _cache.get(text) for text in wanted}
    absent = sum(1 for vector in resolved.values() if vector is None)
    if absent:
        logger.info(
            "embeddings.partial",
            absent=absent,
            total=len(resolved),
            detail="those pairs score on string similarity alone, which asks rather than "
            "auto-applies",
        )
    return resolved


async def schema_vectors(
    client: LLMClient, fields: list[FieldSpec]
) -> dict[str, Vector | None]:
    """Vectors for an existing schema, keyed by FIELD KEY, ready for ``classify``."""
    if not fields:
        return {}
    texts = {field.key: field_embedding_text(field) for field in fields}
    resolved = await vectors_for(client, list(texts.values()))
    return {key: resolved.get(text) for key, text in texts.items()}


def clear_cache() -> None:
    """Drop the cache. For tests, and after a provider change."""
    _cache.clear()


def cache_size() -> int:
    return len(_cache)
