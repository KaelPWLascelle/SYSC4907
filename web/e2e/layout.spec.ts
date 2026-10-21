import { expect, type Page, test } from '@playwright/test';

// Discover's media must fit its cell whatever the engine and window shape (runs in Chromium and WebKit).
// YouTube is answered by a stand-in page that tells Flicks it is playing, as the real player does.
const STAND_IN = `<!doctype html><body style="margin:0;background:#234"><script>
  addEventListener('message', () => parent.postMessage(JSON.stringify({ event: 'infoDelivery', info: { playerState: 1 } }), '*'));
</script></body>`;

async function box(page: Page, selector: string) {
  return page.evaluate(sel => {
    const card = document.querySelector('[data-index="0"]');
    const rect = (node: Element | null | undefined) => node?.getBoundingClientRect().toJSON() as DOMRect | undefined;
    return { cell: rect(card?.querySelector('.discover-media')), box: rect(card?.querySelector(sel)) };
  }, selector);
}

function expectInside({ cell, box: inner }: { cell?: DOMRect; box?: DOMRect }) {
  expect(cell && inner).toBeTruthy();
  if (!cell || !inner) return;
  expect(inner.left).toBeGreaterThanOrEqual(cell.left - 1);
  expect(inner.right).toBeLessThanOrEqual(cell.right + 1);
  expect(inner.top).toBeGreaterThanOrEqual(cell.top - 1);
  expect(inner.bottom).toBeLessThanOrEqual(cell.bottom + 1);
}

for (const size of [
  { width: 1000, height: 584 },
  { width: 2000, height: 1168 },
  { width: 844, height: 390 },
]) {
  test(`Discover's trailer and poster fit their space at ${size.width}×${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.route('https://www.youtube-nocookie.com/**', route =>
      route.fulfill({ contentType: 'text/html', body: STAND_IN }),
    );
    await page.goto('/');
    await page.getByRole('button', { name: 'Discover' }).click();
    const feed = page.getByRole('dialog', { name: 'Discover' });
    await expect(feed.getByRole('article').first()).toBeVisible();
    expectInside(await box(page, '.discover-poster'));

    await feed.getByRole('button', { name: 'Online trailers off' }).click();
    await feed.getByRole('button', { name: 'Allow trailers' }).click();
    await expect(feed.locator('[data-index="0"] iframe')).not.toHaveClass(/discover-frame-hidden/);
    expectInside(await box(page, '.discover-trailer'));
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    await page.evaluate(() => localStorage.clear());
  });
}
