using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;
using DocumentFormat.OpenXml.Wordprocessing;
using AutoFormat.DocxIndex;

namespace AutoFormat.DocxEditor;

/// <summary>
/// Applies a confirmed set of paragraph operations to one candidate copy. No output
/// is published until every target and the complete resulting package are verified.
/// </summary>
public static class ParagraphAlignmentBatchEditor
{
    public static BatchEditResult Apply(string taskDirectory, BatchEditManifest manifest)
    {
        if (manifest.SchemaVersion != "edit-batch-manifest/1.0" ||
            string.IsNullOrWhiteSpace(manifest.BatchId) ||
            string.IsNullOrWhiteSpace(manifest.BaseVersionId) ||
            !ParagraphAlignmentEditor.IsSha256(manifest.BaseDocxSha256) ||
            !ParagraphAlignmentEditor.IsSimpleDocxName(manifest.InputFile) ||
            !ParagraphAlignmentEditor.IsSimpleDocxName(manifest.OutputFile) ||
            manifest.InputFile.Equals(manifest.OutputFile, StringComparison.OrdinalIgnoreCase) ||
            manifest.Operations is null or { Count: 0 or > 5000 })
        {
            return Failure(manifest, "needs_user_input", "Batch manifest is incomplete or invalid.");
        }

        var root = Path.GetFullPath(taskDirectory);
        if (!Directory.Exists(root) ||
            (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
            return Failure(manifest, "needs_user_input", "Task directory is redirected.");

        var input = Path.Combine(root, manifest.InputFile);
        var output = Path.Combine(root, manifest.OutputFile);
        if (!File.Exists(input) || File.Exists(output) ||
            (File.GetAttributes(input) & FileAttributes.ReparsePoint) != 0)
            return Failure(manifest, "needs_user_input", "Input is unavailable or output exists.");

        var source = DocxTextIndex.Build(input);
        if (!source.Sha256.Equals(manifest.BaseDocxSha256, StringComparison.OrdinalIgnoreCase))
            return Failure(manifest, "stale_base_version", "Input hash differs from the plan base.");

        var seenOperations = new HashSet<string>(StringComparer.Ordinal);
        var seenTargets = new HashSet<string>(StringComparer.Ordinal);
        var prepared = new List<(BatchEditOperation Operation, int Index, JustificationValues Desired,
            string? Before)>();
        foreach (var operation in manifest.Operations)
        {
            if (operation is null || string.IsNullOrWhiteSpace(operation.OperationId) ||
                string.IsNullOrWhiteSpace(operation.RuleId) ||
                !seenOperations.Add(operation.OperationId) ||
                !seenTargets.Add(operation.TargetObjectId))
                return Failure(manifest, "needs_user_input", "Batch contains duplicate or incomplete operations.");
            var desired = ParagraphAlignmentEditor.ParseAlignment(operation.Value);
            if (operation.Property != "paragraph.alignment" || desired is null)
                return Failure(manifest, "unsupported_property", "Batch property or value is unsupported.");
            if (operation.EffectiveScope != "paragraph" ||
                !ParagraphAlignmentEditor.IsSha256(operation.ExpectedParagraphTextSha256))
                return Failure(manifest, "needs_user_input", "Batch target scope is invalid.");
            var index = ParagraphAlignmentEditor.ParseTargetIndex(operation.TargetObjectId);
            if (index < 0 || index >= source.Paragraphs.Count)
                return Failure(manifest, "ambiguous_target", "Batch target is absent.");
            var target = source.Paragraphs[index];
            if (target.ObjectId != operation.TargetObjectId ||
                target.XmlPath != operation.ExpectedXmlPath ||
                !ParagraphAlignmentEditor.HashText(target.Text).Equals(
                    operation.ExpectedParagraphTextSha256, StringComparison.OrdinalIgnoreCase) ||
                target.RequiresManualTargeting || target.Text.Length == 0 ||
                target.RoleCandidate is "table_cell" or "heading_candidate" ||
                !string.Equals(target.DirectAlignment,
                    operation.ExpectedBeforeDirectAlignment, StringComparison.Ordinal))
                return Failure(manifest, "ambiguous_target", "Batch target differs from confirmed scope.");
            prepared.Add((operation, index, desired.Value, target.DirectAlignment));
        }

        var temp = Path.Combine(root, $".{Guid.NewGuid():N}.staging.docx");
        try
        {
            File.Copy(input, temp, overwrite: false);
            var changed = prepared.Where(item => !string.Equals(
                item.Before, item.Operation.Value, StringComparison.OrdinalIgnoreCase)).ToList();
            if (changed.Count > 0)
            {
                using var document = WordprocessingDocument.Open(temp, true);
                foreach (var item in changed)
                {
                    var paragraph = ParagraphAlignmentEditor.FindParagraph(document, item.Index)
                        ?? throw new InvalidDataException("Target disappeared in copied DOCX.");
                    var properties = paragraph.ParagraphProperties;
                    if (properties is null)
                        properties = paragraph.PrependChild(new ParagraphProperties());
                    properties.Justification = new Justification { Val = item.Desired };
                }
                document.MainDocumentPart?.Document?.Save();
            }

            var edited = DocxTextIndex.Build(temp);
            if (!source.Paragraphs.Select(p => p.Text).SequenceEqual(
                    edited.Paragraphs.Select(p => p.Text), StringComparer.Ordinal) ||
                !ParagraphAlignmentEditor.OtherPartsEqual(input, temp))
                return Failure(manifest, "validation_failed", "Text or a non-target part changed.");

            var expected = source.Paragraphs.Select(p => p.DirectAlignment).ToArray();
            foreach (var item in prepared) expected[item.Index] = item.Operation.Value;
            if (!expected.SequenceEqual(edited.Paragraphs.Select(p => p.DirectAlignment),
                    StringComparer.OrdinalIgnoreCase))
                return Failure(manifest, "validation_failed", "Target or unrelated alignment differs.");

            using (var document = WordprocessingDocument.Open(temp, false))
            {
                if (new OpenXmlValidator().Validate(document).Any())
                    return Failure(manifest, "validation_failed", "Edited DOCX failed Open XML validation.");
            }

            File.Move(temp, output);
            return new BatchEditResult("edit-batch-result/1.0",
                changed.Count > 0 ? "ready" : "already_satisfied",
                manifest.BatchId, edited.Sha256,
                prepared.Select(item => new BatchOperationResult(
                    item.Operation.OperationId, item.Operation.TargetObjectId,
                    string.Equals(item.Before, item.Operation.Value, StringComparison.OrdinalIgnoreCase)
                        ? "already_satisfied" : "ready",
                    item.Before, item.Operation.Value)).ToArray(),
                "Verified every target, all paragraph text, all alignments, and other package parts.");
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    private static BatchEditResult Failure(BatchEditManifest manifest, string status, string reason) =>
        new("edit-batch-result/1.0", status, manifest.BatchId, null,
            Array.Empty<BatchOperationResult>(), reason);
}
