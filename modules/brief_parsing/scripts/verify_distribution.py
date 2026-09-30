"""Build and inspect the wheel without network or Provider access."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from brief_parser.version import __version__

REQUIRED_WHEEL_PATHS = frozenset(
    {
        "brief_parser/py.typed",
        "brief_parser/adapters/bounded_provider.py",
        "brief_parser/adapters/observability.py",
        "brief_parser/application/resource_limits.py",
        "brief_parser/ports/observability.py",
        "brief_parser/prompts/extractor/v1.md",
        "brief_parser/prompts/auditor/v1.md",
        "brief_parser/prompts/resolver/v1.md",
        "brief_parser/domain_packs_data/generic_requirements/1.0.0.json",
        "brief_parser/domain_packs_data/advertising_brief/1.0.0.json",
        "brief_parser/evaluation_data/golden/v1/dataset.json",
    }
)


def _find_uv(root: Path) -> Path:
    installed = shutil.which("uv")
    candidates = [
        Path(installed) if installed is not None else None,
        root / ".tools" / "bin" / "uv.exe",
        root / ".tools" / "bin" / "uv",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise RuntimeError("uv executable is required for offline distribution verification")


def _is_forbidden(path: str) -> bool:
    parts = PurePosixPath(path).parts
    lowered = tuple(part.lower() for part in parts)
    return (
        any(part in {".env", "var", "output", "tests"} for part in lowered)
        or any(part in {"runs", "reports"} for part in lowered)
        or path.lower().endswith((".sqlite", ".sqlite3", ".db"))
    )


def validate_wheel(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = sorted(REQUIRED_WHEEL_PATHS - names)
            if missing:
                raise RuntimeError(f"wheel is missing required resources: {missing}")
            forbidden = sorted(name for name in names if _is_forbidden(name))
            if forbidden:
                raise RuntimeError(f"wheel contains forbidden runtime files: {forbidden}")

            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            entry_point_names = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(metadata_names) != 1 or len(entry_point_names) != 1:
                raise RuntimeError("wheel must contain one metadata and entry-point file")
            metadata = archive.read(metadata_names[0]).decode("utf-8")
            if "Name: brief-parser\n" not in metadata:
                raise RuntimeError("wheel metadata has the wrong project name")
            if f"Version: {__version__}\n" not in metadata:
                raise RuntimeError("wheel metadata version does not match package version")

            entry_points = archive.read(entry_point_names[0]).decode("utf-8")
            required_commands = {
                "brief-parser = brief_parser.cli.main:main",
                "brief-parser-eval = brief_parser.evaluation.cli:main",
                "brief-parser-golden-run = brief_parser.evaluation.golden_cli:main",
                "brief-parser-load = brief_parser.evaluation.load_cli:main",
            }
            missing_commands = sorted(
                command for command in required_commands if command not in entry_points
            )
            if missing_commands:
                raise RuntimeError(
                    f"wheel is missing console entry points: {missing_commands}"
                )
    except (BadZipFile, UnicodeError, OSError) as exc:
        raise RuntimeError("wheel cannot be inspected safely") from exc


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    uv = _find_uv(root)
    with tempfile.TemporaryDirectory(prefix="brief-parser-wheel-") as temporary_dir:
        output_dir = Path(temporary_dir)
        completed = subprocess.run(
            [
                str(uv),
                "build",
                "--wheel",
                "--offline",
                "--no-python-downloads",
                "--out-dir",
                str(output_dir),
                str(root),
            ],
            cwd=root,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
        wheels = list(output_dir.glob("*.whl"))
        if len(wheels) != 1:
            print("distribution verification expected exactly one wheel", file=sys.stderr)
            return 1
        try:
            validate_wheel(wheels[0])
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"verified {wheels[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
