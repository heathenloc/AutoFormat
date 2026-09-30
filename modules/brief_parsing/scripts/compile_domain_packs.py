"""Validate YAML Domain Packs and compile deterministic JSON snapshots."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brief_parser.compilers.context import CompilerRegistry  # noqa: E402
from brief_parser.compilers.domain_validation import DomainValidatorRegistry  # noqa: E402
from brief_parser.domain_packs.loader import (  # noqa: E402
    DomainPackLoader,
    DomainPackReferenceRegistry,
)

DOMAIN_PACK_ROOT = PROJECT_ROOT / "domain_packs"


def build_loader() -> DomainPackLoader:
    validators = DomainValidatorRegistry.builtins()
    compilers = CompilerRegistry.builtins()
    return DomainPackLoader(
        DomainPackReferenceRegistry(
            validator_ids=validators.ids,
            compiler_ids=compilers.ids,
        )
    )


def compile_domain_packs(*, check: bool) -> list[Path]:
    loader = build_loader()
    stale: list[Path] = []
    for source in sorted(DOMAIN_PACK_ROOT.rglob("*.yaml")):
        destination = source.with_suffix(".json")
        expected = loader.canonical_json(loader.load_yaml(source))
        current = destination.read_text(encoding="utf-8") if destination.exists() else None
        if current == expected:
            continue
        stale.append(destination.relative_to(PROJECT_ROOT))
        if not check:
            destination.write_text(expected, encoding="utf-8", newline="\n")
    return stale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when compiled Domain Pack JSON differs from YAML sources.",
    )
    args = parser.parse_args()
    stale = compile_domain_packs(check=args.check)
    if args.check and stale:
        for path in stale:
            print(f"stale domain pack: {path}", file=sys.stderr)
        return 1
    if not args.check:
        for path in stale:
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
