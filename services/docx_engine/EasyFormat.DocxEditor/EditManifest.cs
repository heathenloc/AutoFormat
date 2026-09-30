namespace EasyFormat.DocxEditor;

public sealed record EditManifest(
    string SchemaVersion,
    string OperationId,
    string RuleId,
    string BaseVersionId,
    string BaseDocxSha256,
    string InputFile,
    string OutputFile,
    string TargetObjectId,
    string ExpectedParagraphTextSha256,
    string Property,
    string Value,
    string EffectiveScope);

public sealed record EditResult(
    string SchemaVersion,
    string Status,
    string OperationId,
    string? BeforeDirectAlignment,
    string? AfterDirectAlignment,
    string? OutputDocxSha256,
    string Reason);
