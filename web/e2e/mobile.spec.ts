import { expect, type Page, test } from '@playwright/test';

// Phone layout (Pixel 7 profile in playwright.config.ts): nothing may scroll sideways.
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

test('home, the scene sentence and its pickers fit a phone', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#hero-title')).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await page.getByRole('button', { name: 'Time: 2 hours. Change' }).click();
  await expect(page.getByRole('button', { name: '1h 30m' })).toBeVisible();
  await page.getByRole('button', { name: 'More options' }).click();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('“Your taste” and “Why this pick” fit a phone', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Your taste' }).click();
  await expect(page.getByRole('dialog', { name: 'Your taste' })).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Why this pick' }).click();
  await expect(page.getByRole('dialog').locator('.narration')).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('Discover fits a phone', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Discover' }).click();
  await expect(page.getByRole('dialog', { name: 'Discover' }).getByRole('article').first()).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await page.keyboard.press('Escape');
});

test('the couch room fits a phone', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Start a couch session' }).click();
  await expect(page.locator('.couch-code')).toBeVisible();
  await expect(page.getByRole('list', { name: 'Who’s voting' })).toBeAttached();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await page.getByRole('button', { name: 'End session' }).click();
  await expect(page.getByRole('button', { name: 'Start a couch session' })).toBeVisible();
});
