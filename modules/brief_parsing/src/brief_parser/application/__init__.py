"""Provider-neutral application stages and end-to-end parsing orchestration."""

from brief_parser.application.ir_assembler import RequirementIRAssembler
from brief_parser.application.model_stages import (
    ConditionalResolver,
    CoverageAuditor,
    RequirementExtractor,
)
from brief_parser.application.output_compilation import CompiledParseOutputs, OutputCompiler
from brief_parser.application.pipeline import BriefParsingPipeline, ParsePipelineRequest
from brief_parser.application.service import (
    BriefParserService,
    ParseServiceRequest,
    TextSourceInput,
)

__all__ = [
    "BriefParserService",
    "BriefParsingPipeline",
    "CompiledParseOutputs",
    "ConditionalResolver",
    "CoverageAuditor",
    "OutputCompiler",
    "ParsePipelineRequest",
    "ParseServiceRequest",
    "RequirementExtractor",
    "RequirementIRAssembler",
    "TextSourceInput",
]
