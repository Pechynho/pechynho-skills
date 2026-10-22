// Tests of base/shared/browser-harness.mjs. Each test writes a scenario script that imports the harness,
// runs it with node against the fake Playwright in tests/fixtures/fake-playwright and checks result.json,
// the files in the run folder and the exit code. Run with: node --test tests/*.test.mjs

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const HERE = import.meta.dirname;
const ROOT = path.resolve(HERE, '..');
const HARNESS = path.join(ROOT, 'base', 'shared', 'browser-harness.mjs');
const FAKE = path.join(HERE, 'fixtures', 'fake-playwright');
const png = createRequire(import.meta.url)(path.join(FAKE, 'node_modules', 'playwright', 'png.js'));

const DESKTOP = { name: 'desktop', width: 1440, height: 900 };
const MOBILE = { name: 'mobile', width: 390, height: 844, mobile: true };
// The fake takes screenshots at 1/40 of the viewport.
const DESKTOP_SHOT = [36, 23];

function alive(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    return stat.slice(stat.lastIndexOf(')') + 2)[0] !== 'Z';
  } catch {
    try {
      process.kill(pid, 0);
      return true;
    } catch {
      return false;
    }
  }
}

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bt-harness-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

/**
 * Runs one scenario script and returns its exit code, output, result.json, run folder and fake browser events.
 * body is the code inside run(async ({ page, url, step, check, shot, note, ... }) => { body }).
 */
async function scenario(t, body, {
  options = null, site = {}, viewports = [DESKTOP], baselines = null, env = {}, name = 'S1', cwd = null,
  playwrightFrom = FAKE, raw = null,
} = {}) {
  const dir = tempDir(t);
  fs.copyFileSync(HARNESS, path.join(dir, 'harness.mjs'));
  fs.mkdirSync(path.join(dir, 'scenarios'));
  const script = path.join(dir, 'scenarios', `${name}.mjs`);
  fs.writeFileSync(script, raw ?? [
    "import { run } from '../harness.mjs';",
    'await run(async (t) => {',
    '  const { page, url, step, check, shot, note } = t;',
    body,
    `}${options ? `, ${options}` : ''});`,
    '',
  ].join('\n'));
  const out = path.join(dir, 'out');
  const events = path.join(dir, 'events.jsonl');
  const childEnv = {
    ...process.env, BT_OUT: out, BT_BASE_URL: 'http://app.test', BT_VIEWPORTS: JSON.stringify(viewports),
    BT_PLAYWRIGHT_FROM: playwrightFrom, FAKE_PW_SITE: JSON.stringify(site), FAKE_PW_LOG: events, ...env,
  };
  if (baselines) childEnv.BT_BASELINES = JSON.stringify(baselines);
  for (const key of Object.keys(childEnv)) if (childEnv[key] === undefined) delete childEnv[key];
  const child = spawn(process.execPath, [script], { cwd: cwd ?? dir, env: childEnv });
  let output = '';
  child.stdout.on('data', (d) => { output += d; });
  child.stderr.on('data', (d) => { output += d; });
  const code = await new Promise((resolve) => child.on('close', resolve));
  const resultFile = path.join(out, 'result.json');
  const result = fs.existsSync(resultFile) ? JSON.parse(fs.readFileSync(resultFile, 'utf8')) : null;
  const log = fs.existsSync(events)
    ? fs.readFileSync(events, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line)) : [];
  return { code, output, result, out, dir, log };
}

const OK_SITE = { '/ok': { title: 'Orders', text: ['Hello', 'Add'], selectors: ['#list'], links: { Add: '/added' } },
  '/added': { text: ['New order'] } };

describe('result.json and exit code', () => {
  test('a passing scenario writes the full result shape and exits 0', async (t) => {
    const r = await scenario(t, `
      await step('open', () => page.goto(url('/ok')));
      await check('greeting', page.getByText('Hello'));
    `, { site: OK_SITE, env: { BT_SCENARIO: 'ORD-1' } });
    assert.equal(r.code, 0, r.output);
    const res = r.result;
    assert.equal(res.status, 'passed');
    assert.equal(res.scenario, 'ORD-1');
    assert.equal(res.base_url, 'http://app.test');
    assert.equal(res.browser, 'chromium');
    assert.deepEqual(res.viewports, [DESKTOP]);
    assert.equal(res.per_viewport, false);
    assert.ok(!Number.isNaN(Date.parse(res.started_at)));
    assert.equal(typeof res.duration_ms, 'number');
    assert.equal(res.steps.length, 1);
    assert.equal(res.steps[0].name, 'open');
    assert.equal(res.steps[0].status, 'ok');
    assert.equal(typeof res.steps[0].ms, 'number');
    assert.deepEqual(res.checks, [{ name: 'greeting', ok: true, detail: null, step: null }]);
    assert.deepEqual(res.automatic.map((c) => [c.name, c.ok]), [
      ['no uncaught page errors', true], ['no console errors', true], ['no HTTP 5xx responses', true]]);
    for (const key of ['console', 'page_errors', 'http', 'request_failed', 'shots', 'notes']) assert.deepEqual(res[key], [], key);
    assert.equal(res.error, null);
    assert.equal(res.failure_shot, null);
    assert.ok(!fs.existsSync(path.join(r.out, 'failure.png')));
    assert.ok(fs.statSync(path.join(r.out, 'shots')).isDirectory());
  });

  test('the scenario name defaults to the script name', async (t) => {
    const r = await scenario(t, '', { name: 'CHK-7', env: { BT_SCENARIO: undefined } });
    assert.equal(r.result.scenario, 'CHK-7');
  });

  test('pids.json names the node and the browser process, and the browser is closed afterwards', async (t) => {
    const r = await scenario(t, "await page.goto(url('/ok'));", { site: OK_SITE });
    const pids = JSON.parse(fs.readFileSync(path.join(r.out, 'pids.json'), 'utf8'));
    assert.equal(typeof pids.node, 'number');
    assert.equal(typeof pids.browser, 'number');
    assert.notEqual(pids.node, pids.browser);
    assert.equal(alive(pids.browser), false, 'browser process left running');
    const launch = r.log.find((e) => e.event === 'launch');
    assert.equal(launch.headless, true, 'browsers always run headless');
    assert.equal(launch.pid, pids.browser);
    assert.ok(r.log.some((e) => e.event === 'close'));
  });

  test('BT_BROWSER selects the browser type', async (t) => {
    const r = await scenario(t, '', { env: { BT_BROWSER: 'firefox' } });
    assert.equal(r.result.browser, 'firefox');
    assert.equal(r.log.find((e) => e.event === 'launch').browser, 'firefox');
  });

  test('the script gets url(), note(), out, scenario, baseUrl, viewport, page, context and browser', async (t) => {
    const r = await scenario(t, `
      await check.equal('absolute path', url('/orders?x=1'), 'http://app.test/orders?x=1');
      await check.equal('relative path', url('orders'), 'http://app.test/base/orders');
      await check.equal('root', url(), 'http://app.test/');
      await check.equal('out', t.out, process.env.BT_OUT);
      await check.equal('scenario', t.scenario, 'S1');
      await check.equal('base url', t.baseUrl, 'http://app.test/base/');
      await check.equal('viewport', t.viewport.name, 'desktop');
      await check('objects', t.page && t.context && t.browser);
      note('created order 123');
      note(42);
    `, { env: { BT_BASE_URL: 'http://app.test/base/' } });
    assert.equal(r.result.status, 'passed', JSON.stringify(r.result.checks));
    assert.deepEqual(r.result.notes, ['created order 123', '42']);
  });
});

describe('step', () => {
  test('returns the value of its function and records nested steps', async (t) => {
    const r = await scenario(t, `
      const value = await step('outer', () => step('inner', async () => 7));
      await check.equal('value', value, 7);
    `);
    assert.equal(r.result.status, 'passed');
    assert.deepEqual(r.result.steps.map((s) => [s.name, s.status]), [['outer', 'ok'], ['inner', 'ok']]);
  });

  test('a throwing step fails the run with the first line of the error and the innermost step', async (t) => {
    const r = await scenario(t, `
      await step('open', () => page.goto(url('/ok')));
      await step('outer', () => step('inner', () => { throw new Error('\\nboom here\\nsecond line'); }));
      await step('never', () => {});
    `, { site: OK_SITE });
    assert.equal(r.code, 1);
    const res = r.result;
    assert.equal(res.status, 'failed');
    assert.deepEqual(res.error, { message: 'boom here', step: 'inner', check: false });
    assert.deepEqual(res.steps.map((s) => [s.name, s.status, s.error]),
      [['open', 'ok', undefined], ['outer', 'failed', 'boom here'], ['inner', 'failed', 'boom here']]);
    assert.equal(res.failure_shot, 'failure.png');
    assert.equal(res.failure_url, 'http://app.test/ok');
    const failure = png.decode(fs.readFileSync(path.join(r.out, 'failure.png')));
    assert.deepEqual([failure.width, failure.height], DESKTOP_SHOT);
  });

  test('an error outside any step is recorded without a step, also when it is not an Error', async (t) => {
    const r = await scenario(t, "await page.goto(url('/ok'));\nthrow 'plain text';", { site: OK_SITE });
    assert.equal(r.code, 1);
    assert.deepEqual(r.result.error, { message: 'plain text', step: null, check: false });
  });

  test('a failed navigation is a failure of its step', async (t) => {
    const r = await scenario(t, "await step('open', () => page.goto(url('/down')));",
      { site: { '/down': { gotoError: 'net::ERR_CONNECTION_REFUSED at http://app.test/down' } } });
    assert.equal(r.result.status, 'failed');
    assert.equal(r.result.error.step, 'open');
    assert.match(r.result.error.message, /ERR_CONNECTION_REFUSED/);
  });
});

describe('check', () => {
  test('a truthy value passes and a falsy value stops the scenario', async (t) => {
    const r = await scenario(t, `
      await check('truthy', 'yes');
      await step('verify', () => check('falsy', 0));
      await step('never', () => {});
    `);
    assert.equal(r.code, 1);
    assert.deepEqual(r.result.checks, [
      { name: 'truthy', ok: true, detail: null, step: null },
      { name: 'falsy', ok: false, detail: 'condition was false', step: 'verify' },
    ]);
    assert.equal(r.result.error.check, true);
    assert.equal(r.result.error.step, 'verify');
    assert.match(r.result.error.message, /check "falsy" failed: condition was false/);
    assert.ok(!r.result.steps.some((s) => s.name === 'never'));
  });

  test('a soft check records the failure, returns false and lets the scenario continue', async (t) => {
    const r = await scenario(t, `
      const ok = await check('soft one', false, { soft: true });
      await check.equal('soft returned false', ok, false);
      await step('after', () => {});
    `);
    assert.equal(r.code, 1);
    assert.equal(r.result.status, 'failed', 'a failed soft check still fails the scenario');
    assert.equal(r.result.error, null);
    assert.deepEqual(r.result.checks.map((c) => [c.name, c.ok]), [['soft one', false], ['soft returned false', true]]);
    assert.ok(r.result.steps.some((s) => s.name === 'after' && s.status === 'ok'));
  });

  test('a locator must become visible, also when a function returns it', async (t) => {
    const r = await scenario(t, `
      await page.goto(url('/ok'));
      await check('visible locator', page.getByText('Hello'));
      await check('locator from a function', () => page.locator('#list'));
      await check('hidden state', page.getByText('Missing'), { state: 'hidden' });
      await check('async function value', async () => (await page.title()) === 'Orders');
      await check('promise value', page.title());
    `, { site: OK_SITE });
    assert.equal(r.result.status, 'passed', JSON.stringify(r.result.checks));
    assert.ok(r.result.checks.every((c) => c.ok));
  });

  test('a missing locator fails with the timeout detail and the given timeout', async (t) => {
    const r = await scenario(t, `
      await page.goto(url('/ok'));
      await check('missing', page.getByText('Nope'), { timeout: 50, soft: true });
      await check('missing default', page.getByText('Nope'), { soft: true });
    `, { site: OK_SITE });
    const [a, b] = r.result.checks;
    assert.equal(a.ok, false);
    assert.match(a.detail, /Timeout 50ms exceeded/);
    assert.doesNotMatch(a.detail, /\n/, 'only the first line is kept');
    assert.match(b.detail, /Timeout 5000ms exceeded/, 'a check waits 5 s by default');
  });

  test('an error thrown by the condition fails the check with its first line', async (t) => {
    const r = await scenario(t, "await check('throws', () => { throw new Error('bad selector\\nmore'); }, { soft: true });");
    assert.deepEqual(r.result.checks[0], { name: 'throws', ok: false, detail: 'bad selector', step: null });
  });

  test('check.equal compares values as JSON and reports both', async (t) => {
    const r = await scenario(t, `
      await check.equal('objects', { a: [1, 2] }, { a: [1, 2] });
      await check.equal('function', async () => 3, 3);
      await check.equal('soft mismatch', 'x', 'y', { soft: true });
      await step('compare', () => check.equal('count', 2, 3));
      await step('never', () => {});
    `);
    assert.equal(r.code, 1);
    assert.deepEqual(r.result.checks, [
      { name: 'objects', ok: true, detail: null, step: null },
      { name: 'function', ok: true, detail: null, step: null },
      { name: 'soft mismatch', ok: false, detail: 'expected "y", got "x"', step: null },
      { name: 'count', ok: false, detail: 'expected 3, got 2', step: 'compare' },
    ]);
    assert.equal(r.result.error.check, true);
    assert.equal(r.result.error.step, 'compare');
    assert.ok(!r.result.steps.some((s) => s.name === 'never'));
  });
});

describe('automatic checks', () => {
  const NOISY = {
    '/noisy': {
      console: ['Boom in app.js', { type: 'warning', text: 'just a warning' }],
      pageErrors: ['Uncaught TypeError: x is undefined'],
      responses: [{ status: 500, url: '/api/orders', method: 'POST' }, { status: 404, url: '/favicon.ico' }],
      failedRequests: [{ url: '/img.png', errorText: 'net::ERR_CONNECTION_REFUSED' }, { url: '/x', errorText: 'net::ERR_ABORTED' }],
    },
  };

  test('console errors, page errors and 5xx responses fail the scenario and are recorded with their step', async (t) => {
    const r = await scenario(t, "await step('open', () => page.goto(url('/noisy')));", { site: NOISY });
    const res = r.result;
    assert.equal(r.code, 1);
    assert.equal(res.status, 'failed');
    assert.equal(res.error, null, 'no exception, only failed automatic checks');
    assert.deepEqual(res.console, [{ text: 'Boom in app.js', url: 'http://app.test/noisy', step: 'open' }]);
    assert.deepEqual(res.page_errors, [{ text: 'Uncaught TypeError: x is undefined', url: 'http://app.test/noisy', step: 'open' }]);
    assert.deepEqual(res.http, [
      { status: 500, method: 'POST', url: 'http://app.test/api/orders', step: 'open' },
      { status: 404, method: 'GET', url: 'http://app.test/favicon.ico', step: 'open' },
    ]);
    assert.deepEqual(res.request_failed, [{ url: 'http://app.test/img.png', failure: 'net::ERR_CONNECTION_REFUSED' }],
      'aborted requests are not failures');
    assert.deepEqual(res.automatic.map((c) => c.ok), [false, false, false]);
  });

  test('allowConsole and allowStatus tolerate expected errors; 4xx never fails', async (t) => {
    const site = { '/noisy': { ...NOISY['/noisy'], pageErrors: [] } };
    const r = await scenario(t, "await page.goto(url('/noisy'));",
      { site, options: '{ allowConsole: [/^Boom/], allowStatus: [500] }' });
    assert.equal(r.code, 0, JSON.stringify(r.result.automatic));
    assert.equal(r.result.status, 'passed');
    assert.equal(r.result.console.length, 1, 'tolerated errors are still recorded');
    assert.equal(r.result.http.length, 2);
  });
});

describe('shot', () => {
  const VIEWPORTS = [DESKTOP, MOBILE];

  test('takes one screenshot per viewport by resizing in place and restores the viewport', async (t) => {
    const r = await scenario(t, `
      await page.goto(url('/ok'));
      await step('look', () => shot('order list/main'));
      await check.equal('viewport restored', page.viewportSize(), { width: 1440, height: 900 });
    `, { site: OK_SITE, viewports: VIEWPORTS });
    assert.equal(r.result.status, 'passed', JSON.stringify(r.result.checks));
    assert.deepEqual(r.result.shots.map(({ layout, ...s }) => s), [
      { key: 'order list/main@desktop', name: 'order list/main', viewport: 'desktop', size: '1440x900', mobile: false,
        path: 'shots/order-list-main@desktop.png', step: 'look' },
      { key: 'order list/main@mobile', name: 'order list/main', viewport: 'mobile', size: '390x844', mobile: false,
        path: 'shots/order-list-main@mobile.png', step: 'look' },
    ]);
    const desktop = png.decode(fs.readFileSync(path.join(r.out, 'shots/order-list-main@desktop.png')));
    const mobile = png.decode(fs.readFileSync(path.join(r.out, 'shots/order-list-main@mobile.png')));
    assert.deepEqual([desktop.width, desktop.height], DESKTOP_SHOT);
    assert.deepEqual([mobile.width, mobile.height], [10, 22]);
    assert.equal(r.log.filter((e) => e.event === 'newContext').length, 1, 'the scenario is not repeated per viewport');
    assert.equal(r.log.filter((e) => e.event === 'goto').length, 1);
    const shots = r.log.filter((e) => e.event === 'screenshot');
    assert.ok(shots.every((s) => s.fullPage === true), 'full page by default');
  });

  test('viewports and fullPage options narrow the screenshots', async (t) => {
    const r = await scenario(t, `
      await page.goto(url('/ok'));
      await shot('only-mobile', { viewports: ['mobile'], fullPage: false });
    `, { site: OK_SITE, viewports: VIEWPORTS });
    assert.deepEqual(r.result.shots.map((s) => s.key), ['only-mobile@mobile']);
    assert.equal(r.log.find((e) => e.event === 'screenshot').fullPage, false);
  });

  test('layout hints name the elements causing overflow, broken images and clipped text', async (t) => {
    const site = {
      '/broken': {
        dom: {
          scrollWidth: 1700,
          elements: [
            { tag: 'main', id: 'page', right: 1700, width: 1700, children: [
              { tag: 'table', className: 'grid wide extra', text: 'Orders table', right: 1700, width: 1700 },
            ] },
            { tag: 'span', className: 'name', text: 'A very long customer name', overflowX: 'hidden', scrollWidth: 300, clientWidth: 120 },
            { tag: 'span', text: 'fits', overflowX: 'hidden', scrollWidth: 100, clientWidth: 100 },
          ],
          images: [{ attrs: { src: '/logo.png', alt: 'Logo' }, naturalWidth: 0 }, { attrs: { src: '/ok.png' } }],
        },
      },
    };
    const r = await scenario(t, "await page.goto(url('/broken'));\nawait shot('page');", { site });
    assert.equal(r.result.status, 'passed', 'layout hints are not verdicts');
    assert.deepEqual(r.result.shots[0].layout, [
      { kind: 'horizontal_overflow', detail: '1700px wide content in 1440px', elements: ['table.grid.wide "Orders table"'] },
      { kind: 'broken_image', detail: '1 image(s)', elements: ['img "Logo"'] },
      { kind: 'clipped_text', detail: '1+ element(s)', elements: ['span.name "A very long customer name"'] },
    ]);
  });

  test('a page without problems has no layout hints', async (t) => {
    const r = await scenario(t, "await page.goto(url('/ok'));\nawait shot('page');", { site: OK_SITE });
    assert.deepEqual(r.result.shots[0].layout, []);
  });
});

describe('perViewport', () => {
  test('repeats the scenario per viewport in a fresh context with mobile emulation for mobile viewports', async (t) => {
    const r = await scenario(t, `
      await step('open', () => page.goto(url('/ok')));
      await shot('home');
    `, { site: OK_SITE, viewports: [DESKTOP, MOBILE], options: '{ perViewport: true }' });
    const res = r.result;
    assert.equal(res.status, 'passed');
    assert.equal(res.per_viewport, true);
    assert.deepEqual(res.steps.map((s) => s.name), ['[desktop] open', '[mobile] open']);
    assert.deepEqual(res.shots.map((s) => [s.key, s.mobile, s.size]),
      [['home@desktop', false, '1440x900'], ['home@mobile', true, '390x844']]);
    const contexts = r.log.filter((e) => e.event === 'newContext').map((e) => e.options);
    assert.equal(contexts.length, 2);
    assert.deepEqual(contexts[0].viewport, { width: 1440, height: 900 });
    assert.equal(contexts[0].isMobile, undefined);
    assert.deepEqual(contexts[1].viewport, { width: 390, height: 844 });
    assert.equal(contexts[1].isMobile, true);
    assert.equal(contexts[1].hasTouch, true);
    assert.match(contexts[1].userAgent, /Mobile/);
  });

  test('without perViewport a mobile viewport only changes the size', async (t) => {
    const r = await scenario(t, "await page.goto(url('/ok'));\nawait shot('home');",
      { site: OK_SITE, viewports: [MOBILE, DESKTOP] });
    const contexts = r.log.filter((e) => e.event === 'newContext').map((e) => e.options);
    assert.equal(contexts.length, 1);
    assert.deepEqual(contexts[0].viewport, { width: 390, height: 844 }, 'the first viewport is the primary one');
    assert.equal(contexts[0].isMobile, undefined);
  });
});

describe('options', () => {
  test('prepare runs before and cleanup after the browser part, both as steps', async (t) => {
    const r = await scenario(t, "await step('body', () => note('body'));",
      { options: "{ prepare: async (t) => t.note('prepare ' + t.scenario), cleanup: async (t) => t.note('cleanup') }" });
    assert.equal(r.result.status, 'passed');
    assert.deepEqual(r.result.steps.map((s) => s.name), ['prepare', 'body', 'cleanup']);
    assert.deepEqual(r.result.notes, ['prepare S1', 'body', 'cleanup']);
  });

  test('cleanup runs after a failure, and a failing cleanup then leaves a note', async (t) => {
    const r = await scenario(t, "throw new Error('body failed');",
      { options: "{ prepare: async () => {}, cleanup: async (t) => t.note('cleanup ran') }" });
    assert.equal(r.result.status, 'failed');
    assert.deepEqual(r.result.notes, ['cleanup ran']);
    assert.equal(r.result.error.message, 'body failed');
    assert.deepEqual(r.result.steps.map((s) => [s.name, s.status]), [['prepare', 'ok'], ['cleanup', 'ok']]);

    const r2 = await scenario(t, "throw new Error('body failed');",
      { options: "{ prepare: async () => {}, cleanup: async () => { throw new Error('cannot delete'); } }" });
    assert.equal(r2.result.error.message, 'body failed', 'the original error is kept');
    assert.deepEqual(r2.result.notes, ['cleanup failed: cannot delete']);
  });

  test('cleanup without prepare also runs after a failure', async (t) => {
    const r = await scenario(t, "throw new Error('body failed');",
      { options: "{ cleanup: async (t) => t.note('cleanup ran') }" });
    assert.equal(r.result.status, 'failed');
    assert.deepEqual(r.result.notes, ['cleanup ran']);
  });

  test('a failing prepare skips the body and still runs cleanup', async (t) => {
    const r = await scenario(t, "note('body ran');",
      { options: "{ prepare: async () => { throw new Error('no data'); }, cleanup: async (t) => t.note('cleanup ran') }" });
    assert.equal(r.result.status, 'failed');
    assert.equal(r.result.error.step, 'prepare');
    assert.deepEqual(r.result.notes, ['cleanup ran']);
  });

  test('context options reach newContext and timeout sets the action timeout', async (t) => {
    const r = await scenario(t, '', { options: "{ context: { locale: 'cs-CZ', colorScheme: 'dark' }, timeout: 1234 }" });
    const ctx = r.log.find((e) => e.event === 'newContext').options;
    assert.equal(ctx.locale, 'cs-CZ');
    assert.equal(ctx.colorScheme, 'dark');
    assert.equal(ctx.baseURL, 'http://app.test');
    assert.deepEqual(r.log.filter((e) => e.event === 'setDefaultTimeout').map((e) => e.ms), [1234]);
    const r2 = await scenario(t, '');
    assert.deepEqual(r2.log.filter((e) => e.event === 'setDefaultTimeout').map((e) => e.ms), [10000], '10 s by default');
  });
});

describe('Playwright resolution', () => {
  test('without Playwright the run fails with a hint and still writes result.json', async (t) => {
    const empty = tempDir(t);
    const r = await scenario(t, "note('never');", { playwrightFrom: empty, cwd: empty });
    assert.equal(r.code, 1);
    assert.equal(r.result.status, 'failed');
    assert.match(r.result.error.message, /Playwright not found/);
    assert.match(r.result.error.message, /config --playwright/);
    assert.equal(r.result.failure_shot, null);
    assert.deepEqual(r.result.notes, []);
  });

  test('BT_PLAYWRIGHT_FROM is a path list and the current directory is tried last', async (t) => {
    const empty = tempDir(t);
    const listed = await scenario(t, '', { playwrightFrom: [empty, FAKE].join(path.delimiter), cwd: empty });
    assert.equal(listed.result.status, 'passed', listed.output);
    const fromCwd = await scenario(t, '', { playwrightFrom: '', cwd: FAKE });
    assert.equal(fromCwd.result.status, 'passed', fromCwd.output);
  });

  test('a browser that fails to launch fails the run', async (t) => {
    const r = await scenario(t, '', { env: { FAKE_PW_LAUNCH_ERROR: 'Executable doesn\'t exist at /ms-playwright/chromium' } });
    assert.equal(r.code, 1);
    assert.match(r.result.error.message, /Executable doesn't exist/);
  });
});

describe('screenshot differences', () => {
  const body = "await page.goto(url('/page'));\nawait shot('home');";

  function baseline(t, buffer) {
    const file = path.join(tempDir(t), 'baseline.png');
    fs.writeFileSync(file, buffer);
    return file;
  }

  test('an identical baseline gives a zero difference without a diff image', async (t) => {
    const file = baseline(t, png.solid(...DESKTOP_SHOT));
    const r = await scenario(t, body, { site: { '/page': {} }, baselines: { 'home@desktop': file } });
    assert.deepEqual(r.result.shots[0].diff, { ratio: 0, pixels: 0, baseline: file });
    assert.ok(!fs.existsSync(path.join(r.out, 'shots/home@desktop.diff.png')));
  });

  test('changed pixels are counted and painted red in a .diff.png', async (t) => {
    const file = baseline(t, png.solid(...DESKTOP_SHOT));
    const dots = [[0, 0, [255, 0, 0, 255]], [5, 3, [0, 0, 0, 255]], [35, 22, [0, 0, 255, 255]]];
    const r = await scenario(t, body, { site: { '/page': { dots } }, baselines: { 'home@desktop': file } });
    const diff = r.result.shots[0].diff;
    assert.equal(diff.pixels, 3);
    assert.equal(diff.ratio, 3 / (DESKTOP_SHOT[0] * DESKTOP_SHOT[1]));
    assert.equal(diff.baseline, file);
    assert.equal(diff.image, 'shots/home@desktop.diff.png');
    const image = png.decode(fs.readFileSync(path.join(r.out, diff.image)));
    const at = (x, y) => [...image.data.subarray((y * image.width + x) * 4, (y * image.width + x) * 4 + 4)];
    assert.deepEqual(at(5, 3), [255, 0, 0, 255]);
    assert.deepEqual(at(35, 22), [255, 0, 0, 255]);
    assert.notDeepEqual(at(1, 1), [255, 0, 0, 255], 'unchanged pixels are not red');
    assert.equal(r.result.status, 'passed', 'a difference is not a failure');
  });

  test('differences within the per-channel tolerance do not count', async (t) => {
    const file = baseline(t, png.solid(...DESKTOP_SHOT));
    const site = { '/page': { dots: [[1, 1, [240, 240, 240, 255]]] } };
    const within = await scenario(t, body, { site, baselines: { 'home@desktop': file } });
    assert.deepEqual(within.result.shots[0].diff, { ratio: 0, pixels: 0, baseline: file }, 'default tolerance is 24');
    const strict = await scenario(t, body, { site, baselines: { 'home@desktop': file }, env: { BT_DIFF_TOLERANCE: '10' } });
    assert.equal(strict.result.shots[0].diff.pixels, 1);
  });

  test('a different size is a full difference', async (t) => {
    const file = baseline(t, png.solid(10, 10));
    const r = await scenario(t, body, { site: { '/page': {} }, baselines: { 'home@desktop': file } });
    assert.deepEqual(r.result.shots[0].diff, { ratio: 1, size_changed: '10x10 -> 36x23', baseline: file });
  });

  test('a shot without an existing baseline gets no diff', async (t) => {
    const r = await scenario(t, body, { site: { '/page': {} }, baselines: { 'home@desktop': '/nonexistent/baseline.png', 'other@desktop': '/x.png' } });
    assert.equal(r.result.shots[0].diff, undefined);
  });

  test('a diff that cannot be computed leaves a note and does not fail the run', async (t) => {
    const file = baseline(t, Buffer.from('not an image'));
    const r = await scenario(t, body, { site: { '/page': {} }, baselines: { 'home@desktop': file } });
    assert.equal(r.result.status, 'passed');
    assert.match(r.result.notes.join('\n'), /^screenshot diff failed: /m);
  });

  test('screenshots of a failed run are diffed too', async (t) => {
    const file = baseline(t, png.solid(...DESKTOP_SHOT));
    const r = await scenario(t, body + "\nthrow new Error('later failure');",
      { site: { '/page': {} }, baselines: { 'home@desktop': file } });
    assert.equal(r.result.status, 'failed');
    assert.equal(r.result.shots[0].diff.ratio, 0);
  });
});

// One smoke test against a real Playwright installation, skipped when none can be resolved.
const realPlaywright = (() => {
  for (const base of [process.env.BT_REAL_PLAYWRIGHT_FROM, ROOT, process.cwd()].filter(Boolean)) {
    const require = createRequire(path.join(path.resolve(base), 'noop.js'));
    for (const name of ['playwright', 'playwright-core', '@playwright/test']) {
      try {
        require.resolve(name);
        return path.resolve(base);
      } catch { /* not here */ }
    }
  }
  return null;
})();

test('real Playwright smoke test', { skip: realPlaywright ? false : 'Playwright cannot be resolved' }, async (t) => {
  const r = await scenario(t, `
    await page.setContent('<h1>Hello</h1><div style="width:3000px">wide</div>');
    await check('heading', page.getByText('Hello'));
    await shot('page');
  `, { playwrightFrom: realPlaywright, viewports: [DESKTOP, MOBILE] });
  assert.equal(r.result.status, 'passed', r.output);
  assert.equal(r.result.shots.length, 2);
  assert.equal(r.result.shots[0].layout[0].kind, 'horizontal_overflow');
  const pids = JSON.parse(fs.readFileSync(path.join(r.out, 'pids.json'), 'utf8'));
  assert.equal(alive(pids.browser), false);
});
