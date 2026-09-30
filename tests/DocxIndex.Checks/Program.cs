using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using EasyFormat.DocxIndex;

var testDirectory = Path.GetFullPath(Path.Combine("runtime", "tests", "docx-index"));
Directory.CreateDirectory(testDirectory);
var docxPath = Path.Combine(testDirectory, $"anchor-cases-{Guid.NewGuid():N}.docx");

const string mainDocument = """
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr><w:r><w:t>这是</w:t></w:r><w:r><w:t>正文</w:t></w:r><w:r><w:t>。</w:t></w:r></w:p>
        <w:p><w:r><w:t>甲重复文本</w:t></w:r></w:p>
        <w:p><w:r><w:t>乙重复文本</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        <w:p><w:r><w:t>修订段落</w:t></w:r><w:del><w:r><w:delText>删除的文字</w:delText></w:r></w:del></w:p>
        <w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>隐藏文字</w:t></w:r></w:p>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>
        <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>列表项</w:t></w:r></w:p>
        <w:p><w:pPr><w:pStyle w:val="CustomBody"/></w:pPr><w:r><w:t>自定义样式</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """;

using (var archive = ZipFile.Open(docxPath, ZipArchiveMode.Create))
{
    var entry = archive.CreateEntry("word/document.xml");
    using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
    writer.Write(mainDocument);
}

var originalHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(docxPath)));
var index = DocxTextIndex.Build(docxPath);
Require(index.Paragraphs.Count == 9, "Nested table paragraph is indexed once.");
Require(index.Paragraphs[0].Text == "这是正文。", "Text spans DOCX runs.");
Require(index.Paragraphs[3].Text == "表格内容", "Table cell text is indexed.");
Require(index.Paragraphs[3].XmlPath.Contains("tbl[1]/tr[1]/tc[1]/p[1]", StringComparison.Ordinal),
    "Table path identifies the cell.");
Require(index.Paragraphs[0].RoleCandidate == "body_candidate" &&
    index.Paragraphs[0].RoleEvidence == "normal_style_only",
    "Normal style is only a body candidate.");
Require(index.Paragraphs[3].RoleCandidate == "table_cell" &&
    index.Paragraphs[3].RoleEvidence == "inside_table",
    "Table cell is kept outside body paragraph candidates.");
Require(index.Paragraphs[6].RoleCandidate == "heading_candidate" &&
    index.Paragraphs[6].RoleEvidence == "built_in_heading_style",
    "Built-in heading style is recognized without treating it as body.");
Require(index.Paragraphs[7].RoleEvidence == "numbering_properties" &&
    index.Paragraphs[8].RoleEvidence == "no_reliable_body_role",
    "List and custom style paragraphs require classification.");

var hint = new SelectionHint("selection-hint-prototype/1.0", "version-1", index.Sha256,
    "preview-1", "libreoffice", "test", "正文", "这是", "。", 1, 10, 12);
var binding = new PreviewBinding("version-1", index.Sha256,
    "preview-1", "libreoffice", "test", 2);
var wireHint = JsonSerializer.Deserialize<SelectionHint>(JsonSerializer.Serialize(hint,
    new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }),
    new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
Require(wireHint == hint, "Snake-case wire contract preserves selection fields.");
var unique = AnchorLocator.Locate(index, hint, binding);
Require(unique.Status == "ready" && unique.Candidates.Count == 1 &&
    unique.Candidates[0].ObjectId == "p:000001" && unique.Candidates[0].Start == 2 &&
    unique.Anchor is { DocxObjectId: "p:000001", Status: "ready", PreviewArtifactId: "preview-1" },
    "A selection spanning DOCX runs maps to a unique character offset.");

var duplicate = AnchorLocator.Locate(index, hint with
{
    SelectedText = "重复文本", ContextBefore = "", ContextAfter = "",
}, binding);
Require(duplicate.Status == "ambiguous_target" && duplicate.Candidates.Count == 2,
    "Repeated text never silently chooses a target.");

var contextual = AnchorLocator.Locate(index, hint with
{
    SelectedText = "重复文本", ContextBefore = "乙", ContextAfter = "",
}, binding);
Require(contextual.Status == "ambiguous_target" && contextual.Candidates.Count == 2,
    "Repeated text requires user choice even if context suggests one location.");

var stale = AnchorLocator.Locate(index, hint with { BaseDocxSha256 = new string('0', 64) }, binding);
Require(stale.Status == "stale_base_version", "Old preview cannot target a different DOCX hash.");
Require(AnchorLocator.Locate(index, hint with { BaseVersionId = "version-2" }, binding).Status ==
    "stale_base_version", "A different version ID is rejected even when DOCX bytes match.");
Require(AnchorLocator.Locate(index, hint with { PreviewArtifactId = "preview-2" }, binding).Status ==
    "stale_preview", "A different preview artifact cannot reuse the selection.");
Require(AnchorLocator.Locate(index, hint with { RendererVersion = "other" }, binding).Status ==
    "stale_preview", "A renderer change invalidates the preview selection.");
Require(AnchorLocator.Locate(index, hint with { PdfPage = 3 }, binding).Status ==
    "stale_preview", "PDF page must exist in the bound preview.");

var crossParagraph = AnchorLocator.Locate(index, hint with { SelectedText = "正文\n甲" }, binding);
Require(crossParagraph.Status == "ambiguous_target", "Cross-paragraph selection pauses.");

var missing = AnchorLocator.Locate(index, hint with { SelectedText = "不存在" }, binding);
Require(missing.Status == "ambiguous_target", "Missing text pauses instead of guessing.");
Require(AnchorLocator.Locate(index, hint with { ContextBefore = "错误" }, binding).Status ==
    "ambiguous_target", "Mismatched PDF context cannot auto-target a DOCX paragraph.");
Require(AnchorLocator.Locate(index, hint with
    { SelectedText = "修订段落", ContextBefore = "", ContextAfter = "" }, binding).Status ==
    "ambiguous_target", "Tracked-change paragraphs require manual targeting.");
Require(AnchorLocator.Locate(index, hint with
    { SelectedText = "隐藏文字", ContextBefore = "", ContextAfter = "" }, binding).Status ==
    "ambiguous_target", "Hidden-text paragraphs require manual targeting.");

Require(originalHash == Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(docxPath))),
    "Index and locate never alter source DOCX bytes.");
File.Delete(docxPath);

if (args.Length == 1)
{
    var sample = DocxTextIndex.Build(args[0]);
    Require(sample.Paragraphs.Count > 0 && sample.Paragraphs.Any(p => p.Text.Length > 0),
        "Provided real DOCX sample has indexable text.");
    Console.WriteLine($"Real sample indexed: {sample.Paragraphs.Count} paragraphs.");
}

Console.WriteLine("DocxIndex checks passed.");

static void Require(bool condition, string description)
{
    if (!condition) throw new Exception(description);
}
