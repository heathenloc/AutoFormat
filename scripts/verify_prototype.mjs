/**
 * Local UI acceptance + deterministic Modao import-board generation.
 * Start a static server for site/, then run:
 *   node scripts/verify_prototype.mjs http://127.0.0.1:4186
 * Uses the repository's existing apps/web Playwright dependency.
 * Test screenshots/downloads go only to ignored runtime/prototype-qa/.
 */
import { chromium, expect } from '../apps/web/node_modules/@playwright/test/index.mjs';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = fileURLToPath(new URL('../', import.meta.url));
const target = path.join(root, 'site/prototype');
const output = path.join(root, 'runtime/prototype-qa');
await mkdir(output, { recursive: true });
await mkdir(path.join(target, 'pages'), { recursive: true });
const base = (process.argv[2] || 'http://127.0.0.1:4186').replace(/\/$/, '');
const url = base + '/prototype/index.html';
const key = 'autoformat-prototype-v1';
const source = await readFile(path.join(target, 'index.html'), 'utf8');
const inline = source.match(/<script>([\s\S]*?)<\/script>/)[1];
new Function(inline);
assert(!/<script[^>]+src=|<link[^>]+stylesheet|url\(\s*["']?https?:/i.test(source), 'Prototype must be self-contained');

const browser = await chromium.launch({ headless: true });
const contexts = [];
const browserErrors = [];
const checks = [];
const boards = [];
const record = name => { checks.push(name); console.log('PASS ' + name); };
async function freshPage(options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', ...options });
  contexts.push(context);
  const page = await context.newPage();
  page.on('pageerror', e => browserErrors.push(e.message));
  page.on('console', e => { if (e.type() === 'error') browserErrors.push(e.text()); });
  await page.goto(url);
  await expect(page.getByRole('heading', { name: '上传格式要求和原文' })).toBeVisible();
  return page;
}
const stored = page => page.evaluate(k => JSON.parse(localStorage.getItem(k)), key);
async function waitVersion(page, id) {
  await expect(page.locator('#version-select')).toHaveValue(String(id), { timeout: 12000 });
  await expect(page.locator('.notice.good')).toContainText('V' + id);
}
async function navigate(page, route) {
  const trigger = page.locator('#workspace-trigger');
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click();
  await page.locator('.nav [data-route=' + route + ']').click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
}
async function startSample(page, scenario) {
  await page.locator('[data-action=sample]').click();
  // Seed alternate states only for regression and import-board capture.
  // The visitor-facing scenario selector has been removed.
  if (scenario) {
    await page.evaluate(([key, scenario]) => {
      const state = JSON.parse(localStorage.getItem(key));
      state.scenario = scenario;
      localStorage.setItem(key, JSON.stringify(state));
    }, [key, scenario]);
    await page.reload();
  }
  await page.locator('[data-action=parse]').click();
}
async function reviewAnswers(page, alignment = 'center', pageChoice = 'template') {
  await page.locator('input[name=alignment][value=' + alignment + ']').check();
  await page.locator('input[name=page][value=' + pageChoice + ']').check();
}
async function snapshot(page, number, name, screenshot = true) {
  await page.mouse.move(0, 0);
  await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('#toast').hidden = true; });
  const result = await page.evaluate(() => {
    const app = document.querySelector('#app').cloneNode(true);
    app.querySelectorAll('[tabindex="-1"]').forEach(e => e.removeAttribute('tabindex'));
    // Native input state is reflected into static HTML for non-JavaScript importers.
    const inputs = [...document.querySelectorAll('#app input')];
    [...app.querySelectorAll('input')].forEach((e, i) => {
      e.toggleAttribute('checked', inputs[i].checked);
      if (inputs[i].type !== 'file') e.setAttribute('value', inputs[i].value);
    });
    [...app.querySelectorAll('textarea')].forEach((e, i) => { e.textContent = document.querySelectorAll('#app textarea')[i].value; });
    [...app.querySelectorAll('select')].forEach((e, i) => {
      const selected = document.querySelectorAll('#app select')[i].value;
      [...e.options].forEach(o => o.toggleAttribute('selected', o.value === selected));
    });
    const dialog = document.querySelector('dialog[open]');
    return { css: document.querySelector('style').textContent, app: app.innerHTML,
      overlay: dialog ? '<div class="import-overlay"><section class="modal import-modal" role="dialog">' + dialog.innerHTML + '</section></div>' : '' };
  });
  const file = String(number).padStart(2, '0') + '-' + name + '.html';
  boards.push({ number, name, file, ...result });
  if (screenshot) await page.screenshot({ path: path.join(output, file.replace('.html', '.png')), fullPage: true });
}
async function selectAndAnalyze(page, anchor, text, scope = 'selection') {
  await page.locator('[data-anchor=' + anchor + ']').click();
  await page.locator('#feedback-text').fill(text);
  await page.locator('#feedback-scope').selectOption(scope);
  await page.locator('[data-action=analyze]').click();
}
async function apply(page) {
  const approval = page.locator('#scope-approval');
  if (await approval.count()) await approval.check();
  await page.locator('[data-action=apply-plan]').click();
}

try {
  const page = await freshPage();
  const network = [];
  page.on('request', r => { if (r.url().startsWith('http') && !r.url().startsWith(base)) network.push(r.url()); });
  await expect(page.locator('.sidebar,.feature-strip,.sample-strip,.scenario')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '自动填充文件', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '使用示例文件', exact: true })).toHaveCount(0);
  await expect(page.getByText('A LITTLE LESS FORMATTING.', { exact: true })).toHaveCount(0);
  await expect(page.getByText('上传格式要求与论文原稿。先确认疑问，再生成一份可继续编辑的论文副本。', { exact: true })).toHaveCount(0);
  assert.equal(await page.locator('html').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
  assert.equal(await page.locator('.card').first().evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
  assert.equal(await page.locator('.topbar').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(20, 34, 56)');
  await expect(page.locator('.page-heading .chip,.footer-note')).toHaveCount(0);
  await expect(page.locator('.upload-card h2').first()).toHaveText('格式要求');
  assert.deepEqual(await page.locator('.top-actions').evaluate(el => [...el.children].map(e => e.dataset.action || 'return')), ['help', 'return', 'visitor']);

  const trigger = page.locator('#workspace-trigger');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('#workspace-menu')).toBeHidden();
  await expect(page.locator('.workspace-menu [data-action=reset]')).toHaveCount(1);
  await expect(page.locator('[data-action=reset]')).toHaveCount(1);
  await trigger.click();
  await expect(page.locator('.nav a')).toHaveCount(5);
  await expect(page.locator('.nav [data-route=upload]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('.nav [data-route=upload]')).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.locator('.nav [data-action=reset]')).toBeFocused();
  await page.locator('.page-heading h1').click();
  await expect(page.locator('#workspace-menu')).toBeHidden();
  await page.locator('[data-action=visitor]').click();
  await expect(page.getByRole('heading', { name: '访客模式' })).toBeVisible();
  await page.locator('dialog [data-action=close-dialog]').first().click();
  await page.locator('[data-action=help]').click();
  await expect(page.getByRole('heading', { name: '欢迎体验 AutoFormat' })).toBeVisible();
  await page.locator('dialog [data-action=close-dialog]').first().click();
  await trigger.click();
  await page.locator('.nav [data-action=reset]').click();
  await expect(page.getByRole('heading', { name: '清除演示进度并重新开始？' })).toBeVisible();
  await page.locator('dialog [data-action=close-dialog]').first().click();
  record('Simplified upload page, auto-fill button, white theme, unchanged navy navigation and accessible dropdown');
  await snapshot(page, 1, 'upload');
  await trigger.click();
  await snapshot(page, 9, 'navigation');
  await page.keyboard.press('Escape');
  for (const width of [882, 390, 320]) {
    await page.setViewportSize({ width, height: 956 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Upload overflow at ' + width);
    const order = await page.locator('.top-actions').evaluate(el => [...el.children].map(e => e.getBoundingClientRect().x));
    assert(order[0] < order[1] && order[1] < order[2], 'Help/return/avatar visual order at ' + width);
    await page.screenshot({ path: path.join(output, 'upload-' + width + '.png'), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.locator('[data-action=parse]')).toBeDisabled();
  await page.locator('#file-paper').setInputFiles({ name: 'wrong.pdf', mimeType: 'application/pdf', buffer: Buffer.from('sample') });
  await expect(page.locator('#error-paper')).toContainText('仅支持 DOCX');
  await expect(page.locator('[data-action=parse]')).toBeDisabled();
  await page.locator('#file-brief').setInputFiles({ name: 'sample-<img onerror=alert(1)>.docx', mimeType: 'application/octet-stream', buffer: Buffer.from('metadata only') });
  await expect(page.locator('label[for=file-brief] strong')).toHaveText('sample-<img onerror=alert(1)>.docx');
  assert.equal(await page.locator('label[for=file-brief] img').count(), 0);
  record('File type validation, escaped names, empty-state blocking');

  await page.locator('[data-action=sample]').click();
  await page.locator('[data-action=parse]').click();
  await expect(page.locator('.progress-track[role=progressbar]')).toBeVisible();
  await snapshot(page, 2, 'parsing', false);
  await expect(page.locator('[data-question=alignment]')).toBeVisible({ timeout: 12000 });
  await snapshot(page, 3, 'review');
  await page.setViewportSize({ width: 882, height: 956 });
  await page.screenshot({ path: path.join(output, 'review-882.png'), fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Review overflow at 882');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.locator('input[name=alignment]:checked')).toHaveCount(0);
  await expect(page.locator('input[name=page]').first()).toBeDisabled();
  await expect(page.locator('[data-action=generate]')).toBeDisabled();
  await expect(page.locator('.page-heading h1')).toHaveText('选择需要执行的修改');
  await expect(page.locator('.page-heading p,.page-heading .chip')).toHaveCount(0);
  await expect(page.locator('[data-action=generate]')).toContainText('开始修改');
  await expect(page.locator('[data-question=page]>.evidence')).toHaveText('A4 · 纵向 · 四边页边距 2.5 cm');
  await expect(page.locator('[data-question=page]>.evidence small,[data-question=page]>.evidence .small')).toHaveCount(0);
  await expect(page.locator('[data-action=save-decision],[data-action=defer-decision],[data-action=revise-decision]')).toHaveCount(0);
  await expect(page.getByText('请选择处理方式，不预设任何答案', { exact: true })).toHaveCount(0);
  await expect(page.locator('[data-question=alignment]>p')).toHaveText('要求出现冲突，选择一项进行修改');
  await expect(page.locator('[data-question=page]>p')).toHaveText('示例自带的模板或页面设置（观察值），不代表明文要求');
  await expect(page.locator('.summary-card .note-box,.summary-card>.small,.review-footer>span')).toHaveCount(0);
  await expect(page.locator('.review-footer>button')).toHaveText('查看全部修改项');
  await page.locator('[data-action=view-rules]').click();
  await expect(page.getByRole('heading', { name: '全部修改项', exact: true })).toBeVisible();
  await expect(page.locator('[data-review-item]')).toHaveCount(16);
  await expect(page.locator('[data-review-item][data-status=pending]')).toHaveCount(2);
  await expect(page.locator('[data-review-item][data-status=applied]')).toHaveCount(0);
  await page.locator('dialog [data-action=close-dialog]').first().click();
  await page.locator('input[name=alignment][value=center]').check();
  await expect(page.locator('input[name=alignment][value=center]')).toBeChecked();
  await expect(page.locator('input[name=alignment][value=center]')).toBeFocused();
  assert.equal((await stored(page)).decisions.alignment.value, 'center');
  await expect(page.locator('input[name=page][value=template]')).toBeEnabled();
  await expect(page.locator('[data-action=generate]')).toBeDisabled();
  await page.locator('input[name=alignment][value=center]').press('ArrowRight');
  await expect(page.locator('input[name=alignment][value=left]')).toBeChecked();
  assert.equal((await stored(page)).decisions.alignment.value, 'left');
  await page.locator('input[name=page][value=template]').check();
  await expect(page.locator('[data-action=generate]')).toBeEnabled();
  await page.locator('input[name=page][value=keep]').check();
  assert.equal((await stored(page)).decisions.page.value, 'keep');
  await page.locator('[data-action=skip-decision][data-key=alignment]').click();
  await expect(page.locator('input[name=alignment]:checked')).toHaveCount(0);
  await page.locator('[data-action=skip-decision][data-key=page]').click();
  await expect(page.locator('input[name=page]:checked')).toHaveCount(0);
  await expect(page.locator('[data-action=generate]')).toBeEnabled();
  assert.equal((await stored(page)).versions.length, 1);
  await page.locator('[data-action=view-rules]').click();
  await expect(page.locator('[data-review-item][data-status=ignored]')).toHaveCount(2);
  await page.locator('dialog [data-action=close-dialog]').first().click();
  await reviewAnswers(page);
  await page.locator('input[name=alignment][value=left]').check();
  await expect(page.locator('input[name=page][value=template]')).toBeChecked();
  await expect(page.locator('[data-action=generate]')).toBeEnabled();
  await page.reload();
  await expect(page.locator('input[name=alignment][value=left]')).toBeChecked();
  await expect(page.locator('input[name=page][value=template]')).toBeChecked();
  await page.locator('input[name=alignment][value=center]').check();
  const original = JSON.stringify((await stored(page)).versions[0]);
  await page.locator('[data-action=generate]').click();
  await waitVersion(page, 1);
  await snapshot(page, 4, 'workspace');
  await expect(page.locator('.workspace-heading h1')).toHaveText('预览修改结果');
  await expect(page.locator('.workspace-heading .eyebrow')).toHaveCount(0);
  await expect(page.locator('.feedback-panel .panel-title')).toHaveText('选择局部修改的内容');
  await expect(page.locator('.feedback-panel>p.small')).toHaveCount(1);
  await expect(page.locator('.feedback-panel>p.small')).toHaveText('对齐等段落属性会先显示实际作用范围。');
  await expect(page.locator('.report-short h3')).toHaveText('此版本修改记录');
  await page.setViewportSize({ width: 898, height: 956 });
  await page.screenshot({ path: path.join(output, 'workspace-898.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });

  assert.equal(JSON.stringify((await stored(page)).versions[0]), original);
  record('Immediate radio decisions and direct reselection; keyboard focus and persistence; explicit skips; all modification items; V0 immutable');

  await selectAndAnalyze(page, 'h1', '这里改成左对齐');
  await expect(page.locator('[data-action=apply-plan]')).toBeDisabled();
  await apply(page);
  await expect(page.locator('dialog')).toBeVisible();
  await snapshot(page, 5, 'conflict');
  await expect(page.locator('input[name=policy]:checked')).toHaveCount(0);
  await page.locator('[data-action=resolve-conflict]').click();
  assert.equal((await stored(page)).versions.length, 2);
  await page.locator('dialog [data-action=close-dialog]').first().click();
  assert.equal((await stored(page)).versions.length, 2);
  await page.locator('[data-action=apply-plan]').click();
  await page.locator('input[name=policy][value=exception]').check();
  await page.locator('[data-action=resolve-conflict]').click();
  await waitVersion(page, 2);
  let current = await stored(page);
  assert.equal(current.versions[1].styles.h1.align, 'center');
  assert.equal(current.versions[2].styles.h1.align, 'left');
  assert.equal(current.versions[2].events.at(-1).policy, 'exception');
  record('Actual paragraph scope confirmed; no default conflict policy; cancel safe; local exception creates V2');

  await navigate(page, 'history');
  await snapshot(page, 6, 'history');
  await expect(page.locator('.page-heading h1')).toHaveText('查看历史版本');
  await expect(page.locator('.page-heading p')).toHaveCount(0);
  const originalCard = page.locator('.version-card').filter({ has: page.locator('[data-action=view-version][data-id="0"]') });
  const initialCard = page.locator('.version-card').filter({ has: page.locator('[data-action=view-version][data-id="1"]') });
  await expect(originalCard.locator('h2')).toHaveText('论文原稿（不可编辑）');
  await expect(originalCard.locator('p')).toHaveCount(0);
  await expect(initialCard.locator('p')).toHaveCount(0);
  assert.equal(JSON.stringify((await stored(page)).versions[0]), original);
  await page.setViewportSize({ width: 898, height: 956 });
  await page.screenshot({ path: path.join(output, 'history-898.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.locator('[data-action=continue][data-id="1"]').click();
  await page.locator('[data-action=continue-confirmed]').click();
  await selectAndAnalyze(page, 'p1', '选中文字加粗');
  await apply(page);
  await waitVersion(page, 3);
  current = await stored(page);
  assert.equal(current.versions[3].parent, 1);
  assert.equal(current.versions[3].styles.h1.align, 'center');
  assert.equal(current.versions[2].styles.h1.align, 'left');
  assert.equal(JSON.stringify(current.versions[0]), original);
  assert.equal(current.versions[3].events.length, 1);
  await page.reload();
  await waitVersion(page, 3);
  record('Historical branch parent correct; later exceptions not inherited; descendants preserved; reload restores progress');

  await navigate(page, 'review');
  await expect(page.getByRole('heading', { name: '确认格式要求' })).toBeVisible();
  await expect(page.locator('input[name=alignment]').first()).toBeDisabled();
  await expect(page.locator('input[name=page]').first()).toBeDisabled();
  await expect(page.locator('[data-action=skip-decision]')).toHaveCount(0);
  await expect(page.locator('[data-action=generate]')).toHaveCount(0);
  await navigate(page, 'workspace');
  await selectAndAnalyze(page, 'p1', '删除研究结论并改为左对齐');
  await expect(page.locator('#feedback-result')).toContainText('尚未执行');
  assert.equal((await stored(page)).versions.length, 4);
  await selectAndAnalyze(page, 'h1', '这里改成居中');
  await expect(page.locator('#feedback-result')).toContainText('无需创建重复版本');
  await selectAndAnalyze(page, 'h2a', '所有二级标题改为16磅');
  await expect(page.locator('#feedback-result')).toContainText('范围');
  await selectAndAnalyze(page, 'p1', '字号改为0磅');
  await expect(page.locator('#feedback-result')).toContainText('5–72');
  record('Published decisions read-only; ambiguous/content edits rejected; no-op does not create version; scope/size validation');

  // Cancellation during a feedback edit must return to the workspace and never publish late.
  await selectAndAnalyze(page, 'p2', '选中文字加粗');
  await apply(page);
  await page.locator('[data-action=cancel-process]').click();
  await waitVersion(page, 3);
  await page.waitForTimeout(2400);
  assert.equal((await stored(page)).versions.length, 4);
  record('Cancel feedback processing restores parent workspace; no late version publication');

  await navigate(page, 'upload');
  await page.locator('#file-paper').setInputFiles({ name: 'another-candidate.docx', mimeType: 'application/octet-stream', buffer: Buffer.from('metadata only') });
  await navigate(page, 'workspace');
  await expect(page.locator('.workspace-heading')).toContainText('学术文档格式处理研究（示例）.docx');
  assert.equal((await stored(page)).versions[3].inputFiles.paper.name, '学术文档格式处理研究（示例）.docx');
  record('Historical input names remain immutable when a candidate new task file changes');

  for (const id of [1, 2, 3]) {
    await page.locator('#version-select').selectOption(String(id));
    await page.locator('[data-action=downloads]').click();
    const [file] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action=download-docx]').click()]);
    assert.equal(file.suggestedFilename(), 'AutoFormat-demo-V' + id + '.docx');
    await file.saveAs(path.join(output, file.suggestedFilename()));
    await page.locator('dialog [data-action=close-dialog]').first().click();
  }
  await navigate(page, 'report');
  await snapshot(page, 7, 'report');
  await expect(page.locator('.page-heading h1')).toHaveText('本次修改项');
  await expect(page.locator('.page-heading p')).toHaveCount(0);
  const reportReturn = page.locator('.report-actions [data-route=workspace]');
  await expect(reportReturn).toHaveText('返回预览');
  assert(await page.locator('.report-actions [data-action=download-report]').evaluate(el => el.nextElementSibling?.dataset.route === 'workspace'));
  for (const width of [898, 390]) {
    await page.setViewportSize({ width, height: 956 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Report overflow at ' + width);
    const downloadBox = await page.locator('.report-actions [data-action=download-report]').boundingBox();
    const returnBox = await reportReturn.boundingBox();
    assert(returnBox.x > downloadBox.x && Math.abs(returnBox.y - downloadBox.y) < 1, 'Return must be to the right of download at ' + width);
    await page.screenshot({ path: path.join(output, 'report-' + width + '.png'), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.locator('[data-filter=unsupported]').click();
  await expect(page.locator('.report-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.report-table tbody')).toContainText('图片分辨率');
  await page.locator('[data-filter=all]').click();
  let [file] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '下载报告', exact: true }).click()]);
  await file.saveAs(path.join(output, file.suggestedFilename()));
  assert((await readFile(path.join(output, file.suggestedFilename()), 'utf8')).includes('父版本：V1'));
  assert(!(await readFile(path.join(output, file.suggestedFilename()), 'utf8')).includes('another-candidate.docx'));
  await page.locator('#version-select').selectOption('2');
  const beforeReturn = await stored(page);
  await page.locator('.report-actions [data-route=workspace]').click();
  await expect(page.locator('.workspace-heading h1')).toHaveText('预览修改结果');
  await expect(page.locator('#version-select')).toHaveValue('2');
  assert.equal((await stored(page)).active, beforeReturn.active);
  assert.equal((await stored(page)).versions.length, beforeReturn.versions.length);
  await navigate(page, 'report');
  await page.locator('#version-select').selectOption('3');
  await page.locator('.report-actions [data-route=workspace]').click();
  await expect(page.locator('#version-select')).toHaveValue('3');
  record('Version-specific downloads and filtering; report returns to the same preview version without changing history');

  await navigate(page, 'workspace');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => { document.querySelector('#toast').hidden = true; });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile workspace horizontal overflow');
  await page.screenshot({ path: path.join(output, 'mobile-workspace.png'), fullPage: true });
  await navigate(page, 'upload');
  await page.evaluate(() => { document.querySelector('#toast').hidden = true; });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile upload horizontal overflow');
  await page.screenshot({ path: path.join(output, 'mobile-upload.png'), fullPage: true });
  await page.locator('#workspace-trigger').click();
  await expect(page.locator('.nav [data-action=reset]')).toBeVisible();
  const mobileMenu = await page.locator('#workspace-menu').boundingBox();
  assert(mobileMenu.x >= 0 && mobileMenu.x + mobileMenu.width <= 390, 'Mobile dropdown outside viewport');
  await page.screenshot({ path: path.join(output, 'mobile-navigation.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1440, height: 1000 });
  record('390px responsive upload and workspace, no document overflow');

  await navigate(page, 'history');
  await page.locator('[data-action=restart-original]').click();
  await page.locator('[data-action=restart-confirmed]').click();
  await expect(page.locator('[data-action=generate]')).toBeDisabled();
  assert.equal((await stored(page)).versions.length, 4);
  await reviewAnswers(page, 'left', 'keep');
  await page.locator('[data-action=generate]').click();
  await waitVersion(page, 4);
  current = await stored(page);
  assert.equal(current.versions[4].parent, 0);
  assert.equal(current.versions.length, 5);
  assert.equal(JSON.stringify(current.versions[0]), original);
  record('Restart from V0 creates a new numbered branch without replacing existing history');

  const failed = await freshPage();
  await startSample(failed, 'failure');
  await expect(failed.getByRole('heading', { name: '这次解析没有完成。' })).toBeVisible({ timeout: 12000 });
  await snapshot(failed, 8, 'failure');
  assert.equal((await stored(failed)).versions.length, 1);
  await failed.locator('[data-action=retry]').click();
  await expect(failed.locator('[data-question=alignment]')).toBeVisible({ timeout: 12000 });
  record('Parse failure preserves original; retry returns to requirement review');

  const clear = await freshPage();
  await startSample(clear, 'clear');
  await waitVersion(clear, 1);
  assert.equal((await stored(clear)).versions.length, 2);
  await navigate(clear, 'review');
  await expect(clear.getByRole('heading', { name: '要求清楚，已直接生成初稿。' })).toBeVisible();
  await expect(clear.locator('[data-action=generate]')).toHaveCount(0);
  record('No-question scenario continues directly to V1');

  const skipped = await freshPage();
  await startSample(skipped);
  await expect(skipped.locator('[data-question=alignment]')).toBeVisible({ timeout: 12000 });
  await skipped.locator('[data-action=skip-decision][data-key=alignment]').click();
  await skipped.locator('[data-action=skip-decision][data-key=page]').click();
  await skipped.locator('[data-action=generate]').click();
  await waitVersion(skipped, 1);
  const skipState = await stored(skipped);
  assert.equal(skipState.versions[1].styles.h1.align, skipState.versions[0].styles.h1.align);
  assert.equal(skipState.versions[1].rules.filter(r => r.status === 'ignored').length, 2);
  record('Explicit skips preserve original values and remain ignored in published report');

  const cancelled = await freshPage();
  await startSample(cancelled);
  await cancelled.locator('[data-action=cancel-process]').click();
  await expect(cancelled.locator('[data-action=parse]')).toBeVisible();
  await cancelled.waitForTimeout(2400);
  assert.equal((await stored(cancelled)).versions.length, 1);
  record('Cancel parsing never advances to editing');

  const restrictedContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  contexts.push(restrictedContext);
  await restrictedContext.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Blocked', 'SecurityError'); } });
  });
  const restricted = await restrictedContext.newPage();
  await restricted.goto(url);
  await startSample(restricted);
  await expect(restricted.locator('[data-question=alignment]')).toBeVisible({ timeout: 12000 });
  record('Storage denied still supports current-session flow');

  const offline = await browser.newContext();
  contexts.push(offline);
  await offline.route('http**/*', r => r.abort());
  const local = await offline.newPage();
  await local.goto(new URL('../site/prototype/index.html', import.meta.url).href);
  await expect(local.getByRole('heading', { name: '上传格式要求和原文' })).toBeVisible();
  await startSample(local);
  await expect(local.locator('[data-question=alignment]')).toBeVisible({ timeout: 12000 });
  record('Single HTML works through file:// with all network requests disabled');

  const landing = await freshPage();
  await landing.goto(base + '/index.html');
  const link = landing.locator('a[href="./prototype/index.html#upload"]');
  await expect(link).toHaveCount(1);
  assert.equal((await landing.request.get(await link.evaluate(e => e.href))).status(), 200);
  await landing.getByRole('button', { name: 'English', exact: true }).click();
  await expect(link).toContainText('Try the interactive prototype');
  await landing.screenshot({ path: path.join(output, 'landing-link.png'), fullPage: true });
  record('Landing relative link resolves and English CTA translation works');

  assert.equal(network.length, 0, 'Prototype must not contact external services');
  assert.deepEqual(browserErrors, []);
  record('No external-service requests or browser console errors');

  // Static fallback HTML is intentionally independent of runtime JavaScript.
  boards.sort((a, b) => a.number - b.number);
  const names = { upload: '01-upload.html', processing: '02-parsing.html', review: '03-review.html', workspace: '04-workspace.html', history: '06-history.html', report: '07-report.html' };
  const actionTargets = { parse: names.processing, generate: names.workspace, analyze: '05-conflict.html', 'apply-plan': names.workspace, 'resolve-conflict': names.workspace, retry: names.processing, 'view-version': names.workspace, continue: names.workspace, 'restart-original': names.review, 'toggle-workspace': '09-navigation.html' };
  const esc = text => text.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const importCss = '\n.topbar{position:relative;top:auto}.import-overlay{position:absolute;inset:0;min-height:900px;background:#14223870;display:flex;justify-content:center;align-items:flex-start;padding:170px 24px 50px}.import-modal{display:block;position:relative;max-height:none}.import-board{position:relative;width:1440px;margin:0 auto 48px;overflow:hidden;background:#ffffff;border:1px solid #dce3eb}.import-label{width:1440px;margin:35px auto 12px;font:16px \'Segoe UI\',\'Microsoft YaHei\',sans-serif;color:#223047}.import-canvas{margin:0;padding:20px 40px;background:#eef2f6}.import-caption{width:1440px;margin:20px auto;font:14px \'Microsoft YaHei\',sans-serif;line-height:1.9;color:#637183}';
  const labels = ['新建任务', '解析进度', '编辑前确认', '预览与微调', '冲突处理', '版本历史', '修改报告', '解析失败与重试', '论文空间下拉菜单'];
  for (const board of boards) {
    // Convert known navigation/buttons to real local anchors while retaining style and semantics.
    const convert = html => html.replace(/<a([^>]*?)data-route="([^"]+)"([^>]*?)>/g, (all, a, r, b) => {
      const attrs = (a + b).replace(/href="[^"]*"/g, '');
      return '<a href="./' + (names[r] || names.upload) + '"' + attrs + '>';
    }).replace(/<button([^>]*?)data-action="([^"]+)"([^>]*?)>([\s\S]*?)<\/button>/g, (all, a, action, b, text) => {
      if (!actionTargets[action] || /\bdisabled\b/.test(a + b)) return all;
      const destination = action === 'toggle-workspace' && board.number === 9 ? names.upload : actionTargets[action];
      return '<a href="./' + destination + '"' + (a + b).replace(/type="[^"]*"/g, '') + '>' + text + '</a>';
    }).replace('href="../index.html"', 'href="../../index.html"');
    const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AutoFormat · ' + esc(labels[board.number - 1]) + '</title><style>' + board.css + importCss + '</style></head><body><div style="position:relative">' + convert(board.app) + convert(board.overlay) + '</div></body></html>\n';
    await writeFile(path.join(target, 'pages', board.file), html, 'utf8');
    board.standalone = html;
  }
  await writeFile(path.join(target, 'modao-import.html'), '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>AutoFormat · 墨刀导入画板</title><style>' + boards[0].css + importCss + '</style></head><body class="import-canvas"><p class="import-caption">AutoFormat · 产品原型画板集。9 个关键状态全部展开，包含顶部导航的菜单展开状态；各页面为原生 HTML 元素。完整交互体验请打开 index.html。导入后按 README 核对页面与连接。</p>' + boards.map(b => '<h2 class="import-label">' + String(b.number).padStart(2, '0') + ' / ' + esc(labels[b.number - 1]) + '</h2><section class="import-board" data-page-name="' + esc(labels[b.number - 1]) + '" id="artboard-' + b.number + '">' + b.app + b.overlay + '</section>').join('') + '</body></html>\n', 'utf8');
  for (const board of boards) {
    const response = await page.request.get(base + '/prototype/pages/' + board.file);
    assert.equal(response.status(), 200);
    assert(!board.standalone.includes('<script'), 'Static import boards must not need script execution');
  }
  await page.goto(base + '/prototype/pages/01-upload.html');
  await page.locator('#workspace-trigger').click();
  await expect(page.locator('#workspace-menu')).toBeVisible();
  await page.locator('#workspace-trigger').click();
  await expect(page.locator('#workspace-menu')).toBeHidden();
  await page.goto(base + '/prototype/pages/07-report.html');
  await page.locator('.report-actions a[href="./04-workspace.html"]').click();
  await expect(page.locator('.workspace-heading h1')).toHaveText('预览修改结果');
  record('Nine self-contained static pages plus Modao import atlas generated; static dropdown states linked');
  await writeFile(path.join(output, 'verification.json'), JSON.stringify({ verifiedAt: new Date().toISOString(), checks, browserErrors, externalRequests: network, boards: boards.map(b => b.file) }, null, 2), 'utf8');
  console.log('Verified ' + checks.length + ' acceptance groups; generated ' + boards.length + ' import pages.');
} finally {
  await Promise.all(contexts.map(c => c.close()));
  await browser.close();
}
