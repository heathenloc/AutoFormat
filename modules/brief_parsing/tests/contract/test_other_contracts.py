import pytest
from pydantic import ValidationError

from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.execution_brief import ExecutionBrief


def test_execution_brief_round_trip() -> None:
    brief = ExecutionBrief.model_validate(
        {
            "task_type": "write_ad_script",
            "source_artifact_id": "art_sample",
            "source_artifact_version": 1,
            "readiness": "ready",
            "objective": [],
            "facts": {"brand": "示例品牌"},
            "deliverables": [],
            "hard_constraints": [],
            "prohibitions": [],
            "preferences": [],
            "references": [],
            "additional_constraints": [],
            "unresolved": [],
            "applied_defaults": [],
            "consumer_policy": {
                "must_enforce_blockers": True,
                "must_not_infer_unresolved": True,
            },
        }
    )

    assert ExecutionBrief.model_validate_json(brief.model_dump_json()) == brief
    assert brief.schema_version == "execution-brief/1.0"


def test_domain_pack_is_declarative_and_unique() -> None:
    pack = DomainPack.model_validate(
        {
            "id": "advertising_brief",
            "version": "1.0.0",
            "locales": ["zh-CN"],
            "categories": [
                {"id": "duration", "aliases": ["时长"], "risk": "high"},
            ],
            "modality_lexicon": {"must": ["必须"], "must_not": ["不得"]},
            "validators": ["duration_validator"],
            "compilers": ["write_ad_script"],
        }
    )

    assert DomainPack.model_validate_json(pack.model_dump_json()) == pack
    assert pack.schema_version == "domain-pack/1.0"


def test_domain_pack_rejects_duplicate_validator_ids() -> None:
    with pytest.raises(ValidationError, match="validator ids must be unique"):
        DomainPack.model_validate(
            {
                "id": "generic_requirements",
                "version": "1.0.0",
                "locales": ["zh-CN"],
                "validators": ["date_validator", "date_validator"],
            }
        )


def test_domain_pack_rejects_ambiguous_category_aliases() -> None:
    with pytest.raises(ValidationError, match="unambiguous"):
        DomainPack.model_validate(
            {
                "id": "ambiguous",
                "version": "1.0.0",
                "locales": ["zh-CN"],
                "categories": [
                    {"id": "call_to_action", "aliases": ["CTA"]},
                    {"id": "campaign_action", "aliases": ["cta"]},
                ],
            }
        )
