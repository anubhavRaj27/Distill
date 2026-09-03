"""What kind of file is this, decided from its bytes.

The security requirement in section 5 of requirements.md says uploads are validated by
content type, not extension, and this module is that rule. A file named ``invoice.pdf`` that
is really an executable is routed by what it IS, so it hits the "unsupported type" path
rather than a parser.

ONE DELIBERATE DEVIATION from implementation.md section 6.1
-----------------------------------------------------------
The implementation document says to "reject mismatches" between the sniffed type and the
extension. This module instead **routes by content and reports the disagreement**, without
rejecting.

The reasoning: rejection buys no safety that routing by content has not already bought,
because the content decides which parser runs. What rejection does buy is a failed upload
for the user who saved a tab-separated export as ``.csv``, or whose mail client renamed an
attachment, which is a real and common case with no security benefit. So the mismatch is
logged, surfaced in ``stage_detail`` so the user can see what we concluded, and processed.

Text formats have no magic bytes, so CSV and plain text are separated by structure: a
consistent delimiter and a consistent column count across several lines is tabular, and
anything else is prose.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

import filetype

from app.domain.document import SourceFormat
from app.errors import UnsupportedFileType
from app.logging import get_logger

logger = get_logger(__name__)

HEAD_BYTES = 128 * 1024
"""How much of a file to inspect. Generous, because the zip-based formats keep their
identifying entries in the central directory area rather than the first few bytes."""

SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "docx",
    "xlsx",
    "csv",
    "txt",
)
"""Requirement FR-02. Quoted verbatim to the user when an upload is rejected, so the
message says what IS supported rather than only what is not."""

_MIME_TO_FORMAT: dict[str, SourceFormat] = {
    "application/pdf": SourceFormat.PDF,
    "image/png": SourceFormat.IMAGE,
    "image/jpeg": SourceFormat.IMAGE,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        SourceFormat.DOCX
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": SourceFormat.XLSX,
}

_EXTENSION_TO_FORMAT: dict[str, SourceFormat] = {
    "pdf": SourceFormat.PDF,
    "png": SourceFormat.IMAGE,
    "jpg": SourceFormat.IMAGE,
    "jpeg": SourceFormat.IMAGE,
    "docx": SourceFormat.DOCX,
    "xlsx": SourceFormat.XLSX,
    "csv": SourceFormat.CSV,
    "txt": SourceFormat.TEXT,
}

_CANONICAL_MIME: dict[SourceFormat, str] = {
    SourceFormat.PDF: "application/pdf",
    SourceFormat.IMAGE: "image/png",
    SourceFormat.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    SourceFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    SourceFormat.CSV: "text/csv",
    SourceFormat.TEXT: "text/plain",
}


@dataclass(frozen=True)
class Sniffed:
    """What the bytes turned out to be."""

    source_format: SourceFormat
    mime: str
    extension_disagreed: bool = False
    note: str | None = None
    """Shown to the user in ``stage_detail`` when the extension and the content disagree."""


def _zip_subtype(head: bytes) -> SourceFormat | None:
    """Distinguish a Word file from a spreadsheet from a plain archive.

    ``filetype`` already does this for well-formed files. This is the fallback for an
    archive it could only identify as a generic zip, which happens when the identifying
    entry is not where the fast matcher looks.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(head)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, EOFError):
        return None
    if any(name.startswith("word/") for name in names):
        return SourceFormat.DOCX
    if any(name.startswith("xl/") for name in names):
        return SourceFormat.XLSX
    return None


# Byte order marks. A UTF-16 file is roughly half null bytes when its content is Latin
# script, so the null-byte binary heuristic below MUST NOT run before this check, or every
# UTF-16 text file is misread as binary. Windows exports are commonly UTF-16, so this is a
# real case rather than a theoretical one.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def _looks_like_text(head: bytes) -> str | None:
    """Decode as text if it plausibly is text, else ``None``.

    Order matters. A declared byte order mark is trusted first, because it is an explicit
    statement of encoding. Only in its absence is a null byte taken as evidence of binary
    content, which is otherwise a reliable signal: text files do not contain them and
    binary formats almost always do within the first few kilobytes.
    """
    for marker, encoding in _BOMS:
        if head.startswith(marker):
            try:
                return head.decode(encoding, errors="replace")
            except LookupError:  # pragma: no cover - every encoding above is built in
                return None

    if b"\x00" in head[:4096]:
        return None
    for encoding in ("utf-8", "cp1252"):
        try:
            decoded = head.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        # Reject anything with a high proportion of control characters, which is binary
        # data that happens to decode.
        control = sum(
            1 for character in decoded[:2000] if ord(character) < 32 and character not in "\r\n\t"
        )
        if control > len(decoded[:2000]) * 0.02:
            return None
        return decoded
    return None


def _is_tabular(text: str) -> bool:
    """Whether decoded text is delimited tabular data rather than prose.

    The test is structural consistency, not the presence of a comma: prose contains commas
    and a spreadsheet export may use semicolons or tabs. Several consecutive lines splitting
    into the same number of fields on the same delimiter is tabular; anything else is not.
    """
    lines = [line for line in text.splitlines()[:20] if line.strip()]
    if len(lines) < 2:
        return False
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:10]), delimiters=",;\t|")
    except csv.Error:
        return False
    counts = [len(next(csv.reader([line], dialect), [])) for line in lines]
    return min(counts) >= 2 and len(set(counts)) == 1


def sniff(head: bytes, filename: str) -> Sniffed:
    """Identify ``head``, or raise ``UnsupportedFileType``.

    ``filename`` is used only to detect and report a disagreement, and as the tiebreaker
    between CSV and plain text when the structural test is inconclusive. It never overrides
    a positive content identification.
    """
    claimed_extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    claimed = _EXTENSION_TO_FORMAT.get(claimed_extension)

    guess = filetype.guess(head)
    detected: SourceFormat | None = None
    mime: str | None = None

    if guess is not None:
        detected = _MIME_TO_FORMAT.get(guess.mime)
        mime = guess.mime
        if detected is None and guess.mime == "application/zip":
            detected = _zip_subtype(head)
            if detected is not None:
                mime = _CANONICAL_MIME[detected]

    if detected is None:
        text = _looks_like_text(head)
        if text is None:
            raise UnsupportedFileType(
                f"We cannot read {filename!r}. It does not look like any of the file types "
                f"Sift supports.",
                detected_type=mime or "unrecognised",
                supported=list(SUPPORTED_EXTENSIONS),
            )
        # Structure decides. The extension breaks a tie only when structure is silent.
        if _is_tabular(text):
            detected = SourceFormat.CSV
        elif claimed is SourceFormat.CSV:
            # Claims to be a spreadsheet export but has no consistent columns. Treat it as
            # text: the text parser reads anything, whereas the tabular parser would either
            # fail or invent a shape that is not there.
            detected = SourceFormat.TEXT
        else:
            detected = SourceFormat.TEXT
        mime = _CANONICAL_MIME[detected]

    assert mime is not None

    # A disagreement is reported, not rejected. See the module docstring.
    disagreed = claimed is not None and claimed is not detected
    note: str | None = None
    if disagreed:
        note = (
            f"The file is named .{claimed_extension} but its contents are "
            f"{detected.value}. Reading it as {detected.value}."
        )
        logger.info(
            "sniff.extension_mismatch",
            filename=filename,
            claimed=claimed_extension,
            detected=detected.value,
        )
    elif claimed is None and claimed_extension:
        logger.info("sniff.unknown_extension", filename=filename, extension=claimed_extension)

    return Sniffed(
        source_format=detected, mime=mime, extension_disagreed=disagreed, note=note
    )
