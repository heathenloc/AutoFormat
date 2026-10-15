import './style.css';
import { ApiError, errorMessage, sha256 } from './api';

interface Task { task_id: string; created_at: string; working_sequence: number; version_count: number; has_initial_version: boolean }
interface Catalog { schema_version: 'task-catalog/1.0'; tasks: Task[]; next_before: number | null }
interface Info { schema_version: 'application-info/1.0'; mode: 'demo' | 'configured'; upload_available: boolean; max_file_bytes: number | null }
const token = new URLSearchParams(location.hash.slice(1)).get('session') ?? '';
history.replaceState(null, '', location.pathname);
document.title = 'AutoFormat · 论文任务';
document.querySelector('#app')!.innerHTML = `
  <header class="topbar"><div class="brand"><span class="brand-mark">A</span>AutoFormat</div><span class="top-divider"></span><span class="workspace-name">论文工作台</span><span class="local-badge">本地应用</span></header>
  <main class="home-layout"><section class="home-intro"><span class="eyebrow">开始整理论文格式</span><h1>从学校要求，到你的论文初稿。</h1><p class="muted">上传 Brief 与论文原稿。先核对不确定的要求，再生成独立初稿；原稿和历史版本完整保留。</p><p id="application-mode" role="status"></p></section>
  <section class="home-card"><h2>新建论文任务</h2><form id="upload-form"><fieldset id="upload-fields" disabled>
    <label class="upload-file">学校 Brief／格式模板<input id="brief-file" type="file" accept=".docx,.pdf,.txt" required><span class="small muted">支持 DOCX、PDF、TXT</span></label>
    <label class="upload-file">论文原稿<input id="paper-file" type="file" accept=".docx" required><span class="small muted">仅支持 DOCX，原稿保存为 V0</span></label>
    <label class="upload-consent"><input id="model-consent" type="checkbox" required><span>我已了解：Brief 解析可能调用配置的云端模型；论文正文和预览反馈由本地程序处理，不发送给模型。</span></label>
    <button id="upload-task" class="button primary wide" type="submit">上传并解析要求</button>
  </fieldset></form><p id="upload-status" role="status" class="small muted">正在检查本地服务…</p></section>
  <section class="home-card"><div class="section-title"><h2>已有任务</h2><button id="refresh-tasks" class="text-button">刷新任务</button></div><p class="small muted">重新打开后继续处理问题，或查看与下载已保存的版本。</p><ul id="task-list" class="task-list"></ul><p id="task-status" class="small muted" role="status"></p><button id="more-tasks" class="button subtle wide" hidden>加载更早任务</button></section></main>`;
const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let info: Info | null = null, tasks: Task[] = [], before: number | null = null;
let busy = false, listing = false;
let retry: { fingerprint: string; requestId: string } | null = null;
async function request(path: string, body?: FormData): Promise<Response> {
  const response = await fetch(path, { method: body ? 'POST' : 'GET', body, cache: 'no-store', credentials: 'omit', headers: { 'X-AutoFormat-Session': token } });
  if (!response.ok) {
    if ([401, 403].includes(response.status)) throw new ApiError('session_expired');
    const data = await response.json().catch(() => ({})); throw new ApiError(data.status ?? 'unavailable');
  }
  return response;
}
function controls() {
  el<HTMLFieldSetElement>('upload-fields').disabled = busy || !info?.upload_available;
  el<HTMLButtonElement>('refresh-tasks').disabled = busy || listing;
  el<HTMLButtonElement>('more-tasks').disabled = busy || listing;
  for (const button of el('task-list').querySelectorAll('button')) button.disabled = busy;
  el('upload-task').textContent = busy ? '正在处理…' : retry ? '重试同一次上传' : '上传并解析要求';
}
function openTask(id: string) {
  if (!busy && /^[a-f0-9]{32}$/.test(id)) location.hash = `session=${token}&task=${id}`;
}
function renderTasks() {
  el('task-list').replaceChildren();
  for (const task of tasks) {
    const item = document.createElement('li'), button = document.createElement('button'); button.className = 'task-open';
    const title = document.createElement('strong'); title.textContent = `论文任务 · ${task.task_id.slice(0, 8)}`;
    const detail = document.createElement('span'); detail.textContent = `${new Date(task.created_at).toLocaleString('zh-CN')} · ${task.has_initial_version ? `工作起点 V${task.working_sequence} · ${task.version_count} 个版本` : '等待确认或初稿生成'}`;
    button.append(title, detail); button.dataset.taskId = task.task_id; button.addEventListener('click', () => openTask(task.task_id)); item.append(button); el('task-list').append(item);
  }
  el('more-tasks').hidden = before === null; controls();
}
async function loadTasks(more = false) {
  if (listing || busy) return;
  listing = true; controls(); el('task-status').textContent = '正在读取已保存的任务…';
  try {
    const result: Catalog = await (await request('/api/tasks' + (more && before ? `?before=${before}` : ''))).json();
    if (result.schema_version !== 'task-catalog/1.0' || !result.tasks.every(t => /^[a-f0-9]{32}$/.test(t.task_id))) throw new ApiError('validation_failed');
    tasks = more ? [...tasks, ...result.tasks.filter(t => !tasks.some(old => old.task_id === t.task_id))] : result.tasks;
    before = result.next_before; renderTasks(); el('task-status').textContent = tasks.length ? `已加载 ${tasks.length} 个任务。` : '暂无任务。上传两个文件即可开始。';
  } catch (error) { el('task-status').textContent = errorMessage(error); }
  finally { listing = false; controls(); }
}
el('refresh-tasks').addEventListener('click', () => void loadTasks());
el('more-tasks').addEventListener('click', () => void loadTasks(true));
el('upload-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !info?.upload_available) return;
  const brief = el<HTMLInputElement>('brief-file').files?.[0], paper = el<HTMLInputElement>('paper-file').files?.[0];
  if (!brief || !paper || !el<HTMLInputElement>('model-consent').checked) return;
  if (!/\.(docx|pdf|txt)$/i.test(brief.name) || !/\.docx$/i.test(paper.name) || [brief, paper].some(file => !file.size || file.size > info!.max_file_bytes!)) {
    el('upload-status').textContent = `请检查文件类型与大小：每个文件须非空且不超过 ${Math.floor(info.max_file_bytes! / 1024 / 1024)} MB。`; return;
  }
  busy = true; controls(); el('upload-status').textContent = '正在上传、解析 Brief 并检查初稿条件。有不确定项时会先请你确认；请保持本地应用运行。';
  try {
    const fingerprint = JSON.stringify({ brief: await sha256(new Uint8Array(await brief.arrayBuffer())), paper: await sha256(new Uint8Array(await paper.arrayBuffer())), briefName: brief.name, paperName: paper.name });
    if (retry?.fingerprint !== fingerprint) retry = { fingerprint, requestId: crypto.randomUUID().replaceAll('-', '') };
    const form = new FormData(); form.set('request_id', retry.requestId); form.set('model_processing_acknowledged', 'true'); form.set('brief', brief); form.set('paper', paper);
    const result = await (await request('/api/tasks', form)).json();
    if (result.schema_version !== 'task-intake/1.2' || !/^[a-f0-9]{32}$/.test(result.task_id) || !['reviewing_requirements', 'initial_draft_ready'].includes(result.phase)) throw new ApiError('validation_failed');
    retry = null; busy = false; openTask(result.task_id);
  } catch (error) { el('upload-status').textContent = `${errorMessage(error)} 文件选择已保留；重试相同文件会使用同一请求。`; }
  finally { busy = false; controls(); }
});
window.addEventListener('hashchange', () => { if (location.hash.startsWith('#session=')) location.reload(); });
async function start() {
  try {
    info = await (await request('/api/application')).json();
    if (info?.schema_version !== 'application-info/1.0' || (info.upload_available && (!info.max_file_bytes || info.max_file_bytes < 1))) throw new ApiError('validation_failed');
    el('application-mode').textContent = info.mode === 'demo' ? '离线演示模式：不调用云端模型，解析能力不代表真实模型效果。' : 'Brief 使用本机配置的解析服务；原稿与版本保存在本地。';
    el('upload-status').textContent = info.upload_available ? '提交后先解析学校要求；没有待确认项时直接生成初稿。' : '当前宿主仅支持已有任务，未启用上传与初稿发布。'; controls();
    await loadTasks();
  } catch (error) { el('upload-status').textContent = errorMessage(error); }
}
void start();
