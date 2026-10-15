import { ApiError, errorMessage, LocalApi } from './api';

const properties: Record<string, string> = {
  'font.family': '字体', 'font.size': '字号', 'font.bold': '加粗', 'font.italic': '斜体',
  'paragraph.alignment': '对齐', 'paragraph.line_spacing': '行距', 'paragraph.spacing_before': '段前间距',
  'paragraph.spacing_after': '段后间距', 'paragraph.first_line_indent': '首行缩进', 'paragraph.hanging_indent': '悬挂缩进',
  'paragraph.left_indent': '左缩进', 'paragraph.right_indent': '右缩进', 'page.paper_size': '纸张',
  'page.orientation': '页面方向', 'page.margin.all': '页边距', 'page.margin.top': '上边距',
  'page.margin.bottom': '下边距', 'page.margin.left': '左边距', 'page.margin.right': '右边距',
  'table.border_style': '表格边框', 'toc.max_depth': '目录层级', 'page_number.number_format': '页码样式',
};
const roles: Record<string, string> = { body: '正文', heading: '标题', abstract: '摘要',
  document: '文档', table: '表格', table_cell: '单元格', bibliography: '参考文献', references: '参考文献',
  header: '页眉', footer: '页脚', toc: '目录', footnote: '脚注', endnote: '尾注' };
const display = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value);

interface Question {
  question_id: string; kind: string; status: string; prompt: string; reason: string;
  allowed_actions: string[]; rule_ids: string[]; property_id: string | null;
  semantic_role: string | null; requires_scope: boolean;
  candidate_values: { original_text: string; normalized: unknown; unit: string | null }[];
  evidence_refs: { quote: string }[];
  observations: { observation_id: string; property_id: string; semantic_role: string; value: unknown; unit: string | null }[];
}
export interface InitialReview {
  schema_version: 'initial-review/1.0'; task_id: string; phase: string;
  base_version_id: string; base_docx_sha256: string; working_version_id: string;
  snapshot_id: string; pending_count: number; questions: Question[];
}

export class InitialReviewPanel {
  busy = false;
  private current: InitialReview | null = null;
  private retry: { fingerprint: string; body: Record<string, unknown> } | null = null;
  private epoch = 0;
  private values = new Map<string, string>();
  constructor(private root: HTMLElement, private api: LocalApi, private refresh: () => Promise<void>) {}
  hide() { this.epoch++; this.current = null; this.root.hidden = true; }
  async load() {
    const epoch = ++this.epoch, state = await this.api.initialReview();
    if (epoch !== this.epoch) return;
    if (state.schema_version !== 'initial-review/1.0' || state.task_id !== this.api.taskId) throw new ApiError('validation_failed');
    this.current = state; this.root.hidden = state.phase === 'initial_draft_ready'; this.render();
  }
  private text(tag: string, value: string, parent = this.root) {
    const node = document.createElement(tag); node.textContent = value; parent.append(node); return node;
  }
  private choice(label: string, action: () => void, parent = this.root) {
    const choice = document.createElement('button'); choice.type = 'button'; choice.className = 'button review-choice';
    choice.textContent = label; choice.disabled = this.busy; choice.addEventListener('click', action); parent.append(choice);
  }
  private render() {
    this.root.replaceChildren(); const state = this.current; if (!state || this.root.hidden) return;
    this.text('h2', '编辑前确认');
    this.text('p', '先确认学校要求中的疑问，再开始修改论文。可选择一个答案，也可暂时忽略此问题。');
    const status = this.text('p', this.busy ? '正在保存，请稍候…' : `还有 ${state.pending_count} 项需要确认。`);
    status.setAttribute('role', 'status'); status.dataset.reviewStatus = '';
    if (state.phase === 'ready_to_edit') {
      this.text('p', '确认已完成。暂时忽略的项目会保留在报告中，未确认候选不会成为执行规则。');
      this.choice('开始格式编辑并生成初稿', () => void this.generate()); return;
    }
    const question = state.questions.find(item => ['pending', 'deferred'].includes(item.status));
    if (!question) { this.text('p', '问题状态已变化，请刷新后继续。'); return; }
    this.text('h3', question.prompt); this.text('p', question.reason);
    for (const ref of question.evidence_refs) this.text('blockquote', ref.quote);
    const options = document.createElement('div'); options.className = 'review-options'; this.root.append(options);
    const answer = (label: string, value: Record<string, unknown>) => this.choice(label, () => void this.answer(question, value, label), options);
    const allowed = (action: string) => question.allowed_actions.includes(action);
    if (allowed('select_rule')) question.rule_ids.forEach((id, index) => {
      const value = question.candidate_values[index];
      answer(`采用：${value?.original_text ?? ''}（${display(value?.normalized)} ${value?.unit ?? ''}）`, { action: 'select_rule', selected_id: id });
    });
    if (allowed('set_submission')) {
      answer('纸质提交', { action: 'set_submission', submission: { medium: 'print' } });
      answer('电子版 · 其他渠道', { action: 'set_submission', submission: { medium: 'electronic', channel: 'other' } });
      answer('电子版 · 系统上传', { action: 'set_submission', submission: { medium: 'electronic', channel: 'system_upload' } });
    }
    if (allowed('confirm_condition')) {
      if (!question.requires_scope) answer('本次适用', { action: 'confirm_condition', applies: true });
      answer('本次不适用', { action: 'confirm_condition', applies: false });
    }
    if (allowed('keep_brief')) answer('保留学校明文要求', { action: 'keep_brief' });
    if (allowed('select_template')) for (const observation of question.observations)
      answer(`采用模板：${roles[observation.semantic_role] ?? '文档对象'} · ${properties[observation.property_id] ?? '格式'} · ${display(observation.value)} ${observation.unit ?? ''}`, { action: 'select_template', selected_id: observation.observation_id });
    if (allowed('accept_template')) {
      for (const observation of question.observations) this.text('p', `${roles[observation.semantic_role] ?? '文档对象'} · ${properties[observation.property_id] ?? '格式'}：${display(observation.value)} ${observation.unit ?? ''}`);
      answer('沿用以上模板格式', { action: 'accept_template' });
    }
    if (allowed('reject_template')) answer('不沿用模板格式', { action: 'reject_template' });
    if (allowed('clarify_format') && question.property_id && question.semantic_role && !question.requires_scope) {
      if (['font.bold', 'font.italic'].includes(question.property_id)) {
        for (const value of [true, false]) answer(`${value ? '启用' : '关闭'}${properties[question.property_id]}`, { action: 'clarify_format', format: { property_id: question.property_id, normalized: value } });
      } else if (['font.size', 'font.family', 'paragraph.spacing_before', 'paragraph.spacing_after', 'paragraph.first_line_indent', 'paragraph.left_indent', 'paragraph.right_indent'].includes(question.property_id)) {
        const group = document.createElement('div'); group.className = 'review-value'; this.root.append(group);
        const label = document.createElement('label'); label.textContent = '指定格式值';
        const input = document.createElement('input'); input.type = question.property_id === 'font.family' ? 'text' : 'number'; input.step = 'any'; input.disabled = this.busy;
        input.value = this.values.get(question.question_id) ?? '';
        input.addEventListener('input', () => this.values.set(question.question_id, input.value));
        label.append(input); group.append(label);
        const unit = question.candidate_values[0]?.unit ?? (question.property_id === 'font.family' ? null : 'pt');
        if (unit) this.text('span', unit, group);
        this.choice('采用填写值', () => {
          if (!input.value.trim()) { input.focus(); return; }
          void this.answer(question, { action: 'clarify_format', format: { property_id: question.property_id,
            normalized: input.type === 'number' ? Number(input.value) : input.value, unit } }, `采用填写值：${input.value} ${unit ?? ''}`);
        }, group);
      }
    }
    if (allowed('skip')) answer('暂时忽略此问题', { action: 'skip' });
  }
  private failure(error: unknown) {
    const status = this.root.querySelector<HTMLElement>('[data-review-status]');
    if (status) status.textContent = `${errorMessage(error)} 原选择已保留，可重试；也可刷新问题。`;
  }
  private async answer(question: Question, answer: Record<string, unknown>, label: string) {
    const state = this.current; if (!state || this.busy) return;
    const fingerprint = JSON.stringify({ snapshot: state.snapshot_id, question: question.question_id, answer });
    if (this.retry?.fingerprint !== fingerprint) this.retry = { fingerprint, body: {
      schema_version: 'academic-decision-request/1.0', request_id: crypto.randomUUID().replaceAll('-', ''),
      base_version_id: state.working_version_id, expected_snapshot_id: state.snapshot_id,
      question_id: question.question_id, answer, raw_answer: label,
    } };
    this.busy = true; this.render();
    try { await this.api.answerQuestion(this.retry.body); this.retry = null; await this.load(); }
    catch (error) { this.busy = false; this.render(); this.failure(error); return; }
    finally { this.busy = false; }
    this.render();
  }
  private async generate() {
    const state = this.current; if (!state || this.busy) return;
    this.busy = true; this.render();
    try {
      await this.api.generateInitial({ schema_version: 'initial-draft-request/1.0', base_version_id: state.base_version_id,
        expected_base_docx_sha256: state.base_docx_sha256, expected_snapshot_id: state.snapshot_id });
      this.busy = false; this.hide(); await this.refresh();
    } catch (error) { this.busy = false; this.render(); this.failure(error); }
  }
}
