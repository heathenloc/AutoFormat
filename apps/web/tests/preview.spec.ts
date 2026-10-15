import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const token = 'preview-browser-test-session-token-1234567890';
const manifest = () => JSON.parse(readFileSync(resolve('../../runtime/browser-preview/manifest.json'), 'utf8')) as { task: string; v0: string; v1: string; v2: string; pdf_sha256: string; duplicate_task: string; duplicate_v1: string; rules_tasks: Record<string, { task: string; version: string }> };
const headers = { 'X-AutoFormat-Session': token };
const prefix = (version: string) => `/api/tasks/${manifest().task}/versions/${version}`;
async function openRulesTask(page: Page, name: string) {
  const task = manifest().rules_tasks[name];
  await page.goto(`/#session=${token}&task=${task.task}`);
  await expect(page.locator('#next')).toBeEnabled();
  await expect(page.locator('.textLayer')).toContainText('Selectable preview text');
  return task;
}
async function open(page: Page) {
  await page.goto(`/#session=${token}&task=${manifest().task}`);
  await expect(page.locator('#page-count')).toHaveText('2');
  await expect(page.locator('#next')).toBeEnabled();
  await expect(page.locator('.textLayer')).toContainText('Selectable preview text');
}
async function selectText(page: Page, text: string) {
  await expect(page.locator('#pdf')).toHaveAttribute('aria-busy', 'false');
  const span = page.locator('.textLayer span').filter({ hasText: text }).first();
  await expect(span).toBeVisible();
  await span.evaluate(element => {
    const range = document.createRange(); range.selectNodeContents(element);
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
    element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
  });
  await expect(page.locator('#selection-text')).toContainText(text);
}

test('local rule conflict shows evidence and saves a bounded exception without editing', async ({ page, request }) => {
  test.setTimeout(60000);
  const task = await openRulesTask(page, 'local');
  const url = `/api/tasks/${task.task}/versions/${task.version}`;
  const before = await (await request.get(url + '/artifacts/docx', { headers })).body();
  await selectText(page, 'Selectable preview text'); await page.locator('#feedback-text').fill('字号14pt');
  await page.locator('#save-feedback').click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await page.locator('#review-rules').click();
  await expect(page.locator('.rule-conflict')).toHaveCount(1, { timeout: 20000 });
  await expect(page.locator('.old-rule')).toContainText('12 pt'); await expect(page.locator('.incoming-rule')).toContainText('14 pt');
  await page.getByText('查看规则来源', { exact: true }).click();
  await expect(page.locator('.rule-conflict blockquote')).toContainText('正文采用12pt字号');
  await expect(page.locator('.rule-conflict')).toContainText('1 个对象');
  await expect(page.getByRole('button', { name: '更新已确认范围的规则' })).toHaveCount(0);
  await page.screenshot({ path: '../../runtime/preview-step5-conflict.png', fullPage: true });
  await page.getByRole('button', { name: '设为本处例外' }).click();
  await expect(page.locator('#rules-details')).toHaveAttribute('data-status', 'ready', { timeout: 20000 });
  await expect(page.locator('.conflict-resolved')).toContainText('设为本处例外');
  expect(await (await request.get(url + '/artifacts/docx', { headers })).body()).toEqual(before);
  expect((await (await request.get(`/api/tasks/${task.task}/versions`, { headers })).json()).versions).toHaveLength(2);
  await page.goto(`/#session=${token}&task=${task.task}`); await expect(page.locator('#next')).toBeEnabled();
  await page.locator('#feedback-list button').first().click();
  await expect(page.locator('#review-rules')).toBeVisible({ timeout: 15000 }); await page.locator('#review-rules').click();
  await expect(page.locator('.conflict-resolved')).toContainText('设为本处例外', { timeout: 20000 });
});

test('global rule update requires actual scope confirmation and excludes local-only action', async ({ page }) => {
  test.setTimeout(60000);
  await openRulesTask(page, 'global'); await page.locator('#feedback-text').fill('全文字号14pt');
  await page.locator('#save-feedback').click();
  await expect(page.locator('.confirm-scope')).toBeVisible({ timeout: 15000 });
  await page.locator('#review-rules').click();
  await expect(page.locator('#rules-details')).toContainText('请先确认上方实际范围', { timeout: 15000 });
  await expect(page.locator('.rules-action')).toHaveCount(0);
  await page.locator('.confirm-scope').click();
  await expect(page.locator('#analysis-status')).toContainText('已保存 1 项', { timeout: 15000 });
  await expect(page.locator('#review-rules')).toBeEnabled(); await page.locator('#review-rules').click();
  await expect(page.locator('.rule-conflict')).toHaveCount(1, { timeout: 20000 });
  await expect(page.getByRole('button', { name: '设为本处例外' })).toHaveCount(0);
  await page.getByRole('button', { name: '更新已确认范围的规则' }).click();
  await expect(page.locator('#rules-details')).toHaveAttribute('data-status', 'ready', { timeout: 20000 });
  await page.setViewportSize({ width: 760, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(760);
  await page.screenshot({ path: '../../runtime/preview-step5-global.png', fullPage: true });
});

test('lost conflict-choice response retries the same request and locks concurrent controls', async ({ page }) => {
  test.setTimeout(60000);
  await openRulesTask(page, 'retry'); await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-text').fill('字号14pt'); await page.locator('#save-feedback').click();
  await expect(page.locator('#review-rules')).toBeVisible({ timeout: 15000 }); await page.locator('#review-rules').click();
  const choice = page.getByRole('button', { name: '保留原规则', exact: true }); await expect(choice).toBeEnabled({ timeout: 20000 });
  const ids: string[] = []; let first = true;
  await page.route('**/rules/decide', async route => {
    ids.push(JSON.parse(route.request().postData()!).request_id);
    if (first) { first = false; await route.fetch(); await route.abort('failed'); } else await route.continue();
  });
  await choice.click(); await expect(page.locator('.version-item').first()).toBeDisabled();
  await expect(page.locator('#feedback-text')).toBeDisabled();
  await expect(page.locator('#rules-status')).toContainText('原选择已保留', { timeout: 20000 });
  await expect(choice).toBeEnabled(); await choice.click();
  await expect(page.locator('#rules-details')).toHaveAttribute('data-status', 'ready', { timeout: 20000 });
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
  await expect(page.locator('.conflict-resolved')).toContainText('保留原规则');
});

test('opens real PDF, bound report, local-only resources and removes credentials', async ({ page }) => {
  const errors: string[] = [], external: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:58371/') && !request.url().startsWith('blob:')) external.push(request.url()); });
  await open(page);
  await expect(page.locator('#version-badge')).toHaveText('V2');
  await expect(page.locator('#change-count')).toHaveText('1');
  await expect(page.locator('#format-status')).toHaveText('已验证格式规则');
  expect(new URL(page.url()).hash).toBe('');
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect(await page.locator('.pdf-page canvas').evaluate((canvas: HTMLCanvasElement) => canvas.width)).toBeGreaterThan(400);
  expect(errors).toEqual([]); expect(external).toEqual([]);
  await page.screenshot({ path: '../../runtime/preview-step2-desktop.png', fullPage: true });
});

test('paging and zoom clear captured selection; page bounds are clamped', async ({ page }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  await page.getByRole('button', { name: '下一页' }).click();
  await expect(page.locator('.textLayer')).toContainText('Second page content');
  await expect(page.locator('#selection-empty')).toBeVisible();
  await expect(page.getByRole('button', { name: '下一页' })).toBeDisabled();
  await selectText(page, 'Second page content');
  const before = await page.locator('#zoom-label').textContent();
  await page.getByRole('button', { name: '放大' }).click();
  await expect(page.locator('#selection-empty')).toBeVisible();
  await expect(page.locator('#zoom-label')).not.toHaveText(before!);
  await page.locator('#page').fill('999'); await page.locator('#page').press('Tab');
  await expect(page.locator('#page')).toHaveValue('2');
  await page.locator('#page').fill('-5'); await page.locator('#page').press('Tab');
  await expect(page.locator('#page')).toHaveValue('1');
  await expect(page.locator('#next')).toBeEnabled();
});

test('mouse text selection saves exact item offsets and preserves raw feedback without creating a version', async ({ page, request }) => {
  await open(page);
  const span = page.locator('.textLayer span').filter({ hasText: 'Selectable preview text' }).first();
  const box = (await span.boundingBox())!;
  await page.mouse.move(box.x + 1, box.y + box.height / 2);
  await page.mouse.down(); await page.mouse.move(box.x + box.width - 1, box.y + box.height / 2, { steps: 15 }); await page.mouse.up();
  await expect(page.locator('#selection-text')).toHaveText('Selectable preview text');
  const raw = '  这里调整字号\n请核对范围  ';
  await page.locator('#feedback-text').fill(raw);
  const response = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click();
  const receipt = await (await response).json();
  const record = await (await request.get(prefix(manifest().v2) + '/feedback/' + receipt.feedback_id, { headers })).json();
  expect(record.submission.raw_text).toBe(raw);
  expect(record.submission.selection.selected_text).toBe('Selectable preview text');
  expect(record.submission.selection.spans[0].end_offset_utf16 - record.submission.selection.spans[0].start_offset_utf16).toBe(23);
  expect(record.submission.base_version_id).toBe(manifest().v2);
  await expect(page.locator('#feedback-status')).toHaveText('反馈已保存，尚未执行论文修改。');
  await expect(page.locator('#feedback-list time').first()).toHaveText(/^\d{2}:\d{2}$/);
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ready', { timeout: 15000 });
  const target = await (await request.get(prefix(manifest().v2) + '/feedback/' + receipt.feedback_id + '/selection', { headers })).json();
  expect(target.anchor.base_version_id).toBe(manifest().v2);
  expect(target.anchor.ranges[0].object_id).toMatch(/^o:[a-f0-9]{24}$/);
  expect(target.anchor.ranges[0].matched_text).toBe('Selectable preview text');
  const versions = await (await request.get(`/api/tasks/${manifest().task}/versions`, { headers })).json();
  expect(versions.versions).toHaveLength(3);
  const pdf = await request.get(prefix(manifest().v2) + '/artifacts/preview', { headers });
  expect(createHash('sha256').update(await pdf.body()).digest('hex')).toBe(manifest().pdf_sha256);
});

test('selection from textarea does not replace PDF selection; unselected feedback is document scope', async ({ page }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-text').fill('修改字号');
  await page.locator('#feedback-text').press('Control+A');
  await expect(page.locator('#selection-text')).toHaveText('Selectable preview text');
  await page.locator('#clear-selection').click();
  const response = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click();
  const submission = JSON.parse((await response).request().postData()!);
  expect(submission.requested_scope).toBe('document'); expect(submission.selection).toBeNull();
});

test('historical browsing is read-only and cannot change working version', async ({ page, request }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  await page.locator(`[data-version-id="${manifest().v1}"]`).click();
  await expect(page.locator('#next')).toBeEnabled();
  await expect(page.locator('#version-badge')).toHaveText('V1');
  await expect(page.locator('#selection-empty')).toBeVisible();
  await expect(page.locator('#change-count')).toHaveText('0');
  await expect(page.locator('#format-status')).toHaveText('未评估格式完成度');
  await expect(page.locator('#feedback-text')).toBeDisabled();
  await page.locator(`[data-version-id="${manifest().v0}"]`).click();
  await expect(page.locator('#preview-state')).toContainText('论文原稿 V0');
  await expect(page.locator('#download-docx')).toBeEnabled();
  await expect(page.locator('#download-report')).toBeDisabled();
  const listing = await (await request.get(`/api/tasks/${manifest().task}/versions`, { headers })).json();
  expect(listing.working_version_id).toBe(manifest().v2);
});

test('downloads use selected version and authenticated requests', async ({ page }) => {
  await open(page);
  const docxResponse = page.waitForResponse(response => response.url().endsWith('/artifacts/docx'));
  const docxDownload = page.waitForEvent('download');
  await page.locator('#download-docx').click();
  expect((await docxDownload).suggestedFilename()).toBe('AutoFormat-V2.docx');
  expect((await docxResponse).request().headers()['x-autoformat-session']).toBe(token);
  await page.locator(`[data-version-id="${manifest().v1}"]`).click();
  await expect(page.locator('#next')).toBeEnabled();
  const reportResponse = page.waitForResponse(response => response.url().endsWith('/artifacts/report_markdown'));
  const reportDownload = page.waitForEvent('download');
  await page.locator('#download-report').click();
  expect((await reportDownload).suggestedFilename()).toBe('AutoFormat-V1.md');
  expect((await reportResponse).url()).toContain(manifest().v1);
});

test('late responses cannot replace the selected historical preview', async ({ page }) => {
  await page.route('**/' + manifest().v2 + '/feedback-context', async route => {
    const response = await route.fetch(); await new Promise(resolve => setTimeout(resolve, 500));
    await route.fulfill({ response }).catch(() => undefined);
  });
  await page.goto(`/#session=${token}&task=${manifest().task}`);
  await page.locator(`[data-version-id="${manifest().v1}"]`).click();
  await expect(page.locator('#next')).toBeEnabled();
  await expect(page.locator('#version-badge')).toHaveText('V1');
  await expect(page.locator('#change-count')).toHaveText('0');
  await expect(page.locator('#feedback-text')).toBeDisabled();
});

test('PDF hash mismatch blocks text selection and feedback while downloads remain available', async ({ page }) => {
  await page.route('**/artifacts/preview', async route => {
    const response = await route.fetch(); const bytes = await response.body(); bytes[bytes.length - 1] ^= 1;
    await route.fulfill({ response, body: bytes });
  });
  await page.goto(`/#session=${token}&task=${manifest().task}`);
  await expect(page.locator('#notice')).toContainText('预览与该版本不再匹配');
  await expect(page.locator('#feedback-text')).toBeDisabled();
  await expect(page.locator('#download-docx')).toBeEnabled();
  await expect(page.locator('#download-report')).toBeEnabled();
});

test('lost response retries the same idempotent payload', async ({ page, request }) => {
  await open(page); await page.locator('#feedback-text').fill('丢失响应测试');
  const ids: string[] = [];
  let aborted = false;
  await page.route('**/feedback', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    ids.push(JSON.parse(route.request().postData()!).request_id);
    if (!aborted) { aborted = true; await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await page.locator('#save-feedback').click();
  await expect(page.locator('#feedback-status')).toContainText('原输入保留');
  await expect(page.locator('#feedback-text')).toHaveValue('丢失响应测试');
  const response = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click();
  expect((await (await response).json()).replayed).toBe(true);
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
  const listing = await (await request.get(`/api/tasks/${manifest().task}/versions`, { headers })).json();
  expect(listing.versions).toHaveLength(3);
});

test('missing session has a clear empty state; smaller viewport remains usable', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#preview-state')).toContainText('请从 AutoFormat 打开预览');
  await page.setViewportSize({ width: 760, height: 900 });
  await open(page);
  await expect(page.locator('#download-docx')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(760);
  await page.screenshot({ path: '../../runtime/preview-step2-narrow.png', fullPage: true });
});

test('Chinese and multiline selections retain item indices and raw text', async ({ page }) => {
  test.skip(!process.env.AUTOFORMAT_TEST_SOFFICE, 'Real renderer is required for Chinese fixture text.');
  await open(page);
  await selectText(page, '材料学院毕业论文格式预览');
  await expect(page.locator('#selection-text')).toHaveText('材料学院毕业论文格式预览');
  await page.locator('.textLayer').evaluate(layer => {
    const spans = [...layer.querySelectorAll('span')];
    const first = spans.find(span => span.textContent?.includes('Selectable preview text'))!;
    const last = spans.find(span => span.textContent?.includes('Another line of text'))!;
    const range = document.createRange(); range.setStart(first.firstChild!, 0); range.setEnd(last.firstChild!, last.textContent!.length);
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
    last.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
  });
  await expect(page.locator('#selection-text')).toContainText('Another line of text');
  const text = await page.locator('#selection-text').textContent();
  expect(text).toContain('\n');
  await page.locator('#feedback-text').fill('跨行格式反馈');
  const response = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click();
  const submission = JSON.parse((await response).request().postData()!);
  expect(submission.selection.selected_text).toBe(text);
  expect(submission.selection.spans[0].end_item).toBeGreaterThan(submission.selection.spans[0].start_item);
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ambiguous', { timeout: 15000 });
  await expect(page.locator('.target-candidate')).toHaveCount(1);
  await expect(page.locator('.target-candidate')).toContainText('第 1 段 至 正文 · 第 3 段');
  await page.locator('.target-candidate button').click();
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ready', { timeout: 15000 });
  await expect(page.locator('#target-candidates')).toContainText('已定位 3 处 DOCX 文字范围');
});

async function ambiguousFeedback(page: Page) {
  await page.goto(`/#session=${token}&task=${manifest().duplicate_task}`);
  await expect(page.locator('#next')).toBeEnabled();
  await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-text').fill('重复文字定位测试');
  await page.locator('#save-feedback').click();
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ambiguous', { timeout: 15000 });
  await expect(page.locator('.target-candidate')).toHaveCount(2);
}

test('duplicate targets show source candidates; explicit choice survives a new session', async ({ page, request }) => {
  await ambiguousFeedback(page);
  await expect(page.locator('.target-candidate').last()).toContainText('第 2 段');
  await page.screenshot({ path: '../../runtime/preview-step3-candidates.png', fullPage: true });
  const response = page.waitForResponse(response => response.url().endsWith('/selection/confirm'));
  await page.locator('.target-candidate button').last().click();
  const result = await (await response).json();
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ready');
  expect(result.anchor.ranges).toHaveLength(1);
  await page.goto(`/#session=${token}&task=${manifest().duplicate_task}`);
  await expect(page.locator('#next')).toBeEnabled();
  await page.locator('#feedback-list button').first().click();
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ready', { timeout: 15000 });
  const listing = await (await request.get(`/api/tasks/${manifest().duplicate_task}/versions`, { headers })).json();
  expect(listing.versions).toHaveLength(2);
});

test('lost target confirmation retries one request and prevents concurrent version changes', async ({ page }) => {
  await ambiguousFeedback(page);
  const ids: string[] = [];
  let first = true;
  await page.route('**/selection/confirm', async route => {
    ids.push(JSON.parse(route.request().postData()!).request_id);
    if (first) { first = false; await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await page.locator('.target-candidate button').last().click();
  await expect(page.locator('.version-item').first()).toBeDisabled();
  await expect(page.locator('#target-status')).not.toContainText('请核对上下文');
  await expect(page.locator('.target-candidate button').last()).toBeEnabled({ timeout: 15000 });
  await page.locator('.target-candidate button').last().click();
  await expect(page.locator('#target-status')).toHaveAttribute('data-status', 'ready', { timeout: 15000 });
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
});

test('late selection resolution cannot appear on another version', async ({ page }) => {
  await open(page);
  let release!: () => void;
  let started!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const pending = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/analysis', async route => {
    const response = await route.fetch(); started(); await gate;
    await route.fulfill({ response }).catch(() => {});
  });
  await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-text').fill('迟到定位测试');
  await page.locator('#save-feedback').click();
  await pending;
  await page.locator(`[data-version-id="${manifest().v1}"]`).click();
  await expect(page.locator('#version-badge')).toHaveText('V1');
  release();
  await expect(page.locator('#next')).toBeEnabled();
  await expect(page.locator('#target-panel')).toBeHidden();
  await expect(page.locator('#feedback-text')).toBeDisabled();
});

test('paragraph promotion is reviewed before saving; lost scope confirmation retries once', async ({ page, request }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  const original = await (await request.get(prefix(manifest().v2) + '/artifacts/docx', { headers })).body();
  await page.locator('#feedback-text').fill('这里居中');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#draft-review')).toContainText('所在整段，包含选区以外的文字');
  await page.screenshot({ path: '../../runtime/preview-step4-draft.png', fullPage: true });
  const saved = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click(); const receipt = await (await saved).json();
  await expect(page.locator('.confirm-scope')).toBeEnabled({ timeout: 15000 });
  const ids: string[] = []; let first = true;
  await page.route('**/analysis/confirm', async route => {
    ids.push(JSON.parse(route.request().postData()!).request_id);
    if (first) { first = false; await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await page.locator('.confirm-scope').click();
  await expect(page.locator('#analysis-status')).toContainText('原答案已保留', { timeout: 15000 });
  await page.locator('.confirm-scope').click();
  await expect(page.locator('#analysis-details')).toContainText('实际范围已确认', { timeout: 15000 });
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
  const analysis = await (await request.get(prefix(manifest().v2) + `/feedback/${receipt.feedback_id}/analysis`, { headers })).json();
  expect(analysis.decision_count).toBe(1);
  expect(await (await request.get(prefix(manifest().v2) + '/artifacts/docx', { headers })).body()).toEqual(original);
  expect((await (await request.get(`/api/tasks/${manifest().task}/versions`, { headers })).json()).versions).toHaveLength(3);
  await page.screenshot({ path: '../../runtime/preview-step4-scope.png', fullPage: true });
});

test('two missing format values can be completed sequentially without rewriting the feedback', async ({ page, request }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  const raw = '这里字体和字号需要调整'; await page.locator('#feedback-text').fill(raw);
  await expect(page.locator('#draft-review')).toContainText('值待补充', { timeout: 15000 });
  const saved = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click(); const receipt = await (await saved).json();
  await expect(page.locator('.clarify-form')).toHaveCount(2, { timeout: 15000 });
  await page.locator('.clarify-form').filter({ hasText: '字体名称' }).getByLabel('字体名称').fill('宋体');
  await page.locator('.clarify-form').filter({ hasText: '字体名称' }).getByRole('button', { name: '保存此项补充' }).click();
  await expect(page.locator('.clarify-form')).toHaveCount(1, { timeout: 15000 });
  await expect(page.locator('.clarify-form fieldset')).toBeEnabled();
  await page.locator('.clarify-form').getByLabel('字号（pt）').fill('12');
  await page.screenshot({ path: '../../runtime/preview-step4-clarification.png', fullPage: true });
  await page.locator('.clarify-form').getByRole('button', { name: '保存此项补充' }).click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#analysis-status')).toContainText('已保存 2 项');
  const record = await (await request.get(prefix(manifest().v2) + `/feedback/${receipt.feedback_id}`, { headers })).json();
  expect(record.submission.raw_text).toBe(raw);
  await page.reload(); await page.goto(`/#session=${token}&task=${manifest().task}`);
  await expect(page.locator('#next')).toBeEnabled(); await page.locator('#feedback-list button').first().click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#analysis-details')).toContainText('12 pt');
});

test('scope control must agree with prose; same-kind preview counts actual DOCX paragraphs', async ({ page }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-text').fill('全部正文加粗');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'clarification_needed', { timeout: 15000 });
  await expect(page.locator('#draft-review')).toContainText('统一上方范围控件与原话');
  await page.locator('#feedback-range').selectOption('same_kind');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#draft-review')).toContainText('实际影响 6 个段落');
  await page.locator('#save-feedback').click();
  await expect(page.locator('.confirm-scope')).toBeEnabled({ timeout: 15000 });
  await expect(page.locator('#analysis-details')).toContainText('实际影响 6 个段落');
});

test('paragraph font scope explicitly includes the whole paragraph', async ({ page }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-range').selectOption('paragraph'); await page.locator('#feedback-text').fill('宋体');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#draft-review')).toContainText('所选段落的全部文字');
  await page.locator('#save-feedback').click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#analysis-details')).toContainText('所选段落的全部文字');
  await expect(page.locator('.confirm-scope')).toHaveCount(0);
});

test('unknown restrictions cannot be bypassed by a value form; consultations create no candidates', async ({ page }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  await page.locator('#feedback-text').fill('宋体但不改英文');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'clarification_needed', { timeout: 15000 });
  await page.locator('#save-feedback').click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'clarification_needed', { timeout: 15000 });
  await expect(page.locator('#analysis-details')).toContainText('条件、排除项');
  await expect(page.locator('.clarify-form')).toHaveCount(0); await expect(page.locator('.confirm-scope')).toHaveCount(0);
  await page.locator('#feedback-text').fill('为什么是宋体？');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'question', { timeout: 15000 });
  await page.locator('#save-feedback').click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'question', { timeout: 15000 });
  await expect(page.locator('#analysis-details .format-facts')).toHaveCount(0);
  await page.setViewportSize({ width: 760, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(760);
  await page.screenshot({ path: '../../runtime/preview-step4-narrow.png', fullPage: true });
});

test('late or mismatched preflight cannot authorize saving another input', async ({ page }) => {
  await open(page); await selectText(page, 'Selectable preview text');
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; }); const pending = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/feedback/review', async route => {
    const response = await route.fetch(); const raw = JSON.parse(route.request().postData()!).raw_text;
    if (raw === '居中') { started(); await gate; await route.fulfill({ response }).catch(() => {}); }
    else if (raw === '斜体') { const data = await response.json(); data.source_submission_sha256 = '0'.repeat(64); await route.fulfill({ json: data }); }
    else await route.fulfill({ response });
  });
  await page.locator('#feedback-text').fill('居中'); await pending;
  await expect(page.locator('#save-feedback')).toBeDisabled();
  await page.locator('#feedback-text').fill('加粗');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  release(); await expect(page.locator('#draft-review')).toContainText('加粗');
  await expect(page.locator('#draft-review')).not.toContainText('段落对齐');
  await page.locator('#feedback-text').fill('斜体');
  await expect(page.locator('#draft-review')).toContainText('重试', { timeout: 15000 });
  await expect(page.locator('#save-feedback')).toBeDisabled(); await expect(page.locator('#feedback-text')).toHaveValue('斜体');
  await page.unroute('**/feedback/review'); await page.locator('#review-feedback').click();
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#save-feedback')).toBeEnabled();
  // A host/autofill integration may change the DOM without an input event.
  // Saving still has to review the exact changed content first.
  let saves = 0;
  page.on('request', request => { if (request.url().endsWith('/feedback') && request.method() === 'POST') saves++; });
  await page.locator('#feedback-text').evaluate((input: HTMLTextAreaElement) => { input.value = '宋体'; });
  await page.locator('#save-feedback').click();
  expect(saves).toBe(0);
  await expect(page.locator('#draft-review')).toContainText('宋体', { timeout: 15000 });
  const saved = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'POST');
  await page.locator('#save-feedback').click();
  expect(JSON.parse((await saved).request().postData()!).raw_text).toBe('宋体');
});

test('character condition is visible and global count excludes paragraphs without matching text', async ({ page }) => {
  test.skip(!process.env.AUTOFORMAT_TEST_SOFFICE, 'Real renderer is required for Chinese fixture text.');
  await open(page); await selectText(page, '材料学院毕业论文格式预览');
  await page.locator('#feedback-text').fill('中文宋体');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#draft-review')).toContainText('字符范围：中文字符');
  await expect(page.locator('#draft-review')).toContainText('实际影响 1 个文字范围');
  await page.locator('#feedback-range').selectOption('document');
  await page.locator('#feedback-text').fill('全文中文加粗');
  await expect(page.locator('#draft-review')).toHaveAttribute('data-kind', 'new_rule', { timeout: 15000 });
  await expect(page.locator('#draft-review')).toContainText('实际影响 3 个段落');
  await expect(page.locator('#draft-review')).toContainText('字符范围：中文字符');
  await page.screenshot({ path: '../../runtime/preview-step4-characters.png', fullPage: true });
});
