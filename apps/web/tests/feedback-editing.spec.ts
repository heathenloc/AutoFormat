import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';

test.skip(process.env.AUTOFORMAT_TEST_FEEDBACK_EDITING !== '1', 'Requires the real feedback editor fixture');
const token = 'preview-browser-test-session-token-1234567890';
const headers = { 'X-AutoFormat-Session': token };
function fixture(name: string) {
  return JSON.parse(readFileSync(resolve('../../runtime/browser-preview/manifest.json'), 'utf8')).rules_tasks[name] as { task: string; version: string };
}
async function open(page: Page, name: string) {
  const task = fixture(name);
  await page.goto(`/#session=${token}&task=${task.task}`);
  await expect(page.locator('#version-badge')).toHaveText('V1');
  await expect(page.locator('#pdf')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('.textLayer')).toContainText('Selectable preview text');
  return task;
}
async function selectFirstWord(page: Page) {
  const span = page.locator('.textLayer span').filter({ hasText: 'Selectable preview text' }).first();
  await span.evaluate(element => {
    const range = document.createRange(); range.setStart(element.firstChild!, 0); range.setEnd(element.firstChild!, 10);
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
    element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
  });
  await expect(page.locator('#selection-text')).toHaveText('Selectable');
}
function characterFormats(docx: Buffer): { char: string; size: number | null; bold: boolean | null }[] {
  const python = process.env.AUTOFORMAT_TEST_PYTHON ?? resolve('../../.venv/Scripts/python.exe');
  const script = `import sys,io,json
from docx import Document
p=Document(io.BytesIO(sys.stdin.buffer.read())).paragraphs[0]
def size(run):
    if run.font.size is not None: return run.font.size.pt
    for origin in (run.style,p.style):
        style=origin
        while style is not None:
            if style.font.size is not None: return style.font.size.pt
            style=style.base_style
    return None
print(json.dumps([dict(char=c,size=size(r),bold=r.bold) for r in p.runs for c in r.text]))`;
  return JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', script], { input: docx, encoding: 'utf8' }));
}

test('feedback editing automatically publishes a bounded edit and loads the new preview', async ({ page, request }) => {
  test.setTimeout(120000);
  const task = await open(page, 'execution_auto');
  const base = `/api/tasks/${task.task}`;
  const before = await (await request.get(`${base}/versions/${task.version}/artifacts/docx`, { headers })).body();
  await selectFirstWord(page); await page.locator('#feedback-text').fill('字号14pt');
  await page.locator('#save-feedback').click();
  await expect(page.locator('#version-badge')).toHaveText('V2', { timeout: 90000 });
  await expect(page.locator('.textLayer')).toContainText('Selectable', { timeout: 15000 });
  await expect(page.locator('#selection-empty')).toBeVisible();
  await expect(page.locator('#download-docx')).toBeEnabled();
  const list = await (await request.get(`${base}/versions`, { headers })).json();
  expect(list.versions).toHaveLength(3);
  const docx = await (await request.get(`${base}/versions/${list.working_version_id}/artifacts/docx`, { headers })).body();
  const chars = characterFormats(docx);
  expect(chars.map(c => c.char).join('')).toBe('Selectable preview text');
  expect(chars.slice(0, 10).every(c => c.size === 14)).toBeTruthy();
  expect(chars.slice(10).every(c => c.size !== 14)).toBeTruthy();
  expect(await (await request.get(`${base}/versions/${task.version}/artifacts/docx`, { headers })).body()).toEqual(before);
  const report = await (await request.get(`${base}/versions/${list.working_version_id}/artifacts/report_json`, { headers })).json();
  expect(report.changes_this_round.length).toBeGreaterThan(0);
  expect(report.rules.at(-1).after_value.span).toMatchObject({ start_utf16: 0, length_utf16: 10 });
  await page.screenshot({ path: '../../runtime/preview-step6-edited.png', fullPage: true });
});

test('feedback editing waits for a local exception and retains it in the next round', async ({ page, request }) => {
  test.setTimeout(180000);
  const task = await open(page, 'execution_exception');
  await selectFirstWord(page); await page.locator('#feedback-text').fill('字号14pt'); await page.locator('#save-feedback').click();
  await expect(page.locator('.rule-conflict')).toHaveCount(1, { timeout: 30000 });
  await expect(page.locator('#version-badge')).toHaveText('V1');
  await page.getByRole('button', { name: '设为本处例外' }).click();
  await expect(page.locator('#version-badge')).toHaveText('V2', { timeout: 90000 });
  await expect(page.locator('#feedback-text')).toBeEnabled({ timeout: 15000 });
  await page.locator('#feedback-text').fill('全文加粗'); await page.locator('#save-feedback').click();
  await expect(page.locator('.confirm-scope')).toBeVisible({ timeout: 30000 });
  await page.locator('.confirm-scope').click();
  await expect(page.locator('#version-badge')).toHaveText('V3', { timeout: 90000 });
  const base = `/api/tasks/${task.task}`;
  const list = await (await request.get(`${base}/versions`, { headers })).json();
  const chars = characterFormats(await (await request.get(`${base}/versions/${list.working_version_id}/artifacts/docx`, { headers })).body());
  expect(chars.every(c => c.bold === true)).toBeTruthy();
  expect(chars.slice(0, 10).every(c => c.size === 14)).toBeTruthy();
  expect(chars.slice(10).every(c => c.size === 12)).toBeTruthy();
});

test('feedback editing recovers a lost publish response without creating another version', async ({ page, request }) => {
  test.setTimeout(120000);
  const task = await open(page, 'execution_retry');
  let posted: Record<string, unknown> | undefined;
  await page.route('**/feedback-executions', async route => {
    posted = JSON.parse(route.request().postData()!);
    await route.fetch({ timeout: 90000 }); await route.abort('failed');
  });
  await selectFirstWord(page); await page.locator('#feedback-text').fill('字号15pt'); await page.locator('#save-feedback').click();
  await expect(page.locator('#version-badge')).toHaveText('V2', { timeout: 90000 });
  expect(posted).toBeDefined();
  const retried = await request.post(`/api/tasks/${task.task}/versions/${task.version}/feedback-executions`, { headers, data: posted });
  expect(retried.ok()).toBeTruthy(); expect((await retried.json()).phase).toBe('ready');
  expect((await (await request.get(`/api/tasks/${task.task}/versions`, { headers })).json()).versions).toHaveLength(3);
});

test('feedback editing confirms paragraph promotion before publishing alignment', async ({ page }) => {
  test.setTimeout(120000);
  await open(page, 'execution_paragraph');
  await selectFirstWord(page); await page.locator('#feedback-text').fill('这一段居中'); await page.locator('#save-feedback').click();
  await expect(page.locator('.confirm-scope')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('#version-badge')).toHaveText('V1');
  await page.locator('.confirm-scope').click();
  await expect(page.locator('#version-badge')).toHaveText('V2', { timeout: 90000 });
  await expect(page.locator('#change-count')).toHaveText('1');
});
