using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

namespace AutoFormat.DocxEditor;

internal sealed class AcademicPackage
{
    internal static readonly XNamespace W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    internal static readonly XNamespace R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    internal readonly Dictionary<string, byte[]> Bytes = new(StringComparer.Ordinal);
    internal readonly Dictionary<string, XDocument> Xml = new(StringComparer.Ordinal);
    internal readonly List<AcademicObject> Objects = [];
    private readonly Dictionary<string, XElement> styles = new(StringComparer.Ordinal);
    internal XElement? Defaults;
    internal HashSet<XElement> NewFields = [];
    internal string Sha256 { get; }

    internal AcademicPackage(string path)
    {
        using var file = File.OpenRead(path);
        if (file.Length is 0 or > 104857600) throw new InvalidDataException("DOCX size exceeds engine limit.");
        Sha256 = Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant();
        file.Position = 0;
        using var zip = new ZipArchive(file, ZipArchiveMode.Read);
        if (zip.Entries.Count > 4096 || zip.Entries.Sum(e => e.Length) > 268435456)
            throw new InvalidDataException("DOCX expanded size exceeds engine limit.");
        foreach (var entry in zip.Entries)
        {
            if (entry.Length > 67108864 || Bytes.ContainsKey(entry.FullName) || entry.FullName.Contains("..") || entry.FullName.Contains('\\'))
                throw new InvalidDataException("Unsafe or duplicate DOCX package part.");
            using var stream = entry.Open();
            using var buffer = new MemoryStream();
            stream.CopyTo(buffer);
            Bytes.Add(entry.FullName, buffer.ToArray());
            if (entry.FullName.EndsWith(".xml", StringComparison.OrdinalIgnoreCase) || entry.FullName.EndsWith(".rels", StringComparison.OrdinalIgnoreCase))
            {
                using var data = new MemoryStream(buffer.ToArray());
                using var reader = XmlReader.Create(data, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 67108864 });
                Xml.Add(entry.FullName, XDocument.Load(reader, LoadOptions.PreserveWhitespace));
            }
        }
        if (!Xml.ContainsKey("word/document.xml") || !Xml.ContainsKey("[Content_Types].xml"))
            throw new InvalidDataException("DOCX package lacks required parts.");
        if (Bytes.Keys.Any(n => n.Contains("vbaProject", StringComparison.OrdinalIgnoreCase) || n.Contains("/embeddings/", StringComparison.OrdinalIgnoreCase)) ||
            Xml.Values.SelectMany(d => d.Descendants()).Any(e => e.Name == W + "documentProtection" || e.Name == W + "altChunk") ||
            Xml["[Content_Types].xml"].ToString().Contains("macroEnabled", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Protected, macro or embedded-content DOCX is unsupported.");
        foreach (var relation in Xml.Where(p => p.Key.EndsWith(".rels", StringComparison.Ordinal)).SelectMany(p => p.Value.Descendants()))
            if ((string?)relation.Attribute("TargetMode") == "External" && !(((string?)relation.Attribute("Type"))?.EndsWith("/hyperlink", StringComparison.Ordinal) ?? false))
                throw new InvalidDataException("External non-hyperlink relationship is unsupported.");
        if (Xml.TryGetValue("word/styles.xml", out var styleDoc))
        {
            foreach (var style in styleDoc.Descendants(W + "style"))
            {
                var id = (string?)style.Attribute(W + "styleId");
                if (id is not null && !styles.TryAdd(id, style)) throw new InvalidDataException("Repeated style identifier.");
            }
            Defaults = styleDoc.Root?.Element(W + "docDefaults");
        }
        Index();
    }

    internal static string PathOf(XElement node) => string.Join('/', node.AncestorsAndSelf().Reverse().Select(e => e.Name.LocalName + "[" + (e.ElementsBeforeSelf(e.Name).Count() + 1) + "]"));
    internal static string Id(string part, XElement node) => "o:" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(part + ":" + PathOf(node))))[..24].ToLowerInvariant();
    internal static string Text(XElement node) => string.Concat(node.Descendants(W + "t").Where(e => !e.Ancestors().Any(a => a.Name == W + "del" || a.Name == W + "moveFrom")).Select(e => e.Value));

    internal IEnumerable<XElement> StyleChain(string? id)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        while (id is not null && styles.TryGetValue(id, out var style))
        {
            if (!seen.Add(id)) throw new FormatBlocked("ambiguous_target", "Cyclic style inheritance.");
            yield return style;
            id = (string?)style.Element(W + "basedOn")?.Attribute(W + "val");
        }
    }

    internal IEnumerable<XElement> PropertySources(XElement node, string kind)
    {
        var paragraph = node.Name == W + "p" ? node : node.Ancestors(W + "p").FirstOrDefault();
        var direct = node.Element(W + kind);
        if (direct is not null) yield return direct;
        if (kind == "rPr")
            foreach (var style in StyleChain((string?)direct?.Element(W + "rStyle")?.Attribute(W + "val")))
                if (style.Element(W + kind) is { } value) yield return value;
        var styleId = (string?)paragraph?.Element(W + "pPr")?.Element(W + "pStyle")?.Attribute(W + "val") ??
            styles.Values.FirstOrDefault(s => (string?)s.Attribute(W + "type") == "paragraph" && On(s.Attribute(W + "default")))?.Attribute(W + "styleId")?.Value;
        foreach (var style in StyleChain(styleId))
            if (style.Element(W + kind) is { } value) yield return value;
        if (Defaults?.Element(W + (kind + "Default"))?.Element(W + kind) is { } defaults) yield return defaults;
    }

    internal string? Effective(XElement node, string kind, string element, string attribute = "val") =>
        PropertySources(node, kind).Select(p => (string?)p.Element(W + element)?.Attribute(W + attribute)).FirstOrDefault(v => v is not null);
    internal bool NeedsDirectProof(XElement node, string property, string? script)
    {
        var paragraph = node.Name == W + "p" ? node : node.Ancestors(W + "p").FirstOrDefault();
        var table = paragraph?.Ancestors(W + "tbl").FirstOrDefault();
        var list = paragraph is not null && PropertySources(paragraph, "pPr").Any(p => p.Element(W + "numPr") is not null);
        if (table?.Element(W + "tblPr")?.Element(W + "tblStyle") is null && !list) return false;
        var name = property switch {
            "font.family" => "rFonts", "font.size" => script == "complex_script" ? "szCs" : "sz", "font.bold" => script == "complex_script" ? "bCs" : "b", "font.italic" => script == "complex_script" ? "iCs" : "i",
            "paragraph.alignment" => "jc", "paragraph.keep_with_next" => "keepNext", "paragraph.keep_together" => "keepLines",
            "paragraph.page_break_before" => "pageBreakBefore", "paragraph.snap_to_grid" => "snapToGrid",
            _ => property.Contains("indent", StringComparison.Ordinal) ? "ind" : "spacing",
        };
        var direct = node.Element(W + (property.StartsWith("font.", StringComparison.Ordinal) ? "rPr" : "pPr"))?.Element(W + name);
        if (direct is null) return true;
        if (property == "font.family")
        {
            var slots = script == "chinese" ? new[] { "eastAsia" } : script == "complex_script" ? ["cs"] : new[] { "ascii", "hAnsi" };
            return slots.Any(slot => direct.Attribute(W + slot) is null && direct.Attribute(W + (slot == "cs" ? "cstheme" : slot + "Theme")) is null);
        }
        return false;
    }
    internal static bool On(XAttribute? value) => value is null || value.Value is not ("0" or "false" or "off");
    internal bool EffectiveOn(XElement node, string element)
    {
        var direct = node.Element(W + "rPr")?.Element(W + element);
        if (direct is not null) return On(direct.Attribute(W + "val"));
        // Style bold/italic are toggle properties, unlike direct formatting.
        var sources = PropertySources(node, "rPr").ToList();
        var result = false;
        foreach (var source in sources.AsEnumerable().Reverse())
            if (source.Element(W + element) is { } item && On(item.Attribute(W + "val"))) result = !result;
        return result;
    }

    internal string? Font(XElement run, string script)
    {
        var runes = Text(run).EnumerateRunes().Where(r => Script(r) == script).ToList();
        if (script is "latin" or "other" && runes.Any(r => r.Value > 127))
        {
            var high = FontSlot("hAnsi");
            return runes.Any(r => r.Value <= 127) && FontSlot("ascii") != high ? null : high;
        }
        return FontSlot(script == "chinese" ? "eastAsia" : script == "complex_script" ? "cs" : "ascii");
        string? FontSlot(string slot)
        {
        foreach (var source in PropertySources(run, "rPr"))
        {
            var fonts = source.Element(W + "rFonts");
            var theme = (string?)fonts?.Attribute(W + (slot == "cs" ? "cstheme" : slot + "Theme"));
            if (theme is not null)
            {
                if (!Xml.TryGetValue("word/theme/theme1.xml", out var themeDoc)) return null;
                XNamespace a = "http://schemas.openxmlformats.org/drawingml/2006/main";
                var family = theme.StartsWith("major", StringComparison.Ordinal) ? "majorFont" : "minorFont";
                var group = themeDoc.Descendants(a + family).FirstOrDefault();
                var face = (string?)group?.Element(a + (script == "chinese" ? "ea" : script == "complex_script" ? "cs" : "latin"))?.Attribute("typeface");
                if (!string.IsNullOrWhiteSpace(face)) return face;
                if (script == "chinese")
                {
                    var scriptTag = runes.Any(r => r.Value is >= 0x3040 and <= 0x30FF) ? "Jpan" : runes.Any(r => r.Value is >= 0xAC00 and <= 0xD7AF) ? "Hang" : "Hans";
                    return (string?)group?.Elements(a + "font").FirstOrDefault(f => (string?)f.Attribute("script") == scriptTag)?.Attribute("typeface");
                }
                return null;
            }
            if ((string?)fonts?.Attribute(W + slot) is { } literal) return literal;
        }
        return null;
        }
    }

    internal static string Script(Rune value) => value.Value switch
    {
        >= 0x2E80 and <= 0xA4CF or >= 0xAC00 and <= 0xD7AF or >= 0xF900 and <= 0xFAFF or >= 0xFF00 and <= 0xFFEF or >= 0x20000 and <= 0x323AF => "chinese",
        >= 0x30 and <= 0x39 => "digits",
        >= 0x41 and <= 0x5A or >= 0x61 and <= 0x7A or >= 0xC0 and <= 0x24F or >= 0x1E00 and <= 0x1EFF => "latin",
        >= 0x590 and <= 0x1CFF or >= 0xFB1D and <= 0xFDFF or >= 0xFE70 and <= 0xFEFF => "complex_script",
        _ => "other",
    };

    internal static bool Unsafe(XElement node) => node.AncestorsAndSelf().Concat(node.Descendants()).Any(e =>
        e.Name.Namespace == W && (new[] { "ins", "del", "moveFrom", "moveTo", "txbxContent", "vanish", "webHidden", "customXml", "pPrChange", "rPrChange" }.Contains(e.Name.LocalName) ||
        e.Name.LocalName == "sdt" && (e.Element(W + "sdtPr")?.Element(W + "lock") is not null || e.Element(W + "sdtPr")?.Element(W + "dataBinding") is not null ||
            (string?)e.Element(W + "sdtPr")?.Element(W + "docPartObj")?.Element(W + "docPartGallery")?.Attribute(W + "val") is not ("Table of Contents" or "目录"))));

    private void Index()
    {
        var main = Xml["word/document.xml"].Root?.Element(W + "body") ?? throw new InvalidDataException("DOCX has no body.");
        var mainParagraphs = main.Descendants(W + "p").Where(p => !p.Ancestors(W + "txbxContent").Any()).ToList();
        var section = 1;
        var chapter = (string?)null;
        var region = (string?)null;
        var zone = (string?)null;
        var tableOrdinal = 0;
        var tableNumbers = main.Descendants(W + "tbl").ToDictionary(t => t, t => ++tableOrdinal);
        foreach (var p in mainParagraphs)
        {
            var style = (string?)p.Element(W + "pPr")?.Element(W + "pStyle")?.Attribute(W + "val");
            var chain = StyleChain(style).ToList();
            var names = chain.Select(s => ((string?)s.Attribute(W + "styleId") + " " + (string?)s.Element(W + "name")?.Attribute(W + "val"))).Prepend(style ?? "").ToArray();
            var text = Text(p).Trim();
            var role = Role(p, text, names);
            if (role == "heading_1")
            {
                region = "body"; zone = "body";
                var number = Regex.Match(text, @"^(?:第([零〇一二三四五六七八九十百千\d]+)章|([1-9]\d*)[.、\s])");
                chapter = number.Success ? ChineseNumber(number.Groups[1].Success ? number.Groups[1].Value : number.Groups[2].Value) : null;
            }
            var sectionRole = role switch { "abstract_heading" => "abstract", "toc_heading" => "toc", "bibliography_heading" => "bibliography", "acknowledgements_heading" => "acknowledgements", "appendix_heading" => "appendix", _ => null };
            if (sectionRole is not null)
            {
                region = sectionRole; chapter = null;
                zone = region is "abstract" or "toc" ? "front_matter" : "body";
            }
            if (role == "body" && region is not (null or "body")) role = region;
            if (role == "unclassified" && region is not null && text.Length > 0 && !p.Descendants(W + "drawing").Any() && !p.Descendants(W + "fldChar").Any()) role = region;
            var table = p.Ancestors(W + "tbl").FirstOrDefault();
            var language = role == "abstract_heading" && text.Equals("Abstract", StringComparison.OrdinalIgnoreCase) ? "english" :
                role == "abstract_heading" ? "chinese" : Language(text);
            Objects.Add(new AcademicObject(Id("word/document.xml", p), "word/document.xml", p, role, region, zone, chapter,
                table is not null ? tableNumbers[table].ToString() : null, language, section, Unsafe(p), "paragraph"));
            if (p.Element(W + "pPr")?.Element(W + "sectPr") is not null) section++;
        }
        var sections = main.Descendants(W + "sectPr").Where(s => !s.Ancestors(W + "sectPrChange").Any()).ToList();
        for (var i = 0; i < sections.Count; i++)
        {
            var members = Objects.Where(o => o.Section == i + 1 && o.Part == "word/document.xml").ToList();
            var regions = members.Select(o => o.Region).Distinct().ToList();
            var zones = members.Select(o => o.Zone).Distinct().ToList();
            var chapters = members.Select(o => o.Chapter).Distinct().ToList();
            Objects.Add(new AcademicObject(Id("word/document.xml", sections[i]), "word/document.xml", sections[i], "page", regions.Count == 1 ? regions[0] : null,
                zones.Count == 1 ? zones[0] : null, chapters.Count == 1 ? chapters[0] : null, null, null, i + 1, false, "section"));
        }
        foreach (var (table, ordinal) in tableNumbers)
        {
            var member = Objects.FirstOrDefault(o => o.Node.Ancestors(W + "tbl").Contains(table));
            Objects.Add(new AcademicObject(Id("word/document.xml", table), "word/document.xml", table, "table", member?.Region, member?.Zone,
                member?.Chapter, ordinal.ToString(), null, member?.Section ?? 1, Unsafe(table), "table"));
        }
        foreach (var pair in Xml.Where(p => Regex.IsMatch(p.Key, @"^word/(?:header\d*|footer\d*|footnotes|endnotes)\.xml$")))
        {
            var role = pair.Key.Contains("footnotes") ? "footnote" : pair.Key.Contains("endnotes") ? "endnote" : pair.Key.Contains("header") ? "header" : "footer";
            foreach (var p in pair.Value.Descendants(W + "p"))
            {
                if (p.Ancestors().Any(a => (a.Name == W + "footnote" || a.Name == W + "endnote") && (string?)a.Attribute(W + "type") is "separator" or "continuationSeparator")) continue;
                Objects.Add(new AcademicObject(Id(pair.Key, p), pair.Key, p, role, null, null, null, null, Language(Text(p)), 0, Unsafe(p), "paragraph"));
            }
        }
    }

    private string Role(XElement p, string text, string[] names)
    {
        if (p.Ancestors(W + "tbl").FirstOrDefault() is not null)
        {
            var row = p.Ancestors(W + "tr").FirstOrDefault();
            if (row?.Element(W + "trPr")?.Element(W + "tblHeader") is { } header && On(header.Attribute(W + "val"))) return "table_header";
            // An unmarked first row is a possible header; do not label it body text.
            return row?.ElementsBeforeSelf(W + "tr").Any() == true ? "table_body" : "table_cell";
        }
        foreach (var name in names)
        {
            var toc = Regex.Match(name, @"(?:^|\s)(?:TOC|目录)\s*([1-9])(?:$|\s)", RegexOptions.IgnoreCase);
            if (toc.Success) return "toc_heading_" + toc.Groups[1].Value;
        }
        var normalized = Regex.Replace(text, @"\s+", "");
        if (normalized is "摘要" or "中文摘要" or "英文摘要" || normalized.Equals("Abstract", StringComparison.OrdinalIgnoreCase)) return "abstract_heading";
        if (normalized is "目录" || normalized.Equals("Contents", StringComparison.OrdinalIgnoreCase) || normalized.Equals("TableofContents", StringComparison.OrdinalIgnoreCase)) return "toc_heading";
        if (normalized is "参考文献" || normalized.Equals("References", StringComparison.OrdinalIgnoreCase) || normalized.Equals("Bibliography", StringComparison.OrdinalIgnoreCase)) return "bibliography_heading";
        if (normalized is "致谢" || normalized.Equals("Acknowledgements", StringComparison.OrdinalIgnoreCase)) return "acknowledgements_heading";
        if (Regex.IsMatch(normalized, @"^(?:附录|Appendix)(?:[A-Z一二三\d])?$", RegexOptions.IgnoreCase)) return "appendix_heading";
        if (Regex.IsMatch(text, @"^(?:关键词|Key\s*words?)\s*[:：]", RegexOptions.IgnoreCase)) return "keywords";
        if (Regex.IsMatch(text, @"^(?:表|Table)\s*\d+(?:[.\-]\d+)*\s+\S", RegexOptions.IgnoreCase)) return "table_caption";
        if (Regex.IsMatch(text, @"^(?:图|Figure)\s*\d+(?:[.\-]\d+)*\s+\S", RegexOptions.IgnoreCase)) return "figure_caption";
        foreach (var name in names)
        {
            var match = Regex.Match(name, @"(?:^|\s)(?:Heading|标题)\s*([1-9])(?:$|\s)", RegexOptions.IgnoreCase);
            if (match.Success) return "heading_" + match.Groups[1].Value;
            if (Regex.IsMatch(name, @"(?:^|\s)(?:Quote|IntenseQuote|引用)(?:$|\s)", RegexOptions.IgnoreCase)) return "citation";
            if (Regex.IsMatch(name, @"(?:^|\s)(?:BodyText|Body Text|正文)(?:$|\s)", RegexOptions.IgnoreCase)) return "body";
        }
        var outline = Effective(p, "pPr", "outlineLvl");
        if (int.TryParse(outline, out var level) && level is >= 0 and <= 8) return "heading_" + (level + 1);
        if (Regex.IsMatch(text, @"^第[零〇一二三四五六七八九十百千\d]+章\s+\S") && text.Length <= 80 && !p.Descendants(W + "tab").Any()) return "heading_1";
        return "unclassified";
    }

    private static string? Language(string text)
    {
        var letters = text.EnumerateRunes().Where(Rune.IsLetter).ToList();
        if (letters.Count == 0) return null;
        if (letters.Any(r => Script(r) == "chinese")) return "chinese";
        return letters.All(r => Script(r) == "latin") ? "english" : null;
    }
    private static string? ChineseNumber(string text)
    {
        if (int.TryParse(text, out var number)) return number.ToString();
        var total = 0; var digit = 0;
        foreach (var character in text)
        {
            var index = "零一二三四五六七八九".IndexOf(character);
            if (index >= 0) digit = index;
            else if (character == '〇') digit = 0;
            else if (character is '十' or '百' or '千') { total += (digit == 0 ? 1 : digit) * (character == '十' ? 10 : character == '百' ? 100 : 1000); digit = 0; }
            else return null;
        }
        return total + digit > 0 ? (total + digit).ToString() : null;
    }

    internal void Save(string path)
    {
        using var zip = ZipFile.Open(path, ZipArchiveMode.Create);
        foreach (var (name, bytes) in Bytes)
        {
            using var stream = zip.CreateEntry(name, CompressionLevel.Optimal).Open();
            if (Xml.TryGetValue(name, out var xml) && !XNode.DeepEquals(xml, Parse(bytes)))
            {
                using var writer = XmlWriter.Create(stream, new XmlWriterSettings { Encoding = new UTF8Encoding(false), Indent = false, CloseOutput = false });
                xml.Save(writer);
            }
            else stream.Write(bytes);
        }
    }
    private static XDocument Parse(byte[] bytes)
    {
        using var input = new MemoryStream(bytes);
        using var reader = XmlReader.Create(input, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
        return XDocument.Load(reader, LoadOptions.PreserveWhitespace);
    }

    internal static void Validate(string path)
    {
        using var document = WordprocessingDocument.Open(path, false);
        if (new OpenXmlValidator(DocumentFormat.OpenXml.FileFormatVersions.Microsoft365).Validate(document).Any())
            throw new InvalidDataException("DOCX failed Open XML validation.");
    }

    internal Dictionary<string, string[]> ProtectedContent() => Xml.Where(p => p.Key.StartsWith("word/", StringComparison.Ordinal))
        .ToDictionary(p => p.Key, p => p.Value.Descendants().Where(e => e.Name == W + "p").Select(p =>
            string.Concat(p.Descendants().Where(e => e.Name == W + "t" || e.Name == W + "tab" || e.Name == W + "br" || e.Name == W + "cr" || e.Name == W + "footnoteReference" || e.Name == W + "endnoteReference")
                .Select(e => e.Name.LocalName == "t" ? e.Value : e.Name.LocalName + ":" + string.Join(",", e.Attributes().Select(a => a.ToString()))))).ToArray(), StringComparer.Ordinal);
}

internal sealed record AcademicObject(string Id, string Part, XElement Node, string Role, string? Region, string? Zone,
    string? Chapter, string? Ordinal, string? Language, int Section, bool Unsafe, string Kind);
