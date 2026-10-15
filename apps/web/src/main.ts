import './style.css';
import 'pdfjs-dist/web/pdf_viewer.css';
import { ApiError, bootstrap, errorMessage, LocalApi, sha256 } from './api';
import type { FeedbackContext, Receipt, Report, SelectionHint, Submission, Version, VersionList, SelectionResolution, TargetConfirmation } from './contracts';
import { PdfViewer } from './viewer';
import { renderFacts, renderAnalysis, renderRules, conflictActionNames } from './feedback';
import { InitialReviewPanel } from './initial-review';
import { renderPendingReport, workNames, isPending } from './workspace';
import type { ContinuationRequest, WorkItem, WorkQueue } from './contracts';
import type { DraftReview, FeedbackAnalysis, FeedbackScope, ProcessingAnswer, ProcessingConfirmation } from './contracts';
import type { RulesReview, RulesDecision, ConflictAction, ExecutionRequest, ExecutionResult } from './contracts';

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `
  <header class="topbar">
    <div class="brand" aria-label="AutoFormat"><span class="brand-mark">A</span>AutoFormat</div>
    <span class="top-divider"></span><span class="workspace-name">论文工作台</span>
    <button id="home" class="text-button">返回任务列表</button><span class="local-badge"><i></i>本地预览</span>
  </header>
  <main class="workspace">
    <aside class="versions-panel" aria-label="版本历史">
      <div class="panel-heading"><span class="eyebrow">你的论文</span><h1>版本历史</h1></div>
      <p class="muted small">每个版本保留独立的论文与报告。</p>
      <nav id="versions" aria-label="选择预览版本"></nav>
      <button id="refresh" class="button subtle wide">↻ 刷新版本</button>
      <section class="continue-panel"><p id="version-origin" class="small muted"></p><button id="continue-version" class="button wide" hidden>从此版本继续修改</button><p id="continue-status" class="small muted" role="status"></p></section>
      <div class="sidebar-note"><span class="note-symbol">↗</span><p>查看历史版本不会改变当前工作起点。</p></div>
    </aside>
    <section class="preview-panel" aria-label="论文预览">
      <div class="preview-heading">
        <div><div class="eyebrow">DOCUMENT PREVIEW</div><h2>论文预览 <span id="version-badge" class="pill">—</span></h2></div>
        <div class="download-actions"><button id="download-report" class="button" disabled>↓ 报告</button><button id="download-docx" class="button primary" disabled>↓ 下载 DOCX</button></div>
      </div>
      <div class="preview-toolbar">
        <div class="page-controls"><button id="previous" class="icon-button" aria-label="上一页" disabled>‹</button>
          <label class="page-label">第 <input id="page" type="number" min="1" value="1" aria-label="页码" disabled /> / <span id="page-count">—</span> 页</label>
          <button id="next" class="icon-button" aria-label="下一页" disabled>›</button></div>
        <div class="zoom-controls"><button id="zoom-out" class="icon-button" aria-label="缩小" disabled>−</button><span id="zoom-label">—</span><button id="zoom-in" class="icon-button" aria-label="放大" disabled>+</button><button id="fit" class="button compact" disabled>适合宽度</button></div>
      </div>
      <div id="notice" class="notice" role="status" hidden></div>
      <section id="initial-review" class="initial-review" aria-label="编辑前确认" hidden></section>
      <div id="preview-state" class="preview-state" role="status"><div class="empty-symbol">▤</div><strong>正在读取版本</strong><p>准备论文、报告和预览…</p></div>
      <div id="pdf" class="pdf-scroll" tabindex="0" aria-label="PDF 页面" hidden></div>
      <div class="preview-footer"><span id="renderer">预览由论文版本生成</span><span>分页与 Word 可能略有差异</span></div>
    </section>
    <aside class="detail-panel" aria-label="版本报告与反馈">
      <div class="panel-heading"><span class="eyebrow">检查与微调</span><h2>版本概览</h2></div>
      <div id="report-empty" class="muted small">加载后展示该版本的处理结果。</div>
      <section id="report" hidden>
        <span id="format-status" class="status-tag"></span>
        <div class="metrics"><div><strong id="change-count">0</strong><span>本轮修改</span></div><div><strong id="pending-count">0</strong><span>待处理项</span></div></div>
        <p id="report-note" class="small muted report-note"></p>
        <section id="report-pending" class="report-pending" hidden></section>
      </section>
      <div class="section-divider"></div>
      <section class="selection-panel">
        <div class="section-title"><h3>选中文字</h3><button id="clear-selection" class="text-button" hidden>清除</button></div>
        <div id="selection-empty" class="selection-empty"><span>⌖</span><p>在预览中拖动选择文字<br />为反馈标记具体位置。</p></div>
        <blockquote id="selection-text" hidden></blockquote><p id="selection-location" class="small muted" hidden></p>
      </section>
      <section class="feedback-panel">
        <label class="section-title" for="feedback-text"><h3>添加反馈</h3></label>
        <p id="feedback-scope" class="small muted">可选中文字，或记录关于全文的反馈。</p>
        <label class="scope-label" for="feedback-range">请求范围</label>
        <select id="feedback-range" disabled><option value="selection">仅选中文字</option><option value="paragraph">所在整个段落</option><option value="same_kind">所有同类内容</option><option value="document">全文</option></select>
        <textarea id="feedback-text" maxlength="4096" rows="4" placeholder="例如：这里的字号需要调整。" disabled></textarea>
        <button id="review-feedback" class="button subtle wide" disabled>解析需求与范围</button>
        <section id="draft-panel" class="draft-panel" hidden><h3>保存前的需求预览</h3><div id="draft-review" role="status"></div></section>
        <button id="save-feedback" class="button primary wide" disabled>保存反馈</button>
        <p id="feedback-status" class="small muted" role="status">反馈保存后待后续处理，暂不执行论文修改。</p>
      </section>
      <div class="section-divider"></div>
      <section id="target-panel" hidden><h3 class="target-heading">已保存反馈的位置</h3><p id="target-status" class="small muted" role="status"></p><div id="target-candidates"></div></section>
      <section id="analysis-panel" hidden><h3>已保存反馈的需求</h3><p id="analysis-status" class="small muted" role="status"></p><div id="analysis-details"></div><button id="review-rules" class="button wide review-rules" hidden>核对规则冲突</button><p id="rules-status" class="small muted" role="status"></p><div id="rules-details"></div></section>
      <section id="execution-panel" hidden><button id="execute-feedback" class="button primary wide">生成新版本</button><p id="execution-status" class="small muted" role="status"></p></section>
      <section class="work-panel"><div class="section-title"><h3>反馈问题与进度</h3><span id="feedback-count" class="count">0</span></div><div class="work-toolbar"><select id="work-filter" aria-label="筛选反馈"><option value="all">全部反馈</option><option value="pending">待处理</option><option value="done">已完成／记录</option></select><button id="refresh-work" class="text-button">刷新进度</button></div><p id="work-status" class="small muted" role="status"></p><ul id="feedback-list" class="feedback-list"></ul><button id="more-work" class="button subtle wide" hidden>加载更早反馈</button><p id="feedback-empty" class="small muted">尚无已保存的反馈。</p></section>
    </aside>
  </main>`;

const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const button = (id: string) => el<HTMLButtonElement>(id);
const pageInput = el<HTMLInputElement>('page');
const textarea = el<HTMLTextAreaElement>('feedback-text');
const viewer = new PdfViewer(el('pdf'));
const session = bootstrap();
const api = session ? new LocalApi(session.token, session.task) : null;
const initialReview = api ? new InitialReviewPanel(el('initial-review'), api, async () => { selected = null; await refresh(); }) : null;
let versions: VersionList | null = null;
let selected: Version | null = null;
let context: FeedbackContext | null = null;
let selection: SelectionHint | null = null;
let receipts: Receipt[] = [];
let page = 1, scale: number | 'fit' = 'fit', effectiveScale = 1;
let epoch = 0, renderEpoch = 0;
let controller: AbortController | null = null;
let loading = false, rendering = false, saving = false;
let lastRenderedWidth = 0;
let retrySubmission: { fingerprint: string; body: Submission } | null = null;
let targetEpoch = 0;
let targetController: AbortController | null = null;
let confirmingTarget = false;
let targetRetry: TargetConfirmation | null = null;
const scopeSelect = el<HTMLSelectElement>('feedback-range');
let requestedScope: FeedbackScope = 'document';
let draft: DraftReview | null = null, draftPending = false, draftEpoch = 0;
let draftController: AbortController | null = null;
let draftTimer: ReturnType<typeof setTimeout>;
let currentAnalysis: FeedbackAnalysis | null = null;
let processingRetry: { fingerprint: string; body: ProcessingConfirmation } | null = null;
let currentRules: RulesReview | null = null;
let rulesRetry: { fingerprint: string; body: RulesDecision } | null = null;
let executionAvailable = false;
let executionRetry: { fingerprint: string; body: ExecutionRequest } | null = null;
let switching = false;
let continuationRetry: { fingerprint: string; body: ContinuationRequest } | null = null;
let workQueue: WorkQueue | null = null;
let workItems: WorkItem[] = [];
let workEpoch = 0, workLoading = false;
let workController: AbortController | null = null;

function notice(message = '', isError = false) {
  el('notice').textContent = message; el('notice').hidden = !message;
  el('notice').classList.toggle('error', isError);
}
function state(title: string, detail: string) {
  el('pdf').hidden = true; el('preview-state').hidden = false;
  el('preview-state').querySelector('strong')!.textContent = title;
  el('preview-state').querySelector('p')!.textContent = detail;
}
function canInput() { return Boolean(context && selected && versions?.working_version_id === selected.version_id && !loading && !rendering && !saving && !confirmingTarget && !switching); }
function canSave() { return canInput() && Boolean(draft) && !draftPending; }
function controls() {
  el('pdf').setAttribute('aria-busy', String(loading || rendering));
  const ready = Boolean(context && !loading && !rendering && !switching);
  button('previous').disabled = !ready || page <= 1;
  button('next').disabled = !ready || page >= (context?.page_count ?? 0);
  pageInput.disabled = !ready;
  for (const id of ['zoom-in', 'zoom-out', 'fit']) button(id).disabled = !ready;
  button('zoom-in').disabled ||= effectiveScale >= 2;
  button('zoom-out').disabled ||= effectiveScale <= 0.4;
  button('download-docx').disabled = !selected || loading;
  button('download-report').disabled = selected?.kind !== 'output' || loading;
  textarea.disabled = !canInput(); scopeSelect.disabled = !canInput();
  for (const option of scopeSelect.options) option.disabled = !selection && option.value !== 'document';
  button('review-feedback').disabled = !canInput() || draftPending || !textarea.value.trim();
  button('save-feedback').disabled = !canSave() || !textarea.value.trim();
  button('save-feedback').textContent = saving ? '正在保存…' : '保存反馈';
  button('home').disabled = !session || saving || confirmingTarget || switching;
  button('continue-version').hidden = !selected || selected.kind !== 'output' || selected.version_id === versions?.working_version_id;
  button('continue-version').disabled = loading || saving || confirmingTarget || switching || !versions?.versions.some(v => v.version_id === versions?.working_version_id);
  const parent = versions?.versions.find(v => v.version_id === selected?.parent_version_id);
  el('version-origin').textContent = !selected ? '' : selected.kind === 'original' ? 'V0 是上传时的原稿。' : `此版本${parent ? `基于 V${parent.sequence}` : ''}。${selected.version_id === versions?.working_version_id ? '当前工作起点。' : '点击下方按钮可从这里创建新分支，已有后代保留。'}`;
  button('refresh-work').disabled = !context || switching || confirmingTarget || workLoading;
  button('more-work').disabled = switching || confirmingTarget || workLoading;
}
function setSelection(value: SelectionHint | null) {
  const hadSelection = Boolean(selection);
  selection = value;
  if (!value) requestedScope = 'document'; else if (!hadSelection) requestedScope = 'selection';
  scopeSelect.value = requestedScope;
  el('selection-empty').hidden = Boolean(value);
  el('selection-text').hidden = !value;
  el('selection-location').hidden = !value;
  el('clear-selection').hidden = !value;
  el('selection-text').textContent = value?.selected_text ?? '';
  el('selection-location').textContent = value ? `第 ${value.spans[0].page} 页 · 已记录位置提示` : '';
  el('feedback-scope').textContent = value ? '反馈关联这段选中文字；实际修改范围待定位与核对。' : '未选中文字：此反馈将记录为全文需求或咨询。';
  scheduleDraft();
}
function prepareSubmission(): Submission {
  const fingerprint = JSON.stringify({ context: context!.context_id, text: textarea.value, selection, requestedScope });
  if (retrySubmission?.fingerprint !== fingerprint) retrySubmission = { fingerprint, body: {
    schema_version: 'feedback-submission/1.0', request_id: crypto.randomUUID().replaceAll('-', ''), task_id: api!.taskId,
    base_version_id: context!.base_version_id, expected_base_docx_sha256: context!.base_docx_sha256,
    expected_context_id: context!.context_id, preview_artifact_id: context!.preview_artifact_id,
    expected_preview_pdf_sha256: context!.preview_pdf_sha256, raw_text: textarea.value, requested_scope: requestedScope, selection,
  } };
  return retrySubmission.body;
}
function clearDraft() {
  draftEpoch++; clearTimeout(draftTimer); draftController?.abort(); draftController = null;
  draft = null; draftPending = false; el('draft-panel').hidden = true; el('draft-review').replaceChildren();
  delete el('draft-review').dataset.kind;
}
function scheduleDraft(immediate = false) {
  clearDraft(); controls();
  if (!api || !canInput() || !textarea.value.trim()) return;
  draftPending = true; el('draft-panel').hidden = false; el('draft-review').textContent = '正在解析需求并核对实际范围…'; controls();
  const current = draftEpoch, version = epoch, body = prepareSubmission();
  draftTimer = setTimeout(() => void reviewDraft(body, current, version), immediate ? 0 : 300);
}
async function reviewDraft(body: Submission, current: number, version: number) {
  draftController = new AbortController(); const signal = draftController.signal;
  try {
    const result = await api!.review(body, signal);
    if (current !== draftEpoch || version !== epoch) return;
    const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ?
      Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => [key, canonical(item)])) : value;
    const sourceHash = await sha256(new TextEncoder().encode(JSON.stringify(canonical(body))));
    if (current !== draftEpoch || version !== epoch) return;
    if (result.task_id !== api!.taskId || result.base_version_id !== selected?.version_id || result.version_context_id !== context?.context_id || result.source_submission_sha256 !== sourceHash) throw new ApiError('stale_preview');
    draft = result; renderFacts(el('draft-review'), result);
  } catch (error) {
    if (current !== draftEpoch || version !== epoch || signal.aborted) return;
    el('draft-review').textContent = `${errorMessage(error)} 可点击“解析需求与范围”重试，原输入已保留。`;
  } finally {
    if (current === draftEpoch && version === epoch) { draftPending = false; controls(); }
  }
}
function clearSelection() { window.getSelection()?.removeAllRanges(); setSelection(null); }
function renderVersions() {
  const nav = el('versions'); nav.replaceChildren();
  for (const version of [...(versions?.versions ?? [])].reverse()) {
    const item = document.createElement('button'); item.className = 'version-item';
    item.dataset.versionId = version.version_id;
    item.classList.toggle('selected', selected?.version_id === version.version_id);
    item.setAttribute('aria-current', selected?.version_id === version.version_id ? 'true' : 'false');
    const marker = document.createElement('span'); marker.className = 'version-dot';
    const info = document.createElement('span'); info.className = 'version-info';
    const title = document.createElement('strong'); title.textContent = `V${version.sequence} · ${version.kind === 'original' ? '论文原稿' : version.sequence === 1 ? '初稿' : '修改版本'}`;
    const time = document.createElement('span'); time.textContent = new Date(version.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    info.append(title, time);
    if (version.version_id === versions?.working_version_id) {
      const current = document.createElement('em'); current.textContent = '工作起点'; info.append(current);
    }
    if (version.parent_version_id) {
      const parent = versions?.versions.find(value => value.version_id === version.parent_version_id);
      const lineage = document.createElement('em'); lineage.textContent = `基于 V${parent?.sequence ?? '?'}`; info.append(lineage);
    }
    item.append(marker, info); item.addEventListener('click', () => { if (!saving && !switching && selected?.version_id !== version.version_id) void selectVersion(version); });
    item.disabled = saving || confirmingTarget || switching; nav.append(item);
  }
}
function showReport(report: Report) {
  el('report-empty').hidden = true; el('report').hidden = false;
  el('format-status').textContent = { verified: '已验证格式规则', partial: '仍有待处理项', unassessed: '未评估格式完成度' }[report.summary.format_status];
  el('format-status').classList.toggle('pending', report.summary.format_status !== 'verified');
  el('change-count').textContent = String(report.summary.this_round_change_count);
  el('pending-count').textContent = String(report.summary.pending_count);
  el('report-note').textContent = report.summary.note;
  renderPendingReport(el('report-pending'), report);
}
function showReceipts() {
  el('feedback-count').textContent = String(receipts.length);
  el('feedback-empty').hidden = receipts.length > 0;
  el('feedback-list').replaceChildren();
  const filter = el<HTMLSelectElement>('work-filter').value;
  const entries = workQueue ? workItems.filter(item => filter === 'all' || (filter === 'pending' ? isPending(item) : !isPending(item))) : [];
  const displayed = workQueue ? entries.map(item => receipts.find(r => r.feedback_id === item.feedback_id)!).filter(Boolean) : [...receipts].reverse();
  for (const receipt of displayed) {
    const work = workItems.find(item => item.feedback_id === receipt.feedback_id);
    const item = document.createElement('li');
    if (work) { item.dataset.workStatus = work.status; item.dataset.feedbackId = work.feedback_id; }
    const status = document.createElement('span'); status.textContent = work ? workNames[work.status] : '已接收 · 待核对进度';
    const time = document.createElement('time'); time.dateTime = receipt.created_at;
    time.textContent = new Date(receipt.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const inspect = document.createElement('button'); inspect.className = 'text-button'; inspect.textContent = '查看需求与位置';
    inspect.disabled = confirmingTarget || switching;
    inspect.addEventListener('click', () => { if (!confirmingTarget && !switching) void openWorkItem(receipt, work); });
    const summary = document.createElement('div'); summary.className = 'receipt-summary'; summary.append(status, time);
    item.append(summary);
    if (work) {
      const raw = document.createElement('p'); raw.className = 'work-raw'; raw.textContent = work.raw_text;
      const reason = document.createElement('p'); reason.className = 'work-reason'; reason.textContent = work.reason;
      item.append(raw, reason);
      if (work.selected_text) { const excerpt = document.createElement('details'); const title = document.createElement('summary'); title.textContent = '所选文字'; const text = document.createElement('blockquote'); text.textContent = work.selected_text; excerpt.append(title, text); item.append(excerpt); }
      if (work.output_version_id) {
        const output = document.createElement('button'); output.className = 'text-button'; output.textContent = '查看生成版本'; output.disabled = confirmingTarget || switching;
        output.addEventListener('click', () => void openOutput(work.output_version_id!)); item.append(output);
      }
    }
    item.append(inspect); el('feedback-list').append(item);
  }
  button('more-work').hidden = !workQueue?.next_before;
  if (workQueue && !entries.length && receipts.length) { el('feedback-empty').textContent = '已加载的反馈中没有符合此筛选的事项。'; el('feedback-empty').hidden = false; }
  else el('feedback-empty').textContent = '尚无已保存的反馈。';
}

async function reloadWork(more = false) {
  if (!api || !context || switching || (more && !workQueue?.next_before)) return;
  const version = epoch, local = ++workEpoch, bound = context;
  workController?.abort(); workController = new AbortController(); const signal = workController.signal;
  workLoading = true; el('work-status').textContent = '正在按原话、确认记录和执行结果核对进度…'; controls();
  try {
    const result = await api.workItems(bound.base_version_id, signal, more ? workQueue!.next_before! : undefined);
    if (version !== epoch || local !== workEpoch) return;
    if (result.schema_version !== 'feedback-work-queue/1.0' || result.task_id !== api.taskId || result.base_version_id !== bound.base_version_id || result.base_docx_sha256 !== bound.base_docx_sha256 || result.version_context_id !== bound.context_id) throw new ApiError('stale_preview');
    workItems = more ? [...workItems, ...result.items.filter(item => !workItems.some(old => old.feedback_id === item.feedback_id))] : result.items;
    workQueue = result;
    if (versions && versions.working_version_id !== result.working_version_id) {
      versions.working_version_id = result.working_version_id; renderVersions();
      notice('工作起点已变化，请核对版本列表；需要时刷新后继续。');
    }
    el('work-status').textContent = `已核对 ${workItems.length} 条反馈 · 其中 ${workItems.filter(isPending).length} 条待处理。${result.next_before ? ' 可继续加载更早反馈。' : ''}`;
    showReceipts();
  } catch (error) {
    if (version === epoch && local === workEpoch && !signal.aborted) el('work-status').textContent = `${errorMessage(error)} 可刷新进度重试，论文和报告仍可查看。`;
  } finally { if (version === epoch && local === workEpoch) { workLoading = false; controls(); } }
}
async function openWorkItem(receipt: Receipt, work?: WorkItem) {
  await locateReceipt(receipt);
  if (receipt.base_version_id !== selected?.version_id || !currentAnalysis || currentAnalysis.interpretation.feedback_id !== receipt.feedback_id) return;
  if (work && isPending(work) && currentAnalysis.interpretation.kind === 'new_rule' && selected.version_id === versions?.working_version_id) {
    await reviewRules();
    if (work?.execution_request_id && currentRules && context && currentRules.snapshot.status === 'ready') {
      const result = await api!.execution(work.execution_request_id).catch(() => null);
      if (result?.snapshot_id === currentRules.snapshot.snapshot_id && result.base_version_id === context.base_version_id && receipt.base_version_id === selected?.version_id) {
        executionRetry = { fingerprint: JSON.stringify({ snapshot: result.snapshot_id, context: context.context_id }), body: {
          schema_version: 'feedback-execution-request/1.0', request_id: result.request_id, task_id: api!.taskId,
          base_version_id: context.base_version_id, expected_base_docx_sha256: context.base_docx_sha256,
          expected_context_id: context.context_id, expected_snapshot_id: result.snapshot_id,
        } };
      }
    }
  }
}
async function openOutput(versionId: string) {
  if (!api || switching || saving || confirmingTarget) return;
  const version = epoch;
  try {
    const list = await api.versions();
    if (version !== epoch || switching || saving || confirmingTarget) return;
    const output = list.versions.find(item => item.version_id === versionId);
    if (!output) throw new ApiError('stale_base_version');
    versions = list; await selectVersion(output);
  } catch (error) { if (version === epoch) notice(errorMessage(error), true); }
}
button('refresh-work').addEventListener('click', () => void reloadWork());
button('more-work').addEventListener('click', () => void reloadWork(true));
el('work-filter').addEventListener('change', showReceipts);
button('continue-version').addEventListener('click', async () => {
  if (!api || !versions || !selected || selected.kind !== 'output' || loading || switching || saving || confirmingTarget) return;
  const version = selected;
  const fingerprint = JSON.stringify({ version: version.version_id, hash: version.docx_sha256, working: versions.working_version_id });
  if (continuationRetry?.fingerprint !== fingerprint) continuationRetry = { fingerprint, body: {
    schema_version: 'version-continuation-request/1.0', request_id: crypto.randomUUID().replaceAll('-', ''), task_id: api.taskId,
    version_id: version.version_id, expected_docx_sha256: version.docx_sha256, expected_working_version_id: versions.working_version_id,
  } };
  const body = continuationRetry.body;
  switching = true; workEpoch++; workController?.abort(); workLoading = false;
  clearTarget(); clearSelection(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = true;
  el('continue-status').textContent = '正在校验历史文件并切换工作起点…';
  try {
    const result = await api.continueVersion(body);
    if (result.schema_version !== 'version-continuation/1.0' || result.request_id !== body.request_id || result.task_id !== api.taskId || result.continued_version_id !== version.version_id) throw new ApiError('validation_failed');
    versions = await api.versions(); continuationRetry = null;
    el('continue-status').textContent = '';
    switching = false; await selectVersion(version);
    notice(versions.working_version_id === version.version_id ? `已从 V${version.sequence} 继续修改。之后的编辑会生成新的子版本，已有后代保留。` : '此请求已完成，但工作起点随后发生变化，请刷新并核对。');
  } catch (error) { el('continue-status').textContent = `${errorMessage(error)} 可重试同一操作；历史文件保持不变。`; }
  finally { switching = false; renderVersions(); showReceipts(); controls(); button('refresh').disabled = false; }
});
function clearTarget() {
  el('execution-panel').hidden = true; el('execution-status').textContent = '';
  targetEpoch++; targetController?.abort(); targetController = null; targetRetry = null;
  el('target-panel').hidden = true; el('target-candidates').replaceChildren();
  currentAnalysis = null; processingRetry = null; el('analysis-panel').hidden = true; el('analysis-details').replaceChildren();
  currentRules = null; rulesRetry = null; el('rules-details').replaceChildren(); el('rules-status').textContent = '';
}
function showTarget(result: SelectionResolution) {
  el('target-panel').hidden = false; el('target-status').textContent = result.reason;
  el('target-status').dataset.status = result.status;
  const list = el('target-candidates'); list.replaceChildren();
  if (result.status === 'ready' && result.anchor) {
    const count = document.createElement('p'); count.className = 'small muted';
    count.textContent = `已定位 ${result.anchor.ranges.length} 处 DOCX 文字范围。`; list.append(count);
  }
  for (const candidate of result.candidates) {
    const card = document.createElement('div'); card.className = 'target-candidate';
    const label = document.createElement('strong'); label.textContent = candidate.location_label;
    const excerpt = document.createElement('p'); excerpt.textContent = candidate.excerpt;
    const choose = document.createElement('button'); choose.className = 'button compact'; choose.textContent = '确认此位置';
    choose.disabled = !context || selected?.version_id !== versions?.working_version_id || confirmingTarget;
    choose.addEventListener('click', () => void confirmTarget(result, candidate.candidate_id, candidate.location_label));
    card.append(label, excerpt, choose); list.append(card);
  }
  el('target-panel').scrollIntoView({ block: 'nearest' });
}
async function locateReceipt(receipt: Receipt, autoContinue = false) {
  if (!api || receipt.base_version_id !== selected?.version_id || confirmingTarget) return;
  clearTarget(); const currentTarget = targetEpoch, currentVersion = epoch;
  targetController = new AbortController(); const signal = targetController.signal;
  el('target-panel').hidden = false; el('target-status').textContent = '正在验证 PDF 文字层并定位 DOCX…';
  el('target-status').dataset.status = 'loading';
  el('analysis-panel').hidden = false; el('analysis-status').textContent = '正在核对已保存需求与实际范围…';
  try {
    const analysis = await api.analysis(receipt.base_version_id, receipt.feedback_id, signal);
    if (currentTarget !== targetEpoch || currentVersion !== epoch) return;
    if (analysis.interpretation.feedback_id !== receipt.feedback_id || analysis.interpretation.version_context_id !== context?.context_id) throw new ApiError('stale_preview');
    if (analysis.selection) showTarget(analysis.selection); else el('target-panel').hidden = true;
    showAnalysis(analysis);
    if (autoContinue && executionAvailable && analysis.interpretation.kind === 'new_rule') await reviewRules(true);
  } catch (error) {
    if (currentTarget !== targetEpoch || currentVersion !== epoch || signal.aborted) return;
    el('target-status').textContent = errorMessage(error); el('target-status').dataset.status = 'unavailable';
    el('analysis-status').textContent = errorMessage(error);
  } finally { if (currentTarget === targetEpoch && currentVersion === epoch) void reloadWork(); }
}
function showAnalysis(analysis: FeedbackAnalysis) {
  el('execution-panel').hidden = true;
  currentRules = null; rulesRetry = null; el('rules-details').replaceChildren(); el('rules-status').textContent = '';
  button('review-rules').hidden = analysis.interpretation.kind !== 'new_rule';
  currentAnalysis = analysis; el('analysis-panel').hidden = false;
  el('analysis-status').textContent = analysis.decision_count ? `已保存 ${analysis.decision_count} 项补充／范围确认，尚未执行论文修改。` : '解析与范围核对不代表已完成格式修改。';
  renderAnalysis(el('analysis-details'), analysis, selected?.version_id === versions?.working_version_id,
    (answer, rawAnswer) => void confirmProcessing(answer, rawAnswer));
  analysisBusy();
  el('analysis-panel').scrollIntoView({ block: 'nearest' });
}
function analysisBusy() {
  const editable = Boolean(context && selected?.version_id === versions?.working_version_id && !confirmingTarget && !switching);
  for (const field of el('analysis-details').querySelectorAll<HTMLFieldSetElement>('fieldset')) field.disabled = !editable;
  for (const choice of el('analysis-details').querySelectorAll<HTMLButtonElement>('.confirm-scope')) choice.disabled = !editable;
  for (const choice of el('target-candidates').querySelectorAll<HTMLButtonElement>('button')) choice.disabled = !editable;
  for (const choice of el('rules-details').querySelectorAll<HTMLButtonElement>('.rules-action')) choice.disabled = !editable;
  button('review-rules').disabled = !context || confirmingTarget || switching || selected?.version_id !== versions?.working_version_id;
  button('execute-feedback').disabled = confirmingTarget || switching || !context || selected?.version_id !== versions?.working_version_id || currentRules?.snapshot.status !== 'ready';
}
button('review-rules').addEventListener('click', () => void reviewRules());
function acceptRules(review: RulesReview) {
  if (!context || !currentAnalysis || review.parse_result.feedback_id !== currentAnalysis.interpretation.feedback_id ||
      review.snapshot.version_context_id !== context.context_id || review.snapshot.base_docx_sha256 !== context.base_docx_sha256 ||
      review.snapshot.base_version_id !== context.base_version_id) throw new ApiError('stale_preview');
  currentRules = review;
  el('execution-panel').hidden = !executionAvailable || review.snapshot.status !== 'ready' || selected?.version_id !== versions?.working_version_id;
  renderRules(el('rules-details'), review, selected?.version_id === versions?.working_version_id,
    (conflict, action) => void decideRule(conflict, action));
  el('rules-status').textContent = '已按所选版本的原文件、反馈和历史决定核对。尚未修改论文。';
  analysisBusy();
}
async function reviewRules(autoContinue = false) {
  if (!api || !context || !currentAnalysis || confirmingTarget || switching || selected?.version_id !== versions?.working_version_id) return;
  const version = epoch, target = targetEpoch, feedbackId = currentAnalysis.interpretation.feedback_id;
  confirmingTarget = true; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = true;
  el('rules-status').textContent = '正在核对规则来源与实际相交范围…';
  try {
    const review = await api.rules(context.base_version_id, feedbackId, targetController?.signal ?? new AbortController().signal);
    if (version !== epoch || target !== targetEpoch) return;
    rulesRetry = null; acceptRules(review);
  } catch (error) { if (version === epoch && target === targetEpoch) el('rules-status').textContent = errorMessage(error); }
  finally { confirmingTarget = false; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = false; }
  if (version === epoch) void reloadWork();
  if (autoContinue && version === epoch && target === targetEpoch && currentRules?.snapshot.status === 'ready') await executeRules();
}
async function decideRule(conflictId: string, action: ConflictAction) {
  if (!api || !context || !currentRules || confirmingTarget || selected?.version_id !== versions?.working_version_id) return;
  const version = epoch, target = targetEpoch, review = currentRules;
  const fingerprint = JSON.stringify({ snapshot: review.snapshot.snapshot_id, conflictId, action });
  if (rulesRetry?.fingerprint !== fingerprint) rulesRetry = { fingerprint, body: {
    schema_version: 'feedback-decision-request/1.1', request_id: crypto.randomUUID().replaceAll('-', ''),
    task_id: api.taskId, base_version_id: context.base_version_id, expected_base_docx_sha256: context.base_docx_sha256,
    expected_context_id: context.context_id, feedback_id: review.parse_result.feedback_id,
    expected_parse_result_id: review.parse_result.result_id, expected_snapshot_id: review.snapshot.snapshot_id,
    conflict_id: conflictId, action, raw_answer: conflictActionNames[action],
  } };
  confirmingTarget = true; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = true;
  el('rules-status').textContent = '正在保存冲突选择并编译规则快照…';
  try {
    const result = await api.decideRule(rulesRetry.body);
    if (version !== epoch || target !== targetEpoch) return;
    acceptRules(result); rulesRetry = null;
  } catch (error) {
    if (version === epoch && target === targetEpoch) el('rules-status').textContent = `${errorMessage(error)} 原选择已保留，可重试同一操作；依据变化时请重新核对规则。`;
  } finally { confirmingTarget = false; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = false; }
  if (version === epoch) void reloadWork();
  if (version === epoch && target === targetEpoch && !rulesRetry && currentRules?.snapshot.status === 'ready' && executionAvailable) await executeRules();
}

button('execute-feedback').addEventListener('click', () => void executeRules());
async function executeRules() {
  if (!api || !context || !currentRules || !executionAvailable || confirmingTarget || currentRules.snapshot.status !== 'ready' || selected?.version_id !== versions?.working_version_id) return;
  const version = epoch, snapshot = currentRules.snapshot;
  const fingerprint = JSON.stringify({ snapshot: snapshot.snapshot_id, context: context.context_id });
  if (executionRetry?.fingerprint !== fingerprint) executionRetry = { fingerprint, body: {
    schema_version: 'feedback-execution-request/1.0', request_id: crypto.randomUUID().replaceAll('-', ''),
    task_id: api.taskId, base_version_id: context.base_version_id, expected_base_docx_sha256: context.base_docx_sha256,
    expected_context_id: context.context_id, expected_snapshot_id: snapshot.snapshot_id,
  } };
  const request = executionRetry.body;
  confirmingTarget = true; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = true;
  button('execute-feedback').textContent = '正在生成…';
  const labels: Record<ExecutionResult['phase'], string> = { planning: '正在核对修改范围…', editing: '正在修改论文副本…', validating: '正在校验修改结果…', rendering: '正在生成 PDF 预览…', ready: '新版本已生成。', no_document_change: '目标格式已经满足要求，本轮没有产生新版本。', failed: '生成失败，当前版本保留，可重试。' };
  const show = (result: ExecutionResult) => {
    if (result.request_id !== request.request_id || result.task_id !== api.taskId || result.base_version_id !== request.base_version_id || result.snapshot_id !== request.expected_snapshot_id) throw new ApiError('stale_preview');
    if (version === epoch) el('execution-status').textContent = labels[result.phase];
  };
  el('execution-status').textContent = labels.planning;
  let polling = false;
  const timer = setInterval(() => {
    if (polling) return;
    polling = true;
    void api.execution(request.request_id).then(show).catch(() => {}).finally(() => { polling = false; });
  }, 1500);
  let published: string | null = null;
  try {
    let result: ExecutionResult;
    try { result = await api.executeFeedback(request); }
    catch (error) {
      const recovered = await api.execution(request.request_id).catch(() => null);
      if (recovered?.phase === 'ready' || recovered?.phase === 'no_document_change') result = recovered;
      else throw error;
    }
    show(result);
    if (result.phase === 'failed') throw new ApiError(result.error_status ?? 'validation_failed');
    if (result.phase === 'ready') { if (!result.version_id) throw new ApiError('validation_failed'); published = result.version_id; }
    else if (result.phase !== 'no_document_change') el('execution-status').textContent = '执行仍在进行，可稍后检查同一请求。';
  } catch (error) {
    if (version === epoch) el('execution-status').textContent = `${errorMessage(error)} 可重试同一生成请求。`;
  } finally {
    clearInterval(timer); confirmingTarget = false; button('execute-feedback').textContent = '检查／重试生成';
    analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = false;
  }
  if (published && version === epoch) {
    try {
      versions = await api.versions();
      const next = versions.versions.find(item => item.version_id === published);
      if (!next) { notice('新版本已发布，请刷新版本列表。'); return; }
      executionRetry = null; await selectVersion(next); notice(`V${next.sequence} 已生成，论文、报告和预览已更新。`);
    } catch { notice('新版本已发布，版本列表读取失败，可刷新后查看。', true); }
  }
  if (version === epoch) void reloadWork();
}
async function confirmProcessing(answer: ProcessingAnswer, rawAnswer: string) {
  if (!api || !context || !currentAnalysis || confirmingTarget || selected?.version_id !== versions?.working_version_id) return;
  const result = currentAnalysis.interpretation, version = epoch, target = targetEpoch;
  const fingerprint = JSON.stringify({ result: result.result_id, answer });
  if (processingRetry?.fingerprint !== fingerprint) processingRetry = { fingerprint, body: {
    schema_version: 'feedback-confirmation-request/1.0', request_id: crypto.randomUUID().replaceAll('-', ''),
    task_id: api.taskId, base_version_id: context.base_version_id, expected_base_docx_sha256: context.base_docx_sha256,
    expected_context_id: context.context_id, feedback_id: result.feedback_id, expected_parse_result_id: result.result_id, raw_answer: rawAnswer, answer,
  } };
  confirmingTarget = true; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = true;
  try {
    const confirmed = await api.confirmProcessing(processingRetry.body);
    if (version !== epoch || target !== targetEpoch) return;
    if (confirmed.interpretation.feedback_id !== result.feedback_id || confirmed.interpretation.version_context_id !== context.context_id) throw new ApiError('stale_preview');
    processingRetry = null; showAnalysis(confirmed);
  } catch (error) {
    if (version === epoch && target === targetEpoch) el('analysis-status').textContent = `${errorMessage(error)} 原答案已保留，可重试同一操作。`;
  } finally {
    confirmingTarget = false; analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = false;
  }
  if (version === epoch) void reloadWork();
  if (version === epoch && target === targetEpoch && !processingRetry && executionAvailable && currentAnalysis?.interpretation.kind === 'new_rule') await reviewRules(true);
}
async function confirmTarget(result: SelectionResolution, candidateId: string, label: string) {
  if (!api || !context || confirmingTarget || selected?.version_id !== versions?.working_version_id) return;
  const currentVersion = epoch, currentTarget = targetEpoch;
  if (targetRetry?.candidate_id !== candidateId || targetRetry.expected_resolution_id !== result.resolution_id) {
    targetRetry = { schema_version: 'selection-target-confirmation/1.0', request_id: crypto.randomUUID().replaceAll('-', ''),
      task_id: api.taskId, base_version_id: context.base_version_id, feedback_id: result.feedback_id,
      expected_base_docx_sha256: context.base_docx_sha256, expected_context_id: context.context_id,
      expected_resolution_id: result.resolution_id, candidate_id: candidateId, raw_answer: `确认此位置：${label}` };
  }
  let confirmedTarget = false;
  confirmingTarget = true; showTarget(result); analysisBusy(); renderVersions(); showReceipts(); controls(); button('refresh').disabled = true;
  try {
    const confirmed = await api.confirmTarget(targetRetry);
    if (currentVersion !== epoch || currentTarget !== targetEpoch) return;
    if (confirmed.feedback_id !== result.feedback_id || confirmed.version_context_id !== context?.context_id) throw new Error('目标确认结果与当前反馈不一致，请重新加载。');
    targetRetry = null; showTarget(confirmed); confirmedTarget = true;
  } catch (error) {
    if (currentVersion === epoch && currentTarget === targetEpoch) el('target-status').textContent = errorMessage(error);
  } finally {
    confirmingTarget = false; renderVersions(); showReceipts(); controls(); button('refresh').disabled = false;
    for (const choice of el('target-candidates').querySelectorAll<HTMLButtonElement>('button')) choice.disabled = !context || selected?.version_id !== versions?.working_version_id;
    analysisBusy();
    if (confirmedTarget) {
      const receipt = receipts.find(receipt => receipt.feedback_id === result.feedback_id);
      if (receipt) void locateReceipt(receipt, executionAvailable);
    }
  }
}
async function renderPage() {
  if (!context || loading) return;
  const currentEpoch = epoch, localRender = ++renderEpoch;
  rendering = true; clearSelection(); controls();
  el('pdf').hidden = false; el('preview-state').hidden = true;
  lastRenderedWidth = el('pdf').clientWidth;
  pageInput.value = String(page);
  try {
    const actualScale = await viewer.render(page, scale);
    if (currentEpoch !== epoch || localRender !== renderEpoch || actualScale === null) return;
    effectiveScale = actualScale; el('zoom-label').textContent = `${Math.round(actualScale * 100)}%`;
    el('pdf').hidden = false; el('preview-state').hidden = true;
    el('pdf').scrollTop = 0;
  } catch {
    if (currentEpoch !== epoch || localRender !== renderEpoch) return;
    context = null;
    state('页面显示失败', '请刷新版本列表后重新加载预览。');
    notice('无法显示该页，已有论文和报告仍可下载。', true);
  } finally {
    if (currentEpoch === epoch && localRender === renderEpoch) { rendering = false; scheduleDraft(); }
  }
}
async function selectVersion(version: Version) {
  if (!api || saving || confirmingTarget || switching) return;
  const currentEpoch = ++epoch;
  controller?.abort(); controller = new AbortController(); const signal = controller.signal;
  selected = version; context = null; loading = true; rendering = false;
  workEpoch++; workController?.abort(); workQueue = null; workItems = []; workLoading = false;
  el('work-status').textContent = ''; el('continue-status').textContent = '';
  clearTarget();
  page = 1; scale = 'fit'; receipts = []; retrySubmission = null;
  clearSelection(); textarea.value = ''; notice(); showReceipts();
  el('report').hidden = true; el('report-empty').hidden = false;
  el('report-empty').textContent = version.kind === 'original' ? 'V0 保存上传时的论文原稿。' : '正在读取该版本的报告…';
  el('feedback-status').textContent = version.version_id === versions?.working_version_id ?
    (executionAvailable ? '明确的格式需求在核对后自动生成新版本；有疑问时先确认。' : '反馈保存后待后续处理，暂不执行论文修改。') : '此版本仅供查看；添加反馈需回到当前工作起点。';
  el('version-badge').textContent = `V${version.sequence}`;
  el('page-count').textContent = '—'; el('zoom-label').textContent = '—';
  el('renderer').textContent = '预览由论文版本生成';
  renderVersions(); controls(); state('正在加载预览', `读取 V${version.sequence} 的 PDF 与报告…`);
  try {
    await viewer.dispose();
    if (currentEpoch !== epoch) return;
    if (version.kind === 'original') { state('论文原稿 V0', '原稿保留上传文件；待确认项处理完成后，可生成初稿预览与报告。'); return; }
    const [bound, report, pdfBytes, feedback] = await Promise.all([
      api.context(version.version_id, signal), api.report(version.version_id, signal),
      api.pdf(version.version_id, signal), api.receipts(version.version_id, signal),
    ]);
    const digest = await sha256(pdfBytes);
    if (currentEpoch !== epoch) return;
    if (bound.task_id !== api.taskId || bound.base_version_id !== version.version_id || bound.base_docx_sha256 !== version.docx_sha256 || digest !== bound.preview_pdf_sha256 ||
      report.task_id !== api.taskId || report.version_id !== version.version_id || report.output_docx_sha256 !== version.docx_sha256 || report.preview.artifact_id !== bound.preview_artifact_id) throw new ApiError('stale_preview');
    await viewer.open(pdfBytes, bound.page_count);
    if (currentEpoch !== epoch) return;
    context = bound; receipts = feedback;
    el('page-count').textContent = String(bound.page_count); pageInput.max = String(bound.page_count);
    el('renderer').textContent = `${bound.renderer_id} · V${version.sequence}`;
    showReport(report); showReceipts();
    loading = false; await renderPage();
    if (currentEpoch === epoch) void reloadWork();
  } catch (error) {
    if (currentEpoch !== epoch || signal.aborted) return;
    context = null;
    state('预览加载失败', '可刷新后重试，或先下载该版本的论文。');
    notice(errorMessage(error), true);
  } finally {
    if (currentEpoch === epoch) { loading = false; controls(); }
  }
}
async function refresh() {
  if (!api || saving || confirmingTarget || switching || initialReview?.busy) return;
  button('refresh').disabled = true;
  try {
    const [list, available] = await Promise.all([api.versions(), api.executionEnabled()]); versions = list; executionAvailable = available;
    if (list.versions.some(item => item.kind === 'output')) initialReview?.hide();
    else {
      try { await initialReview?.load(); }
      catch (error) {
        if (error instanceof ApiError && error.status === 'unavailable') initialReview?.hide();
        else throw error;
      }
    }
    const version = list.versions.find(item => item.version_id === selected?.version_id) ?? list.versions.find(item => item.version_id === list.working_version_id);
    if (!version) { state('还没有可预览的版本', '请先完成论文首次处理。'); return; }
    await selectVersion(version);
  } catch (error) { state('无法读取版本', '请刷新重试。'); notice(errorMessage(error), true); }
  finally { button('refresh').disabled = false; }
}
button('refresh').addEventListener('click', () => void refresh());
button('clear-selection').addEventListener('click', clearSelection);
// Pointer/keyboard selection events only come from the PDF, preserving the
// captured hint when focus moves to the feedback textarea.
el('pdf').addEventListener('pointerup', () => { if (!rendering && !saving) setSelection(viewer.selection()); });
el('pdf').addEventListener('keyup', () => { if (!rendering && !saving) setSelection(viewer.selection()); });
button('home').addEventListener('click', () => { if (session && !saving && !confirmingTarget && !switching) location.hash = `session=${session.token}`; });
button('previous').addEventListener('click', () => { page--; void renderPage(); });
button('next').addEventListener('click', () => { page++; void renderPage(); });
pageInput.addEventListener('change', () => { page = Math.max(1, Math.min(context?.page_count ?? 1, Math.trunc(Number(pageInput.value)) || 1)); void renderPage(); });
button('zoom-in').addEventListener('click', () => { scale = Math.min(2, effectiveScale + 0.2); void renderPage(); });
button('zoom-out').addEventListener('click', () => { scale = Math.max(0.4, effectiveScale - 0.2); void renderPage(); });
button('fit').addEventListener('click', () => { scale = 'fit'; void renderPage(); });
textarea.addEventListener('input', () => scheduleDraft());
scopeSelect.addEventListener('change', () => { requestedScope = scopeSelect.value as FeedbackScope; scheduleDraft(); });
button('review-feedback').addEventListener('click', () => scheduleDraft(true));
for (const [id, kind] of [['download-docx', 'docx'], ['download-report', 'report_markdown']] as const) {
  button(id).addEventListener('click', async () => {
    const version = selected;
    if (!api || !version) return;
    try { await api.download(version.version_id, kind, `V${version.sequence}`); }
    catch (error) { notice(errorMessage(error), true); }
  });
}
button('save-feedback').addEventListener('click', async () => {
  if (!api || !context || !canSave() || !textarea.value.trim()) return;
  const currentEpoch = epoch;
  const reviewed = retrySubmission?.body;
  const body = prepareSubmission();
  if (body !== reviewed) { scheduleDraft(true); return; }
  saving = true; controls(); renderVersions(); button('refresh').disabled = true;
  try {
    const receipt = await api.submit(body);
    if (currentEpoch !== epoch) return;
    if (!receipts.some(value => value.feedback_id === receipt.feedback_id)) receipts.push(receipt);
    workQueue = null; workItems = [];
    textarea.value = ''; retrySubmission = null; clearDraft(); showReceipts();
    el('feedback-status').textContent = '反馈已保存，尚未执行论文修改。';
    notice('反馈已保存，正在核对需求、位置与实际范围。');
    void locateReceipt(receipt, true);
  } catch (error) {
    if (currentEpoch !== epoch) return;
    el('feedback-status').textContent = '保存未完成，原输入保留；可重试同一请求。'; notice(errorMessage(error), true);
    if (error instanceof ApiError && ['stale_base_version', 'stale_preview'].includes(error.status)) { context = null; clearSelection(); }
  } finally { saving = false; controls(); renderVersions(); button('refresh').disabled = false; }
});
let resizeTimer: ReturnType<typeof setTimeout>;
new ResizeObserver(() => {
  // Initial visibility and height changes also fire this observer. Only an
  // actual width change needs a new fit render, otherwise selection is lost.
  if (Math.abs(el('pdf').clientWidth - lastRenderedWidth) < 1) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (scale === 'fit' && context && !loading && !saving) void renderPage(); }, 180);
}).observe(el('pdf'));

window.addEventListener('hashchange', () => {
  // A host can open a new task in an existing tab. Reinitialize with that new
  // ephemeral session; the fragment is erased by bootstrap on reload.
  if (location.hash.startsWith('#session=')) location.reload();
});

if (api) void refresh();
else { state('请从 AutoFormat 打开预览', '此页面需要由本地任务会话启动。'); button('refresh').disabled = true; }
