"""Export deterministic standalone OpenAPI contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brief_parser.api.app import create_app  # noqa: E402
from brief_parser.config import Settings  # noqa: E402

OPENAPI_PATH = PROJECT_ROOT / "contracts/openapi/standalone-v1.openapi.json"


def render_openapi() -> str:
    app = create_app(
        Settings(
            mode="standalone",
            environment="test",
            provider="fake",
            storage_dir=Path("var"),
            sqlite_path=Path("var/brief-parser.sqlite3"),
        )
    )
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_openapi(*, check: bool) -> bool:
    expected = render_openapi()
    current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.exists() else None
    if current == expected:
        return False
    if not check:
        OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_PATH.write_text(expected, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = export_openapi(check=args.check)
    if args.check and stale:
        print(f"stale OpenAPI snapshot: {OPENAPI_PATH.relative_to(PROJECT_ROOT)}", file=sys.stderr)
        return 1
    if stale:
        print(f"wrote {OPENAPI_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
