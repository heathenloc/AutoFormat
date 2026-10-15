using System.Security.Cryptography;
using System.Text.Json;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using AutoFormat.DocxEditor;

var root = Path.GetFullPath(Path.Combine("runtime", "tests", "academic-editor", Guid.NewGuid().ToString("N")));
Directory.CreateDirectory(root);
var input = Path.Combine(root, "v0.docx");
Create(input);
var hash = Hash(input);
var cases = new Dictionary<string, (string Role, object Value, string? Unit)>
{
    ["font.family"] = ("body", "Arial", null), ["font.size"] = ("body", 10.5, "pt"), ["font.bold"] = ("body", true, null), ["font.italic"] = ("body", true, null),
    ["paragraph.alignment"] = ("body", "both", null), ["paragraph.spacing_before"] = ("body", 0.5, "lines"), ["paragraph.spacing_after"] = ("body", 6, "pt"),
    ["paragraph.line_spacing"] = ("body", new { mode = "exact", amount = 18 }, "pt"), ["paragraph.first_line_indent"] = ("body", 2, "characters"),
    ["paragraph.hanging_indent"] = ("body", 0.5, "cm"), ["paragraph.left_indent"] = ("body", 3, "mm"), ["paragraph.right_indent"] = ("body", 2, "characters"),
    ["paragraph.keep_with_next"] = ("body", true, null), ["paragraph.keep_together"] = ("body", true, null), ["paragraph.page_break_before"] = ("body", true, null),
    ["paragraph.snap_to_grid"] = ("body", true, null), ["page.paper_size"] = ("page", "A5", null),
    ["page.dimensions"] = ("page", new { width_cm = 20, height_cm = 28 }, "cm"), ["page.orientation"] = ("page", "landscape", null),
    ["page.margin.all"] = ("page", 2.5, "cm"), ["page.margin.top"] = ("page", 30, "mm"), ["page.margin.bottom"] = ("page", 60, "pt"),
    ["page.margin.left"] = ("page", 2, "cm"), ["page.margin.right"] = ("page", 2, "cm"), ["page.margin.header_distance"] = ("page", 1.2, "cm"),
    ["page.margin.footer_distance"] = ("page", 1.2, "cm"), ["page.margin.gutter"] = ("page", 0.5, "cm"),
    ["section.column_count"] = ("page", 2, null), ["section.text_direction"] = ("page", "vertical", null),
    ["page_number.number_format"] = ("page_number", "lower_roman", null), ["page_number.start"] = ("page_number", 3, null),
    ["toc.max_depth"] = ("toc", 3, null), ["table.border_style"] = ("table", "three_line", null),
    ["caption.position"] = ("table_caption", "below", null), ["document.position"] = ("bibliography", "before_body", null),
};
var checks = 0;
Require(cases.Keys.ToHashSet().SetEquals(AcademicFormatEditor.Capabilities().Select(c => c.PropertyId)), "Every registered property has a positive edit test.");
foreach (var (property, item) in cases)
{
    var rule = Rule("r1", property, item.Role, item.Value, item.Unit);
    var manifest = Manifest(input, "one.docx", [rule]);
    var result = AcademicFormatEditor.Apply(root, manifest);
    Require(result.Status == "ready" && result.Operations.Length > 0, property + ": " + result.Status + ": " + result.Reason + ": " + JsonSerializer.Serialize(result.Rules));
    Require(result.ContentPreserved && result.PackageValidated, "Package and content verified: " + property);
    Require(Hash(input) == hash, "V0 stays byte-identical: " + property);
    if (property == "paragraph.spacing_after")
    {
        using var doc = WordprocessingDocument.Open(Path.Combine(root, "one.docx"), false);
        var p = doc.MainDocumentPart!.Document!.Body!.Elements<Paragraph>().First(p => p.InnerText.StartsWith("中文"));
        Require(p.ParagraphProperties!.SpacingBetweenLines!.After == "120" && p.ParagraphProperties.SpacingBetweenLines.AfterLines is null,
            "Physical paragraph spacing is not masked by a zero line-unit attribute.");
    }
    if (property == "table.border_style")
    {
        using var doc = WordprocessingDocument.Open(Path.Combine(root, "one.docx"), false);
        var rows = doc.MainDocumentPart!.Document!.Descendants<Table>().Single().Elements<TableRow>().ToArray();
        var headerBorders = rows[0].Elements<TableCell>().Single().TableCellProperties!.TableCellBorders!;
        var bodyBorders = rows[1].Elements<TableCell>().Single().TableCellProperties!.TableCellBorders!;
        Require(headerBorders.TopBorder!.Val!.Value == BorderValues.Single && headerBorders.BottomBorder!.Val!.Value == BorderValues.Single &&
            bodyBorders.TopBorder!.Val!.Value == BorderValues.Single && bodyBorders.BottomBorder!.Val!.Value == BorderValues.Single,
            "Three-line table cell edges do not suppress top, middle or bottom borders through nil conflicts.");
    }
    var repeat = AcademicFormatEditor.Apply(root, manifest with { InputFile = "one.docx", OutputFile = "two.docx", BaseDocxSha256 = result.OutputDocxSha256! });
    // after_body and document_end can describe the same physical position, handled as a satisfied constraint.
    Require(repeat.Status == "already_satisfied", "Idempotent " + property + ": " + repeat.Status + ": " + repeat.Reason);
    Require(Hash(Path.Combine(root, "one.docx")) == Hash(Path.Combine(root, "two.docx")), "Idempotency preserves package bytes: " + property);
    if (property is "toc.max_depth" or "page_number.start" or "page_number.number_format")
        Require(repeat.FieldRefreshStatus == "pending_manual_check" && repeat.Operations.All(o => !o.Changed), "Repeated field definition never claims its cache is refreshed.");
    File.Delete(Path.Combine(root, "one.docx")); File.Delete(Path.Combine(root, "two.docx"));
}
var latin = Rule("latin", "font.family", "body", "Times New Roman", null, ["latin", "digits"]);
var chinese = Rule("chinese", "font.family", "body", "黑体", null, ["chinese"]);
var size = Rule("size", "font.size", "body", 14, "pt", ["chinese"]);
var mix = AcademicFormatEditor.Apply(root, Manifest(input, "mix.docx", [latin, chinese, size]));
Require(mix.Status == "ready", "Mixed-script family and size: " + mix.Reason);
using (var doc = WordprocessingDocument.Open(Path.Combine(root, "mix.docx"), false))
{
    var bodyParagraph = doc.MainDocumentPart!.Document!.Body!.Elements<Paragraph>().First(p => p.InnerText.StartsWith("中文"));
    Require(bodyParagraph.InnerText == "中文Ab12中Cd", "Exact mixed-script text preserved.");
    foreach (var run in bodyParagraph.Elements<Run>())
    {
        if (run.InnerText.Any(c => c is >= '\u4e00' and <= '\u9fff'))
            Require(run.RunProperties!.RunFonts!.EastAsia!.Value == "黑体" && run.RunProperties!.FontSize!.Val!.Value == "28", "CJK-only properties applied.");
        else Require(run.RunProperties!.RunFonts!.Ascii!.Value == "Times New Roman" && run.RunProperties!.FontSize is null, "Latin/digits preserve their original inherited size.");
    }
}
foreach (var role in new[] { "footnote", "endnote", "header", "footer", "page_number", "citation", "table_header", "table_body", "toc_heading_1", "heading_1", "heading_9", "abstract", "abstract_heading", "keywords", "bibliography", "bibliography_heading", "acknowledgements", "appendix" })
{
    var result = AcademicFormatEditor.Apply(root, Manifest(input, "role.docx", [Rule("role", "font.size", role, 16, "pt")]));
    Require(result.Status == "ready" && result.Operations.Length > 0, "Role " + role + " edited: " + result.Reason + ": " + JsonSerializer.Serialize(result.Rules));
    File.Delete(Path.Combine(root, "role.docx"));
}
foreach (var item in new (string Property, string Role, object Value, string? Unit)[] {
    ("paragraph.line_spacing", "body", 1.5, "multiple"), ("paragraph.line_spacing", "body", new { mode = "atLeast", amount = 20 }, "pt"),
    ("paragraph.first_line_indent", "body", 0.5, "cm"), ("paragraph.left_indent", "body", 2, "characters"),
    ("paragraph.spacing_after", "body", 0.5, "lines"), ("table.border_style", "table", "all_borders", null),
    ("table.border_style", "table", "none", null), ("page.paper_size", "page", "Letter", null),
    ("page_number.number_format", "page_number", "upper_roman", null), ("document.position", "bibliography", "document_end", null),
    ("font.bold", "heading_1", false, null), ("font.italic", "heading_1", false, null), })
{
    var valueResult = AcademicFormatEditor.Apply(root, Manifest(input, "value.docx", [Rule("value", item.Property, item.Role, item.Value, item.Unit)]));
    Require(valueResult.Status is "ready" or "already_satisfied" && valueResult.Operations.Length > 0, "Value/unit variant: " + item.Property + ": " + valueResult.Reason);
    File.Delete(Path.Combine(root, "value.docx"));
}
var manualInput = Path.Combine(root, "manual.docx"); File.Copy(input, manualInput);
using (var doc = WordprocessingDocument.Open(manualInput, true))
{
    var body = doc.MainDocumentPart!.Document!.Body!;
    var fieldParagraph = body.Elements<Paragraph>().Single(p => p.Descendants<FieldCode>().Any());
    var entry = body.Elements<Paragraph>().Single(p => p.ParagraphProperties?.ParagraphStyleId?.Val?.Value == "TOC1");
    fieldParagraph.Remove();
    entry.RemoveAllChildren(); entry.Append(new ParagraphProperties(new ParagraphStyleId { Val = "TOC1" }), new Run(new Text("第1章 绪论")), new Run(new TabChar()), new Run(new Text("1")));
    entry.InsertAfterSelf(new Paragraph(new ParagraphProperties(new ParagraphStyleId { Val = "TOC1" }), new Run(new Text("第2章 结果")), new Run(new TabChar()), new Run(new Text("2"))));
}
var manualResult = AcademicFormatEditor.Apply(root, Manifest(manualInput, "manual-out.docx", [Rule("manual", "toc.max_depth", "toc", 1, null)]));
Require(manualResult.Status == "ready" && manualResult.FieldRefreshStatus == "pending_manual_check", "Complete manual TOC converted without inventing cache pages: " + manualResult.Reason);
using (var doc = WordprocessingDocument.Open(Path.Combine(root, "manual-out.docx"), false))
    Require(doc.MainDocumentPart!.Document!.Descendants<FieldCode>().Single().Text.Contains("1-1"), "Manual TOC has an updateable typed field.");
var simpleInput = Path.Combine(root, "simple.docx"); File.Copy(input, simpleInput);
using (var doc = WordprocessingDocument.Open(simpleInput, true))
{
    var p = doc.MainDocumentPart!.Document!.Body!.Elements<Paragraph>().Single(p => p.Descendants<FieldCode>().Any());
    p.RemoveAllChildren(); p.Append(new SimpleField(new Run(new Text("目录缓存"))) { Instruction = " TOC \\o \"1-2\" \\h " });
}
var simpleResult = AcademicFormatEditor.Apply(root, Manifest(simpleInput, "simple-out.docx", [Rule("simple", "toc.max_depth", "toc", 3, null)]));
Require(simpleResult.Status == "ready" && simpleResult.FieldRefreshStatus == "pending_manual_check", "Simple TOC field supported: " + simpleResult.Reason);
var hiddenInput = Path.Combine(root, "hidden.docx"); File.Copy(input, hiddenInput);
using (var doc = WordprocessingDocument.Open(hiddenInput, true))
{
    var p = doc.MainDocumentPart!.Document!.Body!.Elements<Paragraph>().First(p => p.InnerText.StartsWith("中文"));
    p.Append(new Run(new RunProperties(new Vanish()), new Text("不可误改")));
}
var hiddenResult = AcademicFormatEditor.Apply(root, Manifest(hiddenInput, "hidden-out.docx", [Rule("hidden", "paragraph.alignment", "body", "center", null)]));
Require(hiddenResult.Status == "ready" && hiddenResult.Rules[0].Status == "ambiguous_target" && hiddenResult.Operations.Length == 1, "Unsafe target withheld while independent safe target runs.");
var sameMargin = AcademicFormatEditor.Apply(root, Manifest(input, "same-margin.docx", [Rule("all", "page.margin.all", "page", 2.5, "cm"), Rule("top", "page.margin.top", "page", 25, "mm")]));
Require(sameMargin.Status == "ready" && sameMargin.Rules.All(r => r.Status == "modified_verified"), "Equivalent units at a shared Word property coexist.");
Require(sameMargin.Operations.Single(o => o.RuleId == "top").After.GetDouble() == 25, "Each alias keeps its own normalized units in its result.");
var citationInput = Path.Combine(root, "citation.docx"); File.Copy(input, citationInput);
using (var doc = WordprocessingDocument.Open(citationInput, true))
{
    var p = doc.MainDocumentPart!.Document!.Body!.Elements<Paragraph>().First(p => p.InnerText.StartsWith("中文"));
    p.RemoveAllChildren(); p.Append(new Run(new Text("正文 [1] 保留外观")));
}
var citationResult = AcademicFormatEditor.Apply(root, Manifest(citationInput, "citation-out.docx", [Rule("citation", "font.size", "citation", 10.5, "pt")]));
Require(citationResult.Status == "ready", "Inline citation safely split: " + citationResult.Reason);
using (var doc = WordprocessingDocument.Open(Path.Combine(root, "citation-out.docx"), false))
{
    var p = doc.MainDocumentPart!.Document!.Body!.Elements<Paragraph>().First(p => p.InnerText.StartsWith("正文 [1]"));
    Require(p.InnerText == "正文 [1] 保留外观", "Inline citation text stays identical.");
    Require(p.Elements<Run>().Where(r => r.InnerText.Any(c => c is '1')).All(r => r.RunProperties?.FontSize?.Val?.Value == "21"), "Citation digits have the requested size.");
    Require(p.Elements<Run>().Where(r => r.InnerText.StartsWith("正文") || r.InnerText.Contains("保留")).All(r => r.RunProperties?.FontSize is null), "Text surrounding an inline citation stays unformatted.");
}
var bodySectionInput = Path.Combine(root, "bodysection.docx"); File.Copy(input, bodySectionInput);
using (var doc = WordprocessingDocument.Open(bodySectionInput, true))
{
    var body = doc.MainDocumentPart!.Document!.Body!;
    foreach (var element in body.Elements().ToArray()) if (element is not SectionProperties && element.InnerText is not ("第1章 绪论" or "中文Ab12中Cd")) element.Remove();
}
var bodySectionResult = AcademicFormatEditor.Apply(root, Manifest(bodySectionInput, "bodysection-out.docx", [Rule("columns", "section.column_count", "body", 2, null)]));
Require(bodySectionResult.Status == "ready" && bodySectionResult.Operations.Length == 1, "Body-specific section property uses a proven body section.");
var mixedSectionResult = AcademicFormatEditor.Apply(root, Manifest(input, "mixedsection-out.docx", [Rule("columns", "section.column_count", "body", 2, null)]));
Require(mixedSectionResult.Status == "already_satisfied" && mixedSectionResult.Rules[0].Status == "ambiguous_target" && mixedSectionResult.Operations.Length == 0, "Body-only columns never expand into front matter sharing the section.");
var geometryResult = AcademicFormatEditor.Apply(root, Manifest(input, "geometry.docx", [Rule("paper", "page.paper_size", "page", "A5", null),
    Rule("dimensions", "page.dimensions", "page", new { width_cm = 20, height_cm = 28 }, "cm"), Rule("safe", "paragraph.alignment", "body", "center", null)]));
Require(geometryResult.Status == "ready" && geometryResult.Rules.Where(r => r.RuleId != "safe").All(r => r.Status == "pending_conflict") &&
    geometryResult.Operations.All(o => o.RuleId == "safe"), "Incompatible paper/dimension constraints block geometry while independent body edits continue.");
var scoped = Rule("scoped", "paragraph.alignment", "body", "right", null);
scoped.Semantics.Scope.Axes.Add("chapter", new FormatAxis(["1"], []));
var scopedResult = AcademicFormatEditor.Apply(root, Manifest(input, "scoped.docx", [scoped]));
Require(scopedResult.Status == "ready" && scopedResult.Operations.Length == 1, "Chapter selector is retained.");
var unsupported = Rule("unknown", "future.property", "body", true, null);
var unknownResult = AcademicFormatEditor.Apply(root, Manifest(input, "unknown.docx", [unsupported, Rule("safe", "paragraph.alignment", "body", "center", null)]));
Require(unknownResult.Status == "ready" && unknownResult.Rules.Single(r => r.RuleId == "unknown").Status == "unsupported", "Unknown properties reported; independent safe rule runs.");
var condition = Rule("conditional", "font.size", "body", 18, "pt") with { Status = "pending_condition", Semantics = Rule("tmp", "font.size", "body", 18, "pt").Semantics with { Condition = JsonSerializer.SerializeToElement(new { original_text = "print", resolution = "known", reason = "not bound" }) } };
var conditionalResult = AcademicFormatEditor.Apply(root, Manifest(input, "condition.docx", [condition]));
Require(conditionalResult.Status == "already_satisfied" && conditionalResult.Operations.Length == 0 && conditionalResult.Rules[0].Status == "pending_condition", "Unbound conditions never execute.");
var collision = AcademicFormatEditor.Apply(root, Manifest(input, "collision.docx", [Rule("a", "paragraph.alignment", "body", "left", null), Rule("b", "paragraph.alignment", "body", "center", null)]));
Require(collision.Operations.Length == 0 && collision.Rules.All(r => r.Status == "pending_conflict"), "Physical collisions cannot overwrite one another.");
var futureScope = Rule("futureScope", "font.size", "body", 18, "pt"); futureScope.Semantics.Scope.Axes.Add("future_axis", new FormatAxis(["x"], []));
var scopeResult = AcademicFormatEditor.Apply(root, Manifest(input, "scope.docx", [futureScope]));
Require(scopeResult.Operations.Length == 0 && scopeResult.Rules[0].Status == "unsupported", "Unknown axes are retained and rejected.");
var stale = AcademicFormatEditor.Apply(root, Manifest(input, "stale.docx", [scoped]) with { BaseDocxSha256 = new string('0', 64) });
Require(stale.Status == "stale_base_version" && !File.Exists(Path.Combine(root, "stale.docx")), "Stale parent produces no output.");
var exists = AcademicFormatEditor.Apply(root, Manifest(input, "mix.docx", [scoped]));
Require(exists.Status == "output_exists", "Historical output cannot be overwritten.");
var spacedInput = Path.Combine(root, "inherited-cell-spacing.docx"); File.Copy(input, spacedInput);
using (var doc = WordprocessingDocument.Open(spacedInput, true))
{
    doc.MainDocumentPart!.StyleDefinitionsPart!.Styles!.Append(new Style(new StyleName { Val = "Spaced table" },
        new StyleTableProperties(new TableCellSpacing { Width = "120", Type = TableWidthUnitValues.Dxa }))
        { StyleId = "SpacedTable", Type = StyleValues.Table });
    doc.MainDocumentPart.Document!.Descendants<Table>().Single().TableProperties!.PrependChild(new TableStyle { Val = "SpacedTable" });
}
var spacedResult = AcademicFormatEditor.Apply(root, Manifest(spacedInput, "inherited-cell-spacing-out.docx",
    [Rule("border", "table.border_style", "table", "three_line", null), Rule("body", "paragraph.alignment", "body", "center", null)]));
Require(spacedResult.Status == "ready" && spacedResult.Rules.Single(r => r.RuleId == "border").Status == "ambiguous_target" && spacedResult.Operations.All(o => o.RuleId == "body"),
    "Inherited cell spacing cannot silently produce a discontinuous three-line table; independent paragraph edits still run.");
foreach (var declared in new PageOrientationValues?[] { null, PageOrientationValues.Landscape })
{
    var orientationInput = Path.Combine(root, declared is null ? "missing-orientation.docx" : "inconsistent-orientation.docx");
    File.Copy(input, orientationInput);
    using (var doc = WordprocessingDocument.Open(orientationInput, true))
    {
        var page = doc.MainDocumentPart!.Document!.Body!.Elements<SectionProperties>().Single().GetFirstChild<PageSize>()!;
        page.Width = declared is null ? 16838U : 11906U;
        page.Height = declared is null ? 11906U : 16838U;
        page.Orient = declared;
    }
    var orientationOutput = Path.GetFileNameWithoutExtension(orientationInput) + "-out.docx";
    var orientationResult = AcademicFormatEditor.Apply(root, Manifest(orientationInput, orientationOutput,
        [Rule("orientation", "page.orientation", "page", "landscape", null)]));
    Require(orientationResult.Status == "ready", "Inconsistent or absent page orientation is reconciled with physical dimensions: " + orientationResult.Reason);
    using var edited = WordprocessingDocument.Open(Path.Combine(root, orientationOutput), false);
    var actual = edited.MainDocumentPart!.Document!.Body!.Elements<SectionProperties>().Single().GetFirstChild<PageSize>()!;
    Require(actual.Width!.Value == 16838U && actual.Height!.Value == 11906U && actual.Orient!.Value == PageOrientationValues.Landscape,
        "Landscape is physically landscape; existing landscape dimensions are never swapped to portrait.");
}
Console.WriteLine($"Academic editor checks passed: {checks}; all {cases.Count} properties; artifacts: {root}");

void Require(bool valid, string message) { checks++; if (!valid) throw new Exception(message); }
string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
AcademicEditManifest Manifest(string path, string output, EffectiveFormatRule[] rules) => new("academic-edit-manifest/1.0", "version-0", Hash(path), Path.GetFileName(path), output, new string('a', 64), rules,
    rules.Select(r => new FormatFragment("fragment-" + r.RuleId, r.RuleId, r.Semantics.Scope, r.Semantics.Condition is null ? "verified" : "pending_condition", [], "source verified")).ToArray());
EffectiveFormatRule Rule(string id, string prop, string role, object value, string? unit, string[]? chars = null)
{
    var axes = new Dictionary<string, FormatAxis> { ["roles"] = new([role], []), ["characters"] = new(chars ?? ["chinese", "latin", "digits", "complex_script", "other"], []) };
    if (prop.StartsWith("page.margin.") && prop.Split('.').Last() is "all" or "top" or "bottom" or "left" or "right") axes["property_component"] = new(prop.EndsWith(".all") ? ["top", "bottom", "left", "right"] : [prop.Split('.').Last()], []);
    return new("academic-effective-rule/1.0", id, "brief_explicit", [id], [JsonSerializer.SerializeToElement(new { evidence_id = "e1" })], [], [],
        new(prop.StartsWith("page.") ? "section" : "paragraph", role, "semantic_role_scope"), prop,
        new(value.ToString()!, JsonSerializer.SerializeToElement(value), unit, "test/1.0"), "all",
        new("academic-rule-semantics/1.0", new(axes), new("eq", null, null), null), "typed", "verified", "literal proof");
}
void Create(string path)
{
    using var doc = WordprocessingDocument.Create(path, WordprocessingDocumentType.Document);
    var main = doc.AddMainDocumentPart();
    var styles = main.AddNewPart<StyleDefinitionsPart>();
    styles.Styles = new Styles(new DocDefaults(new RunPropertiesDefault(new RunPropertiesBaseStyle(new FontSize { Val = "24" }))),
        new Style(new StyleName { Val = "Heading 1" }) { StyleId = "Heading1", Type = StyleValues.Paragraph },
        new Style(new StyleName { Val = "Heading 9" }) { StyleId = "Heading9", Type = StyleValues.Paragraph },
        new Style(new StyleName { Val = "Body Text" }) { StyleId = "BodyText", Type = StyleValues.Paragraph },
        new Style(new StyleName { Val = "Quote" }) { StyleId = "Quote", Type = StyleValues.Paragraph },
        new Style(new StyleName { Val = "TOC 1" }) { StyleId = "TOC1", Type = StyleValues.Paragraph });
    var header = main.AddNewPart<HeaderPart>(); header.Header = new Header(P("页眉Ab"));
    var footer = main.AddNewPart<FooterPart>(); footer.Footer = new Footer(new Paragraph(new Run(new Text("页脚Ab第")),
        new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }), new Run(new FieldCode(" PAGE ")),
        new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }), new Run(new Text("1")),
        new Run(new FieldChar { FieldCharType = FieldCharValues.End }), new Run(new Text("页"))));
    var footnotes = main.AddNewPart<FootnotesPart>(); footnotes.Footnotes = new Footnotes(new Footnote(P("脚注Ab")) { Id = 1 });
    var endnotes = main.AddNewPart<EndnotesPart>(); endnotes.Endnotes = new Endnotes(new Endnote(P("尾注Ab")) { Id = 1 });
    var table = new Table(new TableProperties(), new TableGrid(new GridColumn { Width = "3000" }),
        new TableRow(new TableRowProperties(new TableHeader()), new TableCell(new Paragraph(new Run(new Text("表头Ab"))))),
        new TableRow(new TableCell(new Paragraph(new Run(new Text("表内Ab"))))));
    var toc = new Paragraph(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }), new Run(new FieldCode(" TOC \\o \"1-2\" \\h ")),
        new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }), new Run(new Text("目录缓存")), new Run(new FieldChar { FieldCharType = FieldCharValues.End }));
    main.Document = new Document(new Body(P("摘要"), P("摘要Ab"), P("关键词：test"), P("目录"), toc, P("一级目录Ab", "TOC1"),
        P("第1章 绪论", "Heading1"), P("中文Ab12中Cd"), P("九级标题Ab", "Heading9"), P("引用Ab", "Quote"),
        P("表1 实验结果"), table, P("第2章 结果", "Heading1"), P("第二章正文Ab"), P("参考文献"), P("[1] 条目Ab"),
        P("致谢"), P("感谢Ab"), P("附录"), P("附录Ab"),
        new SectionProperties(new HeaderReference { Id = main.GetIdOfPart(header), Type = HeaderFooterValues.Default },
            new FooterReference { Id = main.GetIdOfPart(footer), Type = HeaderFooterValues.Default },
            new PageSize { Width = 11906, Height = 16838 }, new PageMargin { Top = 1440, Bottom = 1440, Left = 1440, Right = 1440, Header = 720, Footer = 720, Gutter = 0 })));
    Paragraph P(string text, string? style = null)
    {
        var p = new Paragraph();
        if (style is not null) p.Append(new ParagraphProperties(new ParagraphStyleId { Val = style }));
        p.Append(new Run(new RunProperties(new RunFonts { EastAsia = "宋体", Ascii = "Calibri", HighAnsi = "Calibri" }), new Text(text)));
        return p;
    }
}
