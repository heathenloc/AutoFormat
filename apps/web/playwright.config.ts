import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';

const project = resolve('../..');
const python = process.env.AUTOFORMAT_TEST_PYTHON ?? resolve(project, '.venv/Scripts/python.exe');
export default defineConfig({
  testDir: './tests', timeout: 30000, workers: 1, fullyParallel: false,
  outputDir: '../../runtime/playwright-results',
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:58371', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'off' },
  webServer: {
    command: `"${python}" -X utf8 tests/preview/serve_browser_fixture.py`, cwd: project,
    url: 'http://127.0.0.1:58371', timeout: 120000, reuseExistingServer: false,
  },
});
