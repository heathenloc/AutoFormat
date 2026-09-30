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

public sealed record AnchorMatch(string ObjectId, string XmlPath, int Start, int Length);

public sealed record AnchorResult(string Status, IReadOnlyList<AnchorMatch> Candidates, string Reason);

public static class AnchorLocator
{
    public static AnchorResult Locate(DocumentIndex document, SelectionHint hint)
    {
        if (hint.SchemaVersion != "selection-hint-prototype/1.0" ||
            string.IsNullOrWhiteSpace(hint.BaseVersionId) ||
            string.IsNullOrWhiteSpace(hint.BaseDocxSha256) ||
            hint.BaseDocxSha256.Length != 64 ||
            !hint.BaseDocxSha256.All(Uri.IsHexDigit) ||
            hint.ContextBefore is null || hint.ContextAfter is null ||
            string.IsNullOrWhiteSpace(hint.PreviewArtifactId) ||
            string.IsNullOrWhiteSpace(hint.RendererId) ||
            string.IsNullOrWhiteSpace(hint.RendererVersion) ||
            hint.PdfPage < 1 || hint.TextLayerStart < 0 ||
            hint.TextLayerEnd <= hint.TextLayerStart ||
            string.IsNullOrEmpty(hint.SelectedText) || hint.SelectedText.Length > 4096)
        {
            return new AnchorResult("needs_user_input", [], "Selection metadata is incomplete or invalid.");
        }

        if (!string.Equals(document.Sha256, hint.BaseDocxSha256, StringComparison.OrdinalIgnoreCase))
        {
            return new AnchorResult("stale_base_version", [], "DOCX hash differs from the preview base version.");
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
                var end = start + hint.SelectedText.Length;
                var beforeMatches = hint.ContextBefore.Length == 0 ||
                    paragraph.Text.AsSpan(0, start).EndsWith(hint.ContextBefore, StringComparison.Ordinal);
                var afterMatches = hint.ContextAfter.Length == 0 ||
                    paragraph.Text.AsSpan(end).StartsWith(hint.ContextAfter, StringComparison.Ordinal);
                if (beforeMatches && afterMatches)
                {
                    candidates.Add(new AnchorMatch(paragraph.ObjectId, paragraph.XmlPath, start, hint.SelectedText.Length));
                }

                offset = start + 1;
            }
        }

        return candidates.Count switch
        {
            0 => new AnchorResult("ambiguous_target", [], "No exact DOCX text and context match; do not edit."),
            1 => new AnchorResult("ready", candidates, "Unique exact match in this DOCX version."),
            _ => new AnchorResult("ambiguous_target", candidates, "Multiple DOCX matches; user must choose one."),
        };
    }
}
