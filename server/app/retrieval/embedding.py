"""Producing vectors for chunks and questions, with an offline path that actually works.

THE PROBLEM THIS SOLVES
-----------------------
Retrieval needs the question and the chunks to live in the **same** vector space. With a
real key that is trivially true. Without one, ``FakeClient.embed`` returns ``None`` for any
text it has no recording of, and ``None`` is the right answer there: decision D18 relies on
it, because an invented vector would score a confident cosine against every schema field and
make drift auto-apply on noise.

But a chat that retrieves nothing is not a chat. So this module adds a **lexical fallback**:
a deterministic hashed bag-of-words vector. Cosine over two of those approximates token
overlap, which is a real (if shallow) similarity signal, so an offline clone genuinely
retrieves the passage that mentions the words in the question. That is what makes the chat
demonstrable with no key at all, which is decision D11's whole purpose.

WHY THE FALLBACK LIVES HERE AND NOT IN THE PROVIDER
----------------------------------------------------
Putting it in ``FakeClient.embed`` would have been less code and a real bug: schema drift
matching would silently start receiving pseudo-vectors and treating them as meaning. The
provider stays honest about having no vector, and the decision to substitute one is taken
by the layer that knows it is safe to do so.

MIXING SPACES IS THE FAILURE TO AVOID
--------------------------------------
A chunk embedded by Gemini and a question embedded lexically would produce cosines that are
pure noise, and the symptom would be a chat that retrieves confidently and wrongly. So every
vector records the model that produced it, and ``vector_space_for`` reads back what a
workspace's chunks were actually embedded with so the question is embedded the same way.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from app.llm.base import EmbedTask, LLMClient, Vector
from app.logging import get_logger

logger = get_logger(__name__)

LEXICAL_MODEL = "lexical-fallback-v1"
"""Recorded as a chunk's ``embedding_model`` when the lexical fallback produced it. Never a
real model name, so a workspace indexed offline is identifiable rather than looking like a
workspace indexed badly."""

LEXICAL_DIMENSIONS = 512
_TOKEN = re.compile(r"[a-z0-9]+")

# Words too common to carry retrieval signal. Short list on purpose: over-pruning hurts
# more than under-pruning when the corpus is small.
_STOP_WORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "at", "by", "with",
        "is", "are", "was", "were", "be", "been", "this", "that", "these", "those", "it",
        "as", "from", "has", "have", "had", "do", "does", "did", "but", "not", "any",
    }
)


def lexical_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOP_WORDS]


def lexical_vector(text: str, dimensions: int = LEXICAL_DIMENSIONS) -> Vector:
    """A deterministic hashed bag-of-words vector.

    Each token is hashed to a bucket and contributes a sub-linear weight, so a word repeated
    twenty times does not drown out the rest of the passage. The result is L2 normalised, so
    a plain dot product is the cosine and long passages are not favoured over short ones
    purely for being long.
    """
    counts: dict[int, float] = {}
    for token in lexical_tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest, "big") % dimensions
        counts[bucket] = counts.get(bucket, 0.0) + 1.0

    vector = [0.0] * dimensions
    for bucket, count in counts.items():
        vector[bucket] = 1.0 + math.log(count)

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


@dataclass(frozen=True)
class EmbeddedText:
    text: str
    vector: Vector
    model: str

    @property
    def is_lexical(self) -> bool:
        return self.model == LEXICAL_MODEL


async def embed_texts(
    client: LLMClient,
    texts: list[str],
    *,
    model_name: str,
    task: EmbedTask = "similarity",
    force_lexical: bool = False,
) -> list[EmbeddedText]:
    """Embed ``texts``, falling back to lexical vectors for anything the provider skipped.

    ``force_lexical`` embeds everything lexically, which is what a caller does once it knows
    a workspace's existing chunks are lexical: consistency with what is already indexed
    matters more than the quality of any single new vector.

    ``task`` says whether these texts are passages or a question, so a real provider can
    embed each side of the pair appropriately. The lexical fallback has no
    notion of it and needs none: token overlap is symmetric.
    """
    if not texts:
        return []

    if force_lexical:
        return [
            EmbeddedText(text=text, vector=lexical_vector(text), model=LEXICAL_MODEL)
            for text in texts
        ]

    vectors = await client.embed(texts, task=task)
    if len(vectors) != len(texts):
        # The provider broke the positional contract in ``LLMClient.embed``. A misaligned
        # vector is worse than a missing one, so discard the whole batch and go lexical.
        logger.error(
            "embedding.length_mismatch", requested=len(texts), returned=len(vectors)
        )
        vectors = [None] * len(texts)

    embedded: list[EmbeddedText] = []
    fell_back = 0
    for text, vector in zip(texts, vectors, strict=True):
        if vector:
            embedded.append(EmbeddedText(text=text, vector=vector, model=model_name))
        else:
            fell_back += 1
            embedded.append(
                EmbeddedText(text=text, vector=lexical_vector(text), model=LEXICAL_MODEL)
            )

    if fell_back:
        logger.info(
            "embedding.lexical_fallback",
            count=fell_back,
            total=len(texts),
            detail="retrieval will rank these by token overlap rather than meaning",
        )
    return embedded


def cosine(left: Vector, right: Vector) -> float:
    """Cosine similarity, clamped to ``[0, 1]``.

    Mismatched dimensions return 0.0 rather than raising: that means two different embedding
    spaces got mixed, and the honest answer is "no signal", not a crash in the middle of
    answering a question. ``vector_space_for`` exists to stop it happening at all.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))
