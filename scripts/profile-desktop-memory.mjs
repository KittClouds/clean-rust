import WebSocket from 'ws';

const collectGarbage = process.argv.includes('--gc');
const metricsOnly = process.argv.includes('--metrics-only');
const targetsUrl = 'http://127.0.0.1:9222/json';
const targets = await fetch(targetsUrl).then((response) => response.json());
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
const pending = new Map();
socket.on('message', (raw) => {
  const message = JSON.parse(String(raw));
  if (message.id) {
    const callback = pending.get(message.id);
    if (!callback) return;
    pending.delete(message.id);
    callback(message);
    return;
  }
});

function call(method, params = {}, timeoutMs = 30_000) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), timeoutMs);
    pending.set(id, (message) => {
      clearTimeout(timer);
      if (message.error) reject(new Error(`${method}: ${message.error.message}`));
      else resolve(message.result);
    });
  });
}

async function evaluate(expression) {
  const result = await call('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Runtime evaluation failed.');
  return result.result?.value;
}

async function queryObjects(prototypeExpression, functionDeclaration) {
  const prototype = await call('Runtime.evaluate', {
    expression: prototypeExpression,
    objectGroup: 'phoenix-memory-profile',
  });
  const prototypeObjectId = prototype.result?.objectId;
  if (!prototypeObjectId) return null;
  const queried = await call('Runtime.queryObjects', { prototypeObjectId });
  const objectId = queried.objects?.objectId;
  if (!objectId) return null;
  try {
    const summary = await call('Runtime.callFunctionOn', {
      objectId,
      functionDeclaration,
      returnByValue: true,
    });
    return summary.result?.value ?? null;
  } finally {
    await call('Runtime.releaseObject', { objectId }).catch(() => undefined);
    await call('Runtime.releaseObjectGroup', { objectGroup: 'phoenix-memory-profile' });
  }
}

function megabytes(bytes) {
  return Math.round((Number(bytes || 0) / 1024 / 1024) * 10) / 10;
}

await call('Runtime.enable');
await call('Performance.enable');
await call('HeapProfiler.enable');

if (collectGarbage) await call('HeapProfiler.collectGarbage', {}, 60_000);

const heap = await call('Runtime.getHeapUsage');
const performanceMetrics = await call('Performance.getMetrics');
const metric = Object.fromEntries((performanceMetrics.metrics || []).map((row) => [row.name, row.value]));
const dom = await call('Memory.getDOMCounters').catch(() => null);
const app = await evaluate(`(async () => ({
  title: document.title,
  url: location.href,
  rendererMode: localStorage.getItem('phoenix.graph.renderer.v3.authority'),
  graphText: [...document.querySelectorAll('*')]
    .map((node) => node.textContent || '')
    .find((text) => /CORPUS\\s+\\d+.*RESIDENT\\s+\\d+.*VISIBLE\\s+\\d+/is.test(text))
    ?.match(/CORPUS\\s+\\d+.*?AGGREGATED\\s+\\d+/is)?.[0] || null,
  canvases: [...document.querySelectorAll('canvas')].map((canvas) => ({
    width: canvas.width,
    height: canvas.height,
    cssWidth: Math.round(canvas.getBoundingClientRect().width),
    cssHeight: Math.round(canvas.getBoundingClientRect().height),
  })),
  resources: performance.getEntriesByType('resource')
    .filter((entry) => /worker|model|onnx|wasm|graph|galaxy/i.test(entry.name))
    .map((entry) => ({
      name: entry.name.replace(location.origin + '/', ''),
      transferKb: Math.round((entry.transferSize || 0) / 1024),
      decodedKb: Math.round((entry.decodedBodySize || 0) / 1024),
    })),
  indexedDb: typeof indexedDB.databases === 'function'
    ? (await indexedDB.databases()).map((database) => database.name)
    : [],
  modelCacheDebugKeys: Object.keys(window.modelCacheDb || {}),
}))()`);

const buffers = metricsOnly ? null : await queryObjects('ArrayBuffer.prototype', `function () {
  let bytes = 0;
  let maximum = 0;
  const buckets = { over1mb: 0, over10mb: 0, over100mb: 0 };
  for (const value of this) {
    let size = 0;
    try { size = value.byteLength || 0; } catch { continue; }
    bytes += size;
    maximum = Math.max(maximum, size);
    if (size >= 1024 * 1024) buckets.over1mb += 1;
    if (size >= 10 * 1024 * 1024) buckets.over10mb += 1;
    if (size >= 100 * 1024 * 1024) buckets.over100mb += 1;
  }
  return { count: this.length, bytes, maximum, buckets };
}`);
const maps = metricsOnly ? null : await queryObjects('Map.prototype', `function () {
  let entries = 0;
  let maximum = 0;
  for (const value of this) {
    const size = value.size || 0;
    entries += size;
    maximum = Math.max(maximum, size);
  }
  return { count: this.length, entries, maximum };
}`);
const sets = metricsOnly ? null : await queryObjects('Set.prototype', `function () {
  let entries = 0;
  let maximum = 0;
  for (const value of this) {
    const size = value.size || 0;
    entries += size;
    maximum = Math.max(maximum, size);
  }
  return { count: this.length, entries, maximum };
}`);

socket.close();
console.log(JSON.stringify({
  capturedAt: new Date().toISOString(),
  heapMb: {
    used: megabytes(heap.usedSize),
    total: megabytes(heap.totalSize),
    embedder: megabytes(heap.embedderHeapUsedSize),
    backingStorage: megabytes(heap.backingStorageSize),
  },
  runtime: {
    jsHeapUsedMb: megabytes(metric.JSHeapUsedSize),
    jsHeapTotalMb: megabytes(metric.JSHeapTotalSize),
    documents: metric.Documents,
    nodes: metric.Nodes,
    listeners: metric.JSEventListeners,
  },
  dom,
  buffers: buffers && {
    count: buffers.count,
    totalMb: megabytes(buffers.bytes),
    maximumMb: megabytes(buffers.maximum),
    ...buffers.buckets,
  },
  maps,
  sets,
  app,
}, null, 2));
