using System.Text;
using System.Text.Json;
using System.Xml.Linq;

namespace AutoFormat.DocxEditor;

public sealed record FeedbackEditRule(string RuleId, string SourceKind, string SourceRuleId,
    string PropertyId, FormatValue Value);
public sealed record FeedbackEditFragment(string FragmentId, string RuleId, string PropertyId,
    string ObjectId, int? StartUtf16, int? LengthUtf16);
public sealed record FeedbackEditManifest(string SchemaVersion, string BaseVersionId, string BaseDocxSha256,
    string InputFile, string OutputFile, string RulesSnapshotId, FeedbackEditRule[] Rules, FeedbackEditFragment[] Fragments);

public static partial class AcademicFormatEditor
{
    public static AcademicEditResult ApplyFeedback(string directory, FeedbackEditManifest manifest, bool planOnly)
    {
        if (manifest.SchemaVersion != "feedback-edit-manifest/1.0" || manifest.Rules.Length > 1024 || manifest.Fragments.Length > 20000 ||
            manifest.Rules.Select(r => r.RuleId).Distinct().Count() != manifest.Rules.Length ||
            manifest.Fragments.Select(f => f.FragmentId).Distinct().Count() != manifest.Fragments.Length ||
            manifest.Rules.Any(r => r.SourceKind is not ("academic" or "feedback") || string.IsNullOrWhiteSpace(r.SourceRuleId)) ||
            manifest.Fragments.Any(f => !manifest.Rules.Any(r => r.RuleId == f.RuleId) ||
                !f.ObjectId.StartsWith("o:", StringComparison.Ordinal) || (f.StartUtf16 is null) != (f.LengthUtf16 is null) ||
                f.StartUtf16 < 0 || f.LengthUtf16 <= 0 ||
                f.PropertyId.StartsWith("font.", StringComparison.Ordinal) != (f.StartUtf16 is not null)))
            throw new InvalidDataException("Invalid explicit feedback edit manifest.");
        var scope = new FormatScope(new());
        // The Python source-replay boundary authorizes these exact targets.
        // No semantic selector from this manifest is evaluated by the editor.
        var rules = manifest.Fragments.GroupBy(f => (f.RuleId, f.PropertyId)).Select(group =>
        {
            var source = manifest.Rules.Single(r => r.RuleId == group.Key.RuleId);
            var prop = group.Key.PropertyId;
            if (source.PropertyId != prop && !(source.PropertyId == "page.margin.all" &&
                prop is "page.margin.top" or "page.margin.bottom" or "page.margin.left" or "page.margin.right"))
                throw new InvalidDataException("Fragment changed its typed source property.");
            return new EffectiveFormatRule("academic-effective-rule/1.0", Key(group.Key.RuleId, prop),
                "user_decision", [source.SourceRuleId], [], [], [manifest.RulesSnapshotId],
                new FormatTarget("paragraph", "body", "semantic_role"), prop, source.Value, "all",
                new FormatSemantics("academic-rule-semantics/1.0", scope, new FormatConstraint("eq", null, null), null),
                "typed", "verified", "Source-replayed explicit feedback target.");
        }).ToArray();
        var exact = manifest.Fragments.ToDictionary(f => f.FragmentId, f => f with { RuleId = Key(f.RuleId, f.PropertyId) });
        var internalManifest = new AcademicEditManifest("academic-edit-manifest/1.0", manifest.BaseVersionId,
            manifest.BaseDocxSha256, manifest.InputFile, manifest.OutputFile, manifest.RulesSnapshotId, rules,
            exact.Values.Select(f => new FormatFragment(f.FragmentId, f.RuleId, scope, "verified", [], "Exact target.")).ToArray());
        var result = ApplyCore(directory, internalManifest, planOnly, exact);
        var sources = exact.Values.GroupBy(f => f.RuleId).ToDictionary(g => g.Key, g => manifest.Fragments.First(f => f.FragmentId == g.First().FragmentId).RuleId);
        return result with { SchemaVersion = "feedback-edit-result/1.0",
            Operations = result.Operations.Select(o => o with { RuleId = sources[o.RuleId] }).ToArray(),
            Rules = result.Rules.GroupBy(r => sources[r.RuleId]).Select(g => new FormatRuleResult(g.Key,
                g.Any(r => r.Status == "modified_verified") ? "modified_verified" : g.First().Status,
                g.Sum(r => r.TargetCount), string.Join("; ", g.Select(r => r.Reason).Distinct()))).ToArray() };
        static string Key(string rule, string prop) => rule + ":" + prop;
    }

    private static void PrepareFeedbackRanges(AcademicPackage package, IEnumerable<FeedbackEditFragment> fragments)
    {
        foreach (var group in fragments.Where(f => f.StartUtf16 is not null).GroupBy(f => f.ObjectId))
        {
            var obj = package.Objects.SingleOrDefault(o => o.Id == group.Key && o.Kind == "paragraph")
                ?? throw new InvalidDataException("Feedback paragraph is absent.");
            if (obj.Unsafe) throw new FormatBlocked("ambiguous_target", "Feedback text container is protected.");
            var runs = obj.Node.Descendants(W + "r").Where(r => r.Ancestors(W + "p").FirstOrDefault() == obj.Node).ToArray();
            if (runs.Any(r => r.Elements().Any(e => e.Name != W + "rPr" && e.Name != W + "t")) ||
                obj.Node.Descendants().Any(e => e.Name == W + "fldSimple" || e.Name == W + "instrText") ||
                string.Concat(runs.Select(AcademicPackage.Text)) != AcademicPackage.Text(obj.Node))
                throw new FormatBlocked("ambiguous_target", "Feedback text includes an unsupported field or inline object.");
            var text = AcademicPackage.Text(obj.Node);
            var cuts = group.SelectMany(f => new[] { f.StartUtf16!.Value, checked(f.StartUtf16.Value + f.LengthUtf16!.Value) }).ToHashSet();
            if (cuts.Any(c => c < 0 || c > text.Length || c > 0 && c < text.Length && char.IsHighSurrogate(text[c - 1]) && char.IsLowSurrogate(text[c])))
                throw new InvalidDataException("Feedback range is outside text or splits a Unicode scalar.");
            var offset = 0;
            foreach (var run in runs)
            {
                var value = AcademicPackage.Text(run);
                var boundaries = cuts.Where(c => c > offset && c < offset + value.Length).Select(c => c - offset).Append(0).Append(value.Length).Distinct().Order().ToArray();
                if (boundaries.Length > 2)
                {
                    for (var i = 1; i < boundaries.Length; i++)
                        run.AddBeforeSelf(new XElement(run.Name, run.Attributes(), run.Element(W + "rPr") is { } pr ? new XElement(pr) : null,
                            new XElement(W + "t", new XAttribute(XNamespace.Xml + "space", "preserve"), value[boundaries[i - 1]..boundaries[i]])));
                    run.Remove();
                }
                offset += value.Length;
            }
        }
    }

    private static void PlanFeedbackRule(AcademicPackage package, EffectiveFormatRule rule, FormatFragment fragment,
        FeedbackEditFragment exact, List<Prepared> prepared)
    {
        var prop = rule.PropertyId;
        var kind = prop.StartsWith("font.", StringComparison.Ordinal) || prop.StartsWith("paragraph.", StringComparison.Ordinal) ? "paragraph" :
            prop == "table.border_style" ? "table" : prop.StartsWith("page.", StringComparison.Ordinal) ? "section" :
            throw new FormatBlocked("unsupported", "Feedback property has no explicit-target executor.");
        var obj = package.Objects.SingleOrDefault(o => o.Id == exact.ObjectId && o.Kind == kind)
            ?? throw new FormatBlocked("ambiguous_target", "Feedback object kind or identity differs.");
        if (obj.Unsafe) throw new FormatBlocked("ambiguous_target", "Feedback object is protected.");
        if (kind == "paragraph" && prop.StartsWith("font.", StringComparison.Ordinal))
        {
            var offset = 0;
            var count = prepared.Count;
            foreach (var run in obj.Node.Descendants(W + "r").Where(r => r.Ancestors(W + "p").FirstOrDefault() == obj.Node))
            {
                var text = AcademicPackage.Text(run);
                var end = offset + text.Length;
                if (text.Length > 0 && offset >= exact.StartUtf16 && end <= exact.StartUtf16 + exact.LengthUtf16)
                {
                    if (package.Effective(run, "rPr", "rtl") is "1" or "true" || package.Effective(run, "rPr", "cs") is "1" or "true")
                        throw new FormatBlocked("ambiguous_target", "Explicit complex-script formatting needs an additional target binding.");
                    foreach (var script in text.EnumerateRunes().Select(AcademicPackage.Script).Distinct()) Add(run, script);
                }
                offset = end;
            }
            if (prepared.Count == count) throw new FormatBlocked("no_target", "Feedback text range is empty.");
        }
        else Add(obj.Node, null);

        void Add(XElement node, string? script)
        {
            var component = prop.StartsWith("page.margin.", StringComparison.Ordinal) ? prop.Split('.').Last() : null;
            var family = prop is "paragraph.first_line_indent" or "paragraph.hanging_indent" ? "paragraph.initial_indent" : prop;
            var slot = obj.Part + ":" + AcademicPackage.PathOf(node) + ":" + family + ":" + script;
            var item = new Prepared(rule, fragment, obj, node, script, component, null, slot);
            if (prop == "table.border_style") WriteBorders(package, new XElement(node), rule.Value.Normalized.GetString()!);
            else FormatProperties.Write(package, new XElement(node), rule, script, component);
            prepared.Add(item with { Before = Read(package, node, item) });
        }
    }
}
