using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using System.Xml.Linq;

namespace EasyFormat.DocxIndex;

public sealed record IndexedParagraph(
    string ObjectId, string XmlPath, string? StyleId, string Text, bool RequiresManualTargeting,
    string RoleCandidate, string RoleEvidence, string? DirectAlignment);

public sealed record DocumentIndex(string Sha256, IReadOnlyList<IndexedParagraph> Paragraphs);

/// <summary>
/// Read-only proof of concept for version-local DOCX text anchors. The editing engine will
/// use Open XML SDK; this reader deliberately has no write path to a user document.
/// </summary>
public static class DocxTextIndex
{
    private const long MaxDocxBytes = 100L * 1024 * 1024;
    private const long MaxDocumentXmlBytes = 64L * 1024 * 1024;
    private static readonly XNamespace W =
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

    public static DocumentIndex Build(string path)
    {
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length is 0 or > MaxDocxBytes)
        {
            throw new InvalidDataException("DOCX missing, empty, or larger than prototype limit.");
        }

        var hash = Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant();
        file.Position = 0;

        using var archive = new ZipArchive(file, ZipArchiveMode.Read, leaveOpen: true);
        var entry = archive.GetEntry("word/document.xml")
            ?? throw new InvalidDataException("DOCX has no word/document.xml.");
        if (entry.Length is 0 or > MaxDocumentXmlBytes)
        {
            throw new InvalidDataException("DOCX main document XML exceeds prototype limit.");
        }

        using var content = entry.Open();
        using var reader = XmlReader.Create(content, new XmlReaderSettings
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = MaxDocumentXmlBytes,
        });
        var xml = XDocument.Load(reader);
        var body = xml.Root?.Element(W + "body")
            ?? throw new InvalidDataException("DOCX has no main document body.");

        var paragraphs = new List<IndexedParagraph>();
        foreach (var paragraph in body.Descendants(W + "p"))
        {
            // Nested text boxes have their own paragraph; avoid counting their text twice.
            var text = ReadVisibleText(paragraph);
            var style = (string?)paragraph.Element(W + "pPr")?.Element(W + "pStyle")?.Attribute(W + "val");
            paragraphs.Add(new IndexedParagraph(
                $"p:{paragraphs.Count + 1:D6}",
                GetPath(paragraph, body),
                style,
                text,
                RequiresManualTargeting(paragraph),
                RoleCandidate(paragraph, style, text),
                RoleEvidence(paragraph, style, text),
                (string?)paragraph.Element(W + "pPr")?.Element(W + "jc")?.Attribute(W + "val")));
        }

        return new DocumentIndex(hash, paragraphs);
    }

    private static string ReadVisibleText(XElement paragraph)
    {
        var result = new StringBuilder();
        foreach (var node in paragraph.Descendants())
        {
            if (node.Ancestors(W + "p").FirstOrDefault() != paragraph ||
                node.Ancestors().Any(a => a.Name == W + "del" || a.Name == W + "moveFrom"))
            {
                continue;
            }

            if (node.Name == W + "t") result.Append(node.Value);
            else if (node.Name == W + "tab") result.Append('\t');
            else if (node.Name == W + "br" || node.Name == W + "cr") result.Append('\n');
        }

        return result.ToString();
    }

    private static bool RequiresManualTargeting(XElement paragraph)
    {
        if (paragraph.Ancestors().Any(node => node.Name == W + "txbxContent")) return true;

        return paragraph.Descendants().Any(node =>
            node.Name == W + "del" || node.Name == W + "moveFrom" ||
            node.Name == W + "ins" || node.Name == W + "moveTo" ||
            node.Name == W + "fldChar" || node.Name == W + "instrText" ||
            node.Name == W + "drawing" || node.Name == W + "pict" ||
            node.Name == W + "object" || node.Name == W + "vanish" ||
            node.Name == W + "webHidden");
    }

    private static string RoleCandidate(XElement paragraph, string? style, string text)
    {
        if (paragraph.Ancestors(W + "tbl").Any()) return "table_cell";
        if (IsHeadingStyle(style)) return "heading_candidate";
        if (text.Length == 0 || RequiresManualTargeting(paragraph) ||
            paragraph.Element(W + "pPr")?.Element(W + "numPr") is not null)
            return "unclassified";
        // Normal is a weak candidate, not proof of the academic body role.
        return style == "Normal" ? "body_candidate" : "unclassified";
    }

    private static string RoleEvidence(XElement paragraph, string? style, string text)
    {
        if (paragraph.Ancestors(W + "tbl").Any()) return "inside_table";
        if (IsHeadingStyle(style)) return "built_in_heading_style";
        if (text.Length == 0) return "empty_paragraph";
        if (RequiresManualTargeting(paragraph)) return "complex_or_hidden_content";
        if (paragraph.Element(W + "pPr")?.Element(W + "numPr") is not null)
            return "numbering_properties";
        return style == "Normal" ? "normal_style_only" : "no_reliable_body_role";
    }

    private static bool IsHeadingStyle(string? style) =>
        style is { Length: 8 } && style.StartsWith("Heading", StringComparison.Ordinal) &&
        style[7] is >= '1' and <= '9';

    private static string GetPath(XElement element, XElement body)
    {
        var parts = new Stack<string>();
        for (var cursor = element; cursor != body && cursor.Parent is not null; cursor = cursor.Parent)
        {
            var ordinal = cursor.ElementsBeforeSelf(cursor.Name).Count() + 1;
            parts.Push($"{cursor.Name.LocalName}[{ordinal}]");
        }

        return "body/" + string.Join('/', parts);
    }
}
