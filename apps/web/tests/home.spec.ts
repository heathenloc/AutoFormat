import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const token = 'preview-browser-test-session-token-1234567890';
const manifest = () => JSON.parse(readFileSync(resolve('../../runtime/browser-preview/manifest.json'), 'utf8'));
const headers = { 'X-AutoFormat-Session': token };

test('home restores tasks and returns from preview without persisting credentials', async ({ page }) => {
  await page.goto(`/#session=${token}`);
  await expect(page.getByRole('heading', { name: '新建论文任务' })).toBeVisible();
  await expect(page.locator('#application-mode')).toContainText('离线演示模式');
  await expect(page.locator(`[data-task-id="${manifest().task}"]`)).toBeVisible();
  expect(page.url()).not.toContain(token);
  await page.locator(`[data-task-id="${manifest().task}"]`).click();
  await expect(page.locator('#version-badge')).toHaveText('V2');
  await page.locator('#home').click();
  await expect(page.getByRole('heading', { name: '已有任务' })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.setViewportSize({ width: 760, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(760);
  await page.screenshot({ path: '../../runtime/desktop-home.png', fullPage: true });
});

test('two-file upload waits for explicit review, then publishes and restores the task', async ({ page, request }) => {
  test.setTimeout(120000);
  await page.goto(`/#session=${token}`);
  await expect(page.locator('#upload-fields')).toBeEnabled();
  await page.locator('#brief-file').setInputFiles({ name: 'school.txt', mimeType: 'text/plain', buffer: Buffer.from('正文：宋体。\n正文：黑体。') });
  await page.locator('#paper-file').setInputFiles(manifest().paper);
  await page.locator('#model-consent').check();
  await page.locator('#upload-task').click();
  await expect(page.getByRole('heading', { name: '编辑前确认' })).toBeVisible();
  const catalog = await (await request.get('/api/tasks', { headers })).json();
  const task = catalog.tasks[0]; expect(task.has_initial_version).toBe(false);
  await page.getByRole('button', { name: '暂时忽略此问题' }).click();
  await page.getByRole('button', { name: '开始格式编辑并生成初稿' }).click();
  await expect(page.locator('#version-badge')).toHaveText('V1', { timeout: 90000 });
  await expect(page.locator('#download-docx')).toBeEnabled();
  await page.locator('#home').click();
  await expect(page.locator(`[data-task-id="${task.task_id}"]`)).toContainText('2 个版本');
  await page.locator(`[data-task-id="${task.task_id}"]`).click();
  await expect(page.locator('#version-badge')).toHaveText('V1');
});

test('lost upload response keeps files and retries the same task request', async ({ page, request }) => {
  test.setTimeout(60000);
  await page.goto(`/#session=${token}`);
  await expect(page.locator('#upload-fields')).toBeEnabled();
  await page.locator('#brief-file').setInputFiles({ name: 'school.txt', mimeType: 'text/plain', buffer: Buffer.from('正文：宋体。\n正文：黑体。') });
  await page.locator('#paper-file').setInputFiles(manifest().paper); await page.locator('#model-consent').check();
  const ids: string[] = []; let first = true;
  await page.route('**/api/tasks', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    ids.push(route.request().postData()!.match(/name="request_id"\r\n\r\n([a-f0-9]{32})/)![1]);
    if (first) { first = false; await route.fetch(); await route.abort(); } else await route.continue();
  });
  const initial = (await (await request.get('/api/tasks', { headers })).json()).tasks.length;
  await page.locator('#upload-task').click();
  await expect(page.locator('#upload-status')).toContainText('文件选择已保留');
  await page.locator('#upload-task').click();
  await expect(page.getByRole('heading', { name: '编辑前确认' })).toBeVisible();
  expect(ids).toHaveLength(2); expect(ids[0]).toBe(ids[1]);
  expect((await (await request.get('/api/tasks', { headers })).json()).tasks).toHaveLength(initial + 1);
});
