// Wire names match the versioned Python/JSON contracts. PDF offsets are UTF-16.
export interface Version {
  version_id: string; parent_version_id: string | null; sequence: number;
  kind: 'original' | 'output'; status: string; docx_sha256: string; created_at: string;
}
export interface VersionList { status: 'ready'; working_version_id: string; versions: Version[] }
export interface FeedbackContext {
  schema_version: 'feedback-version-context/1.0'; context_id: string; task_id: string;
  base_version_id: string; base_docx_sha256: string; preview_artifact_id: string;
  preview_pdf_sha256: string; preview_metadata_sha256: string; page_count: number;
  renderer_id: string; renderer_version: string; rules_snapshot_id: string;
  brief_version_id: string; feedback_rules_snapshot_id: string | null;
}
export interface PdfSpan {
  page: number; start_item: number; start_offset_utf16: number;
  end_item: number; end_offset_utf16: number;
}
export interface SelectionHint {
  selected_text: string; context_before: string; context_after: string; spans: PdfSpan[];
}
export interface Submission {
  schema_version: 'feedback-submission/1.0'; request_id: string; task_id: string;
  base_version_id: string; expected_base_docx_sha256: string; expected_context_id: string;
  preview_artifact_id: string; expected_preview_pdf_sha256: string;
  raw_text: string; requested_scope: FeedbackScope; selection: SelectionHint | null;
}
export type FeedbackScope = 'selection' | 'paragraph' | 'same_kind' | 'document';
export interface FormatValue { normalized: string | number | boolean | { mode: string; amount: number }; unit: string | null }
export interface ApplicabilityScope { axes: Record<string, { include: string[] | null; exclude: string[] }> }
export interface FormatCandidate { candidate_id: string; property_id: string; value: FormatValue; requested_scope: FeedbackScope; semantic_role: string | null; character_scope: string; applicability_scope?: ApplicabilityScope | null }
export interface PartialFormat { candidate_id: string; property_id: string | null; value: FormatValue | null; requested_scope: FeedbackScope | null; semantic_role: string | null }
export interface ScopeReview { review_id: string; candidate_id: string; requested_scope: FeedbackScope; effective_scope: FeedbackScope; minimum_unit: string; target_ids: string[]; estimated_affected_count: number; requires_confirmation: boolean; reason: string }
export interface Interpretation { kind: 'execution_defect' | 'new_rule' | 'clarification_needed' | 'question' | 'out_of_scope'; candidates: FormatCandidate[]; understood: PartialFormat[]; missing_fields: string[]; scope_reviews: ScopeReview[]; existing_rule_ids: string[]; reason: string }
export interface DraftReview extends Interpretation { schema_version: 'feedback-draft-review/1.0'; review_id: string; task_id: string; base_version_id: string; version_context_id: string; source_submission_sha256: string; target_status: string }
export interface ParseResult extends Interpretation { result_id: string; feedback_id: string; task_id: string; version_context_id: string; source_submission_sha256: string }
export interface FeedbackAnalysis { schema_version: 'feedback-analysis/1.0'; analysis_id: string; interpretation: ParseResult; selection: SelectionResolution | null; confirmed_review_ids: string[]; decision_count: number }
export type ProcessingAnswer = { action: 'confirm_scope'; accepted_review_ids: string[] } | { action: 'clarify_format'; format: FormatCandidate };
export interface ProcessingConfirmation { schema_version: 'feedback-confirmation-request/1.0'; request_id: string; task_id: string; base_version_id: string; expected_base_docx_sha256: string; expected_context_id: string; feedback_id: string; expected_parse_result_id: string; raw_answer: string; answer: ProcessingAnswer }
export type ConflictAction = 'keep_rule' | 'local_exception' | 'update_rule';
export interface RuleSpan { object_id: string; start_utf16: number | null; length_utf16: number | null }
export interface CompiledRule { rule_id: string; source_kind: 'academic' | 'feedback'; feedback_id: string | null; property_id: string; value: FormatValue; original_requirement: string; evidence_quotes: string[]; requested_scope: FeedbackScope }
export interface RuleConflict { conflict_id: string; feedback_id: string; candidate_id: string; incoming_rule_id: string; existing_rule_id: string; property_id: string; spans: RuleSpan[]; allowed_actions: ConflictAction[]; resolution: ConflictAction | null; decision_id: string | null; reason: string }
export interface RulesSnapshot { schema_version: 'feedback-rule-snapshot/1.1' | 'feedback-rule-snapshot/1.2'; snapshot_id: string; task_id: string; base_version_id: string; base_docx_sha256: string; version_context_id: string; revision: number; basis_available: boolean; rules: CompiledRule[]; fragments: { rule_id: string; property_id: string; span: RuleSpan; status: 'verified' | 'pending_conflict' | 'pending_scope' | 'pending_basis' | 'pending_target' | 'superseded' }[]; conflicts: RuleConflict[]; decision_ids: string[]; invalidated_decision_ids: string[]; pending_feedback_ids: string[]; status: 'ready' | 'needs_user_input' | 'no_rule_change'; reason: string }
export interface RulesReview { schema_version: 'feedback-rules-review/1.0' | 'feedback-rules-review/1.1'; review_id: string; parse_result: ParseResult; snapshot: RulesSnapshot }
export interface ExecutionRequest { schema_version: 'feedback-execution-request/1.0'; request_id: string; task_id: string; base_version_id: string; expected_base_docx_sha256: string; expected_context_id: string; expected_snapshot_id: string }
export interface ExecutionResult { schema_version: 'feedback-execution/1.0'; request_id: string; task_id: string; base_version_id: string; snapshot_id: string; phase: 'planning' | 'editing' | 'validating' | 'rendering' | 'ready' | 'no_document_change' | 'failed'; version_id: string | null; error_status: string | null; reason: string }
export interface RulesDecision { schema_version: 'feedback-decision-request/1.1'; request_id: string; task_id: string; base_version_id: string; expected_base_docx_sha256: string; expected_context_id: string; feedback_id: string; expected_parse_result_id: string; expected_snapshot_id: string; conflict_id: string; action: ConflictAction; raw_answer: string }
export interface Receipt {
  schema_version: 'feedback-receipt/1.0'; feedback_id: string; base_version_id: string;
  task_id: string; status: 'received'; created_at: string; replayed: boolean;
}
export interface SelectionResolution {
  schema_version: 'selection-resolution/1.0'; resolution_id: string; feedback_id: string; version_context_id: string;
  status: 'ready' | 'ambiguous' | 'needs_user_input' | 'unsupported_target' | 'stale_base_version' | 'stale_preview';
  reason: string;
  anchor: null | { anchor_id: string; base_version_id: string; ranges: { object_id: string; start_utf16: number; length_utf16: number; matched_text: string }[] };
  candidates: { candidate_id: string; object_id: string; location_label: string; excerpt: string }[];
}
export interface TargetConfirmation {
  schema_version: 'selection-target-confirmation/1.0'; request_id: string; task_id: string;
  base_version_id: string; feedback_id: string; expected_base_docx_sha256: string; expected_context_id: string;
  expected_resolution_id: string; candidate_id: string; raw_answer: string;
}
export interface Report {
  schema_version: 'version-report/1.0'; task_id: string; version_id: string;
  output_docx_sha256: string; preview: { artifact_id: string };
  summary: {
    format_status: 'verified' | 'partial' | 'unassessed'; this_round_change_count: number;
    cumulative_change_count: number; pending_count: number; note: string;
  };
  rules: { rule_id: string; original_requirement: string; property_id: string; status: string; reason: string; next_action: string | null; evidence_refs: { quote: string }[] }[];
  issues: { issue_id: string; status: string; reason: string; next_action: string }[];
}

export interface ContinuationRequest { schema_version: 'version-continuation-request/1.0'; request_id: string; task_id: string; version_id: string; expected_docx_sha256: string; expected_working_version_id: string }
export interface Continuation { schema_version: 'version-continuation/1.0'; request_id: string; task_id: string; continued_version_id: string; previous_working_version_id: string; working_version_id: string; replayed: boolean }
export interface WorkItem { feedback_id: string; created_at: string; raw_text: string; requested_scope: FeedbackScope; selected_text: string | null; status: 'needs_target' | 'needs_value' | 'needs_scope' | 'needs_conflict' | 'ready' | 'executing' | 'failed' | 'completed' | 'no_document_change' | 'rule_kept' | 'question' | 'out_of_scope' | 'blocked' | 'invalid'; reason: string; execution_request_id: string | null; output_version_id: string | null }
export interface WorkQueue { schema_version: 'feedback-work-queue/1.0'; queue_id: string; task_id: string; base_version_id: string; base_docx_sha256: string; version_context_id: string; working_version_id: string; rules_snapshot_id: string | null; items: WorkItem[]; next_before: number | null }
