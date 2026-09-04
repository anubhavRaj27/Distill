"""Prompt templates, kept as files rather than string literals in code.

Three reasons this is a directory of ``.md`` files and not a module of constants:

* a prompt is the most frequently edited artefact in a project like this, and a diff of a
  markdown file is readable in a way a diff of an embedded triple-quoted string is not
* the fixture keys the fake provider replays are content-derived, never prompt-derived
  (review finding 8.6), so a prompt edit does not invalidate the test suite and prompts can
  be tuned freely
* they are legible to a reviewer without reading Python
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load(name: str) -> str:
    """Load a prompt template by stem. Cached, since prompts do not change at runtime."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt template named {name!r} in {PROMPT_DIR}")
    return path.read_text(encoding="utf-8").strip()


def render(name: str, **values: object) -> str:
    """Load ``name`` and substitute ``{placeholders}``.

    Uses ``str.format_map`` with a forgiving mapping, so a template referring to a value the
    caller did not supply renders the placeholder literally instead of raising. A prompt
    that is slightly wrong is recoverable; a request that never goes out is not.
    """

    class _Forgiving(dict[str, object]):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return load(name).format_map(_Forgiving(values))
