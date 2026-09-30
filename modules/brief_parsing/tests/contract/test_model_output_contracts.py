import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from brief_parser.domain.candidates import AuditorOutput, ExtractorOutput, ResolverOutput
from brief_parser.ports.model_provider import StructuredModelResult


@pytest.mark.parametrize("model", [ExtractorOutput, AuditorOutput, ResolverOutput])
def test_model_outputs_convert_to_openai_strict_json_schema(model: type[object]) -> None:
    schema = to_strict_json_schema(model)  # type: ignore[arg-type]

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_completed_provider_result_requires_output() -> None:
    with pytest.raises(ValidationError, match="require output"):
        StructuredModelResult[ExtractorOutput](
            output=None,
            provider_alias="fake",
            model_id="fake-extractor",
            completion_status="completed",
        )


def test_refused_provider_result_cannot_carry_output() -> None:
    output = ExtractorOutput(
        facts=[],
        objectives=[],
        requirements=[],
        references=[],
        candidate_conflicts=[],
        unresolved_items=[],
    )

    with pytest.raises(ValidationError, match="only refusal_reason"):
        StructuredModelResult[ExtractorOutput](
            output=output,
            provider_alias="fake",
            model_id="fake-extractor",
            completion_status="refused",
            refusal_reason="synthetic",
        )
