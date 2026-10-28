import { expect, type Page, test } from '@playwright/test';

// The real app on the bundled catalogue (playwright.config.ts). Tests share one server and database,
// so they run in order and each leaves the profile as it found it unless the test says otherwise.
test.describe.configure({ mode: 'serial' });

let errors: string[] = [];
test.beforeEach(({ page }) => {
  errors = [];
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', error => errors.push(error.message));
});
test.afterEach(() => {
  expect(errors, 'console errors').toEqual([]);
});

const heroTitle = (page: Page) => page.locator('#hero-title');
/** The top pick's title, once picks have loaded (the hero shows a placeholder until then). */
async function topPick(page: Page) {
  await expect(page.getByRole('button', { name: 'Why this pick' })).toBeVisible();
  return (await heroTitle(page).textContent()) ?? '';
}

test('home shows a top pick with its reasons and a full row of picks', async ({ page }) => {
  await page.goto('/');
  await topPick(page);
  await expect(page.getByRole('list', { name: 'Why this pick' }).first()).toBeVisible();
  await expect(page.locator('#picks .tile')).toHaveCount(12);
  await expect(page.locator('.scene-sentence')).toHaveText('I have 2 hours for something any mood, balanced.');
  // Couch mode is offered without a flag; nothing listens on the network until a session starts.
  await expect(page.getByRole('navigation', { name: 'Sections' }).getByRole('link', { name: 'Couch' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start a couch session' })).toBeVisible();
});

test('a like shows at once, survives a reload, and clears on a second press', async ({ page }) => {
  // Rated titles leave the picks, so rate in Browse, where a title stays put.
  const arrival = () => page.locator('#browse').getByRole('article').filter({ hasText: 'Arrival' }).first();
  await page.goto('/');
  await page.getByRole('searchbox').fill('Arrival');
  await arrival().getByRole('button', { name: 'Like: Arrival' }).click();
  await expect(arrival().getByRole('button', { name: 'Clear rating: Arrival' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.reload();
  await page.getByRole('searchbox').fill('Arrival');
  await expect(arrival().getByRole('button', { name: 'Clear rating: Arrival' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await arrival().getByRole('button', { name: 'Clear rating: Arrival' }).click();
  await expect(arrival().getByRole('button', { name: 'Like: Arrival' })).toHaveAttribute('aria-pressed', 'false');
  await expect.poll(async () => (await (await page.request.get('/api/state')).json()).feedback).toEqual({});
});

test('the scene sentence re-ranks the picks, and More options hide the rest', async ({ page }) => {
  await page.goto('/');
  await topPick(page);
  const request = page.waitForRequest(
    r => r.url().endsWith('/api/recommend') && r.postDataJSON().session.mood === 'tense',
  );
  await page.getByRole('button', { name: 'Mood: any mood. Change' }).click();
  await page.getByRole('radio', { name: 'Tense' }).click();
  await request;
  await expect(page.getByRole('button', { name: 'Mood: tense. Change' })).toBeVisible();
  await expect(page.getByRole('slider', { name: /Discovery/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'More options' }).click();
  await expect(page.getByRole('slider', { name: /Discovery/ })).toBeVisible();
  await page.getByRole('button', { name: 'Horror' }).click();
  await expect(page.getByRole('button', { name: /Fewer options/ })).toContainText('1');
  await page.getByRole('button', { name: 'Reset scene' }).click();
  await expect(page.getByRole('button', { name: 'Mood: any mood. Change' })).toBeVisible();
});

test('“Why this pick” explains the score in words and parts, and the sheet fits its content', async ({ page }) => {
  await page.goto('/');
  await topPick(page);
  await page.getByRole('button', { name: 'Why this pick' }).click();
  const sheet = page.getByRole('dialog');
  await expect(sheet.locator('.narration')).toContainText('fits the 2h you have');
  const parts = await sheet.locator('.factor-value').allTextContents();
  const values = parts.slice(0, -1).map(text => Number(text.split(' / ')[0]));
  const total = Number(parts.at(-1));
  expect(Math.abs(values.reduce((a, b) => a + b, 0) - total)).toBeLessThanOrEqual(0.011); // shown to two decimals
  const fit = await sheet.evaluate(node => node.scrollHeight - node.clientHeight);
  expect(fit).toBeLessThanOrEqual(1); // never a stretched, empty sheet
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
});

test('Ask reads a described evening into the scene, and the student needs no model server', async ({ page }) => {
  await page.goto('/');
  const ask = page.getByRole('textbox', { name: 'Ask Flicks, or edit the transcript' });
  await ask.fill('long week, i want to switch off, nothing scary');
  await ask.press('Enter');
  await expect(page.locator('.ask .ask-message')).toContainText('mood: relaxing');
  await expect(page.locator('.ask .ask-message')).toContainText('avoid horror');
  await page.getByRole('button', { name: 'Apply' }).click();
  await expect(page.getByRole('button', { name: 'Mood: relaxing. Change' })).toBeVisible();
  await page.getByRole('button', { name: 'Reset scene' }).click();
});

test('“Your taste” charts the ratings, and a tuned mix reaches every pick request', async ({ page }) => {
  for (const [id, value] of [
    ['m001', 1],
    ['m004', 1],
    ['m008', -1],
  ] as const) {
    await page.request.post('/api/feedback', { data: { id, value } });
  }
  await page.goto('/');
  await page.getByRole('button', { name: 'Your taste' }).click();
  const sheet = page.getByRole('dialog', { name: 'Your taste' });
  await expect(sheet.getByText('Built from 2 likes and 1 pass.')).toBeVisible();
  await expect(
    sheet
      .getByRole('list', { name: /Genre lean/ })
      .getByRole('button')
      .first(),
  ).toBeVisible();
  const sliders = sheet.getByRole('slider');
  for (const index of [1, 2, 3]) await sliders.nth(index).fill('0');
  const tuned = page.waitForRequest(r => r.url().endsWith('/api/recommend') && r.postDataJSON().session.mix[0] === 1);
  await sheet.getByRole('button', { name: 'Use this mix' }).click();
  await tuned;
  for (const id of ['m001', 'm004', 'm008']) await page.request.post('/api/feedback', { data: { id, value: 0 } });
  await page.evaluate(() => localStorage.clear());
});

test('Discover: a like in the feed is a rating, and trailers wait for permission', async ({ page }) => {
  // Answer YouTube ourselves: the test checks what Flicks asks for, not YouTube.
  const asked: string[] = [];
  await page.route('https://www.youtube-nocookie.com/**', route => {
    asked.push(route.request().url());
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>trailer</title>' });
  });
  await page.goto('/');
  await topPick(page);
  await page.getByRole('button', { name: 'Discover' }).click();
  const feed = page.getByRole('dialog', { name: 'Discover' });
  const first = feed.getByRole('article').first();
  await expect(first.locator('.eyebrow')).toHaveText('For you');
  const title = (await first.getByRole('heading').textContent()) ?? '';
  await first.getByRole('button', { name: `Like: ${title}` }).click();
  await expect
    .poll(async () => Object.keys((await (await page.request.get('/api/state')).json()).feedback))
    .toHaveLength(1);
  expect(asked).toEqual([]); // nothing went to YouTube before the viewer allowed it

  await feed.getByRole('button', { name: 'Online trailers off' }).click();
  await feed.getByRole('button', { name: 'Allow trailers' }).click();
  await expect(feed.locator('iframe')).toHaveAttribute(
    'src',
    /^https:\/\/www\.youtube-nocookie\.com\/embed\/e2e\d{8}\?/,
  );
  await expect.poll(() => asked.length).toBeGreaterThan(0);
  expect(asked.every(url => url.startsWith('https://www.youtube-nocookie.com/embed/'))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(feed).toBeHidden();
  const { feedback } = await (await page.request.get('/api/state')).json();
  for (const id of Object.keys(feedback)) await page.request.post('/api/feedback', { data: { id, value: 0 } });
  await page.evaluate(() => localStorage.clear());
});

test('“Pick for me” draws one of the top picks and says how likely it was', async ({ page }) => {
  await page.goto('/');
  await topPick(page);
  await page.getByRole('button', { name: 'Pick for me' }).click();
  const sheet = page.getByRole('dialog').filter({ has: page.getByText('Picked at random') });
  await expect(sheet.getByRole('status')).toContainText(/your top 12 picks: a 1 in \d+ chance/);
  await sheet.getByRole('button', { name: 'From anything' }).click();
  await expect(sheet.getByRole('status')).toContainText(/all \d+ titles that fit this scene/);
  await page.keyboard.press('Escape');
});

test('the server refuses requests from other sites', async ({ request }) => {
  const response = await request.post('/api/feedback', {
    data: { id: 'm001', value: 1 },
    headers: { Origin: 'https://evil.example' },
  });
  expect(response.status()).toBe(403);
});

test('a PIN profile asks who is watching and needs its PIN', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Profile: Me' }).click();
  await page.getByRole('button', { name: 'Switch profile' }).click();
  await expect(page.getByRole('heading', { name: 'Who’s watching?' })).toBeVisible();
  await page.getByRole('button', { name: /Add profile/ }).click();
  await page.getByLabel('Name').fill('Sam');
  await page.getByLabel('PIN (optional, 4–8 digits)').fill('2468');
  await page.getByRole('button', { name: 'Create profile' }).click();
  await expect(page.getByRole('button', { name: 'Profile: Sam' })).toBeVisible();

  await page.getByRole('button', { name: 'Profile: Sam' }).click();
  await page.getByRole('button', { name: 'Switch profile' }).click();
  await page.getByRole('button', { name: /Sam/ }).click();
  await page.getByLabel('PIN for Sam').fill('1111');
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('alert')).toContainText('Wrong PIN');
  errors = errors.filter(error => !error.includes('403')); // the refused PIN is an expected 403
  await page.getByLabel('PIN for Sam').fill('2468');
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('button', { name: 'Profile: Sam' })).toBeVisible();
  // Leave one profile behind, so later tests (and fresh browsers) are not asked who is watching.
  expect((await page.request.delete('/api/profiles/current')).status()).toBe(200);
});

test('the spotlight follows the pick you point at, without moving the page below', async ({ page }) => {
  await page.goto('/');
  const first = await topPick(page);
  const actions = page.locator('.hero-actions');
  const before = await actions.boundingBox();
  const tile = page.locator('#picks .tile').nth(2).locator('.tile-open');
  await tile.scrollIntoViewIfNeeded();
  await tile.hover();
  await expect(heroTitle(page)).not.toHaveText(first);
  await page.evaluate(() => window.scrollTo(0, 0));
  expect((await actions.boundingBox())?.y).toBeCloseTo(before?.y ?? 0, 0);
});

test('the bulb on the i dims the house lights, and Escape brings them back', async ({ page }) => {
  await page.goto('/');
  await topPick(page);
  const html = page.locator('html');
  await page.getByRole('button', { name: 'Dim the lights' }).click();
  await expect(html).toHaveClass(/is-dim/);
  await page.keyboard.press('Escape');
  await expect(html).not.toHaveClass(/is-dim/);
  await page.keyboard.press('l');
  await expect(html).toHaveClass(/is-dim/);
  await page.keyboard.press('l');
  await expect(html).not.toHaveClass(/is-dim/);
});

test('“Your taste” hangs rated films in a web of genres, and a usual night becomes the scene', async ({ page }) => {
  for (const [id, value] of [
    ['m001', 1],
    ['m004', 1],
    ['m008', -1],
  ] as const) {
    await page.request.post('/api/feedback', { data: { id, value } });
  }
  await page.goto('/');
  await topPick(page);
  await page.getByRole('button', { name: 'Your taste' }).click();
  const sheet = page.getByRole('dialog', { name: 'Your taste' });
  const web = sheet.getByRole('group', { name: 'Your taste as a web of genres' });
  await expect(web).toBeVisible();
  await expect(web.locator('.web-drop')).toHaveCount(3);
  await web.getByRole('button', { name: /^Horror: liked 0, passed 1$/ }).click();
  await expect(sheet.getByText(/^You passed on the one horror title you rated/)).toBeVisible();

  const pad = sheet.getByRole('slider', { name: /Your usual night/ });
  await pad.focus();
  for (const key of ['ArrowLeft', 'ArrowLeft', 'ArrowLeft', 'ArrowDown', 'ArrowDown']) await page.keyboard.press(key);
  await expect(sheet.getByText('Most nights you want something gentle, about 1½ hours.')).toBeVisible();
  const asked = page.waitForRequest(r => r.url().endsWith('/api/recommend') && r.postDataJSON().session.minutes === 90);
  await sheet.getByRole('button', { name: 'Use as my usual night' }).click();
  await asked;
  await sheet.getByRole('button', { name: 'Close' }).click();
  await expect(page.getByRole('button', { name: 'Time: 1½ hours. Change' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Time: 1½ hours. Change' })).toBeVisible();

  for (const id of ['m001', 'm004', 'm008']) await page.request.post('/api/feedback', { data: { id, value: 0 } });
  await page.evaluate(() => localStorage.clear());
});

test('late at night the room dims and offers picks that end sooner', async ({ page }) => {
  await page.goto('/?hour=23');
  await topPick(page);
  await expect(page.locator('html')).toHaveAttribute('data-time', 'late');
  await page.getByRole('button', { name: 'Show picks that end in 90 minutes' }).click();
  await expect(page.getByRole('button', { name: 'Time: 1½ hours. Change' })).toBeVisible();
});
