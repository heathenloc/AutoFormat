namespace EasyFormat.DocxIndex;

public sealed record SelectionHint(
    string SchemaVersion,
    string BaseVersionId,
    string BaseDocxSha256,
    string PreviewArtifactId,
    string RendererId,
    string RendererVersion,
    string SelectedText,
    string ContextBefore,
    string ContextAfter,
    int PdfPage,
    int TextLayerStart,
    int TextLayerEnd);

/// <summary>Server-side preview metadata, never supplied from the selection request.</summary>
public sealed record PreviewBinding(
    string BaseVersionId,
    string BaseDocxSha256,
    string PreviewArtifactId,
    string RendererId,
    string RendererVersion,
    int PdfPageCount);

public sealed record AnchorMatch(
    string ObjectId, string XmlPath, int Start, int Length, bool RequiresManualTargeting);

public sealed record SelectionAnchor(
    string SchemaVersion,
    string BaseVersionId,
    string PreviewArtifactId,
    string RendererId,
    string RendererVersion,
    string SelectedText,
    string ContextBefore,
    string ContextAfter,
    int PdfPage,
    int TextLayerStart,
    int TextLayerEnd,
    string DocxObjectId,
    string DocxXmlPath,
    int DocxStart,
    int DocxLength,
    string Status);

public sealed record AnchorResult(
    string Status, IReadOnlyList<AnchorMatch> Candidates, string Reason,
    SelectionAnchor? Anchor = null);

public static class AnchorLocator
{
    public static AnchorResult Locate(DocumentIndex document, SelectionHint hint, PreviewBinding binding)
    {
        if (hint.SchemaVersion != "selection-hint-prototype/1.0" ||
            string.IsNullOrWhiteSpace(hint.BaseVersionId) ||
            string.IsNullOrWhiteSpace(hint.BaseDocxSha256) ||
            hint.BaseDocxSha256.Length != 64 ||
            !hint.BaseDocxSha256.All(Uri.IsHexDigit) ||
            hint.ContextBefore is null || hint.ContextAfter is null ||
            hint.ContextBefore.Length > 4096 || hint.ContextAfter.Length > 4096 ||
            string.IsNullOrWhiteSpace(hint.PreviewArtifactId) ||
            string.IsNullOrWhiteSpace(hint.RendererId) ||
            string.IsNullOrWhiteSpace(hint.RendererVersion) ||
            hint.PdfPage < 1 || hint.TextLayerStart < 0 ||
            hint.TextLayerEnd <= hint.TextLayerStart ||
            string.IsNullOrWhiteSpace(hint.SelectedText) || hint.SelectedText.Length > 4096)
        {
            return new AnchorResult("needs_user_input", [], "Selection metadata is incomplete or invalid.");
        }

        if (string.IsNullOrWhiteSpace(binding.BaseVersionId) ||
            string.IsNullOrWhiteSpace(binding.PreviewArtifactId) ||
            string.IsNullOrWhiteSpace(binding.RendererId) ||
            string.IsNullOrWhiteSpace(binding.RendererVersion) ||
            string.IsNullOrWhiteSpace(binding.BaseDocxSha256) ||
            binding.PdfPageCount < 1 ||
            binding.BaseDocxSha256.Length != 64 ||
            !binding.BaseDocxSha256.All(Uri.IsHexDigit))
        {
            return new AnchorResult("needs_user_input", [], "Trusted preview binding is incomplete.");
        }

        if (!string.Equals(document.Sha256, binding.BaseDocxSha256, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(hint.BaseDocxSha256, binding.BaseDocxSha256, StringComparison.OrdinalIgnoreCase) ||
            hint.BaseVersionId != binding.BaseVersionId)
        {
            return new AnchorResult("stale_base_version", [], "DOCX and selection base version differ.");
        }

        if (hint.PreviewArtifactId != binding.PreviewArtifactId ||
            hint.RendererId != binding.RendererId ||
            hint.RendererVersion != binding.RendererVersion ||
            hint.PdfPage > binding.PdfPageCount)
        {
            return new AnchorResult("stale_preview", [], "Selection does not belong to this preview artifact.");
        }

        if (hint.SelectedText.Contains('\n') || hint.SelectedText.Contains('\r'))
        {
            return new AnchorResult("ambiguous_target", [], "Cross-paragraph selection needs manual targeting.");
        }

        var candidates = new List<AnchorMatch>();
        foreach (var paragraph in document.Paragraphs)
        {
            var offset = 0;
            while (offset <= paragraph.Text.Length - hint.SelectedText.Length)
            {
                var start = paragraph.Text.IndexOf(hint.SelectedText, offset, StringComparison.Ordinal);
                if (start < 0) break;
                candidates.Add(new AnchorMatch(paragraph.ObjectId, paragraph.XmlPath, start,
                    hint.SelectedText.Length, paragraph.RequiresManualTargeting));

                offset = start + 1;
            }
        }

        if (candidates.Count != 1)
        {
            return candidates.Count == 0
                ? new AnchorResult("ambiguous_target", [], "No exact DOCX text match; do not edit.")
                : new AnchorResult("ambiguous_target", candidates,
                    "Selected text occurs more than once; user must choose a target.");
        }

        var match = candidates[0];
        if (match.RequiresManualTargeting)
        {
            return new AnchorResult("ambiguous_target", candidates,
                "DOCX paragraph contains tracked, hidden, field, or drawing content.");
        }

        var paragraphText = document.Paragraphs.Single(p => p.ObjectId == match.ObjectId).Text;
        var end = match.Start + match.Length;
        var beforeMatches = hint.ContextBefore.Length == 0 ||
            paragraphText.AsSpan(0, match.Start).EndsWith(hint.ContextBefore, StringComparison.Ordinal);
        var afterMatches = hint.ContextAfter.Length == 0 ||
            paragraphText.AsSpan(end).StartsWith(hint.ContextAfter, StringComparison.Ordinal);
        if (!beforeMatches || !afterMatches)
        {
            return new AnchorResult("ambiguous_target", candidates,
                "PDF selection context does not match the DOCX paragraph.");
        }

        var anchor = new SelectionAnchor(
            "selection-anchor/1.0", hint.BaseVersionId, hint.PreviewArtifactId,
            hint.RendererId, hint.RendererVersion, hint.SelectedText,
            hint.ContextBefore, hint.ContextAfter, hint.PdfPage,
            hint.TextLayerStart, hint.TextLayerEnd, match.ObjectId,
            match.XmlPath, match.Start, match.Length, "ready");
        return new AnchorResult("ready", candidates,
            "Unique exact text and context match in this bound DOCX version.", anchor);
    }
}
