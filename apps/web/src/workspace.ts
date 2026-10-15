import type { Report, WorkItem } from './contracts';
import { propertyNames } from './feedback';

export const workNames: Record<WorkItem['status'], string> = {
  needs_target: '待确认位置', needs_value: '待补充格式', needs_scope: '待确认范围', needs_conflict: '待解决冲突',
  ready: '待核对／生成', executing: '正在执行', failed: '执行失败', completed: '已生成版本',
  no_document_change: '格式已满足', question: '咨询', out_of_scope: '超出处理范围', blocked: '需进一步核对', invalid: '依据校验失败',
  rule_kept: '已保留原规则',
};
export const isPending = (item: WorkItem) => !['completed', 'no_document_change', 'rule_kept', 'question', 'out_of_scope'].includes(item.status);
function text<K extends keyof HTMLElementTagNameMap>(tag: K, value: string, parent: HTMLElement) {
  const node = document.createElement(tag); node.textContent = value; parent.append(node); return node;
}
export function renderPendingReport(root: HTMLElement, report: Report) {
  root.replaceChildren();
  const rules = report.rules.filter(rule => !['modified_verified', 'already_satisfied'].includes(rule.status));
  root.hidden = !rules.length && !report.issues.length;
  if (root.hidden) return;
  const details = document.createElement('details'); root.append(details);
  text('summary', `报告待处理项 · ${rules.length + report.issues.length}`, details);
  text('p', '以下事项保留在此版本的报告中。未确认要求不会成为默认规则；需要人工处理的项目请按提示核对。', details).className = 'small muted';
  for (const rule of rules) {
    const item = document.createElement('article'); item.className = 'pending-report-item'; details.append(item);
    text('strong', propertyNames[rule.property_id] ?? '格式要求', item);
    text('p', rule.original_requirement, item);
    text('p', rule.reason, item);
    if (rule.next_action) text('p', `后续处理：${rule.next_action}`, item);
    const evidence = document.createElement('details'); item.append(evidence); text('summary', '查看原文依据', evidence);
    for (const ref of rule.evidence_refs) text('blockquote', ref.quote, evidence);
  }
  for (const issue of report.issues) {
    const item = document.createElement('article'); item.className = 'pending-report-item'; details.append(item);
    text('p', issue.reason, item); text('p', `后续处理：${issue.next_action}`, item);
  }
}
