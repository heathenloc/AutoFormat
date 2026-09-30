"""Stable enumerations used by public contracts."""

from enum import StrEnum


class Readiness(StrEnum):
    COMPLETE = "complete"
    USABLE_WITH_WARNINGS = "usable_with_warnings"
    INCOMPLETE = "incomplete"


class ExecutionReadiness(StrEnum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    BLOCKED = "blocked"


class Modality(StrEnum):
    MUST = "must"
    MUST_NOT = "must_not"
    SHOULD = "should"
    MAY = "may"
    INFORMATIONAL = "informational"


class Operator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    BETWEEN = "between"
    IN = "in"
    CONTAINS = "contains"
    MATCHES = "matches"
    BEFORE = "before"
    AFTER = "after"
    CUSTOM = "custom"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    VERIFIED_WITH_WARNING = "verified_with_warning"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"


class DownstreamPolicy(StrEnum):
    ENFORCE = "enforce"
    PREFER = "prefer"
    INFORM = "inform"
    DO_NOT_ASSUME = "do_not_assume"
    BLOCK = "block"


class Severity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class EvidenceMatchStatus(StrEnum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    INVALID = "invalid"


class ModelRole(StrEnum):
    EXTRACTOR = "extractor"
    AUDITOR = "auditor"
    RESOLVER = "resolver"
    OFFLINE_JUDGE = "offline_judge"

