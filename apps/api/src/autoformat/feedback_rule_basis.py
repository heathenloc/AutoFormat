"""Selected-version rule sources. Never infer an empty basis from a report."""
from brief_parser.domain.academic_decisions import AcademicEffectiveRule
from brief_parser.domain.academic_semantics import AcademicRuleSemantics, AcademicConstraint
from brief_parser.compilers.academic_scope import analyze_rules, base_scope
from .academic_decisions import AcademicDecisionStore
from .academic_intake import AcademicTaskIntake
from .feedback_rules_contracts import FeedbackRuleBasis
from .rule_snapshots import RuleSnapshotError


def source_loader(versions, snapshots, intake=None):
    # load_bundle reads immutable intake artifacts; the parser service is never
    # called on this preview/feedback path.
    decisions = AcademicDecisionStore(versions, intake or AcademicTaskIntake(store=versions, service=None))
    def load(context):
        if versions.get_academic_intake(context.task_id) is not None:
            baseline = decisions._engine(context.task_id).compile()
            selected = baseline if baseline.snapshot_id == context.rules_snapshot_id else decisions.load(context.task_id, context.rules_snapshot_id)
            return FeedbackRuleBasis(academic_rules_snapshot_id=selected.snapshot_id,
                rules=selected.rules, fragments=selected.fragments)
        try:
            legacy = snapshots.load(context.task_id)
        except RuleSnapshotError as error:
            if error.status == "needs_user_input": return None
            raise
        if legacy.snapshot_id != context.rules_snapshot_id:
            raise RuleSnapshotError("validation_failed", "版本引用了另一份 Brief 规则快照。")
        rules = []
        for rule in legacy.ruleset.rules:
            if rule.source_kind == "template_observation_confirmed":
                # Legacy projections lack the observation identities needed
                # for effective-rule provenance; retain a pending basis.
                return None
            if rule.semantics is None and rule.condition:
                return None
            semantics = rule.semantics or AcademicRuleSemantics(scope=base_scope(rule.target.semantic_role, rule.property_id, rule.character_scope), constraint=AcademicConstraint())
            rules.append(AcademicEffectiveRule(rule_id=rule.rule_id, source_kind="brief_explicit" if rule.source_kind == "brief_explicit" else "user_decision", source_rule_ids=[rule.rule_id],
                evidence_refs=rule.evidence_refs, observation_ids=[], decision_ids=[rule.decision_id] if rule.decision_id else [], target=rule.target,
                property_id=rule.property_id, value=rule.value, character_scope=rule.character_scope,
                semantics=semantics, status="check_only" if rule.status == "unsupported" else rule.status,
                execution_support="report_only" if rule.status == "unsupported" else "typed", reason=rule.reason))
        fragments = [f for f in legacy.ruleset.fragments if f.rule_id in {r.rule_id for r in rules}] or analyze_rules(rules)[2]
        return FeedbackRuleBasis(academic_rules_snapshot_id=legacy.snapshot_id, rules=rules, fragments=fragments)
    return load
