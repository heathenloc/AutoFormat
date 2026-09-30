"""Run the complete local quality gate without contacting a model Provider."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks: tuple[tuple[str, ...], ...] = (
        (sys.executable, "-m", "pytest"),
        (sys.executable, "-m", "ruff", "check", "."),
        (sys.executable, "-m", "mypy"),
        (sys.executable, "scripts/export_schemas.py", "--check"),
        (sys.executable, "scripts/export_openapi.py", "--check"),
        (sys.executable, "scripts/compile_domain_packs.py", "--check"),
        (sys.executable, "scripts/verify_distribution.py"),
    )
    for command in checks:
        print(f"\n[verify] {' '.join(command[1:])}", flush=True)
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode != 0:
            return completed.returncode
    print("\n[verify] all offline checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
