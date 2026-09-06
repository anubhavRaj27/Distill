"""Turning a parsed document into a model's structured answer.

Two modes, as implementation.md section 6.2 describes:

* **open extraction** for the first batch, when no schema exists. Finds whatever is salient,
  and its output is what the initial schema is inferred from.
* **schema-guided extraction** thereafter. Fills the agreed schema and reports what did not
  fit in ``extra_fields``, which is what feeds drift detection.

Both return the same flat response shape (decision D15), so there is one fixture shape and
one set of downstream handling.

PAGES ARE SENT AS NUMBERED BLOCKS WITHOUT LINE NUMBERS
-------------------------------------------------------
A small deviation from implementation.md section 6.2, which suggested line numbers. Line
numbers would help a model cite precisely, but they also leak into the quotes: a model asked
for a verbatim span from text that reads ``12: Total Due: $480`` will sometimes include the
``12:``. Grounding then fails to find the quote, the value's tier is capped at low, and the
user is told a correct value is unreliable. Since grounding is the mechanism the whole trust
story rests on, protecting the quote matters more than helping the citation, and the page
header alone gives the model what it needs to report ``page_index``.
"""

from __future__ import annotations

from app.config import Settings
from app.domain.document import ParsedDocument
from app.domain.fields import FieldSpec
from app.llm import prompts
from app.llm.base import CallKind, LLMClient, LLMRequest
from app.llm.contracts import GuidedExtraction, OpenExtraction
from app.llm.fake import fixture_key_for_document
from app.logging import get_logger

logger = get_logger(__name__)

MAX_PROMPT_CHARACTERS = 120_000
"""Roughly 30,000 tokens of document text. A cap rather than an assumption about the
model's context window: a 400 page scan should degrade to "we read the first part of this"
with a visible note, not to a rejected request or a surprise bill."""

TRUNCATION_NOTICE = (
    "\n\n[This document is longer than we send to the model in one pass. The text above is "
    "the beginning of it. Fields that appear only later in the document may be missing.]"
)


def page_blocks(document: ParsedDocument, max_characters: int = MAX_PROMPT_CHARACTERS) -> str:
    """Render the document's text as numbered page blocks.

    Truncates whole pages rather than mid-page, so the model never sees half a table and
    infers a value from a fragment.
    """
    blocks: list[str] = []
    used = 0
    for page in document.pages:
        locator = f" ({page.locator})" if page.locator else ""
        # Telling the model the page came from text recognition measurably improves its
        # handling of the resulting typos, and it is honest about what it is reading.
        scanned = (
            " [text recognised from a scan, so it may contain errors]"
            if page.ocr_applied
            else ""
        )
        header = f"=== PAGE {page.index}{locator}{scanned} ==="
        body = page.text.strip()
        block = f"{header}\n{body}" if body else f"{header}\n[no readable text on this page]"

        if used + len(block) > max_characters and blocks:
            blocks.append(TRUNCATION_NOTICE.strip())
            logger.info(
                "extract.prompt_truncated",
                pages_included=len(blocks) - 1,
                pages_total=document.page_count,
            )
            break
        blocks.append(block)
        used += len(block)

    return "\n\n".join(blocks)


def render_schema(fields: list[FieldSpec]) -> str:
    """The schema, as a compact list the model can follow.

    Includes the description and any enum values, because those are what let a model decide
    whether a document's value belongs in a field, and excludes machinery like weight and
    source keys, which are ours and would only be noise.
    """
    lines: list[str] = []
    for field in fields:
        parts = [f"- `{field.key}` ({field.type.value}), shown to the user as {field.label!r}"]
        if field.description:
            parts.append(f"  Meaning: {field.description}")
        if field.enum_values:
            parts.append(f"  Must be one of: {', '.join(field.enum_values)}")
        if field.currency_default:
            parts.append(
                f"  If the document states an amount with no currency marker, it is "
                f"{field.currency_default}."
            )
        lines.append("\n".join(parts))
    return "\n".join(lines) if lines else "[the schema is empty]"


async def open_extract(
    document: ParsedDocument,
    *,
    filename: str,
    content_hash: str,
    client: LLMClient,
    settings: Settings,
) -> OpenExtraction:
    """Find every salient field, with no schema to follow."""
    prompt = prompts.render(
        "open_extract",
        filename=filename,
        source_format=document.source_format.value,
        page_count=document.page_count,
        pages=page_blocks(document),
    )
    request = LLMRequest(
        kind=CallKind.OPEN_EXTRACT,
        prompt=prompt,
        response_model=OpenExtraction,
        fixture_key=fixture_key_for_document(content_hash, CallKind.OPEN_EXTRACT),
        context={"document": document},
    )
    response = await client.structured(request)
    result = response.value
    assert isinstance(result, OpenExtraction)
    logger.info(
        "extract.open_completed",
        filename=filename,
        fields=len(result.fields),
        document_kind=result.document_kind,
        model=response.usage.model,
        latency_ms=round(response.usage.latency_ms, 1),
    )
    return result


async def guided_extract(
    document: ParsedDocument,
    *,
    filename: str,
    content_hash: str,
    fields: list[FieldSpec],
    schema_version: int,
    client: LLMClient,
    settings: Settings,
    only_keys: list[str] | None = None,
) -> GuidedExtraction:
    """Fill the current schema, and report what did not fit.

    ``only_keys`` restricts the call to a subset of fields, which is what backfill uses:
    after adding a field, there is no reason to re-extract the whole schema, and doing so
    would waste tokens and risk disturbing values that are already correct.
    """
    target = (
        [field for field in fields if field.key in set(only_keys)] if only_keys else fields
    )
    prompt = prompts.render(
        "guided_extract",
        filename=filename,
        source_format=document.source_format.value,
        page_count=document.page_count,
        pages=page_blocks(document),
        schema=render_schema(target),
    )
    request = LLMRequest(
        kind=CallKind.GUIDED_EXTRACT,
        prompt=prompt,
        response_model=GuidedExtraction,
        fixture_key=fixture_key_for_document(
            content_hash, CallKind.GUIDED_EXTRACT, schema_version
        ),
        context={"document": document, "schema": target},
    )
    response = await client.structured(request)
    result = response.value
    assert isinstance(result, GuidedExtraction)
    logger.info(
        "extract.guided_completed",
        filename=filename,
        schema_version=schema_version,
        filled=sum(1 for value in result.values if value.value_text is not None),
        of=len(target),
        extras=len(result.extra_fields),
        model=response.usage.model,
        latency_ms=round(response.usage.latency_ms, 1),
    )
    return result
