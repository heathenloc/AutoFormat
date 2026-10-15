import type { FeedbackAnalysis, FormatValue, Interpretation, PartialFormat, ProcessingAnswer } from './contracts';
import type { RulesReview, ConflictAction } from './contracts';

export const propertyNames: Record<string, string> = {
  'font.family': '字体', 'font.size': '字号', 'font.bold': '加粗', 'font.italic': '斜体',
  'paragraph.alignment': '段落对齐', 'paragraph.line_spacing': '行距',
  'paragraph.spacing_before': '段前间距', 'paragraph.spacing_after': '段后间距',
  'paragraph.first_line_indent': '首行缩进', 'paragraph.hanging_indent': '悬挂缩进',
  'paragraph.left_indent': '左缩进', 'paragraph.right_indent': '右缩进',
  'paragraph.keep_with_next': '与下段同页', 'paragraph.keep_together': '段中不分页',
  'paragraph.page_break_before': '段前分页', 'paragraph.snap_to_grid': '对齐网格',
  'page.paper_size': '纸张尺寸', 'page.orientation': '页面方向',
  'page.margin.all': '四边页边距', 'page.margin.top': '上页边距', 'page.margin.bottom': '下页边距',
  'page.margin.left': '左页边距', 'page.margin.right': '右页边距', 'table.border_style': '表格边框',
};
const units: Record<string, string> = { pt: 'pt', cm: 'cm', mm: 'mm', multiple: '倍', characters: '字符', lines: '行' };
const values: Record<string, string> = { center: '居中', left: '左对齐', right: '右对齐', both: '两端对齐', landscape: '横向', portrait: '纵向', three_line: '三线表', all_borders: '全框线', none: '无边框' };
const missingNames: Record<string, string> = {
  value: '具体格式值或单位', property_id: '要修改的格式属性', semantic_role: '明确的对象类别，请修改原话后重新保存',
  requested_scope: '请统一上方范围控件与原话；修改后重新保存反馈',
  character_scope: '字符适用范围，或该属性是否应影响整段', applicability_scope: '条件、排除项或数值区间，请拆成明确需求',
  unrecognized_text: '尚不能理解的文字，请改用明确的格式表达', conflicting_values: '同一属性出现多个互斥值',
  existing_rule_id: '原本应遵守的已确认规则', selection_target: '需先选择或确认目标位置',
  unsafe_targets: '范围包含不可靠的 Word 结构，请缩小或重新选择', scope_index: '本地范围索引组件未就绪',
  unsupported_property: '该属性的目标结构暂不能可靠核对', too_many_targets: '影响对象过多，请缩小范围', too_many_rules: '格式条目过多，请分开反馈',
};
const kindNames: Record<string, string> = { new_rule: '已识别格式需求', clarification_needed: '需要补充或核对', execution_defect: '已有规则执行问题', question: '咨询', out_of_scope: '超出当前处理范围' };
const characterNames: Record<string, string> = { chinese: '中文字符', latin: '拉丁字母', digits: '数字', complex_script: '复杂文字', other: '其他字符' };
const roleNames: Record<string, string> = { body: '正文', heading: '各级标题', abstract: '摘要', abstract_heading: '摘要标题', toc: '目录', toc_heading: '目录标题', bibliography: '参考文献', bibliography_heading: '参考文献标题', header: '页眉', footer: '页脚', footnote: '脚注', endnote: '尾注', table: '表格', table_header: '表头文字', table_body: '表内文字', table_cell: '表格单元文字', table_caption: '表题', figure_caption: '图题', keywords: '关键词', citation: '引用段落', acknowledgements: '致谢', acknowledgements_heading: '致谢标题', appendix: '附录', appendix_heading: '附录标题' };

function node<K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') {
  const result = document.createElement(tag); result.textContent = text; result.className = className; return result;
}
export function formatValue(value: FormatValue): string {
  const normalized = value.normalized;
  if (typeof normalized === 'boolean') return normalized ? '是' : '否';
  if (typeof normalized === 'object') return `${normalized.mode === 'exact' ? '固定值' : '最小值'} ${normalized.amount} pt`;
  return `${values[String(normalized)] ?? normalized}${value.unit ? ` ${units[value.unit] ?? value.unit}` : ''}`;
}
export function renderFacts(container: HTMLElement, facts: Interpretation, confirmed: string[] = []) {
  container.replaceChildren(); container.dataset.kind = facts.kind;
  container.append(node('strong', kindNames[facts.kind], 'interpretation-kind'), node('p', facts.reason, 'small muted'));
  const list = node('ul', '', 'format-facts');
  for (const candidate of facts.candidates) {
    const item = node('li'); item.append(node('strong', propertyNames[candidate.property_id] ?? '格式属性'), node('span', formatValue(candidate.value)));
    if (candidate.semantic_role && candidate.semantic_role !== 'document_text') {
      const heading = /^(toc_)?heading_([1-9])$/.exec(candidate.semantic_role);
      item.append(node('p', `对象类别：${roleNames[candidate.semantic_role] ?? (heading ? `${heading[1] ? '目录 ' : ''}${heading[2]} 级标题` : '待核对类别')}`, 'small muted'));
    }
    const characters = candidate.applicability_scope?.axes.characters;
    const included = characters?.include ?? (candidate.character_scope === 'all' ? null : [candidate.character_scope]);
    if (candidate.character_scope !== 'all' || included && included.length !== Object.keys(characterNames).length || characters?.exclude.length) {
      const names = (included ?? Object.keys(characterNames)).filter(name => !characters?.exclude.includes(name));
      item.append(node('p', `字符范围：${names.map(name => characterNames[name] ?? name).join('、')}`, 'small muted'));
    }
    const review = facts.scope_reviews.find(review => review.candidate_id === candidate.candidate_id);
    const minimum = candidate.property_id.startsWith('font.') ? '文字' : candidate.property_id.startsWith('paragraph.') ? '段落' : candidate.property_id.startsWith('page.') ? '分节' : '整个对象';
    item.append(node('p', review ? review.reason : `最小作用单位：${minimum}；实际目标仍需核对。`, 'small muted'));
    if (review?.requires_confirmation) item.append(node('span', confirmed.includes(review.review_id) ? '实际范围已确认 · 尚未修改' : '实际范围待确认', 'scope-state'));
    list.append(item);
  }
  for (const partial of facts.understood) list.append(node('li', `已理解：${partial.property_id ? propertyNames[partial.property_id] ?? '格式属性' : '尚未确定属性'}${partial.value ? ` · ${formatValue(partial.value)}` : ' · 值待补充'}`));
  if (list.childNodes.length) container.append(list);
  if (facts.missing_fields.length) container.append(node('p', `待核对：${facts.missing_fields.map(key => missingNames[key] ?? '请补充明确需求').join('；')}。`, 'missing-fields'));
}

function options(select: HTMLSelectElement, entries: Record<string, string>) {
  select.append(new Option('请选择', ''));
  for (const [value, label] of Object.entries(entries)) select.append(new Option(label, value));
  select.required = true;
}
function valueEditor(prop: string, partial: PartialFormat, target: HTMLElement): () => FormatValue | null {
  target.replaceChildren();
  if (partial.value) { target.append(node('p', `已确定：${formatValue(partial.value)}`, 'small')); return () => partial.value; }
  const label = node('label', prop === 'font.family' ? '字体名称' : prop === 'font.size' ? '字号（pt）' : '格式值');
  if (prop === 'font.family') {
    const input = node('input'); input.type = 'text'; input.required = true; input.maxLength = 100; input.placeholder = '例如：宋体'; label.append(input); target.append(label);
    return () => input.value.trim() ? { normalized: input.value.trim(), unit: null } : null;
  }
  const enumValues = prop === 'paragraph.alignment' ? { center: '居中', left: '左对齐', right: '右对齐', both: '两端对齐' } : null;
  if (enumValues || ['font.bold', 'font.italic', 'paragraph.keep_with_next', 'paragraph.keep_together', 'paragraph.page_break_before', 'paragraph.snap_to_grid'].includes(prop)) {
    const select = node('select'); options(select, enumValues ?? { true: '是', false: '否' }); label.append(select); target.append(label);
    return () => select.value ? { normalized: enumValues ? select.value : select.value === 'true', unit: null } : null;
  }
  const input = node('input'); input.type = 'number'; input.required = true; input.step = 'any'; input.min = prop === 'font.size' || prop === 'paragraph.line_spacing' ? '0.01' : '0'; label.append(input); target.append(label);
  const select = node('select');
  if (prop !== 'font.size') {
    const unitLabel = node('label', '单位／模式');
    const choices: Record<string, string> = prop === 'paragraph.line_spacing' ? { multiple: '倍数', exact: '固定值（pt）', atLeast: '最小值（pt）' } : { pt: 'pt', cm: 'cm', mm: 'mm' };
    if (prop.includes('indent')) choices.characters = '字符';
    if (['paragraph.spacing_before', 'paragraph.spacing_after'].includes(prop)) choices.lines = '行';
    options(select, choices); unitLabel.append(select); target.append(unitLabel);
  }
  return () => {
    if (!input.value || !Number.isFinite(Number(input.value)) || !input.checkValidity() || prop !== 'font.size' && !select.value) return null;
    return ['exact', 'atLeast'].includes(select.value) ? { normalized: { mode: select.value, amount: Number(input.value) }, unit: 'pt' } :
      { normalized: Number(input.value), unit: prop === 'font.size' ? 'pt' : select.value };
  };
}

export function renderAnalysis(container: HTMLElement, analysis: FeedbackAnalysis, editable: boolean,
  confirm: (answer: ProcessingAnswer, rawAnswer: string) => void) {
  const facts = analysis.interpretation;
  renderFacts(container, facts, analysis.confirmed_review_ids);
  const required = facts.scope_reviews.filter(review => review.requires_confirmation && !analysis.confirmed_review_ids.includes(review.review_id));
  if (facts.kind === 'new_rule' && required.length) {
    const button = node('button', '确认以上实际范围', 'button wide confirm-scope'); button.disabled = !editable;
    button.addEventListener('click', () => confirm({ action: 'confirm_scope', accepted_review_ids: required.map(review => review.review_id) }, '确认当前展示的实际作用范围。'));
    container.append(button, node('p', '此操作只确认影响范围，尚不执行论文修改。', 'small muted'));
  }
  if (facts.kind !== 'clarification_needed' || !facts.missing_fields.every(key => ['value', 'property_id'].includes(key))) return;
  for (const partial of facts.understood) {
    const form = node('form', '', 'clarify-form');
    const heading = node('strong', '补充具体格式'); form.append(heading);
    const fieldset = node('fieldset'); fieldset.disabled = !editable;
    const property = node('select');
    const choices = Object.fromEntries(Object.entries(propertyNames).filter(([key]) => key.startsWith('font.') || key.startsWith('paragraph.')));
    options(property, choices);
    if (partial.property_id) { property.value = partial.property_id; property.disabled = true; }
    const label = node('label', '格式属性'); label.append(property); fieldset.append(label);
    const value = node('div', '', 'clarify-values'); fieldset.append(value);
    let readValue = valueEditor(property.value || 'font.size', partial, value);
    property.addEventListener('change', () => { readValue = valueEditor(property.value, partial, value); });
    const button = node('button', '保存此项补充', 'button wide'); button.type = 'submit'; fieldset.append(button); form.append(fieldset);
    form.addEventListener('submit', event => {
      event.preventDefault(); const entered = readValue();
      if (!editable || !property.value || !entered || !form.reportValidity()) return;
      confirm({ action: 'clarify_format', format: { candidate_id: partial.candidate_id, property_id: property.value,
        value: entered, requested_scope: partial.requested_scope!, semantic_role: partial.semantic_role, character_scope: 'all' } },
      `补充${propertyNames[property.value]}：${formatValue(entered)}`);
    });
    container.append(form);
  }
}

export const conflictActionNames: Record<ConflictAction, string> = {
  keep_rule: '保留原规则', local_exception: '设为本处例外', update_rule: '更新已确认范围的规则',
};
export function renderRules(container: HTMLElement, review: RulesReview, editable: boolean,
  choose: (conflictId: string, action: ConflictAction) => void) {
  container.replaceChildren(); container.dataset.status = review.snapshot.status;
  const snapshot = review.snapshot;
  const names = { ready: '规则快照已就绪', needs_user_input: '规则快照仍需确认', no_rule_change: '此反馈没有新增格式规则' };
  container.append(node('strong', names[snapshot.status]), node('p', snapshot.reason, 'small muted'));
  if (!snapshot.basis_available) container.append(node('p', '所选版本的学术规则来源尚不可核验，不能据此编译可执行的新规则。', 'missing-fields'));
  const verified = snapshot.fragments.filter(f => f.status === 'verified').length;
  const pending = snapshot.fragments.filter(f => f.status.startsWith('pending_')).length;
  container.append(node('p', `快照修订 ${snapshot.revision} · 已核对片段 ${verified} · 待处理片段 ${pending}。这不是论文格式验证结果。`, 'small muted'));
  if (snapshot.fragments.some(f => f.status === 'pending_scope')) container.append(node('p', '请先确认上方实际范围，再重新核对规则冲突。', 'missing-fields'));
  if (snapshot.fragments.some(f => f.status === 'pending_target')) container.append(node('p', '继承规则的目标需在当前 DOCX 中重新定位。', 'missing-fields'));
  if (snapshot.invalidated_decision_ids.length) container.append(node('p', '部分历史选择的依据已改变，已停止用于本次快照；请重新核对。', 'missing-fields'));
  const conflicts = snapshot.conflicts.filter(c => c.feedback_id === review.parse_result.feedback_id);
  for (const conflict of conflicts) {
    const old = snapshot.rules.find(r => r.rule_id === conflict.existing_rule_id)!;
    const incoming = snapshot.rules.find(r => r.rule_id === conflict.incoming_rule_id)!;
    const card = node('article', '', 'rule-conflict'); card.dataset.conflictId = conflict.conflict_id;
    card.append(node('strong', `${propertyNames[conflict.property_id] ?? '格式属性'}要求冲突`));
    const oldLabel = old.source_kind === 'academic' ? '原学术规则' : '先前反馈规则';
    card.append(node('p', `${oldLabel}：${formatValue(old.value)}`, 'old-rule'), node('p', `本次需求：${formatValue(incoming.value)}`, 'incoming-rule'));
    const evidence = node('details'); evidence.append(node('summary', '查看规则来源'));
    evidence.append(node('p', old.original_requirement, 'small'));
    for (const quote of old.evidence_quotes) evidence.append(node('blockquote', quote));
    evidence.append(node('p', `本次原话：${incoming.original_requirement}`, 'small')); card.append(evidence);
    const count = new Set(conflict.spans.map(s => s.object_id)).size;
    card.append(node('p', `相交范围涉及 ${count} 个对象${conflict.spans.some(s => s.start_utf16 !== null) ? `、${conflict.spans.length} 处文字范围` : ''}。只处理这些相交部分，其他范围保留。`, 'small'));
    if (conflict.resolution) card.append(node('p', `已选择：${conflictActionNames[conflict.resolution]} · 尚未修改论文`, 'conflict-resolved'));
    else {
      const actions = node('div', '', 'conflict-actions');
      for (const action of conflict.allowed_actions) {
        const choice = node('button', conflictActionNames[action], 'button rules-action'); choice.disabled = !editable;
        choice.addEventListener('click', () => choose(conflict.conflict_id, action)); actions.append(choice);
      }
      card.append(actions);
    }
    container.append(card);
  }
  if (!conflicts.length && snapshot.status === 'ready') container.append(node('p', '当前已核对范围没有未决冲突；生成新版本后可查看修改结果。', 'small'));
  if (snapshot.conflicts.some(c => c.feedback_id !== review.parse_result.feedback_id && !c.resolution)) container.append(node('p', '此版本的其他反馈仍有未决冲突，请从反馈记录中逐项核对。', 'missing-fields'));
}
