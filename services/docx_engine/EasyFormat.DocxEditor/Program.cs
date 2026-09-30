using System.Text.Json;
using EasyFormat.DocxEditor;

if (args.Length != 3 || args[0] is not ("apply" or "apply-batch"))
{
    Console.Error.WriteLine("Usage: EasyFormat.DocxEditor apply|apply-batch <task-directory> <manifest-json>");
    return 2;
}

try
{
    var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
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
