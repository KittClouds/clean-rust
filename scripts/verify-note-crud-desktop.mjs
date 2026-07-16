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
const pending = new Map();
socket.on('message', (raw) => {
  const message = JSON.parse(String(raw));
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

const response = await call('Runtime.evaluate', {
  expression: `
    (async () => {
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const listNotes = async () => {
        const raw = await window.__TAURI_INTERNALS__.invoke('TauRPC__phoenix.store_command', {
          command: 'note:list',
          payload_json: JSON.stringify({ includeBody: false }),
        });
        const result = JSON.parse(raw);
        return Array.isArray(result.payload) ? result.payload : [];
      };
      const waitFor = async (predicate, label) => {
        const deadline = performance.now() + 10_000;
        while (performance.now() < deadline) {
          const value = await predicate();
          if (value) return value;
          await sleep(50);
        }
        throw new Error('Timed out waiting for ' + label);
      };
      const before = await listNotes();
      const create = [...document.querySelectorAll('button')]
        .find((button) => button.textContent?.includes('Create New Note'));
      if (!create) throw new Error('Create New Note button is unavailable.');
      create.click();
      const created = await waitFor(async () => {
        const rows = await listNotes();
        return rows.find((row) => !before.some((existing) => existing.id === row.id));
      }, 'created note');
      const actions = await waitFor(
        async () => [...document.querySelectorAll('button[aria-label="Actions for Untitled Note"]')].at(-1),
        'new note actions',
      );
      actions.click();
      const remove = await waitFor(
        async () => [...document.querySelectorAll('button')]
          .find((button) => button.textContent?.trim() === 'Delete note'),
        'Delete note action',
      );
      remove.click();
      const rows = await waitFor(async () => {
        const current = await listNotes();
        return current.some((row) => row.id === created.id) ? null : current;
      }, 'deleted note');
      await waitFor(async () => ![...document.querySelectorAll('button')]
        .some((button) => button.textContent?.includes('Saving...')), 'saving state to clear');
      return {
        createdId: created.id,
        deleted: true,
        noteCount: rows.length,
        saving: false,
      };
    })()
  `,
  awaitPromise: true,
  returnByValue: true,
});
socket.close();

if (response.exceptionDetails) {
  throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
}
const result = response.result?.value;
if (!result?.deleted || result.saving) {
  throw new Error(`Desktop note CRUD verification failed: ${JSON.stringify(result)}`);
}
console.log(JSON.stringify(result));
