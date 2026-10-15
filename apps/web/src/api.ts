import type { FeedbackContext, Receipt, Report, Submission, VersionList, SelectionResolution, TargetConfirmation, DraftReview, FeedbackAnalysis, ProcessingConfirmation } from './contracts';

export class ApiError extends Error {
  constructor(readonly status: string) { super(status); }
}
export function errorMessage(error: unknown): string {
  const messages: Record<string, string> = {
    session_expired: '本地会话已失效，请从 AutoFormat 重新打开预览。',
    stale_base_version: '当前工作版本已改变，请刷新版本列表后重新选择。',
    stale_preview: '预览与该版本不再匹配，请重新加载并重新选择文字。',
    needs_user_input: '当前输入或目标无法确定，请重新选择文字或补充说明。',
    unsafe_input: '当前选择或输入无法安全处理，请重新选择文字。',
    blocked_conflict: '请求与已有记录冲突，请刷新后重试。',
    render_failed: '该版本的预览暂时不可用，请检查渲染结果。',
    validation_failed: '文件校验未通过，请重新加载该版本。',
    unsupported_target: '本地定位暂不可用或选区结构不受支持；反馈仍已保存。',
  };
  return error instanceof ApiError ? messages[error.status] ?? '本地服务请求失败，请重试。' :
    '无法连接本地服务，请检查 AutoFormat 是否仍在运行。';
}

export class LocalApi {
  constructor(private readonly token: string, readonly taskId: string) {}
  private prefix(versionId?: string) {
    return `/api/tasks/${this.taskId}${versionId ? `/versions/${versionId}` : ''}`;
  }
  private async request(path: string, signal?: AbortSignal, body?: unknown): Promise<Response> {
    const response = await fetch(path, {
      method: body ? 'POST' : 'GET', signal, cache: 'no-store', credentials: 'omit',
      headers: { 'X-AutoFormat-Session': this.token, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      if ([401, 403].includes(response.status)) throw new ApiError('session_expired');
      const payload = await response.json().catch(() => ({}));
      throw new ApiError(typeof payload.status === 'string' ? payload.status : 'unavailable');
    }
    return response;
  }
  async versions(signal?: AbortSignal): Promise<VersionList> {
    return (await this.request(this.prefix() + '/versions', signal)).json();
  }
  async continueVersion(body: import('./contracts').ContinuationRequest): Promise<import('./contracts').Continuation> {
    return (await this.request(this.prefix(body.version_id) + '/continue', undefined, body)).json();
  }
  async workItems(version: string, signal: AbortSignal, before?: number): Promise<import('./contracts').WorkQueue> {
    return (await this.request(this.prefix(version) + '/work-items' + (before ? `?before=${before}` : ''), signal)).json();
  }
  async initialReview(): Promise<import('./initial-review').InitialReview> {
    return (await this.request(this.prefix() + '/initial-review')).json();
  }
  async answerQuestion(body: Record<string, unknown>): Promise<void> {
    await this.request(this.prefix() + '/decisions', undefined, body);
  }
  async generateInitial(body: Record<string, unknown>): Promise<void> {
    await this.request(this.prefix() + '/initial-draft', undefined, body);
  }
  async context(version: string, signal: AbortSignal): Promise<FeedbackContext> {
    return (await this.request(this.prefix(version) + '/feedback-context', signal)).json();
  }
  async report(version: string, signal: AbortSignal): Promise<Report> {
    return (await this.request(this.prefix(version) + '/artifacts/report_json', signal)).json();
  }
  async pdf(version: string, signal: AbortSignal): Promise<Uint8Array> {
    return new Uint8Array(await (await this.request(this.prefix(version) + '/artifacts/preview', signal)).arrayBuffer());
  }
  async receipts(version: string, signal: AbortSignal): Promise<Receipt[]> {
    return (await (await this.request(this.prefix(version) + '/feedback', signal)).json()).feedback;
  }
  async submit(body: Submission): Promise<Receipt> {
    return (await this.request(this.prefix(body.base_version_id) + '/feedback', undefined, body)).json();
  }
  async review(body: Submission, signal: AbortSignal): Promise<DraftReview> {
    return (await this.request(this.prefix(body.base_version_id) + '/feedback/review', signal, body)).json();
  }
  async analysis(version: string, feedbackId: string, signal: AbortSignal): Promise<FeedbackAnalysis> {
    return (await this.request(this.prefix(version) + `/feedback/${feedbackId}/analysis`, signal)).json();
  }
  async confirmProcessing(body: ProcessingConfirmation): Promise<FeedbackAnalysis> {
    return (await this.request(this.prefix(body.base_version_id) + `/feedback/${body.feedback_id}/analysis/confirm`, undefined, body)).json();
  }
  async rules(version: string, feedbackId: string, signal: AbortSignal): Promise<import('./contracts').RulesReview> {
    return (await this.request(this.prefix(version) + `/feedback/${feedbackId}/rules`, signal)).json();
  }
  async decideRule(body: import('./contracts').RulesDecision): Promise<import('./contracts').RulesReview> {
    return (await this.request(this.prefix(body.base_version_id) + `/feedback/${body.feedback_id}/rules/decide`, undefined, body)).json();
  }
  async executionEnabled(): Promise<boolean> {
    return (await (await this.request(this.prefix() + '/feedback-execution-capability')).json()).available === true;
  }
  async executeFeedback(body: import('./contracts').ExecutionRequest): Promise<import('./contracts').ExecutionResult> {
    return (await this.request(this.prefix(body.base_version_id) + '/feedback-executions', undefined, body)).json();
  }
  async execution(requestId: string): Promise<import('./contracts').ExecutionResult> {
    return (await this.request(this.prefix() + `/feedback-executions/${requestId}`)).json();
  }
  async selection(version: string, feedbackId: string, signal: AbortSignal): Promise<SelectionResolution> {
    return (await this.request(this.prefix(version) + `/feedback/${feedbackId}/selection`, signal)).json();
  }
  async confirmTarget(body: TargetConfirmation): Promise<SelectionResolution> {
    return (await this.request(this.prefix(body.base_version_id) + `/feedback/${body.feedback_id}/selection/confirm`, undefined, body)).json();
  }
  async download(version: string, kind: 'docx' | 'report_markdown', label: string) {
    // Fetch with the session header; a normal link cannot authorize a download.
    const blob = await (await this.request(this.prefix(version) + `/artifacts/${kind}`)).blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = `AutoFormat-${label}.${kind === 'docx' ? 'docx' : 'md'}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as Uint8Array<ArrayBuffer>);
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

export function bootstrap(): { token: string; task: string } | null {
  const parameters = new URLSearchParams(location.hash.slice(1));
  const token = parameters.get('session') ?? '';
  const task = parameters.get('task') ?? '';
  // Do not retain credentials in history, storage, visible URL or telemetry.
  history.replaceState(null, '', location.pathname);
  return /^[a-f0-9]{32}$/.test(task) && /^[A-Za-z0-9_-]{32,200}$/.test(token) ? { token, task } : null;
}
