using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace AutoFormat.DocxEditor;

/// <summary>Deterministic semantic planner and editor. Provenance replay is owned by the Python boundary.</summary>
public static partial class AcademicFormatEditor
{
    private static readonly XNamespace W = AcademicPackage.W;
    private sealed record Prepared(EffectiveFormatRule Rule, FormatFragment Fragment, AcademicObject Object,
        XElement Node, string? Script, string? Component, JsonElement? Before, string Slot);
    public static FormatCapability[] Capabilities() => FormatProperties.Capabilities();

    public static object Inspect(string path)
    {
        var package = new AcademicPackage(path);
        return new { schema_version = "academic-docx-index/1.0", sha256 = package.Sha256,
            objects = package.Objects.Select(o => new { object_id = o.Id, part = o.Part, xml_path = AcademicPackage.PathOf(o.Node),
                kind = o.Kind, semantic_role = o.Role, region = o.Region, region_zone = o.Zone, chapter = o.Chapter,
                object_ordinal = o.Ordinal, object_language = o.Language, section = o.Section, requires_manual_targeting = o.Unsafe }) };
    }

    public static AcademicEditResult Apply(string taskDirectory, AcademicEditManifest manifest, bool planOnly = false)
        => ApplyCore(taskDirectory, manifest, planOnly, null);

    private static AcademicEditResult ApplyCore(string taskDirectory, AcademicEditManifest manifest, bool planOnly,
        Dictionary<string, FeedbackEditFragment>? exact)
    {
        string? temp = null;
        try
        {
            var root = SafeRoot(taskDirectory);
            if (manifest.SchemaVersion != "academic-edit-manifest/1.0" || !ParagraphAlignmentEditor.IsSha256(manifest.BaseDocxSha256) ||
                !ParagraphAlignmentEditor.IsSha256(manifest.RulesSnapshotId) || string.IsNullOrWhiteSpace(manifest.BaseVersionId) ||
                !ParagraphAlignmentEditor.IsSimpleDocxName(manifest.InputFile) || !ParagraphAlignmentEditor.IsSimpleDocxName(manifest.OutputFile) ||
                manifest.InputFile.Equals(manifest.OutputFile, StringComparison.OrdinalIgnoreCase) || manifest.Rules.Length > (exact is null ? 512 : 1024) || manifest.Fragments.Length > 20000)
                throw new InvalidDataException("Invalid academic edit manifest.");
            var input = Path.Combine(root, manifest.InputFile);
            var output = Path.Combine(root, manifest.OutputFile);
            if (File.Exists(output)) throw new FormatBlocked("output_exists", "Published output cannot be overwritten.");
            if (!File.Exists(input) || File.GetAttributes(input).HasFlag(FileAttributes.ReparsePoint)) throw new InvalidDataException("Input is missing or redirected.");
            var package = new AcademicPackage(input);
            if (package.Sha256 != manifest.BaseDocxSha256) throw new FormatBlocked("stale_base_version", "Selected parent DOCX hash differs.");
            AcademicPackage.Validate(input);
            var originalContent = package.ProtectedContent();
            var protectedNodes = ProtectedNodes(package);
            if (exact is not null) PrepareFeedbackRanges(package, exact.Values);
            if (manifest.Rules.Any(r => r.Target.SemanticRole == "citation" && r.PropertyId.StartsWith("font.", StringComparison.Ordinal) &&
                r.Semantics.Condition is null && r.Semantics.Constraint.Operator == "eq" && manifest.Fragments.Any(f => f.RuleId == r.RuleId && f.Status == "verified"))) PrepareCitations(package);
            var results = new List<FormatRuleResult>();
            var prepared = new List<Prepared>();
            if (manifest.Rules.Select(r => r.RuleId).Distinct().Count() != manifest.Rules.Length ||
                manifest.Fragments.Select(f => f.FragmentId).Distinct().Count() != manifest.Fragments.Length ||
                manifest.Fragments.Any(f => !manifest.Rules.Any(r => r.RuleId == f.RuleId))) throw new InvalidDataException("Repeated or unknown rule/fragment IDs.");
            foreach (var rule in manifest.Rules)
            {
                var start = prepared.Count;
                try
                {
                    ValidateRule(rule);
                    FormatProperties.Validate(rule);
                    if (rule.ExecutionSupport != "typed") throw new FormatBlocked("check_only", "Rule is report-only; no typed editing authorization.");
                    if (rule.Semantics.Condition is { } condition && condition.ValueKind != JsonValueKind.Null)
                        throw new FormatBlocked("pending_condition", "Submission or conditional applicability needs confirmation.");
                    if (rule.Semantics.Constraint.Operator != "eq") throw new FormatBlocked("check_only", "Bounds and alternatives are checked without selecting a value.");
                    var fragments = manifest.Fragments.Where(f => f.RuleId == rule.RuleId && f.Status == "verified").ToArray();
                    if (fragments.Length == 0) throw new FormatBlocked(rule.Status == "verified" ? "needs_user_input" : rule.Status, "No independently verified scope fragment.");
                    var withheld = new List<string>();
                    foreach (var fragment in fragments)
                    {
                        if (fragment.ConflictIds.Length != 0 || !Subset(fragment.Scope, rule.Semantics.Scope)) throw new InvalidDataException("Verified fragment exceeds its rule or still has a conflict.");
                        ValidateScope(fragment.Scope);
                        if (exact is null) PlanRule(package, rule, fragment, prepared, withheld);
                        else PlanFeedbackRule(package, rule, fragment, exact[fragment.FragmentId], prepared);
                    }
                    results.Add(new FormatRuleResult(rule.RuleId, withheld.Count > 0 ? "ambiguous_target" : prepared.Count > start ? (rule.Status is "pending_conflict" or "pending_condition" ? rule.Status : "planned") : "no_target", prepared.Count - start,
                        withheld.Count > 0 ? "Independent safe targets retained; withheld targets: " + string.Join("; ", withheld.Distinct().Take(20)) : prepared.Count > start ? "Located full typed scope." : "No reliable matching object was found; no scope expansion."));
                }
                catch (FormatBlocked error)
                {
                    prepared.RemoveRange(start, prepared.Count - start);
                    results.Add(new FormatRuleResult(rule.RuleId, error.Status, 0, error.Message));
                }
            }
            if (prepared.Count > 200000) throw new InvalidDataException("Edit operation limit exceeded.");
            if (exact is not null && results.Any(r => r.Status != "planned"))
                throw new FormatBlocked("needs_user_input", "A feedback target could not be fully and safely planned; no edit was emitted.");
            // Recheck physical collisions, including properties sharing a Word storage slot.
            var blocked = prepared.GroupBy(p => p.Slot).Where(g => g.Select(p => Canonical(p.Rule)).Distinct().Count() > 1).SelectMany(g => g).ToHashSet();
            // Page size, orientation and margins share physical geometry even with different property IDs.
            foreach (var group in prepared.Where(p => p.Object.Kind == "section" && p.Rule.PropertyId.StartsWith("page.", StringComparison.Ordinal)).GroupBy(p => p.Node))
            {
                var simulated = new XElement(group.Key);
                foreach (var p in group.OrderBy(p => Rank(p.Rule.PropertyId))) FormatProperties.Write(package, simulated, p.Rule, p.Script, p.Component);
                var page = simulated.Element(W + "pgSz"); var margins = simulated.Element(W + "pgMar");
                var noTextArea = page is not null && margins is not null && (
                    FormatProperties.Numeric((string?)margins.Attribute(W + "left")) + FormatProperties.Numeric((string?)margins.Attribute(W + "right")) + FormatProperties.Numeric((string?)margins.Attribute(W + "gutter")) >= FormatProperties.Numeric((string?)page.Attribute(W + "w")) ||
                    FormatProperties.Numeric((string?)margins.Attribute(W + "top")) + FormatProperties.Numeric((string?)margins.Attribute(W + "bottom")) >= FormatProperties.Numeric((string?)page.Attribute(W + "h")));
                if (noTextArea || group.Any(p => !FormatProperties.Equal(FormatProperties.Read(package, simulated, p.Rule, p.Script, p.Component), p.Rule.Value.Normalized, Tolerance(p.Rule))))
                    foreach (var p in group) blocked.Add(p);
            }
            foreach (var p in prepared.ToArray())
                if (blocked.Contains(p)) prepared.Remove(p);
            foreach (var id in blocked.Select(p => p.Rule.RuleId).Distinct())
            {
                var index = results.FindIndex(r => r.RuleId == id);
                results[index] = results[index] with { Status = "pending_conflict", Reason = "Typed scopes map to incompatible values at the same Word property; intersecting operations were withheld." };
            }
            if (exact is not null && blocked.Count > 0)
                throw new FormatBlocked("pending_conflict", "Feedback rules share incompatible physical Word properties.");
            var pendingFields = false;
            var operations = new List<FormatOperation>();
            var dirty = false;
            var movable = false;
            var splitRuns = new Dictionary<XElement, List<(XElement Node, string Script)>>();
            if (!planOnly)
                foreach (var group in prepared.Where(p => p.Rule.PropertyId.StartsWith("font.", StringComparison.Ordinal)).GroupBy(p => p.Node))
                    if (group.Any(p => !FormatProperties.Equal(Read(package, p.Node, p), p.Rule.Value.Normalized, Tolerance(p.Rule))))
                        splitRuns.Add(group.Key, SplitRun(group.Key));
            var applied = new List<(Prepared Plan, XElement Node)>();
            var locations = new List<(FormatOperation Operation, XElement Target)>();
            foreach (var group in prepared.GroupBy(p => p.Slot).OrderBy(g => Rank(g.First().Rule.PropertyId)))
            {
                var item = group.First();
                var desired = item.Rule.Value.Normalized;
                var fieldProperty = item.Rule.PropertyId is "toc.max_depth" or "page_number.start" or "page_number.number_format";
                var targets = splitRuns.TryGetValue(item.Node, out var currentPieces) ? currentPieces.Where(p => p.Script == item.Script).Select(p => p.Node).ToArray() : new[] { item.Node };
                var satisfied = !package.NewFields.Contains(item.Node) && targets.All(t => Read(package, t, item) is { } before && FormatProperties.Equal(before, desired, Tolerance(item.Rule)));
                if (planOnly)
                {
                    foreach (var alias in group) operations.Add(Operation(alias, alias.Node, satisfied ? "already_satisfied" : "planned", alias.Rule.Value.Normalized));
                    continue;
                }
                pendingFields |= fieldProperty;
                if (!satisfied)
                {
                    foreach (var target in targets) Write(package, target, item);
                    dirty = true;
                    movable |= item.Rule.PropertyId is "caption.position" or "document.position";
                    pendingFields |= item.Rule.PropertyId is "toc.max_depth" or "page_number.start" or "page_number.number_format";
                }
                foreach (var target in targets)
                {
                    foreach (var alias in group)
                    {
                        applied.Add((alias, target));
                        var op = Operation(alias, target, fieldProperty ? "pending_manual_check" : satisfied ? "already_satisfied" : "modified_verified", alias.Rule.Value.Normalized, !satisfied);
                        locations.Add((op, target));
                    }
                }
            }
            if (planOnly) return Result("planned", null, false, false, "not_run", operations.ToArray(), Summarize(results, operations), "Plan only; source DOCX is read-only.");
            operations = locations.Select(pair => pair.Operation with { XmlPath = AcademicPackage.PathOf(pair.Target) }).ToList();
            temp = Path.Combine(root, "." + Guid.NewGuid().ToString("N") + ".academic.docx");
            if (dirty) package.Save(temp); else File.Copy(input, temp);
            var outputPackage = new AcademicPackage(temp);
            AcademicPackage.Validate(temp);
            var outputContent = outputPackage.ProtectedContent();
            if (!originalContent.Keys.ToHashSet().SetEquals(outputContent.Keys) || originalContent.Any(pair =>
                !outputContent.TryGetValue(pair.Key, out var after) || !(movable ? pair.Value.Order(StringComparer.Ordinal).SequenceEqual(after.Order(StringComparer.Ordinal)) : pair.Value.SequenceEqual(after))))
                throw new InvalidDataException("Body, table or note content changed.");
            if (!protectedNodes.SequenceEqual(ProtectedNodes(outputPackage))) throw new InvalidDataException("Non-format structure changed.");
            // No-op outputs preserve the original bytes. Reproduce range cuts
            // only in the readback model so its paths match the exact plan.
            if (!dirty && exact is not null) PrepareFeedbackRanges(outputPackage, exact.Values);
            foreach (var (item, target) in applied)
            {
                var path = AcademicPackage.PathOf(target);
                var reopened = outputPackage.Xml[item.Object.Part].Descendants().SingleOrDefault(n => AcademicPackage.PathOf(n) == path);
                var actual = reopened is null ? null : Read(outputPackage, reopened, item);
                if (actual is null || !FormatProperties.Equal(actual, item.Rule.Value.Normalized, Tolerance(item.Rule)))
                    throw new InvalidDataException("Effective property failed readback verification: " + item.Rule.PropertyId);
            }
            using (var sourceFile = File.OpenRead(input))
                if (Convert.ToHexString(SHA256.HashData(sourceFile)).ToLowerInvariant() != manifest.BaseDocxSha256)
                    throw new FormatBlocked("stale_base_version", "Parent changed during editing.");
            File.Move(temp, output);
            temp = null;
            return Result(dirty ? "ready" : "already_satisfied", outputPackage.Sha256, true, true, pendingFields ? "pending_manual_check" : "not_required",
                operations.ToArray(), Summarize(results, operations), "Verified effective properties, protected content, non-format structures and Open XML package.");

            AcademicEditResult Result(string status, string? hash, bool content, bool validated, string fields, FormatOperation[] ops, FormatRuleResult[] rules, string reason) =>
                new("academic-edit-result/1.0", status, manifest.BaseDocxSha256, manifest.RulesSnapshotId, hash, ops, rules, content, validated, fields, reason);
        }
        catch (FormatBlocked error) { return Failure(error.Status, error.Message); }
        catch (Exception error) when (error is InvalidDataException or IOException or JsonException or ArgumentException or InvalidOperationException or UnauthorizedAccessException or System.Xml.XmlException)
        { return Failure("validation_failed", error is InvalidDataException ? error.Message : "Malformed document or contract; candidate was not published."); }
        finally { if (temp is not null && File.Exists(temp)) File.Delete(temp); }

        AcademicEditResult Failure(string status, string reason) => new("academic-edit-result/1.0", status, manifest.BaseDocxSha256, manifest.RulesSnapshotId,
            null, [], [], false, false, "not_run", reason);
    }

    internal static string SafeRoot(string directory)
    {
        var root = Path.GetFullPath(directory);
        for (var current = new DirectoryInfo(root); current is not null; current = current.Parent)
            if (!current.Exists || current.Attributes.HasFlag(FileAttributes.ReparsePoint)) throw new InvalidDataException("Task directory is absent or redirected.");
        return root;
    }
    private static void ValidateRule(EffectiveFormatRule rule)
    {
        if (rule.SchemaVersion != "academic-effective-rule/1.0" || rule.Semantics.SchemaVersion != "academic-rule-semantics/1.0" ||
            string.IsNullOrWhiteSpace(rule.RuleId) || rule.Target.Selector is not ("semantic_role" or "semantic_role_scope") ||
            rule.SourceKind is not ("brief_explicit" or "template_observation_confirmed" or "user_decision") ||
            rule.SourceKind == "brief_explicit" && (rule.SourceRuleIds.Length == 0 || rule.EvidenceRefs.Length == 0) ||
            rule.SourceKind != "brief_explicit" && rule.DecisionIds.Length == 0 ||
            rule.SourceKind == "template_observation_confirmed" && rule.ObservationIds.Length == 0)
            throw new InvalidDataException("Rule provenance or schema is invalid.");
        if (rule.Status is not ("verified" or "pending_conflict" or "pending_condition" or "check_only")) throw new InvalidDataException("Unknown rule status.");
    }
    private static void ValidateScope(FormatScope scope)
    {
        foreach (var (name, value) in scope.Axes)
        {
            if (name is not ("roles" or "characters" or "regions" or "region_zone" or "chapter" or "object_ordinal" or "object_language" or "property_component"))
                throw new FormatBlocked(name is "medium" or "channel" ? "pending_condition" : "unsupported", "Scope axis is not bound or registered: " + name);
            if (value.Exclude.Distinct().Count() != value.Exclude.Length || value.Include is { Length: 0 } ||
                value.Include is not null && (value.Include.Distinct().Count() != value.Include.Length || value.Include.Intersect(value.Exclude).Any()))
                throw new InvalidDataException("Scope includes/excludes are invalid.");
        }
    }
    private static bool Subset(FormatScope small, FormatScope big) => big.Axes.All(pair =>
    {
        var axis = small.Axes.GetValueOrDefault(pair.Key, new FormatAxis(null, []));
        return pair.Value.Include is null ? (axis.Include is not null ? !axis.Include.Intersect(pair.Value.Exclude).Any() : pair.Value.Exclude.All(axis.Exclude.Contains)) :
            axis.Include is not null && axis.Include.All(pair.Value.Include.Contains);
    });
    private static bool MatchAxis(FormatScope scope, string name, string? value)
    {
        if (!scope.Axes.TryGetValue(name, out var axis) || axis.Include is null && axis.Exclude.Length == 0) return true;
        if (value is null) throw new FormatBlocked("ambiguous_target", "Cannot reliably determine scope axis: " + name);
        return (axis.Include is null || axis.Include.Contains(value)) && !axis.Exclude.Contains(value);
    }
    private static bool ObjectMatches(AcademicObject obj, EffectiveFormatRule rule, FormatScope scope)
    {
        var role = obj.Role;
        if (rule.Target.SemanticRole == "page_number" && obj.Kind == "paragraph" && PageRuns(obj.Node).Count > 0) role = "page_number";
        if (rule.Target.SemanticRole == "citation" && rule.PropertyId.StartsWith("font.", StringComparison.Ordinal) && obj.Kind == "paragraph" &&
            (obj.Node.Descendants(W + "r").Any(r => r.Annotation<CitationMarker>() is not null) || PageRuns(obj.Node, "CITATION").Count > 0)) role = "citation";
        if (obj.Kind == "section" && rule.Target.SemanticRole != "page" && !rule.PropertyId.StartsWith("page_number.", StringComparison.Ordinal))
        {
            if (obj.Region != rule.Target.SemanticRole) throw new FormatBlocked("ambiguous_target", "Requested role shares a Word section with other or unknown regions; section-wide expansion is withheld.");
            role = rule.Target.SemanticRole;
        }
        if (rule.PropertyId == "document.position" && role.EndsWith("_heading", StringComparison.Ordinal)) role = role[..^8];
        if (obj.Kind == "section" && rule.PropertyId.StartsWith("page_number.", StringComparison.Ordinal)) role = "page_number";
        // A property applies to the actual minimum Word object; never promote a filtered paragraph rule to a section.
        var roles = scope.Axes.GetValueOrDefault("roles", new FormatAxis(null, []));
        var roleMatch = roles.Include is null || roles.Include.Contains(role) || roles.Include.Contains("table") && obj.Kind == "paragraph" && role.StartsWith("table_", StringComparison.Ordinal) ||
            roles.Include.Contains("toc") && role.StartsWith("toc_heading_", StringComparison.Ordinal);
        if (!roleMatch || roles.Exclude.Contains(role)) return false;
        return MatchAxis(scope, "regions", obj.Region) && MatchAxis(scope, "region_zone", obj.Zone) && MatchAxis(scope, "chapter", obj.Chapter) &&
            MatchAxis(scope, "object_ordinal", obj.Ordinal) && MatchAxis(scope, "object_language", obj.Language);
    }

    private static void PlanRule(AcademicPackage package, EffectiveFormatRule rule, FormatFragment fragment, List<Prepared> prepared, List<string> withheld)
    {
        var prop = rule.PropertyId;
        var kind = prop.StartsWith("font.", StringComparison.Ordinal) || prop.StartsWith("paragraph.", StringComparison.Ordinal) || prop is "caption.position" or "document.position" ? "paragraph" : prop == "table.border_style" ? "table" : "section";
        var candidates = package.Objects.Where(o => o.Kind == kind).ToArray();
        if (prop == "toc.max_depth")
        {
            var fields = package.Xml["word/document.xml"].Descendants().Where(e => e.Name == W + "instrText" && Regex.IsMatch(e.Value, @"^\s*TOC\b", RegexOptions.IgnoreCase) ||
                e.Name == W + "fldSimple" && Regex.IsMatch((string?)e.Attribute(W + "instr") ?? "", @"^\s*TOC\b", RegexOptions.IgnoreCase)).ToList();
            if (fields.Count == 0 && ManualToc(package, rule.Value.Normalized.GetInt32()) is { } manual) fields.Add(manual);
            foreach (var instr in fields)
            {
                var paragraph = instr.Ancestors(W + "p").FirstOrDefault();
                var obj = package.Objects.FirstOrDefault(o => o.Node == paragraph);
                if (obj is null) continue;
                if (obj.Unsafe) { withheld.Add(obj.Id + ": unsafe field container"); continue; }
                obj = obj with { Role = "toc", Region = "toc" };
                if (ObjectMatches(obj, rule, fragment.Scope)) Add(instr, obj);
            }
            return;
        }
        foreach (var obj in candidates)
        {
            var objectStart = prepared.Count;
            try
            {
            if (!ObjectMatches(obj, rule, fragment.Scope)) continue;
            if (obj.Unsafe) throw new FormatBlocked("ambiguous_target", "Matched object contains revisions, hidden text or protected structures.");
            if (prop.StartsWith("font.", StringComparison.Ordinal))
            {
                foreach (var run in obj.Node.Descendants(W + "r").Where(r => r.Ancestors(W + "p").FirstOrDefault() == obj.Node && r.Elements(W + "t").Any()))
                {
                    if (rule.Target.SemanticRole == "page_number" && !PageRuns(obj.Node).Contains(run)) continue;
                    if (rule.Target.SemanticRole == "citation" && obj.Role != "citation" && run.Annotation<CitationMarker>() is null && !PageRuns(obj.Node, "CITATION").Contains(run)) continue;
                    if (run.Elements().Any(e => e.Name != W + "rPr" && e.Name != W + "t")) throw new FormatBlocked("ambiguous_target", "Scoped text run includes non-text content.");
                    if (package.Effective(run, "rPr", "rtl") is "1" or "true" || package.Effective(run, "rPr", "cs") is "1" or "true")
                        throw new FormatBlocked("ambiguous_target", "Explicit complex-script font selection needs a script-aware target.");
                    foreach (var script in AcademicPackage.Text(run).EnumerateRunes().Select(AcademicPackage.Script).Distinct())
                        if (MatchAxis(fragment.Scope, "characters", script)) Add(run, obj, script);
                }
            }
            else if (prop == "page.margin.all")
            {
                foreach (var component in new[] { "top", "bottom", "left", "right" })
                    if (MatchAxis(fragment.Scope, "property_component", component)) Add(obj.Node, obj, null, component);
            }
            else if (prop.StartsWith("page.margin.", StringComparison.Ordinal) && fragment.Scope.Axes.ContainsKey("property_component"))
            {
                var component = prop.Split('.').Last();
                if (MatchAxis(fragment.Scope, "property_component", component)) Add(obj.Node, obj, null, component);
            }
            else if (prop == "document.position")
            {
                // Region operations start at the section label; body members are never moved independently.
                if (obj.Role.EndsWith("_heading", StringComparison.Ordinal)) Add(obj.Node, obj);
            }
            else Add(obj.Node, obj);
            }
            catch (FormatBlocked error)
            {
                prepared.RemoveRange(objectStart, prepared.Count - objectStart);
                withheld.Add(obj.Id + ": " + error.Message);
            }
        }
        void Add(XElement node, AcademicObject obj, string? script = null, string? component = null)
        {
            var family = prop == "page.margin.all" || prop is "page.margin.top" or "page.margin.bottom" or "page.margin.left" or "page.margin.right" ? "page.margin." + component :
                prop is "paragraph.first_line_indent" or "paragraph.hanging_indent" ? "paragraph.initial_indent" : prop;
            var slot = obj.Part + ":" + AcademicPackage.PathOf(node) + ":" + family + ":" + script;
            var item = new Prepared(rule, fragment, obj, node, script, component, null, slot);
            if (prop == "table.border_style") WriteBorders(package, new XElement(node), rule.Value.Normalized.GetString()!);
            else if (prop == "document.position") _ = RegionNodes(node);
            else if (prop != "caption.position") FormatProperties.Write(package, new XElement(node), rule, script, component);
            var before = package.NewFields.Contains(node) ? null : Read(package, node, item);
            prepared.Add(item with { Before = before });
        }
    }
    private static string Canonical(EffectiveFormatRule rule)
    {
        var val = rule.Value.Normalized;
        if (val.ValueKind == JsonValueKind.Number && rule.Value.Unit is "cm" or "mm" or "pt")
            return Math.Round(val.GetDouble() * (rule.Value.Unit == "cm" ? 72 / 2.54 : rule.Value.Unit == "mm" ? 72 / 25.4 : 1), 6).ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + (rule.PropertyId.Contains("indent", StringComparison.Ordinal) ? rule.PropertyId : "length");
        return rule.PropertyId + ":" + val.GetRawText() + ":" + rule.Value.Unit;
    }
    private static int Rank(string prop) => prop switch { "page.paper_size" => 0, "page.dimensions" => 1, "page.orientation" => 2, "caption.position" or "document.position" => 9, _ => 3 };
    private static double Tolerance(EffectiveFormatRule rule) => rule.Value.Unit == "cm" ? 0.002 : rule.Value.Unit == "mm" ? 0.02 : rule.Value.Unit is "characters" or "lines" ? 0.006 : 0.026;
    private static FormatOperation Operation(Prepared p, XElement target, string status, JsonElement after, bool changed = false) => new(
        "op:" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(p.Rule.RuleId + p.Fragment.FragmentId + p.Slot + AcademicPackage.PathOf(target))))[..24].ToLowerInvariant(),
        p.Rule.RuleId, p.Fragment.FragmentId, p.Object.Id, p.Object.Part, AcademicPackage.PathOf(target), p.Rule.PropertyId, p.Component, p.Script,
        p.Before, after, p.Rule.PropertyId.StartsWith("font.", StringComparison.Ordinal) ? "run" : p.Object.Kind, status, changed,
        status == "pending_manual_check" ? "Field definition verified; rendered cache needs a separate refresh provider." : "Effective property is checked against the full typed scope.");
    private static FormatRuleResult[] Summarize(List<FormatRuleResult> results, List<FormatOperation> operations) => results.Select(r =>
    {
        var ops = operations.Where(o => o.RuleId == r.RuleId).ToArray();
        if (ops.Length == 0) return r;
        var status = r.Status is "pending_conflict" or "pending_condition" or "ambiguous_target" ? r.Status : ops.Any(o => o.Status == "pending_manual_check") ? "pending_manual_check" :
            ops.Any(o => o.Status == "modified_verified") ? "modified_verified" : ops.Any(o => o.Status == "planned") ? "planned" : "already_satisfied";
        return r with { Status = status, TargetCount = ops.Length };
    }).ToArray();

    private static List<(XElement Node, string Script)> SplitRun(XElement run)
    {
        var text = AcademicPackage.Text(run);
        var groups = new List<(string Script, StringBuilder Text)>();
        foreach (var rune in text.EnumerateRunes())
        {
            var script = AcademicPackage.Script(rune);
            if (groups.Count == 0 || groups[^1].Script != script) groups.Add((script, new StringBuilder()));
            groups[^1].Text.Append(rune.ToString());
        }
        if (groups.Count == 1) return [(run, groups[0].Script)];
        var pieces = new List<(XElement Node, string Script)>();
        foreach (var (script, content) in groups)
        {
            var clone = new XElement(run.Name, run.Attributes(), run.Element(W + "rPr") is { } properties ? new XElement(properties) : null,
                new XElement(W + "t", new XAttribute(XNamespace.Xml + "space", "preserve"), content.ToString()));
            run.AddBeforeSelf(clone); pieces.Add((clone, script));
        }
        run.Remove();
        return pieces;
    }
    private static JsonElement? Read(AcademicPackage package, XElement node, Prepared p) => p.Rule.PropertyId switch
    {
        "table.border_style" => ReadBorders(node), "caption.position" => CaptionPosition(node),
        "document.position" => RegionPosition(package, node, p.Rule.Value.Normalized.GetString()), _ => FormatProperties.Read(package, node, p.Rule, p.Script, p.Component),
    };
    private static void Write(AcademicPackage package, XElement node, Prepared p)
    {
        switch (p.Rule.PropertyId)
        {
            case "table.border_style": WriteBorders(package, node, p.Rule.Value.Normalized.GetString()!); break;
            case "caption.position": MoveCaption(node, p.Rule.Value.Normalized.GetString()!); break;
            case "document.position": MoveRegion(package, node, p.Rule.Value.Normalized.GetString()!); break;
            default: FormatProperties.Write(package, node, p.Rule, p.Script, p.Component); break;
        }
    }

    private static readonly string[] BorderSides = ["top", "left", "bottom", "right", "insideH", "insideV"];
    private static JsonElement? ReadBorders(XElement table)
    {
        var cells = table.Elements(W + "tr").SelectMany(r => r.Elements(W + "tc")).ToArray();
        var borders = table.Element(W + "tblPr")?.Element(W + "tblBorders");
        if (borders is null || cells.Any(c => c.Element(W + "tcPr")?.Element(W + "tcBorders") is null)) return null;
        bool Visible(XElement? b) => (string?)b?.Attribute(W + "val") is not (null or "nil" or "none");
        if (BorderSides.All(s => !Visible(borders.Element(W + s))) && cells.All(c => BorderSides.All(s => !Visible(c.Element(W + "tcPr")?.Element(W + "tcBorders")?.Element(W + s))))) return FormatProperties.Json("none");
        if (BorderSides.All(s => Visible(borders.Element(W + s))) && cells.All(c => BorderSides.All(s => Visible(c.Element(W + "tcPr")?.Element(W + "tcBorders")?.Element(W + s))))) return FormatProperties.Json("all_borders");
        var rows = table.Elements(W + "tr").ToArray();
        if (rows.Length < 2) return null;
        var header = HeaderEnd(rows);
        var threeLine = Visible(borders.Element(W + "top")) && Visible(borders.Element(W + "bottom")) && new[] { "left", "right", "insideH", "insideV" }.All(s => !Visible(borders.Element(W + s))) &&
            rows.Select((row, i) => row.Elements(W + "tc").All(c => BorderSides.All(s => Visible(c.Element(W + "tcPr")?.Element(W + "tcBorders")?.Element(W + s)) ==
                (s == "top" && (i == 0 || i == header + 1) || s == "bottom" && (i == header || i == rows.Length - 1))))).All(v => v);
        return threeLine ? FormatProperties.Json("three_line") : null;
    }
    private static int HeaderEnd(XElement[] rows)
    {
        var end = -1;
        for (var i = 0; i < rows.Length && rows[i].Element(W + "trPr")?.Element(W + "tblHeader") is { } header && AcademicPackage.On(header.Attribute(W + "val")); i++) end = i;
        return end >= 0 ? end : 0;
    }
    private static void WriteBorders(AcademicPackage package, XElement table, string style)
    {
        var rows = table.Elements(W + "tr").ToArray();
        if (style == "three_line" && rows.Length < 2 || table.Descendants(W + "vMerge").Any() || table.Descendants(W + "hMerge").Any() || table.Elements(W + "tr").Any(r => r.Element(W + "tblPrEx") is not null))
            throw new FormatBlocked("ambiguous_target", "Complex merged or exceptional table borders need explicit mapping.");
        var inheritedSpacing = package.StyleChain((string?)table.Element(W + "tblPr")?.Element(W + "tblStyle")?.Attribute(W + "val"))
            .SelectMany(s => s.Descendants(W + "tblCellSpacing"));
        if (style == "three_line" && table.Descendants(W + "tblCellSpacing").Concat(inheritedSpacing).Any(s => FormatProperties.Numeric((string?)s.Attribute(W + "w")) != 0))
            throw new FormatBlocked("ambiguous_target", "Spaced cells cannot form three continuous horizontal borders without changing additional geometry.");
        var header = HeaderEnd(rows);
        if (style == "three_line" && header >= rows.Length - 1) throw new FormatBlocked("ambiguous_target", "Three-line table requires distinct header and body rows.");
        var borders = FormatProperties.Ensure(FormatProperties.Ensure(table, "tblPr"), "tblBorders");
        foreach (var side in BorderSides) Border(borders, side, style == "all_borders" || style == "three_line" && side is "top" or "bottom");
        for (var i = 0; i < rows.Length; i++)
            foreach (var cell in rows[i].Elements(W + "tc"))
            {
                var cellBorders = FormatProperties.Ensure(FormatProperties.Ensure(cell, "tcPr"), "tcBorders");
                foreach (var side in BorderSides) Border(cellBorders, side, style == "all_borders" || style == "three_line" &&
                    (side == "top" && (i == 0 || i == header + 1) || side == "bottom" && (i == header || i == rows.Length - 1)));
                foreach (var diagonal in new[] { "tl2br", "tr2bl" }) if (cellBorders.Element(W + diagonal) is { } existing) existing.SetAttributeValue(W + "val", "nil");
            }
        static void Border(XElement parent, string side, bool visible)
        {
            var border = FormatProperties.Ensure(parent, side); border.SetAttributeValue(W + "val", visible ? "single" : "nil");
            if (visible && border.Attribute(W + "sz") is null) border.SetAttributeValue(W + "sz", "4");
        }
    }

    private static (XElement Object, string Position) CaptionPair(XElement node)
    {
        bool IsObject(XElement value) => value.Name == W + "tbl" || value.Name == W + "p" && value.Descendants(W + "drawing").Count() == 1;
        var previous = node.ElementsBeforeSelf().LastOrDefault(); var next = node.ElementsAfterSelf().FirstOrDefault();
        var pairs = new List<(XElement, string)>();
        if (previous is not null && IsObject(previous)) pairs.Add((previous, "below"));
        if (next is not null && IsObject(next)) pairs.Add((next, "above"));
        if (pairs.Count != 1 || node.Element(W + "pPr")?.Element(W + "sectPr") is not null) throw new FormatBlocked("ambiguous_target", "Caption must have one unique adjacent object without a section break.");
        var isTable = Regex.IsMatch(AcademicPackage.Text(node), @"^(?:表|Table)", RegexOptions.IgnoreCase);
        if (isTable != (pairs[0].Item1.Name == W + "tbl")) throw new FormatBlocked("ambiguous_target", "Caption/object kind mismatch.");
        return pairs[0];
    }
    private static JsonElement? CaptionPosition(XElement node) => FormatProperties.Json(CaptionPair(node).Position);
    private static void MoveCaption(XElement node, string position)
    {
        var pair = CaptionPair(node); if (pair.Position == position) return;
        node.Remove(); if (position == "above") pair.Object.AddBeforeSelf(node); else pair.Object.AddAfterSelf(node);
    }
    private static List<XElement> RegionNodes(XElement node)
    {
        if (node.Parent?.Name != W + "body") throw new FormatBlocked("ambiguous_target", "Region label is not a top-level paragraph.");
        var nodes = new List<XElement> { node };
        foreach (var sibling in node.ElementsAfterSelf())
        {
            if (sibling.Name == W + "sectPr") break;
            var text = AcademicPackage.Text(sibling).Trim();
            if (sibling.Name == W + "p" && (Regex.IsMatch(text, @"^(?:摘要|目录|参考文献|致谢|附录|Abstract|References|Appendix|Acknowledgements)$", RegexOptions.IgnoreCase) ||
                sibling.Element(W + "pPr")?.Element(W + "pStyle")?.Attribute(W + "val")?.Value == "Heading1")) break;
            nodes.Add(sibling);
        }
        if (nodes.Any(n => AcademicPackage.Unsafe(n) || n.Descendants(W + "sectPr").Any())) throw new FormatBlocked("ambiguous_target", "Moving a region would cross protected content or section boundaries.");
        return nodes;
    }
    private static JsonElement? RegionPosition(AcademicPackage package, XElement node, string? requested)
    {
        var body = package.Objects.Where(o => o.Part == "word/document.xml" && o.Region == "body" && o.Node.Parent?.Name == W + "body").Select(o => o.Node).ToList();
        if (body.Count == 0) throw new FormatBlocked("ambiguous_target", "Reliable body boundaries are required for region positioning.");
        var nodes = RegionNodes(node); var siblings = node.Parent!.Elements().ToList();
        if (siblings.IndexOf(nodes[^1]) < siblings.IndexOf(body[0])) return FormatProperties.Json("before_body");
        if (nodes[^1].ElementsAfterSelf().All(e => e.Name == W + "sectPr")) return FormatProperties.Json(requested == "after_body" ? "after_body" : "document_end");
        if (siblings.IndexOf(node) > siblings.IndexOf(body[^1])) return FormatProperties.Json("after_body");
        return null;
    }
    private static void MoveRegion(AcademicPackage package, XElement node, string position)
    {
        var body = package.Objects.Where(o => o.Part == "word/document.xml" && o.Region == "body" && o.Node.Parent?.Name == W + "body").Select(o => o.Node).ToList();
        if (body.Count == 0) throw new FormatBlocked("ambiguous_target", "Reliable body boundaries are required.");
        var parent = node.Parent!; var nodes = RegionNodes(node);
        foreach (var item in nodes) item.Remove();
        if (position == "before_body") body[0].AddBeforeSelf(nodes);
        else if (position == "after_body") body[^1].AddAfterSelf(nodes);
        else if (parent.Element(W + "sectPr") is { } end) end.AddBeforeSelf(nodes); else parent.Add(nodes);
    }
    private static string[] ProtectedNodes(AcademicPackage package) => package.Xml.OrderBy(p => p.Key).SelectMany(p => p.Value.Descendants()
        .Where(e => e.Name.Namespace != W || new[] { "hyperlink", "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "commentReference", "drawing", "pict", "object", "footnoteReference", "endnoteReference", "gridSpan", "vMerge", "hMerge", "tblGrid" }.Contains(e.Name.LocalName))
        .Select(e => p.Key + ":" + e.Name + ":" + string.Join(";", e.Attributes().OrderBy(a => a.Name.ToString()).Select(a => a.ToString())) +
            (e.Name.LocalName is "drawing" or "pict" or "object" or "tblGrid" ? ":" + e.ToString(SaveOptions.DisableFormatting) : "")))
        .Order(StringComparer.Ordinal).ToArray();

    private static HashSet<XElement> PageRuns(XElement paragraph, string keyword = "PAGE")
    {
        var result = new HashSet<XElement>();
        var stack = new List<(StringBuilder Code, bool Result)>();
        foreach (var run in paragraph.Descendants(W + "r").Where(r => r.Ancestors(W + "p").FirstOrDefault() == paragraph))
        {
            if (run.Ancestors(W + "fldSimple").Any(f => Regex.IsMatch((string?)f.Attribute(W + "instr") ?? "", @"^\s*" + keyword + @"\b", RegexOptions.IgnoreCase))) result.Add(run);
            foreach (var item in run.Elements())
            {
                if (item.Name == W + "fldChar")
                {
                    var type = (string?)item.Attribute(W + "fldCharType");
                    if (type == "begin") stack.Add((new StringBuilder(), false));
                    else if (type == "separate" && stack.Count > 0) stack[^1] = (stack[^1].Code, true);
                    else if (type == "end" && stack.Count > 0) stack.RemoveAt(stack.Count - 1);
                }
                else if (item.Name == W + "instrText" && stack.Count > 0) stack[^1].Code.Append(item.Value);
                else if (item.Name == W + "t" && stack.Any(s => s.Result && Regex.IsMatch(s.Code.ToString(), @"^\s*" + keyword + @"\b", RegexOptions.IgnoreCase))) result.Add(run);
            }
        }
        return result;
    }
    private sealed class CitationMarker;
    private static void PrepareCitations(AcademicPackage package)
    {
        var identifiers = package.Objects.Where(o => o.Role == "bibliography").Select(o => Regex.Match(AcademicPackage.Text(o.Node), @"^\s*\[(\d+)\]"))
            .Where(m => m.Success).Select(m => m.Groups[1].Value).ToHashSet();
        if (identifiers.Count == 0) return;
        foreach (var obj in package.Objects.Where(o => o.Kind == "paragraph" && o.Role is "body" or "abstract" && !o.Unsafe))
            foreach (var run in obj.Node.Descendants(W + "r").ToArray())
            {
                if (run.Elements().Any(e => e.Name != W + "rPr" && e.Name != W + "t")) continue;
                var text = AcademicPackage.Text(run);
                var matches = Regex.Matches(text, @"\[(\d+(?:[,，\-–]\d+)*)\]").Where(m => Regex.Matches(m.Groups[1].Value, @"\d+").All(n => identifiers.Contains(n.Value))).ToList();
                if (matches.Count == 0) continue;
                var offset = 0;
                foreach (var match in matches)
                {
                    if (match.Index > offset) Add(text[offset..match.Index], false);
                    Add(match.Value, true); offset = match.Index + match.Length;
                }
                if (offset < text.Length) Add(text[offset..], false);
                run.Remove();
                void Add(string content, bool citation)
                {
                    var clone = new XElement(run.Name, run.Attributes(), run.Element(W + "rPr") is { } properties ? new XElement(properties) : null,
                        new XElement(W + "t", new XAttribute(XNamespace.Xml + "space", "preserve"), content));
                    if (citation) clone.AddAnnotation(new CitationMarker());
                    run.AddBeforeSelf(clone);
                }
            }
    }
    private static XElement? ManualToc(AcademicPackage package, int depth)
    {
        var entries = package.Objects.Where(o => o.Part == "word/document.xml" && o.Kind == "paragraph" && o.Region == "toc" && o.Role != "toc_heading").ToList();
        if (entries.Count == 0 || entries.Any(o => o.Unsafe || o.Node.Parent?.Name != W + "body" || o.Node.Descendants(W + "sectPr").Any())) return null;
        var headings = package.Objects.Where(o => o.Kind == "paragraph" && o.Part == "word/document.xml" && o.Role.StartsWith("heading_", StringComparison.Ordinal) &&
            int.TryParse(o.Role.AsSpan(8), out var level) && level <= depth).Select(o => AcademicPackage.Text(o.Node).Trim()).ToList();
        if (headings.Count == 0 || headings.Distinct().Count() != headings.Count || entries.Count != headings.Count) return null;
        var titles = entries.Select(o => string.Concat(o.Node.Descendants().Where(n => n.Name == W + "t" || n.Name == W + "tab").Select(n => n.Name == W + "tab" ? "\t" : n.Value)))
            .Select(t => Regex.Match(t, @"^(.+?)\t+[ivxlcdmIVXLCDM\d]+\s*$")).ToList();
        if (titles.Any(m => !m.Success) || !titles.Select(m => m.Groups[1].Value.Trim()).SequenceEqual(headings)) return null;
        if (entries[0].Node.ElementsAfterSelf().Take(entries.Count - 1).Where(e => e.Name == W + "p").Count() != entries.Count - 1) return null;
        var field = new XElement(W + "instrText", new XAttribute(XNamespace.Xml + "space", "preserve"), " TOC \\o \"1-" + depth + "\" \\h ");
        var firstRun = entries[0].Node.Elements(W + "r").FirstOrDefault();
        if (firstRun is null) return null;
        firstRun.AddBeforeSelf(new XElement(W + "r", new XElement(W + "fldChar", new XAttribute(W + "fldCharType", "begin"), new XAttribute(W + "dirty", "1"))),
            new XElement(W + "r", field), new XElement(W + "r", new XElement(W + "fldChar", new XAttribute(W + "fldCharType", "separate"))));
        entries[^1].Node.Add(new XElement(W + "r", new XElement(W + "fldChar", new XAttribute(W + "fldCharType", "end"))));
        package.NewFields.Add(field);
        return field;
    }
}
