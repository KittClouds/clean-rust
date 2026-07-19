import { spawnSync } from 'node:child_process';

const args = [
  '--expose-gc',
  'node_modules/vitest/vitest.mjs',
  'run',
  'src/app/graph-rebuild/graph-retrieval-performance.spec.ts',
  '--reporter=verbose',
  ...process.argv.slice(2),
];

const result = spawnSync(process.execPath, args, {
  cwd: process.cwd(),
  env: {
    ...process.env,
    GRAPH_RETRIEVAL_BASELINE: '1',
  },
  stdio: 'inherit',
});

if (result.error) {
  console.error(result.error);
  process.exit(1);
}

process.exit(result.status ?? 1);
