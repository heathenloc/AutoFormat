import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

const token = 'preview-browser-test-session-token-1234567890';
const headers = { 'X-AutoFormat-Session': token, Origin: 'http://127.0.0.1:58371' };

for (const loseResponse of [false, true]) test(`review before editing, explicit skip and initial publication${loseResponse ? ', lost answer response' : ''}`, async ({ page, request }) => {
  const manifest = JSON.parse(readFileSync(resolve('../../runtime/browser-preview/manifest.json'), 'utf8'));
  const created = await request.post('/api/tasks', { headers, multipart: {
    request_id: randomUUID().replaceAll('-', ''), model_processing_acknowledged: 'true',
    brief: { name: 'school.txt', mimeType: 'text/plain', buffer: Buffer.from('正文：宋体。\n正文：黑体。') },
    paper: { name: 'paper.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: readFileSync(manifest.paper) },
  } });
  expect(created.ok()).toBeTruthy(); const task = await created.json();
  expect(task.phase).toBe('reviewing_requirements'); expect(task.initial_version_id).toBeNull();
  const versions = async () => (await (await request.get(`/api/tasks/${task.task_id}/versions`, { headers })).json()).versions;
  expect(await versions()).toHaveLength(1);
  await page.goto(`/#session=${token}&task=${task.task_id}`);
  await expect(page.getByRole('heading', { name: '编辑前确认' })).toBeVisible();
  await expect(page.getByRole('button', { name: /采用：/ })).toHaveCount(2);
  await expect(page.getByRole('button', { name: '开始格式编辑并生成初稿' })).toHaveCount(0);
  if (!loseResponse) await page.screenshot({ path: '../../runtime/initial-review-question.png', fullPage: true });
  if (loseResponse) {
    await page.route(`**/api/tasks/${task.task_id}/decisions`, async route => {
      await route.fetch(); await route.abort(); await page.unroute(`**/api/tasks/${task.task_id}/decisions`);
    });
    await page.getByRole('button', { name: '暂时忽略此问题' }).click();
    await expect(page.locator('[data-review-status]')).toContainText('原选择已保留');
  }
  await page.getByRole('button', { name: '暂时忽略此问题' }).click();
  await expect(page.getByRole('button', { name: '开始格式编辑并生成初稿' })).toBeVisible();
  expect(await versions()).toHaveLength(1);
  const snapshot = await (await request.get(`/api/tasks/${task.task_id}/resolved-rules`, { headers })).json();
  expect(snapshot.revision).toBe(1); expect(snapshot.initial_version_id).toBe(task.base_version_id);
  await page.getByRole('button', { name: '开始格式编辑并生成初稿' }).click();
  await expect(page.locator('#version-badge')).toHaveText('V1');
  await expect(page.locator('#initial-review')).toBeHidden();
  await expect(page.locator('.textLayer')).toContainText('Selectable preview text');
  expect(await versions()).toHaveLength(2);
  await page.screenshot({ path: `../../runtime/initial-review-${loseResponse ? 'retry' : 'complete'}.png`, fullPage: true });
});
