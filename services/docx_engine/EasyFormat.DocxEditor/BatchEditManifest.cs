namespace EasyFormat.DocxEditor;

public sealed record BatchEditOperation(
    string OperationId,
    string RuleId,
    string TargetObjectId,
    string ExpectedParagraphTextSha256,
    string ExpectedXmlPath,
    string Property,
    string Value,
    string EffectiveScope,
    string? ExpectedBeforeDirectAlignment);

public sealed record BatchEditManifest(
    string SchemaVersion,
    string BatchId,
    string BaseVersionId,
    string BaseDocxSha256,
    string InputFile,
    string OutputFile,
    IReadOnlyList<BatchEditOperation> Operations);

public sealed record BatchOperationResult(
    string OperationId,
    string TargetObjectId,
    string Status,
    string? BeforeDirectAlignment,
    string? AfterDirectAlignment);

public sealed record BatchEditResult(
    string SchemaVersion,
    string Status,
    string BatchId,
    string? OutputDocxSha256,
    IReadOnlyList<BatchOperationResult> Operations,
    string Reason);
