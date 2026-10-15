using System.Text.Json;
using AutoFormat.DocxEditor;

if (args.Length == 2 && args[0] == "inspect-selection")
{
    try
    {
        Console.WriteLine(JsonSerializer.Serialize(SelectionTextIndex.Inspect(args[1])));
        return 0;
    }
    catch
    {
        // The local adapter returns a safe status; never print source XML/text.
        Console.Error.WriteLine("Selection text index could not be verified.");
        return 1;
    }
}

if (args.Length == 1 && args[0] == "capabilities")
{
    Console.WriteLine(JsonSerializer.Serialize(AcademicFormatEditor.Capabilities(), new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }));
    return 0;
}
if (args.Length == 2 && args[0] == "inspect-academic")
{
    Console.WriteLine(JsonSerializer.Serialize(AcademicFormatEditor.Inspect(args[1])));
    return 0;
}
if (args.Length != 3 || args[0] is not ("apply" or "apply-batch" or "apply-academic" or "plan-academic" or "apply-feedback" or "plan-feedback"))
{
    Console.Error.WriteLine("Usage: AutoFormat.DocxEditor capabilities | inspect-academic|inspect-selection <docx> | apply|apply-batch|plan-academic|apply-academic <task-directory> <manifest-json>");
    return 2;
}

try
{
    var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    if (args[0] is "apply-academic" or "plan-academic" or "apply-feedback" or "plan-feedback")
    {
        var root = AcademicFormatEditor.SafeRoot(args[1]);
        var path = Path.GetFullPath(args[2]);
        if (Path.GetDirectoryName(path) != root || File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint) || new FileInfo(path).Length > 16777216)
            throw new InvalidDataException("Manifest must be a bounded regular file inside the task directory.");
        options.UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow;
        options.RespectRequiredConstructorParameters = true;
        options.AllowDuplicateProperties = false;
        if (args[0] is "apply-feedback" or "plan-feedback")
        {
            var feedback = JsonSerializer.Deserialize<FeedbackEditManifest>(File.ReadAllText(path), options)
                ?? throw new InvalidDataException("Feedback manifest is null.");
            var feedbackResult = AcademicFormatEditor.ApplyFeedback(root, feedback, args[0] == "plan-feedback");
            Console.WriteLine(JsonSerializer.Serialize(feedbackResult, options));
            return feedbackResult.Status is "ready" or "already_satisfied" or "planned" ? 0 : 1;
        }
        var academic = JsonSerializer.Deserialize<AcademicEditManifest>(File.ReadAllText(path), options)
            ?? throw new InvalidDataException("Academic manifest is null.");
        var academicResult = AcademicFormatEditor.Apply(root, academic, args[0] == "plan-academic");
        Console.WriteLine(JsonSerializer.Serialize(academicResult, options));
        return academicResult.Status is "ready" or "already_satisfied" or "planned" ? 0 : 1;
    }
    if (args[0] == "apply-batch")
    {
        var batch = JsonSerializer.Deserialize<BatchEditManifest>(File.ReadAllText(args[2]), options)
            ?? throw new InvalidDataException("Batch manifest is null.");
        var batchResult = ParagraphAlignmentBatchEditor.Apply(args[1], batch);
        Console.WriteLine(JsonSerializer.Serialize(batchResult, options));
        return batchResult.Status is "ready" or "already_satisfied" ? 0 : 1;
    }
    var manifest = JsonSerializer.Deserialize<EditManifest>(File.ReadAllText(args[2]), options)
        ?? throw new InvalidDataException("Edit manifest is null.");
    var result = ParagraphAlignmentEditor.Apply(args[1], manifest);
    Console.WriteLine(JsonSerializer.Serialize(result, options));
    return result.Status is "ready" or "already_satisfied" ? 0 : 1;
}
catch (Exception error) when (error is IOException or InvalidDataException or
    UnauthorizedAccessException or JsonException)
{
    Console.Error.WriteLine($"{error.GetType().Name}: {error.Message}");
    return 1;
}
