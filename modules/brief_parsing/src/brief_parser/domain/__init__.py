"""Provider- and transport-independent domain contracts."""

from brief_parser.domain.bundle import ParseBundle, ParseDiagnostics
from brief_parser.domain.candidates import AuditorOutput, ExtractorOutput, ResolverOutput
from brief_parser.domain.document import DocumentBlock, ExtractedDocument, NormalizationMap
from brief_parser.domain.domain_pack import DomainPack
from brief_parser.domain.execution_brief import ExecutionBrief
from brief_parser.domain.foundation import (
    Clause,
    ClauseSegmentation,
    CoverageLedger,
    DeterministicClauseAnalysis,
    ReadinessAssessment,
)
from brief_parser.domain.jobs import JobStatus, ParseJobRecord
from brief_parser.domain.pipeline import ParseManifest, PipelineResult
from brief_parser.domain.requirement_ir import RequirementIR

__all__ = [
    "AuditorOutput",
    "Clause",
    "ClauseSegmentation",
    "CoverageLedger",
    "DeterministicClauseAnalysis",
    "DocumentBlock",
    "DomainPack",
    "ExecutionBrief",
    "ExtractedDocument",
    "ExtractorOutput",
    "JobStatus",
    "NormalizationMap",
    "ParseBundle",
    "ParseDiagnostics",
    "ParseJobRecord",
    "ParseManifest",
    "PipelineResult",
    "ReadinessAssessment",
    "RequirementIR",
    "ResolverOutput",
]
