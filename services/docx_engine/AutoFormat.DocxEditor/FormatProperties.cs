using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace AutoFormat.DocxEditor;

internal static class FormatProperties
{
    private static readonly XNamespace W = AcademicPackage.W;
    internal static readonly string[] Registered = [
        "font.family", "font.size", "font.bold", "font.italic", "paragraph.alignment",
        "paragraph.spacing_before", "paragraph.spacing_after", "paragraph.line_spacing",
        "paragraph.first_line_indent", "paragraph.hanging_indent", "paragraph.left_indent", "paragraph.right_indent",
        "paragraph.keep_with_next", "paragraph.keep_together", "paragraph.page_break_before", "paragraph.snap_to_grid",
        "page.paper_size", "page.dimensions", "page.orientation", "page.margin.all", "page.margin.top", "page.margin.bottom",
        "page.margin.left", "page.margin.right", "page.margin.header_distance", "page.margin.footer_distance", "page.margin.gutter",
        "section.column_count", "section.text_direction", "page_number.number_format", "page_number.start",
        "toc.max_depth", "table.border_style", "caption.position", "document.position",
    ];
    internal static FormatCapability[] Capabilities() => Registered.Select(p => new FormatCapability(p, "edit_and_verify",
        p.StartsWith("font.", StringComparison.Ordinal) ? "run" : p.StartsWith("paragraph.", StringComparison.Ordinal) ? "paragraph" :
        p.StartsWith("page.", StringComparison.Ordinal) || p.StartsWith("page_number.", StringComparison.Ordinal) || p.StartsWith("section.", StringComparison.Ordinal) ? "section" :
        p == "table.border_style" ? "table" : p == "document.position" ? "region" : "field_or_object",
        p.StartsWith("page_number.", StringComparison.Ordinal) || p == "toc.max_depth" ? "xml_verified_cache_pending_refresh" : "effective_xml_readback")).ToArray();
    internal static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private static string Number(double value) => value.ToString("0.########", CultureInfo.InvariantCulture);
    private static string Twips(double value, string? unit) => Number(Math.Round(value * (unit == "cm" ? 1440 / 2.54 : unit == "mm" ? 1440 / 25.4 : 20), MidpointRounding.AwayFromZero));
    internal static double Numeric(string? text, double fallback = 0) => double.TryParse(text, CultureInfo.InvariantCulture, out var result) ? result : fallback;
    private static readonly Dictionary<string, string[]> Order = new()
    {
        ["pPr"] = "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange".Split(' '),
        ["rPr"] = "rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange".Split(' '),
        ["sectPr"] = "headerReference footerReference footnotePr endnotePr type pgSz pgMar paperSrc pgBorders lnNumType pgNumType cols formProt vAlign noEndnote titlePg textDirection bidi rtlGutter docGrid printerSettings sectPrChange".Split(' '),
        ["tblPr"] = "tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription tblPrChange".Split(' '),
        ["tcPr"] = "cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark tcPrChange".Split(' '),
        ["tblBorders"] = "top left bottom right insideH insideV".Split(' '),
        ["tcBorders"] = "top left bottom right insideH insideV tl2br tr2bl".Split(' '),
    };
    internal static XElement Ensure(XElement parent, string name)
    {
        if (parent.Element(W + name) is { } existing) return existing;
        var value = new XElement(W + name);
        if (name is "pPr" or "rPr" or "tblPr" or "tcPr") parent.AddFirst(value);
        else if (Order.TryGetValue(parent.Name.LocalName, out var order))
        {
            var index = Array.IndexOf(order, name);
            var following = parent.Elements().FirstOrDefault(e => Array.IndexOf(order, e.Name.LocalName) > index);
            if (following is not null) following.AddBeforeSelf(value); else parent.Add(value);
        }
        else parent.Add(value);
        return value;
    }
    internal static void Set(XElement parent, string name, string attribute, object? value) => Ensure(parent, name).SetAttributeValue(W + attribute, value);

    internal static void Validate(EffectiveFormatRule rule)
    {
        var prop = rule.PropertyId;
        var val = rule.Value.Normalized;
        var unit = rule.Value.Unit;
        if (!Registered.Contains(prop)) throw new FormatBlocked("unsupported", "Property has no registered editor.");
        bool valid;
        var enums = new Dictionary<string, string[]>
        {
            ["paragraph.alignment"] = ["left", "center", "right", "both"], ["page.paper_size"] = ["A4", "A3", "A5", "Letter"],
            ["page.orientation"] = ["portrait", "landscape"], ["section.text_direction"] = ["horizontal", "vertical"],
            ["page_number.number_format"] = ["arabic", "lower_roman", "upper_roman"], ["table.border_style"] = ["three_line", "all_borders", "none"],
            ["caption.position"] = ["above", "below"], ["document.position"] = ["before_body", "after_body", "document_end"],
        };
        if (enums.TryGetValue(prop, out var choices)) valid = val.ValueKind == JsonValueKind.String && choices.Contains(val.GetString()) && unit is null;
        else if (prop is "font.bold" or "font.italic" or "paragraph.keep_with_next" or "paragraph.keep_together" or "paragraph.page_break_before" or "paragraph.snap_to_grid")
            valid = val.ValueKind is JsonValueKind.True or JsonValueKind.False && unit is null;
        else if (prop == "font.family") valid = val.ValueKind == JsonValueKind.String && val.GetString() is { Length: > 0 and <= 100 } s && !s.Any(c => c is '\r' or '\n' or '\0') && unit is null;
        else if (prop == "font.size") valid = IsNumber(val, 0.5, 1638) && unit == "pt" && val.GetDouble() * 2 == Math.Round(val.GetDouble() * 2);
        else if (prop is "toc.max_depth" or "section.column_count" or "page_number.start")
            valid = val.TryGetInt32(out var n) && n >= (prop == "page_number.start" ? 0 : 1) && n <= (prop == "toc.max_depth" ? 9 : prop == "section.column_count" ? 45 : 32767) && unit is null;
        else if (prop == "page.dimensions") valid = unit == "cm" && val.ValueKind == JsonValueKind.Object && val.EnumerateObject().Count() == 2 && val.TryGetProperty("width_cm", out var width) && val.TryGetProperty("height_cm", out var height) && IsNumber(width, 0.01, 55.87) && IsNumber(height, 0.01, 55.87);
        else if (prop == "paragraph.line_spacing") valid = unit == "multiple" && IsNumber(val, 0.01, 100) || unit == "pt" && val.ValueKind == JsonValueKind.Object && val.EnumerateObject().Count() == 2 && val.TryGetProperty("mode", out var mode) && mode.GetString() is "exact" or "atLeast" && val.TryGetProperty("amount", out var amount) && IsNumber(amount, 0.01, 1638);
        else valid = IsNumber(val, 0, 1584) && (unit is "pt" or "cm" or "mm" || prop.Contains("indent", StringComparison.Ordinal) && unit == "characters" || prop is "paragraph.spacing_before" or "paragraph.spacing_after" && unit == "lines");
        if (!valid) throw new FormatBlocked("needs_user_input", "Value or unit is invalid or cannot be represented by Word.");
    }
    private static bool IsNumber(JsonElement value, double min, double max) => value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) && double.IsFinite(number) && number >= min && number <= max;

    internal static JsonElement? Read(AcademicPackage package, XElement node, EffectiveFormatRule rule, string? script = null, string? component = null)
    {
        var prop = rule.PropertyId;
        if (prop.StartsWith("font.", StringComparison.Ordinal) || prop.StartsWith("paragraph.", StringComparison.Ordinal))
            if (package.NeedsDirectProof(node, prop, script)) return null;
        if (prop == "font.family") return package.Font(node, script ?? "latin") is { } family ? Json(family) : null;
        if (prop == "font.size")
        {
            var size = package.Effective(node, "rPr", script == "complex_script" ? "szCs" : "sz");
            return size is null ? null : Json(Numeric(size) / 2);
        }
        if (prop is "font.bold" or "font.italic") return Json(package.EffectiveOn(node, (prop == "font.bold" ? "b" : "i") + (script == "complex_script" ? "Cs" : "")));
        if (prop.StartsWith("paragraph.", StringComparison.Ordinal))
        {
            if (prop == "paragraph.alignment") return Json(package.Effective(node, "pPr", "jc") ?? "left");
            var flag = prop switch { "paragraph.keep_with_next" => "keepNext", "paragraph.keep_together" => "keepLines", "paragraph.page_break_before" => "pageBreakBefore", "paragraph.snap_to_grid" => "snapToGrid", _ => null };
            if (flag is not null)
            {
                var present = package.PropertySources(node, "pPr").Any(p => p.Element(W + flag) is not null);
                if (flag == "snapToGrid" && !present) return null;
                return Json(package.Effective(node, "pPr", flag) is not ("0" or "false" or "off") && present);
            }
            if (prop == "paragraph.line_spacing")
            {
                var mode = package.Effective(node, "pPr", "spacing", "lineRule") ?? "auto";
                var line = package.Effective(node, "pPr", "spacing", "line");
                if (line is null) return null;
                if (rule.Value.Unit == "multiple") return mode == "auto" ? Json(Numeric(line) / 240) : null;
                return mode == "auto" ? null : Json(new { mode, amount = Numeric(line) / 20 });
            }
            var spacing = prop is "paragraph.spacing_before" or "paragraph.spacing_after";
            var side = prop.Split('.').Last() switch { "spacing_before" => "before", "spacing_after" => "after", "first_line_indent" => "firstLine", "hanging_indent" => "hanging", "left_indent" => "left", "right_indent" => "right", _ => "" };
            var units = rule.Value.Unit;
            if (spacing && package.Effective(node, "pPr", "spacing", side + "Autospacing") is "1" or "true" or "on") return null;
            var suffix = units == "characters" ? "Chars" : units == "lines" ? "Lines" : "";
            // Char/line values take priority over twip values in Word, including inheritance.
            if (suffix.Length == 0 && package.Effective(node, "pPr", spacing ? "spacing" : "ind", side + (spacing ? "Lines" : "Chars")) is { } priority) return Numeric(priority) == 0 ? Json(0) : null;
            if (side == "firstLine" && (package.Effective(node, "pPr", "ind", "hanging") is not null || package.Effective(node, "pPr", "ind", "hangingChars") is not null)) return null;
            var value = package.Effective(node, "pPr", spacing ? "spacing" : "ind", side + suffix);
            if (value is null) return suffix.Length > 0 ? null : Json(0);
            var factor = units == "characters" || units == "lines" ? 100 : units == "cm" ? 1440 / 2.54 : units == "mm" ? 1440 / 25.4 : 20;
            return Json(Numeric(value) / factor);
        }
        if (prop.StartsWith("page.margin.", StringComparison.Ordinal))
        {
            var side = component ?? prop.Split('.').Last();
            if (side == "header_distance") side = "header";
            if (side == "footer_distance") side = "footer";
            var value = (string?)node.Element(W + "pgMar")?.Attribute(W + side);
            return value is null ? null : Json(Numeric(value) / (rule.Value.Unit == "cm" ? 1440 / 2.54 : rule.Value.Unit == "mm" ? 1440 / 25.4 : 20));
        }
        if (prop == "page.orientation")
        {
            var size = node.Element(W + "pgSz");
            var orientation = (string?)size?.Attribute(W + "orient") ?? "portrait";
            var width = Numeric((string?)size?.Attribute(W + "w")); var height = Numeric((string?)size?.Attribute(W + "h"));
            if (width <= 0 || height <= 0 || orientation is not ("portrait" or "landscape") ||
                orientation == "portrait" && width > height || orientation == "landscape" && width < height) return null;
            return Json(orientation);
        }
        if (prop == "page.dimensions") return node.Element(W + "pgSz") is { } page ? Json(new { width_cm = Numeric((string?)page.Attribute(W + "w")) * 2.54 / 1440, height_cm = Numeric((string?)page.Attribute(W + "h")) * 2.54 / 1440 }) : null;
        if (prop == "page.paper_size")
        {
            var page = node.Element(W + "pgSz");
            var width = Numeric((string?)page?.Attribute(W + "w"));
            var height = Numeric((string?)page?.Attribute(W + "h"));
            var landscape = (string?)page?.Attribute(W + "orient") == "landscape";
            if (landscape) (width, height) = (height, width);
            return PaperSizes.FirstOrDefault(pair => Math.Abs(width - pair.Value.Item1) <= 2 && Math.Abs(height - pair.Value.Item2) <= 2).Key is { } name ? Json(name) : null;
        }
        if (prop == "section.column_count") return Json((int)Numeric((string?)node.Element(W + "cols")?.Attribute(W + "num"), 1));
        if (prop == "section.text_direction") return (string?)node.Element(W + "textDirection")?.Attribute(W + "val") switch { "tbRl" or "tbRlV" => Json("vertical"), null or "lrTb" or "lrTbV" => Json("horizontal"), _ => null };
        if (prop == "page_number.start") return node.Element(W + "pgNumType")?.Attribute(W + "start") is { } start ? Json((int)Numeric(start.Value)) : null;
        if (prop == "page_number.number_format") return (string?)node.Element(W + "pgNumType")?.Attribute(W + "fmt") switch { "lowerRoman" => Json("lower_roman"), "upperRoman" => Json("upper_roman"), null or "decimal" => Json("arabic"), _ => null };
        if (prop == "toc.max_depth")
        {
            var instruction = node.Name == W + "fldSimple" ? (string?)node.Attribute(W + "instr") ?? "" : node.Value;
            var match = Regex.Match(instruction, "\\\\o\\s+\"1-([1-9])\"");
            return match.Success ? Json(int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture)) : null;
        }
        return null;
    }

    private static readonly Dictionary<string, (int, int)> PaperSizes = new() { ["A4"] = (11906, 16838), ["A3"] = (16838, 23811), ["A5"] = (8391, 11906), ["Letter"] = (12240, 15840) };
    internal static void Write(AcademicPackage package, XElement node, EffectiveFormatRule rule, string? script = null, string? component = null)
    {
        var prop = rule.PropertyId;
        var value = rule.Value.Normalized;
        if (prop.StartsWith("font.", StringComparison.Ordinal))
        {
            var properties = Ensure(node, "rPr");
            if (prop == "font.family")
            {
                var fonts = Ensure(properties, "rFonts");
                var slots = script == "chinese" ? new[] { "eastAsia" } : script == "complex_script" ? ["cs"] : new[] { "ascii", "hAnsi" };
                foreach (var slot in slots)
                {
                    fonts.SetAttributeValue(W + slot, value.GetString());
                    fonts.Attribute(W + (slot == "cs" ? "cstheme" : slot + "Theme"))?.Remove();
                }
            }
            else Set(properties, prop == "font.size" ? (script == "complex_script" ? "szCs" : "sz") : (prop == "font.bold" ? "b" : "i") + (script == "complex_script" ? "Cs" : ""), "val", prop == "font.size" ? Number(value.GetDouble() * 2) : value.GetBoolean() ? "1" : "0");
            return;
        }
        if (prop.StartsWith("paragraph.", StringComparison.Ordinal))
        {
            var properties = Ensure(node, "pPr");
            if (prop == "paragraph.alignment") { Set(properties, "jc", "val", value.GetString()); return; }
            var flag = prop switch { "paragraph.keep_with_next" => "keepNext", "paragraph.keep_together" => "keepLines", "paragraph.page_break_before" => "pageBreakBefore", "paragraph.snap_to_grid" => "snapToGrid", _ => null };
            if (flag is not null) { Set(properties, flag, "val", value.GetBoolean() ? "1" : "0"); return; }
            if (prop == "paragraph.line_spacing")
            {
                Set(properties, "spacing", "line", rule.Value.Unit == "multiple" ? Number(Math.Round(value.GetDouble() * 240)) : Twips(value.GetProperty("amount").GetDouble(), "pt"));
                Set(properties, "spacing", "lineRule", rule.Value.Unit == "multiple" ? "auto" : value.GetProperty("mode").GetString());
                return;
            }
            var spacing = prop is "paragraph.spacing_before" or "paragraph.spacing_after";
            var side = prop.Split('.').Last() switch { "spacing_before" => "before", "spacing_after" => "after", "first_line_indent" => "firstLine", "hanging_indent" => "hanging", "left_indent" => "left", _ => "right" };
            var element = Ensure(properties, spacing ? "spacing" : "ind");
            var units = rule.Value.Unit;
            var alternate = side + (spacing ? "Lines" : "Chars");
            var inherited = package.PropertySources(node, "pPr").Where(p => p != properties).ToList();
            if (units is not ("characters" or "lines") && inherited.Any(p => p.Element(W + (spacing ? "spacing" : "ind"))?.Attribute(W + alternate) is not null))
                throw new FormatBlocked("ambiguous_target", "An inherited character/line-unit setting would override the requested physical length; style isolation is required.");
            if (side == "firstLine" && inherited.Any(p => p.Element(W + "ind")?.Attribute(W + "hanging") is not null || p.Element(W + "ind")?.Attribute(W + "hangingChars") is not null))
                throw new FormatBlocked("ambiguous_target", "Inherited hanging indentation would override first-line indentation; style isolation is required.");
            if (units is "characters" or "lines")
            {
                element.SetAttributeValue(W + alternate, Number(Math.Round(value.GetDouble() * 100)));
                element.Attribute(W + side)?.Remove();
            }
            else
            {
                element.SetAttributeValue(W + side, Twips(value.GetDouble(), units));
                element.Attribute(W + alternate)?.Remove();
            }
            if (spacing) element.SetAttributeValue(W + (side + "Autospacing"), "0");
            if (side is "firstLine" or "hanging")
            {
                var opposite = side == "firstLine" ? "hanging" : "firstLine";
                element.Attribute(W + opposite)?.Remove();
                element.Attribute(W + (opposite + "Chars"))?.Remove();
            }
            return;
        }
        if (prop.StartsWith("page.margin.", StringComparison.Ordinal))
        {
            var side = component ?? prop.Split('.').Last();
            side = side == "header_distance" ? "header" : side == "footer_distance" ? "footer" : side;
            if (node.Element(W + "pgMar") is null) throw new FormatBlocked("ambiguous_target", "Section margins are missing; unspecified margins cannot be invented.");
            Set(node, "pgMar", side, Twips(value.GetDouble(), rule.Value.Unit)); return;
        }
        if (prop is "page.paper_size" or "page.dimensions" or "page.orientation")
        {
            var page = node.Element(W + "pgSz") ?? throw new FormatBlocked("ambiguous_target", "Section page geometry is missing.");
            if (prop == "page.orientation")
            {
                var width = Numeric((string?)page.Attribute(W + "w")); var height = Numeric((string?)page.Attribute(W + "h"));
                if (width <= 0 || height <= 0) throw new FormatBlocked("ambiguous_target", "Page dimensions are missing or invalid.");
                if (value.GetString() == "landscape" && width < height || value.GetString() == "portrait" && width > height)
                {
                    var previousWidth = (string?)page.Attribute(W + "w"); var previousHeight = (string?)page.Attribute(W + "h");
                    page.SetAttributeValue(W + "w", previousHeight); page.SetAttributeValue(W + "h", previousWidth);
                }
                page.SetAttributeValue(W + "orient", value.GetString());
            }
            else
            {
                var sizes = prop == "page.paper_size" ? PaperSizes[value.GetString()!] : ((int)Numeric(Twips(value.GetProperty("width_cm").GetDouble(), "cm")), (int)Numeric(Twips(value.GetProperty("height_cm").GetDouble(), "cm")));
                if (prop == "page.paper_size" && (string?)page.Attribute(W + "orient") == "landscape") sizes = (sizes.Item2, sizes.Item1);
                page.SetAttributeValue(W + "w", sizes.Item1); page.SetAttributeValue(W + "h", sizes.Item2);
            }
            return;
        }
        if (prop == "section.column_count")
        {
            var cols = Ensure(node, "cols"); cols.Elements(W + "col").Remove(); cols.SetAttributeValue(W + "equalWidth", "1"); cols.SetAttributeValue(W + "num", value.GetInt32()); return;
        }
        if (prop == "section.text_direction") { Set(node, "textDirection", "val", value.GetString() == "vertical" ? "tbRl" : "lrTb"); return; }
        if (prop == "page_number.start") { Set(node, "pgNumType", "start", value.GetInt32()); return; }
        if (prop == "page_number.number_format") { Set(node, "pgNumType", "fmt", value.GetString() switch { "lower_roman" => "lowerRoman", "upper_roman" => "upperRoman", _ => "decimal" }); return; }
        if (prop == "toc.max_depth")
        {
            var instruction = node.Name == W + "fldSimple" ? (string?)node.Attribute(W + "instr") ?? "" : node.Value;
            if (!Regex.IsMatch(instruction, "\\\\o\\s+\"[1-9]-[1-9]\"")) throw new FormatBlocked("ambiguous_target", "TOC field lacks a supported outline switch.");
            if (Regex.IsMatch(instruction, @"\\[tf]") || Regex.IsMatch(instruction, @"\\u")) throw new FormatBlocked("ambiguous_target", "TOC uses additional entry sources; complete heading mapping is required.");
            var updated = Regex.Replace(instruction, "\\\\o\\s+\"[1-9]-[1-9]\"", _ => "\\o \"1-" + value.GetInt32() + "\"");
            if (node.Name == W + "fldSimple") { node.SetAttributeValue(W + "instr", updated); node.SetAttributeValue(W + "dirty", "1"); }
            else node.Value = updated;
            var begin = node.Parent?.ElementsBeforeSelf().LastOrDefault()?.Descendants(W + "fldChar").FirstOrDefault();
            if (begin is not null) begin.SetAttributeValue(W + "dirty", "1");
            return;
        }
        throw new FormatBlocked("unsupported", "Property requires its structural handler.");
    }

    internal static bool Equal(JsonElement? actual, JsonElement expected, double tolerance = 0.026)
    {
        if (actual is null) return false;
        if (actual.Value.ValueKind == JsonValueKind.Number && expected.ValueKind == JsonValueKind.Number) return Math.Abs(actual.Value.GetDouble() - expected.GetDouble()) <= tolerance;
        if (actual.Value.ValueKind == JsonValueKind.Object && expected.ValueKind == JsonValueKind.Object)
        {
            var left = actual.Value.EnumerateObject().ToDictionary(p => p.Name, p => p.Value);
            return left.Count == expected.EnumerateObject().Count() && expected.EnumerateObject().All(p => left.TryGetValue(p.Name, out var val) && Equal(val, p.Value, tolerance));
        }
        return JsonElement.DeepEquals(actual.Value, expected);
    }
}
