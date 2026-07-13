import { performance } from 'node:perf_hooks';
import WebSocket from 'ws';

const targets = await fetch('http://127.0.0.1:9222/json').then((response) => response.json());
const target = targets.find((row) => row.type === 'page'
  && row.url?.startsWith('http://localhost:4200')
  && row.webSocketDebuggerUrl);
if (!target) throw new Error('No desktop page target found on port 9222.');

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.once('open', resolve);
  socket.once('error', reject);
});

let nextId = 1;
const observeCurrent = process.argv.includes('--observe-current');
const pending = new Map();
const consoleRows = [];
let captureConsole = observeCurrent;
let finishBoot;
const bootComplete = new Promise((resolve) => { finishBoot = resolve; });

socket.on('message', (raw) => {
  const message = JSON.parse(String(raw));
  if (message.id) {
    const callback = pending.get(message.id);
    if (!callback) return;
    pending.delete(message.id);
    callback(message);
    return;
  }
  if (message.method !== 'Runtime.consoleAPICalled') return;
  if (!captureConsole) return;
  const text = (message.params?.args || [])
    .map((arg) => String(arg.value ?? arg.description ?? ''))
    .join(' ');
  consoleRows.push({ at: performance.now(), browserAt: message.params?.timestamp, text });
  if (text.includes('Boot step -> background:complete')) finishBoot();
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

await call('Runtime.enable');
await call('Page.enable');
let started = performance.now();
if (!observeCurrent) {
  captureConsole = true;
  started = performance.now();
  await call('Page.reload', { ignoreCache: true });
}
let bootTimeout;
await Promise.race([
  bootComplete,
  new Promise((_, reject) => {
    bootTimeout = setTimeout(() => reject(new Error('Desktop boot timeout')), 30_000);
  }),
]);
clearTimeout(bootTimeout);

const browserStarted = consoleRows.find(({ text }) => text.includes('Starting orchestrated boot'))?.browserAt;
const elapsed = (pattern) => {
  const row = consoleRows.find(({ text }) => text.includes(pattern));
  if (!row) return null;
  const duration = observeCurrent && browserStarted && row.browserAt
    ? row.browserAt - browserStarted
    : row.at - started;
  return Math.round(duration * 10) / 10;
};
const nativeLoad = consoleRows.find(({ text }) => text.includes('initialize:native.load:complete'))?.text ?? null;
const entityReads = consoleRows.find(({ text }) => text.includes('relation:list:entities'))?.text ?? null;
const maintenance = consoleRows.find(({ text }) => text.includes('Native store maintenance:'))?.text ?? null;

socket.close();
console.log(JSON.stringify({
  cachedShellMs: elapsed('Cached no-note shell revealed'),
  appReadyMs: elapsed('App interactive in'),
  backgroundCompleteMs: elapsed('Boot step -> background:complete'),
  nativeLoad,
  entityReads,
  maintenance,
  mode: observeCurrent ? 'process-boot' : 'webview-refresh',
}));
