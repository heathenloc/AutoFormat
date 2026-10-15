using System.Text.Json;

namespace AutoFormat.DocxEditor;

public sealed record FormatAxis(string[]? Include, string[] Exclude);
public sealed record FormatScope(Dictionary<string, FormatAxis> Axes);
public sealed record FormatConstraint(string Operator, double? Lower, double? Upper);
public sealed record FormatSemantics(string SchemaVersion, FormatScope Scope, FormatConstraint Constraint, JsonElement? Condition);
public sealed record FormatTarget(string ObjectKind, string SemanticRole, string Selector);
public sealed record FormatValue(string OriginalText, JsonElement Normalized, string? Unit, string DictionaryVersion);
public sealed record EffectiveFormatRule(
    string SchemaVersion, string RuleId, string SourceKind, string[] SourceRuleIds,
    JsonElement[] EvidenceRefs, string[] ObservationIds, string[] DecisionIds,
    FormatTarget Target, string PropertyId, FormatValue Value, string CharacterScope,
    FormatSemantics Semantics, string ExecutionSupport, string Status, string Reason);
public sealed record FormatFragment(string FragmentId, string RuleId, FormatScope Scope, string Status, string[] ConflictIds, string Reason);
public sealed record AcademicEditManifest(
    string SchemaVersion, string BaseVersionId, string BaseDocxSha256,
    string InputFile, string OutputFile, string RulesSnapshotId,
    EffectiveFormatRule[] Rules, FormatFragment[] Fragments);
public sealed record FormatOperation(
    string OperationId, string RuleId, string FragmentId, string ObjectId, string Part,
    string XmlPath, string PropertyId, string? Component, string? CharacterType,
    JsonElement? Before, JsonElement After, string EffectiveScope, string Status, bool Changed, string Reason);
public sealed record FormatRuleResult(string RuleId, string Status, int TargetCount, string Reason);
public sealed record AcademicEditResult(
    string SchemaVersion, string Status, string BaseDocxSha256, string RulesSnapshotId,
    string? OutputDocxSha256, FormatOperation[] Operations, FormatRuleResult[] Rules,
    bool ContentPreserved, bool PackageValidated, string FieldRefreshStatus, string Reason);
public sealed record FormatCapability(string PropertyId, string Level, string MinimumScope, string Verification);

internal sealed class FormatBlocked(string status, string message) : Exception(message)
{
    public string Status { get; } = status;
}
