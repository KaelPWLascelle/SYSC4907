import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { defineConfig, devices } from '@playwright/test';

// End-to-end tests drive the real app: the Python server with the built interface, on the bundled
// 36-title catalogue. HOME points at a fresh folder, so no personal data, podcast catalogue or poster
// cache on this machine can change the results, and every run starts with an empty database.
const port = 8791;
const home = mkdtempSync(join(tmpdir(), 'flicks-e2e-'));
const venv = resolve('../.venv/bin/python');
const python = process.env.FLICKS_PYTHON ?? (existsSync(venv) ? venv : 'python');

export default defineConfig({
  testDir: 'e2e',
  // One server holds one database, so tests run in order rather than racing each other's ratings.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['json', { outputFile: 'test-results/e2e.json' }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      testIgnore: /mobile/,
    },
    { name: 'phone', use: { ...devices['Pixel 7'] }, testMatch: /mobile/ },
    // Safari's engine lays out some CSS differently (it stretched Discover's trailer past its cell).
    {
      name: 'safari',
      use: { ...devices['Desktop Safari'], viewport: { width: 1000, height: 584 } },
      testMatch: /layout/,
    },
  ],
  webServer: {
    command: `npm run build && cd .. && HOME=${home} ${python} -m flicks --port ${port} --no-browser --trailers web/e2e/fixtures/trailers.json`,
    url: `http://127.0.0.1:${port}/api/state`,
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
