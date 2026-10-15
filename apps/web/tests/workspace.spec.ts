import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';

const token = 'preview-browser-test-session-token-1234567890';
const headers = { 'X-AutoFormat-Session': token };
const fixture = (name: string) => JSON.parse(readFileSync(resolve('../../runtime/browser-preview/manifest.json'), 'utf8')).rules_tasks[name] as { task: string; version: string; child?: string };
async function open(page: Page, name: string) {
  const task = fixture(name);
  await page.goto(`/#session=${token}&task=${task.task}`);
  await expect(page.locator('#pdf')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('.textLayer')).toContainText('Selectable preview text');
  await expect(page.locator('#work-status')).toContainText('已核对');
  return task;
}
async function selectText(page: Page) {
  await page.locator('.textLayer span').filter({ hasText: 'Selectable preview text' }).first().evaluate(element => {
    const range = document.createRange(); range.selectNodeContents(element);
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
    element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
  });
  await expect(page.locator('#selection-text')).toContainText('Selectable preview text');
}

test('viewing history leaves the work origin unchanged until explicitly continued', async ({ page, request }) => {
  const task = await open(page, 'workspace_history');
  const base = `/api/tasks/${task.task}`;
  const before = await (await request.get(`${base}/versions/${task.child}/artifacts/docx`, { headers })).body();
  await page.locator(`[data-version-id="${task.version}"]`).click();
  await expect(page.locator('#continue-version')).toBeEnabled();
  await expect(page.locator('#feedback-text')).toBeDisabled();
  expect((await (await request.get(`${base}/versions`, { headers })).json()).working_version_id).toBe(task.child);
  await page.locator('#continue-version').click();
  await expect(page.locator('#continue-version')).toBeHidden();
  await expect(page.locator('#feedback-text')).toBeEnabled();
  const list = await (await request.get(`${base}/versions`, { headers })).json();
  expect(list.working_version_id).toBe(task.version); expect(list.versions).toHaveLength(3);
  expect(await (await request.get(`${base}/versions/${task.child}/artifacts/docx`, { headers })).body()).toEqual(before);
  await page.getByRole('button', { name: /^V0 ·/ }).click();
  await expect(page.locator('#continue-version')).toBeHidden();
});

test('lost continuation response retries the same receipt and locks writes during switching', async ({ page, request }) => {
  const task = await open(page, 'workspace_retry');
  await page.locator(`[data-version-id="${task.version}"]`).click();
  await expect(page.locator('#continue-version')).toBeEnabled();
  const ids: string[] = []; let first = true;
  await page.route('**/continue', async route => {
    ids.push(JSON.parse(route.request().postData()!).request_id);
    if (first) {
      first = false; await route.fetch();
      await expect(page.locator('.version-item').first()).toBeDisabled();
      await expect(page.locator('#feedback-text')).toBeDisabled();
      await route.abort('failed');
    } else await route.continue();
  });
  await page.locator('#continue-version').click();
  await expect(page.locator('#continue-status')).toContainText('可重试同一操作');
  await page.locator('#continue-version').click();
  await expect(page.locator('#feedback-text')).toBeEnabled();
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
  expect((await (await request.get(`/api/tasks/${task.task}/versions`, { headers })).json()).versions).toHaveLength(3);
});

test('unfinished feedback restores its original selection and clarification form after reopening', async ({ page }) => {
  test.setTimeout(60000);
  const task = await open(page, 'workspace_queue');
  await selectText(page); await page.locator('#feedback-text').fill('修改字号'); await page.locator('#save-feedback').click();
  await expect(page.locator('#feedback-list [data-work-status="needs_value"]')).toHaveCount(1, { timeout: 30000 });
  await page.goto(`/#session=${token}&task=${task.task}`);
  await expect(page.locator('#feedback-list [data-work-status="needs_value"]')).toContainText('修改字号', { timeout: 30000 });
  await page.locator('#work-filter').selectOption('done'); await expect(page.locator('#feedback-list li')).toHaveCount(0);
  await page.locator('#work-filter').selectOption('pending');
  await page.getByRole('button', { name: '查看需求与位置' }).click();
  await expect(page.locator('.clarify-form')).toBeVisible();
  await expect(page.locator('#target-status')).toContainText('唯一');
  await page.locator('.clarify-form input[type="number"]').fill('16');
  await page.getByRole('button', { name: '保存此项补充' }).click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'new_rule');
  await expect(page.locator('#work-status')).toContainText('已核对');
  await page.locator('#work-filter').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '../../runtime/preview-step7-workspace.png', fullPage: true });
});

test('pending report exposes the original evidence and next action without applying a default', async ({ page }) => {
  await open(page, 'workspace_report');
  await page.getByText('报告待处理项 · 1', { exact: true }).click();
  await expect(page.locator('#report-pending')).toContainText('字号数值尚未明确');
  await expect(page.locator('#report-pending')).toContainText('请核对学校要求的具体字号');
  await page.getByText('查看原文依据', { exact: true }).click();
  await expect(page.locator('#report-pending blockquote')).toHaveText('正文使用较大字号（测试待确认原文）');
  await expect(page.locator('#change-count')).toHaveText('0');
});

test('continuing before a published exception creates a clean sibling version', async ({ page, request }) => {
  test.skip(process.env.AUTOFORMAT_TEST_FEEDBACK_EDITING !== '1', 'Requires the real feedback editor fixture');
  test.setTimeout(180000);
  const task = await open(page, 'workspace_branch');
  await selectText(page); await page.locator('#feedback-text').fill('字号14pt'); await page.locator('#save-feedback').click();
  await page.getByRole('button', { name: '设为本处例外' }).click();
  await expect(page.locator('#version-badge')).toHaveText('V2', { timeout: 90000 });
  const base = `/api/tasks/${task.task}`;
  const firstList = await (await request.get(`${base}/versions`, { headers })).json();
  const v2 = firstList.working_version_id;
  const artifacts = await Promise.all(['docx', 'report_json', 'preview'].map(async kind => (await request.get(`${base}/versions/${v2}/artifacts/${kind}`, { headers })).body()));
  await page.locator(`[data-version-id="${task.version}"]`).click();
  await expect(page.locator('#continue-version')).toBeEnabled(); await page.locator('#continue-version').click();
  await expect(page.locator('#feedback-list [data-work-status="completed"]')).toHaveCount(1, { timeout: 30000 });
  await page.getByRole('button', { name: '查看需求与位置' }).click();
  await expect(page.locator('#analysis-details')).toHaveAttribute('data-kind', 'new_rule');
  // Viewing an old completed item must not put its rule into the fresh branch.
  await expect(page.locator('#rules-details')).toBeEmpty();
  await page.locator('#feedback-text').fill('全文加粗'); await page.locator('#save-feedback').click();
  await expect(page.locator('.confirm-scope')).toBeVisible(); await page.locator('.confirm-scope').click();
  await expect(page.locator('#version-badge')).toHaveText('V3', { timeout: 90000 });
  const list = await (await request.get(`${base}/versions`, { headers })).json();
  expect(list.versions.find((v: { version_id: string }) => v.version_id === list.working_version_id).parent_version_id).toBe(task.version);
  const bytes = await (await request.get(`${base}/versions/${list.working_version_id}/artifacts/docx`, { headers })).body();
  const python = process.env.AUTOFORMAT_TEST_PYTHON ?? resolve('../../.venv/Scripts/python.exe');
  const formats = JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', 'import sys,io,json; from docx import Document; p=Document(io.BytesIO(sys.stdin.buffer.read())).paragraphs[0]; print(json.dumps(dict(text=p.text, runs=[dict(size=r.font.size.pt if r.font.size else 12, bold=r.bold) for r in p.runs])))'], { input: bytes }).toString());
  expect(formats.text).toBe('Selectable preview text');
  expect(formats.runs.every((run: { size: number; bold: boolean }) => run.size === 12 && run.bold)).toBeTruthy();
  for (const [i, kind] of ['docx', 'report_json', 'preview'].entries()) expect(await (await request.get(`${base}/versions/${v2}/artifacts/${kind}`, { headers })).body()).toEqual(artifacts[i]);
});
