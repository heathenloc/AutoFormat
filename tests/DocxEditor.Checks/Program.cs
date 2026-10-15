using System.Security.Cryptography;
using System.Text.Json;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;
using DocumentFormat.OpenXml.Wordprocessing;
using AutoFormat.DocxEditor;
using AutoFormat.DocxIndex;

var taskRoot = Path.GetFullPath(Path.Combine("runtime", "tests", "docx-editor", Guid.NewGuid().ToString("N")));
Directory.CreateDirectory(taskRoot);
var input = Path.Combine(taskRoot, "v0.docx");

using (var document = WordprocessingDocument.Create(input, WordprocessingDocumentType.Document))
{
    var main = document.AddMainDocumentPart();
    main.Document = new Document(new Body(
        new Paragraph(new ParagraphProperties(new Justification { Val = JustificationValues.Left }),
            new Run(new Text("第一段保持左对齐"))),
        new Paragraph(new Run(new RunProperties(new Bold()), new Text("第二段需要居中"))),
        new Table(new TableProperties(), new TableGrid(new GridColumn()),
            new TableRow(new TableCell(new Paragraph(new Run(new Text("表格文字不变")))))),
        new Paragraph(new Run(new RunProperties(new Vanish()), new Text("隐藏段落"))),
        new SectionProperties()));
    main.Document.Save();
}

var source = DocxTextIndex.Build(input);
using (var document = WordprocessingDocument.Open(input, false))
{
    var errors = new OpenXmlValidator().Validate(document).Select(e => e.Description).Take(3).ToArray();
    Require(errors.Length == 0, "Generated source DOCX is invalid: " + string.Join("; ", errors));
}
var originalHash = source.Sha256;
Require(source.Paragraphs.Count == 4, "Expected main document, table, and hidden paragraphs.");
var manifest = new EditManifest(
    "edit-manifest-prototype/1.0", "operation-1", "rule-1", "version-0",
    originalHash, "v0.docx", "v1.docx", "p:000002",
    ParagraphAlignmentEditor.HashText(source.Paragraphs[1].Text),
    "paragraph.alignment", "center", "paragraph");
var jsonOptions = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
Require(JsonSerializer.Deserialize<EditManifest>(JsonSerializer.Serialize(manifest, jsonOptions), jsonOptions)
    == manifest, "Snake-case edit manifest round-trips across the CLI boundary.");

var result = ParagraphAlignmentEditor.Apply(taskRoot, manifest);
Require(result.Status == "ready", $"Expected ready, got {result.Status}: {result.Reason}");
Require(result.BeforeDirectAlignment is null &&
    string.Equals(result.AfterDirectAlignment, "center", StringComparison.OrdinalIgnoreCase),
    $"Report reflects the direct alignment change: {result.BeforeDirectAlignment} -> {result.AfterDirectAlignment}.");
Require(File.Exists(Path.Combine(taskRoot, "v1.docx")), "A new DOCX exists.");
Require(DocxTextIndex.Build(input).Sha256 == originalHash, "V0 source bytes never change.");

using (var document = WordprocessingDocument.Open(Path.Combine(taskRoot, "v1.docx"), false))
{
    var paragraphs = document.MainDocumentPart?.Document?.Body?.Descendants<Paragraph>().ToList()
        ?? throw new Exception("Edited document has no paragraphs.");
    Require(paragraphs[0].ParagraphProperties?.Justification?.Val?.Value == JustificationValues.Left,
        "Unrelated paragraph alignment stays unchanged.");
    Require(paragraphs[1].ParagraphProperties?.Justification?.Val?.Value == JustificationValues.Center,
        "Target paragraph is centered.");
    Require(paragraphs[1].Descendants<Bold>().Any(), "Existing run formatting stays present.");
    Require(paragraphs[2].InnerText == "表格文字不变", "Table text stays present.");
}

var modified = DocxTextIndex.Build(Path.Combine(taskRoot, "v1.docx"));
Require(source.Paragraphs.Select(p => p.Text).SequenceEqual(modified.Paragraphs.Select(p => p.Text)),
    "No main-document text changed.");

var second = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-2", BaseVersionId = "version-1", BaseDocxSha256 = modified.Sha256,
    InputFile = "v1.docx", OutputFile = "v2.docx",
});
Require(second.Status == "already_satisfied", "Applying the same property is idempotent.");
Require(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(taskRoot, "v1.docx")))) ==
    Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(taskRoot, "v2.docx")))),
    "Already-satisfied operation adds no unrelated package changes.");

var stale = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-stale", OutputFile = "stale.docx",
    BaseDocxSha256 = new string('0', 64),
});
Require(stale.Status == "stale_base_version" && !File.Exists(Path.Combine(taskRoot, "stale.docx")),
    "Stale base does not publish a candidate.");

var changedTarget = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-target", OutputFile = "target.docx",
    ExpectedParagraphTextSha256 = new string('0', 64),
});
Require(changedTarget.Status == "ambiguous_target" &&
    !File.Exists(Path.Combine(taskRoot, "target.docx")),
    "Changed target text does not publish a candidate.");

var hiddenTarget = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-hidden", OutputFile = "hidden.docx",
    TargetObjectId = "p:000004",
    ExpectedParagraphTextSha256 = ParagraphAlignmentEditor.HashText(source.Paragraphs[3].Text),
});
Require(hiddenTarget.Status == "ambiguous_target" &&
    !File.Exists(Path.Combine(taskRoot, "hidden.docx")),
    "Hidden or revision content requires manual targeting.");

var unsupported = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-unsupported", OutputFile = "unsupported.docx",
    Property = "paragraph.shadow",
});
Require(unsupported.Status == "unsupported_property" &&
    !File.Exists(Path.Combine(taskRoot, "unsupported.docx")),
    "Unknown property is never mapped to a similar edit.");

var scope = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-scope", OutputFile = "scope.docx", EffectiveScope = "selection",
});
Require(scope.Status == "needs_user_input" && !File.Exists(Path.Combine(taskRoot, "scope.docx")),
    "Paragraph-only property cannot claim selection scope.");

var escape = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-escape", OutputFile = "..\\escape.docx",
});
Require(escape.Status == "needs_user_input", "Output path cannot escape task directory.");

var driveRelative = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-drive", OutputFile = "C:escape.docx",
});
Require(driveRelative.Status == "needs_user_input", "Drive-relative output is rejected.");

var existing = ParagraphAlignmentEditor.Apply(taskRoot, manifest with
{
    OperationId = "operation-existing", OutputFile = "v1.docx",
});
Require(existing.Status == "needs_user_input", "Published version cannot be overwritten.");

var batch = new BatchEditManifest(
    "edit-batch-manifest/1.0", "batch-1", "version-1", modified.Sha256,
    "v1.docx", "batch.docx", new[]
    {
        new BatchEditOperation("batch-op-1", "rule-body", "p:000001",
            ParagraphAlignmentEditor.HashText(source.Paragraphs[0].Text),
            source.Paragraphs[0].XmlPath, "paragraph.alignment", "center", "paragraph", "left"),
        new BatchEditOperation("batch-op-2", "rule-body", "p:000002",
            ParagraphAlignmentEditor.HashText(source.Paragraphs[1].Text),
            source.Paragraphs[1].XmlPath, "paragraph.alignment", "center", "paragraph", "center"),
    });
var roundTrip = JsonSerializer.Deserialize<BatchEditManifest>(
    JsonSerializer.Serialize(batch, jsonOptions), jsonOptions);
Require(roundTrip is not null && roundTrip.BatchId == batch.BatchId &&
    roundTrip.Operations.SequenceEqual(batch.Operations),
    "Batch manifest serializes across the CLI boundary.");
var batchResult = ParagraphAlignmentBatchEditor.Apply(taskRoot, batch);
Require(batchResult.Status == "ready" &&
    batchResult.Operations.Select(item => item.Status).SequenceEqual(
        new[] { "ready", "already_satisfied" }),
    "Batch verifies changed and already satisfied targets separately.");
using (var document = WordprocessingDocument.Open(Path.Combine(taskRoot, "batch.docx"), false))
{
    var paragraphs = document.MainDocumentPart!.Document!.Body!.Descendants<Paragraph>().ToArray();
    Require(paragraphs[0].ParagraphProperties?.Justification?.Val?.Value == JustificationValues.Center &&
        paragraphs[1].ParagraphProperties?.Justification?.Val?.Value == JustificationValues.Center &&
        paragraphs[2].ParagraphProperties?.Justification is null,
        "Batch changed only its two confirmed paragraphs.");
}
Require(DocxTextIndex.Build(input).Sha256 == originalHash, "Batch preserves original bytes.");

var batchHash = DocxTextIndex.Build(Path.Combine(taskRoot, "batch.docx")).Sha256;
var noChangeBatch = ParagraphAlignmentBatchEditor.Apply(taskRoot, batch with
{
    BatchId = "batch-no-change", BaseDocxSha256 = batchHash,
    InputFile = "batch.docx", OutputFile = "batch-no-change.docx",
    Operations = batch.Operations.Select(item => item with
    {
        ExpectedBeforeDirectAlignment = "center"
    }).ToArray(),
});
Require(noChangeBatch.Status == "already_satisfied" &&
    noChangeBatch.Operations.All(item => item.Status == "already_satisfied") &&
    DocxTextIndex.Build(Path.Combine(taskRoot, "batch-no-change.docx")).Sha256 == batchHash,
    "A repeated batch is byte-for-byte idempotent.");

var rejectedBatch = ParagraphAlignmentBatchEditor.Apply(taskRoot, batch with
{
    BatchId = "batch-rejected", OutputFile = "batch-rejected.docx",
    Operations = new[]
    {
        batch.Operations[0],
        batch.Operations[1] with { ExpectedParagraphTextSha256 = new string('0', 64) },
    },
});
Require(rejectedBatch.Status == "ambiguous_target" &&
    !File.Exists(Path.Combine(taskRoot, "batch-rejected.docx")),
    "One stale target prevents the whole batch from publishing.");

Console.WriteLine("DocxEditor checks passed.");

static void Require(bool condition, string description)
{
    if (!condition) throw new Exception(description);
}
