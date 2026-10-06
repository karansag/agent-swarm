// Run `npx playwright install chromium` once, then `npm run test:browser`.
// Uses the production bundle and isolated API fixtures; never contacts a hub.
import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { preview } from 'vite';
import { chromium } from 'playwright';
import { mock, names, file, image } from './fixtures/mobile-state.js';

let browser, server, base;
before(async () => {
  server = await preview({ preview: { host: '127.0.0.1', port: 0, open: false } });
  base = `http://127.0.0.1:${server.httpServer.address().port}/portal.html`;
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  await new Promise(resolve => server.httpServer.close(resolve));
});
async function setup(width, height, touch = true) {
  const page = await browser.newPage({ viewport: { width, height }, hasTouch: touch, isMobile: touch });
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const state = await mock(page);
  return { page, state, errors };
}
async function fit(page) {
  await page.locator('img').evaluateAll(images => Promise.all(images.map(img => {
    img.loading = 'eager';
    return img.complete ? Promise.resolve() : new Promise(resolve => {
      img.addEventListener('load', resolve, {once:true});
      img.addEventListener('error', resolve, {once:true});
    });
  })));
  const measured = await page.evaluate(() => {
    const stage = document.querySelector('.stage');
    const width = document.documentElement.clientWidth;
    return {
      width, page: document.documentElement.scrollWidth,
      stage: stage.scrollWidth, stageWidth: stage.clientWidth,
      overflow: [...document.querySelectorAll('.stage *')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width && r.right > width + 1 && !e.closest('.sr-only');
      }).map(e => e.className),
      small: [...document.querySelectorAll('button, select, nav.views a, .bee-tile')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width && r.height && (r.height < 43.5 || r.width < 43.5) && !e.closest('[hidden]');
      }).map(e => e.className),
    };
  });
  assert.equal(measured.page, measured.width);
  assert.ok(measured.stage <= measured.stageWidth + 1);
  assert.deepEqual(measured.overflow, []);
  assert.deepEqual(measured.small, []);
}
for (const [width, height] of [[320,568],[390,844],[430,932],[768,1024],[820,1180],[1024,768]]) {
  test(`phone/tablet ${width}x${height}: overview, chat, long names, history fit`, async () => {
    const { page, errors } = await setup(width, height);
    try {
      for (const hash of ['#/', '#/agent/stoat', `#/agent/${names[1]}`, '#/tasks']) {
        await page.goto(base + hash);
        await page.waitForSelector('.roster-drawer');
        await fit(page);
        assert.equal(await page.locator('canvas').count(), 0);
      }
      assert.deepEqual(errors, []);
    } finally { await page.close(); }
  });
}

test('touch navigation, filtering, roster stacking, task details and assignment', async () => {
  const { page, state, errors } = await setup(390,844);
  const patches = [];
  await page.route('**/tasks/73', async route => {
    const patch = route.request().postDataJSON();
    patches.push(patch); Object.assign(state.tasks[0], patch);
    await route.fulfill({ json: { ok: true } });
  });
  try {
    await page.goto(base);
    await page.waitForSelector('.bee-tile');
    assert.equal(await page.locator('.bee-tile').count(), 8);
    assert.equal(await page.locator('.bee-tile .bee-working-halo').count(), 2);
    const identity = await page.locator('.bee-tile').first().evaluate(tile => ({
      machine: tile.style.getPropertyValue('--machine'),
      body: tile.querySelector('ellipse[cx="26"]').getAttribute('fill'),
      harness: tile.querySelectorAll('path')[1].getAttribute('stroke'),
      halo: tile.querySelector('.bee-working-halo circle').getAttribute('stroke'),
    }));
    assert.equal(identity.machine, identity.body);
    assert.equal(identity.harness, '#56b4e9');
    assert.equal(identity.halo, '#9be879');
    await page.getByRole('button', { name: /karans-mbp.*connected/i }).tap();
    assert.equal(await page.locator('.bee-tile').count(), 4);
    await page.locator('.bee-tile').first().tap();
    await page.waitForSelector('.focus-back');
    assert.match(page.url(), /agent\/numbat/);
    assert.ok(await page.locator('.stage').evaluate(e => Math.abs(e.getBoundingClientRect().top) < 30));
    assert.equal(await page.locator('.status-history').getAttribute('open'), null);
    await page.locator('.status-history summary').tap();
    assert.notEqual(await page.locator('.status-history').getAttribute('open'), null);
    await page.locator('.focus-back').tap();
    await page.locator('.hive-task-picker select').selectOption('73');
    await page.locator('.hive-task-detail').getByRole('combobox', { name: 'Assign task #73' }).selectOption('t:1');
    await page.waitForFunction(() => document.querySelector('.hive-task-detail p').textContent.includes('team agent-swarm'));
    await page.locator('.hive-task-detail').getByRole('combobox', { name: 'Assign task #73' }).selectOption('ferret');
    await page.waitForFunction(() => document.querySelector('.hive-task-detail p').textContent.includes('ferret'));
    assert.deepEqual(patches, [{team_id:1}, {assignee:'ferret',team_id:null}]);
    await fit(page);
    await page.getByRole('button', { name: /Agent roster/ }).tap();
    await page.waitForTimeout(500);
    assert.ok(await page.locator('#agent-sidebar').evaluate(e => e.getBoundingClientRect().top < innerHeight));
    const bounds = await page.evaluate(() => ({stage:document.querySelector('.stage').getBoundingClientRect().bottom, roster:document.querySelector('#agent-sidebar').getBoundingClientRect().top}));
    assert.ok(bounds.roster >= bounds.stage - 1);
    await page.getByRole('button', { name: 'Hide agents' }).tap();
    assert.equal(await page.locator('#agent-sidebar').isVisible(), false);
    await page.getByRole('button', { name: /Agent roster/ }).tap();
    assert.equal(await page.locator('#agent-sidebar').isVisible(), true);
    const chip = page.locator('.chip-card').filter({has:page.locator('.nm', {hasText:names[1]})}).first();
    await chip.tap();
    await page.waitForSelector('.focus-back');
    const selected = page.url();
    await chip.tap();
    assert.equal(page.url(), selected);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('task completion has one note-aware action across board, agent, and honeycomb', async () => {
  const { page, state, errors } = await setup(390,844);
  const patches = [];
  await page.route('**/tasks/*', async route => {
    if (route.request().method() !== 'PATCH') return route.continue();
    const id = Number(route.request().url().split('/').pop());
    const patch = route.request().postDataJSON();
    patches.push({ id, ...patch });
    const task = state.tasks.find(t => t.id === id);
    Object.assign(task, patch);
    await route.fulfill({ json: { ok: true, task } });
  });
  try {
    await page.goto(base);
    const card = page.locator('.col.picked_up .tcard').first();
    await card.getByRole('button', { name: 'Complete task' }).tap();
    assert.equal(patches.length, 0);
    await card.locator('.task-verification textarea').fill('Check the mobile dashboard at 390px.');
    await card.getByRole('button', { name: 'Complete task' }).tap();
    await page.waitForFunction(() => [...document.querySelectorAll('.col.done .tcard')]
      .some(e => e.textContent.includes('Make the dashboard mobile friendly')));
    assert.deepEqual(patches[0], { id: 73, status: 'done', note: 'Check the mobile dashboard at 390px.' });
    const done = page.locator('.col.done .tcard').filter({ has: page.locator('.t', { hasText: 'Make the dashboard mobile friendly' }) });
    assert.equal(await done.getByRole('combobox', { name: 'Assign task #73' }).isDisabled(), true);
    await done.getByRole('button', { name: 'Reopen' }).tap();
    await page.waitForFunction(() => [...document.querySelectorAll('.col.picked_up .tcard')]
      .some(e => e.textContent.includes('Make the dashboard mobile friendly')));
    assert.deepEqual(patches[1], { id: 73, status: 'picked_up' });
    const unassigned = page.locator('.col.open .tcard').filter({ hasText: 'Long path regression' });
    assert.equal(await unassigned.getByRole('button', { name: 'Start work' }).isDisabled(), true);
    await unassigned.getByRole('combobox', { name: 'Assign task #74' }).selectOption('stoat');
    await unassigned.getByRole('button', { name: 'Start work' }).tap();
    await page.waitForFunction(() => [...document.querySelectorAll('.col.picked_up .tcard')]
      .some(e => e.textContent.includes('Long path regression')));
    assert.deepEqual(patches[2], { id: 74, assignee: 'stoat' });
    assert.deepEqual(patches[3], { id: 74, status: 'picked_up' });

    await page.goto(base + '#/agent/stoat');
    const row = page.locator('.trow').filter({ hasText: 'Make the dashboard mobile friendly' });
    await row.getByRole('button', { name: 'Complete task' }).tap();
    await page.waitForFunction(() => [...document.querySelectorAll('.trow.done')]
      .some(e => e.textContent.includes('Make the dashboard mobile friendly')));
    assert.deepEqual(patches[4], { id: 73, status: 'done', note: 'Check the mobile dashboard at 390px.' });

    await page.goto(base);
    await page.locator('.hive-task-picker select').selectOption('74');
    const detail = page.locator('.hive-task-detail');
    await detail.getByRole('button', { name: 'Complete task' }).tap();
    await detail.locator('.task-verification textarea').fill('Open the board and inspect task #74.');
    await detail.getByRole('button', { name: 'Complete task' }).tap();
    await page.waitForFunction(() => document.querySelector('.hive-task-detail')?.textContent.includes('done'));
    assert.deepEqual(patches[5], { id: 74, status: 'done', note: 'Open the board and inspect task #74.' });
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('mobile attachments, message actions, and conversation controls stay usable', async () => {
  const { page, errors } = await setup(390,844);
  const sent = [];
  await page.route('**/attachments', r => r.fulfill({json:{name:r.request().headers()['x-attachment-filename']?.endsWith('.png') ? image : file}}));
  await page.route('**/send', async r => {
    sent.push(r.request().postDataJSON());
    await r.fulfill({json:{ok:true,status:'delivered',message_id:3}});
  });
  try {
    await page.goto(base+'#/agent/stoat');
    const composer = page.locator('.thread .composer').first();
    await composer.locator('input[type=file]').setInputFiles({name:'review.txt',mimeType:'text/plain',buffer:Buffer.from('mobile review')});
    await composer.getByRole('button',{name:/Remove/}).waitFor();
    await fit(page);
    await composer.getByRole('button',{name:/Remove/}).tap();
    assert.equal(await composer.locator('.compose-image').count(),0);
    await composer.locator('input[type=file]').setInputFiles({name:'review.txt',mimeType:'text/plain',buffer:Buffer.from('mobile review')});
    await composer.getByRole('button',{name:/Remove/}).waitFor();
    await composer.locator('textarea').fill('Verified the mobile dashboard.');
    await composer.getByRole('button',{name:'send',exact:true}).tap();
    await page.waitForTimeout(100);
    assert.equal(sent.length,1); assert.deepEqual(sent[0].attachments,[file]);
    assert.equal(sent[0].recipient,'stoat');
    const toggle=page.locator('.thread-toggle').first();
    await toggle.tap(); assert.equal(await toggle.getAttribute('aria-expanded'),'false');
    await toggle.tap(); assert.equal(await toggle.getAttribute('aria-expanded'),'true');
    await fit(page);
    await page.goto(base);
    const taskComposer = page.locator('.task-composer');
    await taskComposer.locator('input[type=file]').setInputFiles({name:'layout.png',mimeType:'image/png',buffer:Buffer.from('mock image bytes')});
    await taskComposer.getByRole('button',{name:'Remove Image'}).waitFor();
    await fit(page);
    await taskComposer.getByRole('button',{name:'Remove Image'}).tap();
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('desktop baseline and rotation remount the canvas without errors', async () => {
  const {page, errors} = await setup(1001,900,false);
  try {
    await page.goto(base);
    await page.waitForSelector('canvas');
    assert.equal(await page.locator('.compact-hive').count(),0);
    await page.getByRole('button',{name:'Hide agents'}).click();
    await page.setViewportSize({width:390,height:844});
    await page.waitForSelector('.compact-hive');
    assert.equal(await page.locator('#agent-sidebar').isVisible(),false);
    assert.equal(await page.locator('canvas').count(),0);
    await page.setViewportSize({width:1440,height:900});
    await page.waitForSelector('canvas');
    assert.equal(await page.locator('.compact-hive').count(),0);
    await page.waitForFunction(()=>!!window.__hive);
    assert.equal(await page.locator('#agent-sidebar').isVisible(),false);
    assert.equal(await page.locator('canvas').count(),1);
    assert.deepEqual(errors,[]);
  } finally {await page.close();}
});

test('home-screen app gets a reload button; a browser tab does not', async () => {
  const { page, errors } = await setup(390, 844);
  try {
    await page.goto(base);
    await page.waitForSelector('.roster-drawer');
    assert.equal(await page.locator('header.top .reload').count(), 0);
    // iOS marks a page opened from the home screen with navigator.standalone.
    await page.addInitScript(() => Object.defineProperty(navigator, 'standalone', { value: true }));
    await page.reload();
    await page.waitForSelector('.roster-drawer');
    await fit(page);
    await page.evaluate(() => { window.beforeReload = true; });
    await page.locator('header.top .reload').click();
    await page.waitForSelector('.roster-drawer');
    assert.equal(await page.evaluate(() => window.beforeReload), undefined);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a send whose answer is lost is retried under the same id, not duplicated', async () => {
  const { page, errors } = await setup(390, 844);
  const ids = [];
  await page.route('**/owner/send', async route => {
    ids.push(route.request().postDataJSON().client_id);
    // The first answer is lost on the way back; the retry gets the server's word.
    if (ids.length === 1) return route.abort('connectionreset');
    await route.fulfill({ json: { ok: true, status: 'delivered', message_id: 1 } });
  });
  try {
    await page.goto(base + '#/agent/stoat');
    const box = page.locator('form.composer textarea').first();
    await box.fill('airplane wifi');
    await box.press('Enter');
    await page.waitForFunction(() => document.querySelector('form.composer [role=status]')?.textContent === 'delivered', null, { timeout: 8000 });
    assert.equal(ids.length, 2);
    assert.ok(ids[0] && ids[0] === ids[1]);
    assert.equal(await box.inputValue(), '');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a conversation expands to fill the window and back (button, f, Esc)', async () => {
  const { page, errors } = await setup(1500, 900, false);
  try {
    await page.goto(base + '#/agent/stoat');
    await page.waitForSelector('.thread');
    const history = page.locator('.thread .msgs').first();
    const before = (await history.boundingBox()).height;
    await page.locator('.thread-focus').first().click();
    assert.equal(await page.locator('.thread.focused').count(), 1);
    assert.ok((await history.boundingBox()).height > before + 200);
    const bubble = page.locator('.thread.focused .msg .bubble').first();
    const font = () => bubble.evaluate(e => getComputedStyle(e).fontSize);
    assert.equal(await font(), '16px');
    await page.getByRole('button', { name: 'Larger text' }).click();
    assert.equal(await font(), '18px');
    await page.getByRole('button', { name: 'Smaller text' }).click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.thread.focused').count(), 0);
    await page.keyboard.press('f');
    assert.equal(await page.locator('.thread.focused').count(), 1);
    // Typing "f" into the composer is text, not the shortcut.
    const box = page.locator('.thread.focused textarea').first();
    await box.focus();
    await page.keyboard.type('f');
    assert.equal(await box.inputValue(), 'f');
    assert.equal(await page.locator('.thread.focused').count(), 1);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('desktop: the roster runs to the top and the header stops at its edge', async () => {
  const { page, errors } = await setup(1500, 900, false);
  try {
    await page.goto(base + '#/agent/stoat');
    await page.waitForSelector('.roster-drawer.is-open');
    const roster = await page.locator('.roster-drawer').boundingBox();
    const header = await page.locator('header.top').boundingBox();
    assert.ok(roster.y <= 1);
    assert.ok(header.x + header.width <= roster.x + 1);
    // The roster's own "Hide →" closes it; the floating tab would cover content.
    assert.equal(await page.locator('.roster-toggle').isVisible(), false);
    await page.getByRole('button', { name: 'Hide agents' }).click();
    await page.locator('.roster-toggle').click();
    await page.waitForSelector('.roster-drawer.is-open');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('owner messages sit on the right of a 1:1 thread, the agent on the left', async () => {
  const { page, errors } = await setup(1500, 900, false);
  try {
    await page.goto(base + '#/agent/stoat');
    await page.waitForSelector('.thread .msg');
    const sides = await page.locator('.thread .msg').first().locator('..').locator('.msg').evaluateAll(els =>
      els.map(e => [e.querySelector('.tag').textContent.split('·')[0].trim(), e.classList.contains('right')]));
    assert.ok(sides.length >= 2);
    for (const [who, right] of sides) assert.equal(right, who === 'owner', `${who} on the wrong side`);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});
