import WebSocket from 'ws';

const targets = await fetch('http://127.0.0.1:9222/json').then((response) => response.json());
const target = targets.find((row) => row.type === 'page' && row.webSocketDebuggerUrl);
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
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 60_000);
    pending.set(id, (message) => {
      clearTimeout(timer);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    });
  });
}
const response = await call('Runtime.evaluate', {
  expression: 'window.__PHOENIX_GRAPH_BUILD_BASELINE__.evictArenaAndReadFirstPage()',
  awaitPromise: true,
  returnByValue: true,
});
socket.close();
if (response.exceptionDetails) {
  throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
}
const page = response.result?.value;
if (page?.schemaVersion !== 'phoenix-graph-run-page/v1' || page?.source !== 'rust') {
  throw new Error('Durable graph run did not reopen as a native v1 page.');
}
console.log(JSON.stringify({
  schemaVersion: page.schemaVersion,
  source: page.source,
  runHandle: page.runHandle,
  evictionState: page.evictionState,
  returnedDetailRows: page.returnedDetailRows,
  noTopologyWrites: page.projection?.noTopologyWrites,
}));
