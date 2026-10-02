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
    await page.getByRole('combobox', { name: 'Assign task #73' }).selectOption('t:1');
    await page.waitForFunction(() => document.querySelector('.hive-task-detail p').textContent.includes('team agent-swarm'));
    await page.getByRole('combobox', { name: 'Assign task #73' }).selectOption('ferret');
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
    await page.waitForSelector('.scope');
    const composer = page.locator('.scope .composer');
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
