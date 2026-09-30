using System.Text.Json;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using EasyFormat.DocxIndex;

if (args.Length < 2 || args[0] is not ("index" or "inspect" or "locate") ||
    (args[0] == "locate" && args.Length != 4) ||
    ((args[0] is "index" or "inspect") && args.Length != 2))
{
    Console.Error.WriteLine("Usage: EasyFormat.DocxIndex index|inspect <docx> | locate <docx> <selection-json> <trusted-preview-binding-json>");
    return 2;
}

try
{
    var document = DocxTextIndex.Build(args[1]);
    object result;
    if (args[0] == "index")
    {
        result = new
        {
            schema_version = "docx-index-prototype/1.0",
            sha256 = document.Sha256,
            paragraph_count = document.Paragraphs.Count,
            nonempty_paragraph_count = document.Paragraphs.Count(p => p.Text.Length > 0),
        };
    }
    else if (args[0] == "inspect")
    {
        result = new
        {
            schema_version = "docx-target-index/1.0",
            sha256 = document.Sha256,
            paragraph_count = document.Paragraphs.Count,
            paragraphs = document.Paragraphs.Select(paragraph => new
            {
                object_id = paragraph.ObjectId,
                xml_path = paragraph.XmlPath,
                style_id = paragraph.StyleId,
                text_sha256 = Convert.ToHexString(SHA256.HashData(
                    Encoding.UTF8.GetBytes(paragraph.Text))).ToLowerInvariant(),
                text_preview = paragraph.Text.Length <= 120
                    ? paragraph.Text : paragraph.Text[..120],
                is_empty = paragraph.Text.Length == 0,
                requires_manual_targeting = paragraph.RequiresManualTargeting,
                role_candidate = paragraph.RoleCandidate,
                role_evidence = paragraph.RoleEvidence,
                direct_alignment = paragraph.DirectAlignment,
            }),
        };
    }
    else
    {
        var hint = JsonSerializer.Deserialize<SelectionHint>(File.ReadAllText(args[2]),
            new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            })
            ?? throw new InvalidDataException("Selection JSON is null.");
        var binding = JsonSerializer.Deserialize<PreviewBinding>(File.ReadAllText(args[3]),
            new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            })
            ?? throw new InvalidDataException("Trusted preview binding JSON is null.");
        result = AnchorLocator.Locate(document, hint, binding);
    }

    Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    }));
    return 0;
}
catch (Exception error) when (error is IOException or InvalidDataException or
    UnauthorizedAccessException or JsonException or XmlException)
{
    Console.Error.WriteLine($"{error.GetType().Name}: {error.Message}");
    return 1;
}
