import WebSocket from 'ws';

const AUTHORITY_KEY = 'phoenix.graph.rendererAuthority.v3';
const targets = await fetch('http://127.0.0.1:9222/json').then((response) => response.json());
const target = targets.find((row) => row.type === 'page'
  && row.url?.startsWith('http://localhost:4200')
  && row.webSocketDebuggerUrl);
if (!target) throw new Error('No Phoenix Desktop page target found on port 9222.');

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.once('open', resolve);
  socket.once('error', reject);
});

let nextId = 1;
const pending = new Map();
socket.on('message', (raw) => {
  const message = JSON.parse(String(raw));
  if (!message.id) return;
  const callback = pending.get(message.id);
  if (!callback) return;
  pending.delete(message.id);
  callback(message);
});

function call(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 30_000);
    pending.set(id, (message) => {
      clearTimeout(timer);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    });
  });
}

async function evaluate(expression) {
  const response = await call('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.exception?.description || 'Runtime evaluation failed.');
  }
  return response.result?.value;
}

async function waitFor(expression, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const value = await evaluate(expression);
      if (value) return value;
    } catch {
      // A reload can briefly destroy the execution context.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function openGraphSurface() {
  await waitFor('document.readyState === "complete"');
  await waitFor(`Boolean(window.ng?.getComponent?.(document.querySelector('app-hub-footer')))`);
  await evaluate(`(() => {
    const footer = document.querySelector('app-hub-footer');
    const component = window.ng?.getComponent?.(footer);
    if (component?.hubService?.openPage) {
      component.hubService.openPage('graph');
      const hub = window.ng?.getComponent?.(document.querySelector('app-blueprint-hub'));
      if (hub) window.ng?.applyChanges?.(hub);
      return true;
    }
    if (document.querySelector('app-graph-atlas-preview')) return true;
    const hub = [...document.querySelectorAll('button')]
      .find((candidate) => /\\bHub\\b/i.test(candidate.textContent || '') && candidate.offsetParent !== null);
    hub?.click();
    return true;
  })()`);
  await waitFor(`[...document.querySelectorAll('button')]
    .some((candidate) => candidate.textContent?.trim() === 'Graph' && candidate.offsetParent !== null)`);
  await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')]
      .find((candidate) => candidate.textContent?.trim() === 'Graph' && candidate.offsetParent !== null);
    button?.click();
    return true;
  })()`);
  await waitFor('document.querySelector("app-graph-galaxy-canvas") || document.querySelector("app-graph-galaxy-canvas-v3")', 60_000);
}

async function selectAuthority(authority) {
  await evaluate(`localStorage.setItem(${JSON.stringify(AUTHORITY_KEY)}, ${JSON.stringify(authority)})`);
  await call('Page.reload', { ignoreCache: true });
  await openGraphSurface();
}

async function surfaceState() {
  return evaluate(`(() => {
    const legacy = document.querySelectorAll('app-graph-galaxy-canvas').length;
    const v3 = document.querySelector('app-graph-galaxy-canvas-v3');
    return {
      legacy,
      v3: v3 ? 1 : 0,
      status: v3?.getAttribute('data-v3-status') || '',
      failure: v3?.getAttribute('data-v3-failure') || '',
      resident: Number(v3?.getAttribute('data-v3-resident') || 0),
      shadow: v3?.getAttribute('data-v3-shadow') || '',
    };
  })()`);
}

await call('Runtime.enable');
await call('Page.enable');

const setOnly = process.argv.find((argument) => argument.startsWith('--set='))?.slice('--set='.length);
if (setOnly) {
  if (!['legacy-visible', 'v3-shadow', 'v3-visible'].includes(setOnly)) {
    throw new Error(`Unknown renderer authority: ${setOnly}`);
  }
  await evaluate(`localStorage.setItem(${JSON.stringify(AUTHORITY_KEY)}, ${JSON.stringify(setOnly)})`);
  await call('Page.reload', { ignoreCache: true });
  socket.close();
  console.log(JSON.stringify({ authority: setOnly, reloaded: true }));
  process.exit(0);
}

if (process.argv.includes('--visible-smoke')) {
  let visible;
  try {
    await evaluate(`(() => {
      const url = new URL(location.href);
      url.searchParams.set('graphRenderer', 'v3-visible');
      history.replaceState(null, '', url);
      return true;
    })()`);
    await call('Page.reload', { ignoreCache: true });
    await openGraphSurface();
    await waitFor(`(() => {
      const host = document.querySelector('app-graph-galaxy-canvas-v3');
      return ['first-pixel', 'failed'].includes(host?.getAttribute('data-v3-status'));
    })()`, 60_000);
    visible = await surfaceState();
    if (visible.legacy !== 0 || visible.v3 !== 1) {
      throw new Error(`Visible authority isolation drifted: ${JSON.stringify(visible)}`);
    }
    if (visible.status !== 'first-pixel' || visible.failure || visible.resident <= 0) {
      throw new Error(`Visible renderer failed its readiness gate: ${JSON.stringify(visible)}`);
    }
  } finally {
    await evaluate(`(() => {
      localStorage.setItem(${JSON.stringify(AUTHORITY_KEY)}, 'legacy-visible');
      const url = new URL(location.href);
      url.searchParams.delete('graphRenderer');
      history.replaceState(null, '', url);
      return true;
    })()`);
    await call('Page.reload', { ignoreCache: true });
    socket.close();
  }
  console.log(JSON.stringify({ visible }, null, 2));
  process.exit(0);
}

if (process.argv.includes('--diagnose')) {
  if (process.argv.includes('--open')) {
    await evaluate(`(() => {
      const component = window.ng?.getComponent?.(document.querySelector('app-hub-footer'));
      component?.hubService?.openPage?.('graph');
      const hub = window.ng?.getComponent?.(document.querySelector('app-blueprint-hub'));
      if (hub) window.ng?.applyChanges?.(hub);
      return true;
    })()`);
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  console.log(JSON.stringify(await evaluate(`(() => ({
    ready: document.readyState,
    angularDebug: typeof window.ng,
    footer: Boolean(document.querySelector('app-hub-footer')),
    footerComponent: Boolean(window.ng?.getComponent?.(document.querySelector('app-hub-footer'))),
    tags: [...new Set([...document.querySelectorAll('*')]
      .map((element) => element.tagName.toLowerCase())
      .filter((tag) => tag.startsWith('app-graph') || tag.startsWith('app-blueprint')))],
    buttons: [...document.querySelectorAll('button')]
      .map((button) => ({ text: button.textContent?.trim(), title: button.title, aria: button.getAttribute('aria-label') }))
      .filter((button) => /graph|hub/i.test([button.text, button.title, button.aria].join(' '))),
  }))()`), null, 2));
  socket.close();
  process.exit(0);
}

let result;
try {
  await selectAuthority('legacy-visible');
  const legacy = await surfaceState();
  if (legacy.legacy !== 1 || legacy.v3 !== 0) {
    throw new Error(`Legacy authority drifted: ${JSON.stringify(legacy)}`);
  }

  await selectAuthority('v3-shadow');
  await waitFor(`(() => {
    const host = document.querySelector('app-graph-galaxy-canvas-v3');
    return ['first-pixel', 'failed'].includes(host?.getAttribute('data-v3-status'));
  })()`, 60_000);
  const shadow = await surfaceState();
  if (shadow.legacy !== 1 || shadow.v3 !== 1 || shadow.shadow !== 'true') {
    throw new Error(`Shadow isolation drifted: ${JSON.stringify(shadow)}`);
  }
  if (shadow.status !== 'first-pixel' || shadow.failure || shadow.resident <= 0) {
    throw new Error(`Shadow renderer failed its readiness gate: ${JSON.stringify(shadow)}`);
  }
  result = { legacy, shadow };
} finally {
  await evaluate(`localStorage.setItem(${JSON.stringify(AUTHORITY_KEY)}, 'legacy-visible')`);
  await call('Page.reload', { ignoreCache: true });
  socket.close();
}

console.log(JSON.stringify(result, null, 2));
