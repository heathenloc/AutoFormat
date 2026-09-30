using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;
using DocumentFormat.OpenXml.Wordprocessing;
using EasyFormat.DocxIndex;

namespace EasyFormat.DocxEditor;

/// <summary>
/// First deterministic edit operation. It accepts a typed, already approved operation;
/// it does not interpret brief text or user feedback.
/// </summary>
public static class ParagraphAlignmentEditor
{
    public static EditResult Apply(string taskDirectory, EditManifest manifest)
    {
        if (manifest.SchemaVersion != "edit-manifest-prototype/1.0" ||
            string.IsNullOrWhiteSpace(manifest.OperationId) ||
            string.IsNullOrWhiteSpace(manifest.RuleId) ||
            string.IsNullOrWhiteSpace(manifest.BaseVersionId) ||
            !IsSha256(manifest.BaseDocxSha256) ||
            !IsSha256(manifest.ExpectedParagraphTextSha256) ||
            !IsSimpleDocxName(manifest.InputFile) ||
            !IsSimpleDocxName(manifest.OutputFile) ||
            manifest.InputFile.Equals(manifest.OutputFile, StringComparison.OrdinalIgnoreCase))
        {
            return Result(manifest, "needs_user_input", "Manifest is incomplete or invalid.");
        }

        if (manifest.Property != "paragraph.alignment")
        {
            return Result(manifest, "unsupported_property", "Only paragraph.alignment is registered.");
        }

        if (manifest.EffectiveScope != "paragraph")
        {
            return Result(manifest, "needs_user_input", "Alignment changes a whole paragraph.");
        }

        var desired = ParseAlignment(manifest.Value);
        if (desired is null)
        {
            return Result(manifest, "unsupported_property", "Alignment value is not registered.");
        }

        var root = Path.GetFullPath(taskDirectory);
        if (!Directory.Exists(root) ||
            (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
        {
            return Result(manifest, "needs_user_input", "Task directory is unavailable or redirected.");
        }

        var input = Path.Combine(root, manifest.InputFile);
        var output = Path.Combine(root, manifest.OutputFile);
        if (!File.Exists(input) || File.Exists(output) ||
            (File.GetAttributes(input) & FileAttributes.ReparsePoint) != 0)
        {
            return Result(manifest, "needs_user_input", "Input is unavailable or output already exists.");
        }

        var source = DocxTextIndex.Build(input);
        if (!source.Sha256.Equals(manifest.BaseDocxSha256, StringComparison.OrdinalIgnoreCase))
        {
            return Result(manifest, "stale_base_version", "Input hash differs from selected base version.");
        }

        var targetIndex = ParseTargetIndex(manifest.TargetObjectId);
        if (targetIndex < 0 || targetIndex >= source.Paragraphs.Count ||
            !HashText(source.Paragraphs[targetIndex].Text).Equals(
                manifest.ExpectedParagraphTextSha256, StringComparison.OrdinalIgnoreCase))
        {
            return Result(manifest, "ambiguous_target", "Target paragraph is absent or has changed.");
        }

        if (source.Paragraphs[targetIndex].RequiresManualTargeting)
        {
            return Result(manifest, "ambiguous_target",
                "Target contains hidden or revision content and needs manual targeting.");
        }

        string? before;
        using (var document = WordprocessingDocument.Open(input, false))
        {
            var paragraph = FindParagraph(document, targetIndex);
            if (paragraph is null)
            {
                return Result(manifest, "ambiguous_target", "Open XML paragraph index differs from text index.");
            }

            before = paragraph.ParagraphProperties?.Justification?.Val?.InnerText;
        }

        var temp = Path.Combine(root, $".{Guid.NewGuid():N}.staging.docx");
        try
        {
            File.Copy(input, temp, overwrite: false);
            if (!string.Equals(before, manifest.Value, StringComparison.OrdinalIgnoreCase))
            {
                using var document = WordprocessingDocument.Open(temp, true);
                var paragraph = FindParagraph(document, targetIndex)
                    ?? throw new InvalidDataException("Target disappeared in copied DOCX.");
                var properties = paragraph.ParagraphProperties;
                if (properties is null)
                {
                    properties = paragraph.PrependChild(new ParagraphProperties());
                }

                properties.Justification = new Justification { Val = desired.Value };
                var mainDocument = document.MainDocumentPart?.Document
                    ?? throw new InvalidDataException("DOCX main document is unavailable.");
                mainDocument.Save();
            }

            var edited = DocxTextIndex.Build(temp);
            if (!source.Paragraphs.Select(p => p.Text).SequenceEqual(
                    edited.Paragraphs.Select(p => p.Text), StringComparer.Ordinal) ||
                !OtherPartsEqual(input, temp))
            {
                return Result(manifest, "validation_failed", "Text or a non-target DOCX part changed.");
            }

            string? after;
            using (var document = WordprocessingDocument.Open(temp, false))
            {
                var validationError = new OpenXmlValidator().Validate(document).FirstOrDefault();
                if (validationError is not null)
                {
                    return Result(manifest, "validation_failed", "Edited DOCX failed Open XML validation.");
                }

                after = FindParagraph(document, targetIndex)?
                    .ParagraphProperties?.Justification?.Val?.InnerText;
            }

            if (!string.Equals(after, manifest.Value, StringComparison.OrdinalIgnoreCase))
            {
                return Result(manifest, "validation_failed", "Target alignment did not persist.");
            }

            File.Move(temp, output);
            return new EditResult("edit-result-prototype/1.0",
                before is not null && before.Equals(after, StringComparison.OrdinalIgnoreCase)
                    ? "already_satisfied" : "ready",
                manifest.OperationId, before, after, edited.Sha256,
                "Verified paragraph alignment; source DOCX unchanged.");
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    public static string HashText(string text) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();

    private static EditResult Result(EditManifest manifest, string status, string reason) =>
        new("edit-result-prototype/1.0", status, manifest.OperationId, null, null, null, reason);

    internal static bool IsSha256(string? value) =>
        value is { Length: 64 } && value.All(Uri.IsHexDigit);

    internal static bool IsSimpleDocxName(string? value)
    {
        if (value is null || !Regex.IsMatch(value,
                "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\\.docx$", RegexOptions.CultureInvariant))
            return false;

        var stem = value[..^5];
        return !Regex.IsMatch(stem,
            "^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    }

    internal static int ParseTargetIndex(string? objectId)
    {
        if (objectId is null || !objectId.StartsWith("p:", StringComparison.Ordinal) ||
            !int.TryParse(objectId.AsSpan(2), out var oneBased) || oneBased < 1)
        {
            return -1;
        }

        return oneBased - 1;
    }

    internal static JustificationValues? ParseAlignment(string? value) => value switch
    {
        "left" => JustificationValues.Left,
        "center" => JustificationValues.Center,
        "right" => JustificationValues.Right,
        "both" => JustificationValues.Both,
        _ => null,
    };

    internal static Paragraph? FindParagraph(WordprocessingDocument document, int index) =>
        document.MainDocumentPart?.Document?.Body?.Descendants<Paragraph>().ElementAtOrDefault(index);

    internal static bool OtherPartsEqual(string source, string output)
    {
        using var left = ZipFile.OpenRead(source);
        using var right = ZipFile.OpenRead(output);
        var leftParts = left.Entries.Where(e => e.FullName != "word/document.xml")
            .ToDictionary(e => e.FullName, StringComparer.Ordinal);
        var rightParts = right.Entries.Where(e => e.FullName != "word/document.xml")
            .ToDictionary(e => e.FullName, StringComparer.Ordinal);
        if (!leftParts.Keys.ToHashSet(StringComparer.Ordinal)
            .SetEquals(rightParts.Keys)) return false;

        foreach (var (name, entry) in leftParts)
        {
            using var leftStream = entry.Open();
            using var rightStream = rightParts[name].Open();
            if (!SHA256.HashData(leftStream).SequenceEqual(SHA256.HashData(rightStream)))
                return false;
        }

        return true;
    }
}
