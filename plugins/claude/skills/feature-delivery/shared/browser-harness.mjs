// Harness for one click-through scenario run by browser.py; see shared/browser-tool.md.
//
// A scenario script lives in the testing folder as scenarios/{ID}.mjs and starts with
//
//   import { run } from '../harness.mjs';
//   await run(async ({ page, url, step, check, shot }) => { ... });
//
// browser.py passes the settings through BT_* environment variables, collects result.json and the
// screenshots from BT_OUT and kills what is left of the browser. Node 18+, Playwright resolved from the
// project or the testing folder; no other dependencies.

import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const env = process.env;
const OUT = path.resolve(env.BT_OUT || 'out');
const SCENARIO = env.BT_SCENARIO || path.basename(process.argv[1] || 'scenario', '.mjs');
const BASE_URL = env.BT_BASE_URL || '';
const VIEWPORTS = JSON.parse(env.BT_VIEWPORTS || '[{"name":"desktop","width":1440,"height":900}]');
const BASELINES = JSON.parse(env.BT_BASELINES || '{}');
const DIFF_TOLERANCE = Number(env.BT_DIFF_TOLERANCE || 24);
const BROWSER = env.BT_BROWSER || 'chromium';
const MOBILE_UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

class CheckFailed extends Error {}

function firstLine(error) {
  return String(error?.message ?? error).split('\n').find((line) => line.trim()) ?? 'error';
}

function writeJson(file, data) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n');
  fs.renameSync(tmp, file);
}

function loadPlaywright() {
  const bases = [...(env.BT_PLAYWRIGHT_FROM || '').split(path.delimiter).filter(Boolean), process.cwd()];
  for (const base of bases) {
    const require = createRequire(path.join(path.resolve(base), 'noop.js'));
    for (const name of ['playwright', 'playwright-core', '@playwright/test']) {
      try {
        return require(name);
      } catch (error) {
        if (error.code !== 'MODULE_NOT_FOUND') throw error;
      }
    }
  }
  throw new Error(`Playwright not found from ${bases.join(', ')}; set it with browser.py config --playwright DIR`);
}

function safeName(name) {
  return String(name).replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'shot';
}

// Runs in the page: layout problems a reviewer should look at, not verdicts.
function layoutProbe() {
  const describe = (el) => {
    const id = el.id ? `#${el.id}` : '';
    const cls = typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    const text = (el.innerText || el.getAttribute('alt') || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return `${el.tagName.toLowerCase()}${id}${cls}${text ? ` "${text}"` : ''}`;
  };
  const out = [];
  const doc = document.scrollingElement || document.documentElement;
  const width = doc.clientWidth;
  if (doc.scrollWidth > width + 1) {
    const offenders = [];
    for (const el of document.body.querySelectorAll('*')) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.right <= width + 1) continue;
      if ([...el.children].some((child) => child.getBoundingClientRect().right > width + 1)) continue;
      offenders.push(describe(el));
      if (offenders.length === 5) break;
    }
    out.push({ kind: 'horizontal_overflow', detail: `${doc.scrollWidth}px wide content in ${width}px`, elements: offenders });
  }
  const broken = [...document.images].filter((img) => img.complete && img.naturalWidth === 0 && img.getAttribute('src'));
  if (broken.length) out.push({ kind: 'broken_image', detail: `${broken.length} image(s)`, elements: broken.slice(0, 5).map(describe) });
  const clipped = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!el.childNodes.length || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    const style = getComputedStyle(el);
    if (!/hidden|clip/.test(style.overflowX) && style.textOverflow !== 'ellipsis') continue;
    if (el.scrollWidth > el.clientWidth + 1) clipped.push(describe(el));
    if (clipped.length === 5) break;
  }
  if (clipped.length) out.push({ kind: 'clipped_text', detail: `${clipped.length}+ element(s)`, elements: clipped });
  return out;
}

async function settle(page) {
  await page.evaluate(() => (document.fonts ? document.fonts.ready : Promise.resolve())
    .then(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
}

// Compares each screenshot with its judged baseline inside the browser, so no image library is needed.
async function diffShots(browser, result) {
  let page = null;
  for (const shot of result.shots) {
    const baseline = BASELINES[shot.key];
    if (!baseline || !fs.existsSync(baseline)) continue;
    const before = fs.readFileSync(baseline);
    const after = fs.readFileSync(path.join(OUT, shot.path));
    if (before.equals(after)) {
      shot.diff = { ratio: 0, pixels: 0, baseline };
      continue;
    }
    page ??= await browser.newPage();
    const diff = await page.evaluate(async ({ a, b, tolerance }) => {
      const load = (b64) => createImageBitmap(new Blob([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], { type: 'image/png' }));
      const [ia, ib] = await Promise.all([load(a), load(b)]);
      if (ia.width !== ib.width || ia.height !== ib.height) {
        return { ratio: 1, size_changed: `${ia.width}x${ia.height} -> ${ib.width}x${ib.height}` };
      }
      const canvas = new OffscreenCanvas(ia.width, ia.height);
      const g = canvas.getContext('2d', { willReadFrequently: true });
      g.drawImage(ia, 0, 0);
      const da = g.getImageData(0, 0, ia.width, ia.height).data;
      g.clearRect(0, 0, ia.width, ia.height);
      g.drawImage(ib, 0, 0);
      const image = g.getImageData(0, 0, ia.width, ia.height);
      const db = image.data;
      let changed = 0;
      for (let i = 0; i < db.length; i += 4) {
        const delta = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]),
          Math.abs(da[i + 2] - db[i + 2]), Math.abs(da[i + 3] - db[i + 3]));
        if (delta > tolerance) {
          changed++;
          db[i] = 255; db[i + 1] = 0; db[i + 2] = 0; db[i + 3] = 255;
        } else {
          const grey = 0.3 * db[i] + 0.59 * db[i + 1] + 0.11 * db[i + 2];
          db[i] = db[i + 1] = db[i + 2] = 200 + grey / 5;
        }
      }
      if (!changed) return { ratio: 0, pixels: 0 };
      g.putImageData(image, 0, 0);
      const blob = await canvas.convertToBlob({ type: 'image/png' });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return { ratio: changed / (db.length / 4), pixels: changed, image: btoa(binary) };
    }, { a: before.toString('base64'), b: after.toString('base64'), tolerance: DIFF_TOLERANCE });
    if (diff.image) {
      const file = shot.path.replace(/\.png$/, '.diff.png');
      fs.writeFileSync(path.join(OUT, file), Buffer.from(diff.image, 'base64'));
      diff.image = file;
    }
    shot.diff = { ...diff, baseline };
  }
  if (page) await page.close();
}

/**
 * Runs one scenario: launches a headless browser, records steps, checks, console errors, failed
 * requests and screenshots, writes result.json and sets the exit code (0 passed, 1 failed).
 *
 * options: prepare(t) and cleanup(t) around each browser pass, context (newContext options),
 * timeout (action timeout in ms, default 10000), allowConsole (RegExp[] of tolerated console errors),
 * allowStatus (HTTP statuses >= 500 that are expected), perViewport (repeat the scenario in a fresh
 * context per viewport, with touch and a mobile user agent for viewports marked mobile, for apps that
 * detect the device on load or on the server).
 */
export async function run(body, options = {}) {
  fs.mkdirSync(path.join(OUT, 'shots'), { recursive: true });
  const started = Date.now();
  const result = {
    scenario: SCENARIO, status: 'running', started_at: new Date(started).toISOString(), base_url: BASE_URL,
    browser: BROWSER, viewports: VIEWPORTS, per_viewport: Boolean(options.perViewport), steps: [], checks: [],
    automatic: [], console: [], page_errors: [], http: [], request_failed: [], shots: [], notes: [], error: null,
    failure_shot: null,
  };
  let server = null;
  let browser = null;
  let context = null;
  let page = null;
  let currentStep = null;
  let passViewports = VIEWPORTS;
  let prefix = '';

  const url = (target = '/') => new URL(target, BASE_URL || undefined).toString();

  async function step(name, fn) {
    const record = { name: prefix + name, status: 'running' };
    result.steps.push(record);
    const parent = currentStep;
    currentStep = record.name;
    const t0 = Date.now();
    try {
      const value = await fn();
      record.status = 'ok';
      return value;
    } catch (error) {
      record.status = 'failed';
      record.error = firstLine(error);
      // The innermost step is kept on the error, because currentStep is restored before run() sees it.
      if (error && typeof error === 'object' && !error.btStep) error.btStep = record.name;
      throw error;
    } finally {
      record.ms = Date.now() - t0;
      currentStep = parent;
    }
  }

  // check(name, locator | function | value, { state, timeout, soft }): a locator, also one returned by
  // the function, must reach the state (visible by default); any other value must be truthy. A failed
  // check stops the scenario unless it is soft.
  async function check(name, condition, opts = {}) {
    let ok = false;
    let detail = null;
    try {
      let value = typeof condition === 'function' ? await condition() : await condition;
      if (value && typeof value.waitFor === 'function') {
        await value.first().waitFor({ state: opts.state ?? 'visible', timeout: opts.timeout ?? 5000 });
        value = true;
      }
      ok = Boolean(value);
      if (!ok) detail = 'condition was false';
    } catch (error) {
      detail = firstLine(error);
    }
    result.checks.push({ name, ok, detail, step: currentStep });
    if (!ok && !opts.soft) throw new CheckFailed(`check "${name}" failed: ${detail}`);
    return ok;
  }
  check.equal = async (name, actual, expected, opts = {}) => {
    const value = typeof actual === 'function' ? await actual() : await actual;
    const ok = JSON.stringify(value) === JSON.stringify(expected);
    result.checks.push({ name, ok, detail: ok ? null : `expected ${JSON.stringify(expected)}, got ${JSON.stringify(value)}`, step: currentStep });
    if (!ok && !opts.soft) throw new CheckFailed(`check "${name}" failed`);
    return ok;
  };

  // shot(name, { viewports, fullPage, mask }): one screenshot per viewport of the pass, resized in
  // place so the scenario is not repeated; layout problems found in the page are attached.
  async function shot(name, opts = {}) {
    const wanted = opts.viewports ? passViewports.filter((v) => opts.viewports.includes(v.name)) : passViewports;
    const original = page.viewportSize();
    for (const viewport of wanted) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await settle(page);
      const file = `shots/${safeName(name)}@${viewport.name}.png`;
      await page.screenshot({ path: path.join(OUT, file), fullPage: opts.fullPage ?? true, animations: 'disabled', caret: 'hide', mask: opts.mask });
      const layout = await page.evaluate(layoutProbe).catch((error) => [{ kind: 'probe_error', detail: firstLine(error) }]);
      result.shots.push({ key: `${name}@${viewport.name}`, name, viewport: viewport.name, size: `${viewport.width}x${viewport.height}`, mobile: Boolean(viewport.mobile && options.perViewport), path: file, layout, step: currentStep });
    }
    if (original) await page.setViewportSize(original);
  }

  async function openPage(viewport) {
    const emulation = options.perViewport && viewport.mobile ? { isMobile: true, hasTouch: true, userAgent: MOBILE_UA } : {};
    context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, baseURL: BASE_URL || undefined, ...emulation, ...options.context });
    page = await context.newPage();
    page.setDefaultTimeout(options.timeout ?? 10000);
    page.on('console', (msg) => {
      if (msg.type() === 'error') result.console.push({ text: msg.text().slice(0, 500), url: page.url(), step: currentStep });
    });
    page.on('pageerror', (error) => result.page_errors.push({ text: firstLine(error), url: page.url(), step: currentStep }));
    page.on('response', (response) => {
      if (response.status() >= 400) result.http.push({ status: response.status(), method: response.request().method(), url: response.url().slice(0, 300), step: currentStep });
    });
    page.on('requestfailed', (request) => {
      const failure = request.failure()?.errorText ?? '';
      if (!/ERR_ABORTED|NS_BINDING_ABORTED/.test(failure)) result.request_failed.push({ url: request.url().slice(0, 300), failure });
    });
  }

  const t = { url, step, check, shot, out: OUT, scenario: SCENARIO, baseUrl: BASE_URL, viewport: VIEWPORTS[0], note: (text) => result.notes.push(String(text)) };
  const passes = options.perViewport ? VIEWPORTS.map((v) => [v]) : [VIEWPORTS];
  let prepared = false;
  try {
    const playwright = loadPlaywright();
    // A browser server exposes the browser's pid, so browser.py can kill a leftover browser after a crash.
    server = await playwright[BROWSER].launchServer({ headless: true });
    writeJson(path.join(OUT, 'pids.json'), { node: process.pid, browser: server.process().pid });
    browser = await playwright[BROWSER].connect(server.wsEndpoint());
    for (const viewports of passes) {
      passViewports = viewports;
      prefix = options.perViewport ? `[${viewports[0].name}] ` : '';
      if (options.prepare) {
        prepared = true;
        await step('prepare', () => options.prepare(t));
      }
      await openPage(viewports[0]);
      Object.assign(t, { page, context, browser, viewport: viewports[0] });
      await body(t);
      if (options.cleanup) {
        prepared = false;
        await step('cleanup', () => options.cleanup(t));
      }
      if (passes.length > 1) {
        await context.close();
        context = null;
      }
    }

    const allowConsole = options.allowConsole ?? [];
    const allowStatus = options.allowStatus ?? [];
    const consoleErrors = result.console.filter((c) => !allowConsole.some((re) => re.test(c.text)));
    const serverErrors = result.http.filter((h) => h.status >= 500 && !allowStatus.includes(h.status));
    result.automatic.push(
      { name: 'no uncaught page errors', ok: result.page_errors.length === 0 },
      { name: 'no console errors', ok: consoleErrors.length === 0 },
      { name: 'no HTTP 5xx responses', ok: serverErrors.length === 0 },
    );
    result.status = result.checks.some((c) => !c.ok) || result.automatic.some((c) => !c.ok) ? 'failed' : 'passed';
  } catch (error) {
    result.status = 'failed';
    result.error = { message: firstLine(error), step: error?.btStep ?? currentStep, check: error instanceof CheckFailed };
    if (page && context) {
      result.failure_shot = 'failure.png';
      result.failure_url = page.url();
      await page.screenshot({ path: path.join(OUT, 'failure.png'), fullPage: true }).catch(() => { result.failure_shot = null; });
    }
    if (prepared && options.cleanup) {
      await step('cleanup', () => options.cleanup(t)).catch((e) => result.notes.push(`cleanup failed: ${firstLine(e)}`));
    }
  } finally {
    if (browser) {
      await diffShots(browser, result).catch((error) => result.notes.push(`screenshot diff failed: ${firstLine(error)}`));
      await context?.close().catch(() => {});
      await browser.close().catch(() => {});
    }
    await server?.close().catch(() => {});
    result.duration_ms = Date.now() - started;
    writeJson(path.join(OUT, 'result.json'), result);
    process.exitCode = result.status === 'passed' ? 0 : 1;
  }
  return result;
}
