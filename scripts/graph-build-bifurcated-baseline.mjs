import { spawnSync } from 'node:child_process';

const baselineMode = process.env.GRAPH_BUILD_BASELINE_MODE || 'zeroshot';
const command = process.execPath;
const args = [
  'node_modules/vitest/vitest.mjs',
  'run',
  'src/app/graph-rebuild/graph-build-bifurcated-baseline.spec.ts',
  ...process.argv.slice(2),
];

const result = spawnSync(command, args, {
  cwd: process.cwd(),
  env: {
    ...process.env,
    GRAPH_BUILD_BASELINE: '1',
    GRAPH_BUILD_BASELINE_MODE: baselineMode,
  },
  stdio: 'inherit',
});

if (result.error) {
  console.error(result.error);
  process.exit(1);
}

process.exit(result.status ?? 1);
