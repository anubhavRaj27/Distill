"""Entry point for writing the OpenAPI document. ``uv run python -m app.openapi_export``."""

from __future__ import annotations

import sys
from pathlib import Path

from app.main import export_openapi

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    document = export_openapi(target)
    print(f"wrote {target} ({len(document.get('paths', {}))} paths)", file=sys.stderr)
