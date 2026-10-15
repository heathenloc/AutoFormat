using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace AutoFormat.DocxEditor;

/// <summary>Read-only text positions using the academic editor's exact IDs and text model.</summary>
public static class SelectionTextIndex
{
    public static object Inspect(string path)
    {
        var package = new AcademicPackage(path);
        var w = AcademicPackage.W;
        var objects = package.Objects.Where(o => o.Kind == "paragraph").ToDictionary(o => o.Id);
        var defaultTableStyle = package.Xml.TryGetValue("word/styles.xml", out var styles) ?
            (string?)styles.Descendants(w + "style").FirstOrDefault(s => (string?)s.Attribute(w + "type") == "table" &&
                s.Attribute(w + "default") is { } defaultFlag && AcademicPackage.On(defaultFlag))?.Attribute(w + "styleId") : null;
        var paragraphs = new List<object>();
        var totalCharacters = 0;
        foreach (var pair in package.Xml.Where(p => Regex.IsMatch(p.Key, @"^word/(?:document|header\d*|footer\d*|footnotes|endnotes)\.xml$")))
        {
            var ordinal = 0;
            var fieldDepth = 0;
            foreach (var paragraph in pair.Value.Descendants(w + "p"))
            {
                ordinal++;
                if (paragraph.Ancestors().Any(a => (a.Name == w + "footnote" || a.Name == w + "endnote") &&
                    (string?)a.Attribute(w + "type") is "separator" or "continuationSeparator")) continue;
                var id = AcademicPackage.Id(pair.Key, paragraph);
                var text = AcademicPackage.Text(paragraph);
                totalCharacters += text.Length;
                if (paragraphs.Count >= 50000 || totalCharacters > 2000000)
                    throw new InvalidDataException("Selection text index exceeds configured limits.");
                var fields = paragraph.Descendants(w + "fldChar").ToList();
                var unsafeText = fieldDepth != 0 || fields.Count > 0 || AcademicPackage.Unsafe(paragraph) ||
                    paragraph.Descendants().Any(e => e.Name.Namespace == w &&
                        (new[] { "fldSimple", "instrText", "drawing", "pict", "sym", "tab", "cr", "ptab", "noBreakHyphen", "softHyphen", "footnoteReference", "endnoteReference" }.Contains(e.Name.LocalName) ||
                         e.Name == w + "br" && !(text.Length == 0 && (string?)e.Attribute(w + "type") == "page"))) ||
                    paragraph.Descendants().Any(e => e.Name.NamespaceName == "http://schemas.openxmlformats.org/officeDocument/2006/math") ||
                    // Conditional table formatting is not fully resolved by the
                    // academic run-style model; any possible hidden text blocks it.
                    paragraph.Ancestors(w + "tbl").Any(table => package.StyleChain(
                        (string?)table.Element(w + "tblPr")?.Element(w + "tblStyle")?.Attribute(w + "val") ?? defaultTableStyle)
                        .SelectMany(s => s.Descendants()).Any(e => (e.Name == w + "vanish" || e.Name == w + "webHidden") &&
                            AcademicPackage.On(e.Attribute(w + "val")))) ||
                    paragraph.Descendants(w + "r").Any(run => new[] { "vanish", "webHidden" }.Any(name => {
                        var property = package.PropertySources(run, "rPr").Select(p => p.Element(w + name)).FirstOrDefault(p => p is not null);
                        return property is not null && AcademicPackage.On(property.Attribute(w + "val"));
                    }));
                foreach (var field in fields)
                    fieldDepth += (string?)field.Attribute(w + "fldCharType") switch { "begin" => 1, "end" => -1, _ => 0 };
                objects.TryGetValue(id, out var semantic);
                var note = paragraph.Ancestors().FirstOrDefault(a => a.Name == w + "footnote" || a.Name == w + "endnote");
                var story = "s:" + Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(
                    pair.Key + (note is null ? "" : ":" + (string?)note.Attribute(w + "id")))))[..24].ToLowerInvariant();
                var kind = pair.Key.Contains("header") ? "页眉" : pair.Key.Contains("footer") ? "页脚" :
                    pair.Key.Contains("footnotes") ? "脚注" : pair.Key.Contains("endnotes") ? "尾注" :
                    paragraph.Ancestors(w + "tbl").Any() ? "表格" : "正文";
                paragraphs.Add(new { object_id = id, story_id = story, text,
                    location_label = $"{kind} · 第 {ordinal} 段", editable = semantic is not null && !unsafeText,
                    semantic_role = semantic?.Role ?? "unsupported", ordinal });
            }
        }
        return new { schema_version = "selection-docx-index/1.0", sha256 = package.Sha256, paragraphs };
    }
}
