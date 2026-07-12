import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import WebSocket from 'ws';

const args = parseArgs(process.argv.slice(2));
if (args.documents.length !== 2) {
  throw new Error('Pass exactly two --document paths.');
}

const documents = await Promise.all(args.documents.map(async (path, index) => ({
  title: args.titles[index] || `Benchmark document ${index + 1}`,
  text: await readFile(resolve(path), 'utf8'),
})));
const target = await waitForTarget(args.port);
const cdp = await connectCdp(target.webSocketDebuggerUrl);

try {
  await cdp.call('Page.enable');
  await cdp.call('Runtime.enable');
  await cdp.call('Page.navigate', { url: `http://127.0.0.1:4200/?graphPerf=1` });
  await waitForHarness(cdp);
  const expression = `window.__PHOENIX_GRAPH_BUILD_BASELINE__.run(${JSON.stringify({
    documents,
    warmForceRuns: args.warmRuns,
    deltaRuns: args.deltaRuns,
  })})`;
  const response = await cdp.call('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  }, 10 * 60 * 1000);
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
  }
  const report = response.result?.value;
  if (!report?.schemaVersion) throw new Error('Desktop baseline returned no certificate.');
  const output = resolve(args.output);
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(`[graph-desktop-baseline] wrote ${output}`);
  console.log(JSON.stringify({ summary: report.summary, parity: report.parity }, null, 2));
} finally {
  cdp.close();
}

function parseArgs(argv) {
  const result = {
    documents: [], titles: [], port: 9222, warmRuns: 10, deltaRuns: 10,
    output: 'target/graph-build-baselines/two-document-desktop.json',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--document') result.documents.push(argv[++index]);
    else if (value === '--title') result.titles.push(argv[++index]);
    else if (value === '--port') result.port = Number(argv[++index]);
    else if (value === '--warm-runs') result.warmRuns = Number(argv[++index]);
    else if (value === '--delta-runs') result.deltaRuns = Number(argv[++index]);
    else if (value === '--output') result.output = argv[++index];
    else throw new Error(`Unknown argument: ${value}`);
  }
  return result;
}

async function waitForTarget(port) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const targets = await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json());
      const target = targets.find((row) => row.type === 'page' && row.webSocketDebuggerUrl);
      if (target) return target;
    } catch { /* desktop shell is still starting */ }
    await sleep(250);
  }
  throw new Error(`No WebView2 CDP target found on port ${port}.`);
}

async function waitForHarness(cdp) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const response = await cdp.call('Runtime.evaluate', {
      expression: 'Boolean(window.__PHOENIX_GRAPH_BUILD_BASELINE__)',
      returnByValue: true,
    });
    if (response.result?.value === true) return;
    await sleep(250);
  }
  throw new Error('Desktop graph baseline harness did not become ready.');
}

async function connectCdp(url) {
  const socket = new WebSocket(url);
  await new Promise((resolveOpen, reject) => {
    socket.once('open', resolveOpen);
    socket.once('error', reject);
  });
  let nextId = 1;
  const pending = new Map();
  socket.on('message', (raw) => {
    const message = JSON.parse(String(raw));
    if (!message.id || !pending.has(message.id)) return;
    const { resolve: resolveCall, reject, timer } = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(timer);
    if (message.error) reject(new Error(message.error.message));
    else resolveCall(message.result || {});
  });
  return {
    call(method, params = {}, timeoutMs = 30_000) {
      const id = nextId++;
      return new Promise((resolveCall, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`CDP timeout: ${method}`));
        }, timeoutMs);
        pending.set(id, { resolve: resolveCall, reject, timer });
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    close() { socket.close(); },
  };
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}
