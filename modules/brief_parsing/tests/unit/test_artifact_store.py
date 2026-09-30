from pathlib import Path

import pytest

from brief_parser.adapters.artifact_store import ArtifactDirectoryStore
from brief_parser.errors import BriefParserError, ErrorCode
from tests.phase6_factories import make_parse_bundle


async def test_artifact_directory_is_complete_and_reusable(tmp_path: Path) -> None:
    bundle = await make_parse_bundle()
    output = tmp_path / "result"
    store = ArtifactDirectoryStore()

    written = store.write(bundle, output)

    assert written.reused_existing is False
    assert {path.name for path in written.files} == {
        "manifest.json",
        "requirement-ir.json",
        "execution-brief.write_ad_script.json",
        "result.md",
        "diagnostics.json",
    }
    assert store.read(output) == bundle
    assert not list(tmp_path.glob(".result.tmp-*"))

    reused = store.write(bundle, output)
    assert reused.reused_existing is True


async def test_existing_directory_with_another_fingerprint_is_rejected(
    tmp_path: Path,
) -> None:
    bundle = await make_parse_bundle()
    output = tmp_path / "result"
    store = ArtifactDirectoryStore()
    store.write(bundle, output)
    conflicting = bundle.model_copy(
        update={"manifest": bundle.manifest.model_copy(update={"request_fingerprint": "a" * 64})}
    )

    with pytest.raises(BriefParserError) as error:
        store.write(conflicting, output)

    assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
