from __future__ import annotations

from pathlib import Path

import pytest
from scripts.compile_domain_packs import DOMAIN_PACK_ROOT, compile_domain_packs

from brief_parser.compilers.context import CompilerRegistry
from brief_parser.compilers.domain_validation import DomainValidatorRegistry
from brief_parser.domain_packs.loader import (
    DomainPackLoader,
    DomainPackReferenceRegistry,
)
from brief_parser.errors import BriefParserError, ErrorCode


def _loader() -> DomainPackLoader:
    return DomainPackLoader(
        DomainPackReferenceRegistry(
            validator_ids=DomainValidatorRegistry.builtins().ids,
            compiler_ids=CompilerRegistry.builtins().ids,
        )
    )


def test_mvp_and_example_domain_packs_load_and_compile() -> None:
    loader = _loader()
    catalog = loader.load_directory(DOMAIN_PACK_ROOT)

    assert set(catalog) == {
        ("academic_paper", "1.0.0"),
        ("academic_paper", "1.1.0"),
        ("academic_paper_example", "1.0.0"),
        ("advertising_brief", "1.0.0"),
        ("generic_requirements", "1.0.0"),
    }
    assert catalog[("advertising_brief", "1.0.0")].compilers == [
        "write_ad_script"
    ]
    assert catalog[("academic_paper", "1.0.0")].compilers == []
    assert len(catalog[("academic_paper", "1.0.0")].categories) >= 18
    assert "word_count" not in {category.id for category in catalog[("academic_paper", "1.1.0")].categories}
    assert compile_domain_packs(check=True) == []
    for source in DOMAIN_PACK_ROOT.rglob("*.yaml"):
        assert loader.load_json(source.with_suffix(".json")) == loader.load_yaml(source)


def test_domain_pack_rejects_python_object_tag(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        "!!python/object/apply:os.system ['echo unsafe']\n",
        encoding="utf-8",
    )

    with pytest.raises(BriefParserError) as error:
        _loader().load_yaml(path)

    assert error.value.code == ErrorCode.DOMAIN_PACK_INVALID


def test_domain_pack_rejects_yaml_aliases(tmp_path: Path) -> None:
    path = tmp_path / "alias.yaml"
    path.write_text(
        "id: generic\nversion: 1.0.0\nschema_version: domain-pack/1.0\n"
        "locales: &locales [zh-CN]\ncategories: []\n"
        "modality_lexicon: {}\nvalidators: []\ncompilers: []\n"
        "extra: *locales\n",
        encoding="utf-8",
    )

    with pytest.raises(BriefParserError) as error:
        _loader().load_yaml(path)

    assert error.value.code == ErrorCode.DOMAIN_PACK_INVALID


def test_domain_pack_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "id: first\nid: second\nversion: 1.0.0\n"
        "schema_version: domain-pack/1.0\nlocales: [zh-CN]\n"
        "categories: []\nmodality_lexicon: {}\nvalidators: []\ncompilers: []\n",
        encoding="utf-8",
    )

    with pytest.raises(BriefParserError) as error:
        _loader().load_yaml(path)

    assert error.value.code == ErrorCode.DOMAIN_PACK_INVALID


def test_domain_pack_rejects_unknown_registry_reference(tmp_path: Path) -> None:
    path = tmp_path / "unknown.yaml"
    path.write_text(
        "id: generic\nversion: 1.0.0\nschema_version: domain-pack/1.0\n"
        "locales: [zh-CN]\ncategories: []\nmodality_lexicon: {}\n"
        "validators: [arbitrary.module.Validator]\ncompilers: []\n",
        encoding="utf-8",
    )

    with pytest.raises(BriefParserError) as error:
        _loader().load_yaml(path)

    assert error.value.code == ErrorCode.DOMAIN_PACK_INVALID
    assert error.value.details["unknown_validators"] == [
        "arbitrary.module.Validator"
    ]
