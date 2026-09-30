using System.Text.Json;
using EasyFormat.DocxEditor;

if (args.Length != 3 || args[0] != "apply")
{
    Console.Error.WriteLine("Usage: EasyFormat.DocxEditor apply <task-directory> <manifest-json>");
    return 2;
}

try
{
    var manifest = JsonSerializer.Deserialize<EditManifest>(File.ReadAllText(args[2]),
        new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower })
        ?? throw new InvalidDataException("Edit manifest is null.");
    var result = ParagraphAlignmentEditor.Apply(args[1], manifest);
    Console.WriteLine(JsonSerializer.Serialize(result,
        new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }));
    return result.Status is "ready" or "already_satisfied" ? 0 : 1;
}
catch (Exception error) when (error is IOException or InvalidDataException or
    UnauthorizedAccessException or JsonException)
{
    Console.Error.WriteLine($"{error.GetType().Name}: {error.Message}");
    return 1;
}
