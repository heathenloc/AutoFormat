from pathlib import Path

import pytest

from brief_parser.adapters.prompt_repository import FilePromptRepository
from brief_parser.domain.enums import ModelRole
from brief_parser.errors import BriefParserError, ErrorCode

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def test_versioned_prompt_loads_exact_role_template() -> None:
    template = FilePromptRepository(PROMPTS).get(
        role=ModelRole.EXTRACTOR,
        version="extractor/v1",
    )

    assert template.version == "extractor/v1"
    assert "untrusted data envelope" in template.content
    assert "Return only the requested Structured Output" in template.content


def test_prompt_role_version_mismatch_is_rejected() -> None:
    with pytest.raises(BriefParserError) as error:
        FilePromptRepository(PROMPTS).get(
            role=ModelRole.AUDITOR,
            version="extractor/v1",
        )

    assert error.value.code == ErrorCode.INVALID_REQUEST
