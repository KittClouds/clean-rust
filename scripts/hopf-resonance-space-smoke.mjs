#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const args = process.argv.slice(2).filter(Boolean);
const envDocs = process.env.HOPF_SPACE_DOCS
  ? JSON.parse(process.env.HOPF_SPACE_DOCS)
  : [];
const docs = args.length
  ? args
  : Array.isArray(envDocs) && envDocs.length
    ? envDocs
    : [process.env.HOPF_SPACE_DOC || 'docs/shortrun.md'];
const vitest = resolve('node_modules', 'vitest', 'vitest.mjs');

if (!existsSync(vitest)) {
  console.error('Vitest is not installed. Run npm ci --legacy-peer-deps first.');
  process.exit(1);
}

const result = spawnSync(process.execPath, [
  vitest,
  'run',
  'test/hopf-resonance-space-smoke.test.ts',
  '--pool=forks',
  '--reporter=verbose',
], {
  stdio: 'inherit',
  env: {
    ...process.env,
    HOPF_SPACE_DOC: docs[0],
    HOPF_SPACE_DOCS: JSON.stringify(docs),
  },
});

process.exit(result.status ?? 1);
