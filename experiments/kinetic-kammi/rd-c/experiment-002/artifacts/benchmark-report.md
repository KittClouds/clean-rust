# R&D-C / Experiment 002 benchmark report

Platform: x86_64-windows; logical processors: 16; release build; 20 paired tasks per workload.

Each pair reuses the same task ID, observers, observation sequence, action simulator semantics, and fsync journal policy. The hand-written lane uses the Experiment 001 transition match directly; the compiled lane uses its frozen dense table. Task time includes journal creation, durable writes, simulated action effects, crash recovery, and final close, but excludes the post-task verification replay. Observer time is summed from calls and excludes journal writes.

| Workload | Controller | Completion | Illegal commits | Rejected proposals | Duplicate actions | Missing actions | Replay identity | Paired state/receipts | Shadow disagreements/task | Workflow recoveries/task | Process resumes/task | p50/p95 task us | p50/p95 active observer us | p50/p95 shadow observer us | p50/p95 swap us | Journal bytes/task | Action bytes/task | Idempotent retries |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nominal | compiled runtime | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 0 | 0 | 0 | 27373.50/30817.00 | 0.700/0.800 | 0.300/0.500 | 0.000/0.000 | 13082 | 1743 | 0 |
| nominal | hand-written baseline | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 0 | 0 | 0 | 27543.90/30131.30 | 0.700/0.900 | 0.300/0.500 | 0.000/0.000 | 13077 | 1743 | 0 |
| recovery | compiled runtime | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 0 | 1 | 0 | 43321.20/48627.40 | 1.200/1.600 | 0.400/0.600 | 0.000/0.000 | 23252 | 3167 | 0 |
| recovery | hand-written baseline | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 0 | 1 | 0 | 42888.80/47916.60 | 1.200/1.500 | 0.600/0.900 | 0.000/0.000 | 23233 | 3167 | 0 |
| illegal proposal | compiled runtime | 100.0% | 0 | 20 | 0 | 0 | 20/20 | 20/20 | 0 | 0 | 0 | 29079.10/33633.30 | 0.800/1.000 | 0.300/0.500 | 0.000/0.000 | 14758 | 1736 | 0 |
| illegal proposal | hand-written baseline | 100.0% | 0 | 20 | 0 | 0 | 20/20 | 20/20 | 0 | 0 | 0 | 29837.90/32615.00 | 0.800/1.000 | 0.400/0.500 | 0.000/0.000 | 14749 | 1736 | 0 |
| shadow disagreement | compiled runtime | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 1 | 0 | 0 | 27696.30/30433.10 | 0.700/0.900 | 0.300/0.400 | 0.000/0.000 | 13084 | 1736 | 0 |
| shadow disagreement | hand-written baseline | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 1 | 0 | 0 | 27354.00/29863.80 | 0.800/1.100 | 0.300/0.400 | 0.000/0.000 | 13086 | 1736 | 0 |
| crash and resume | compiled runtime | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 1 | 0 | 4 | 51597.90/55088.70 | 0.600/1.100 | 0.300/0.400 | 0.000/0.000 | 13079 | 1745 | 20 |
| crash and resume | hand-written baseline | 100.0% | 0 | 0 | 0 | 0 | 20/20 | 20/20 | 1 | 0 | 4 | 52810.50/58697.60 | 0.600/0.900 | 0.300/0.500 | 0.000/0.000 | 13089 | 1745 | 20 |
| observer swap | compiled runtime | 100.0% | 0 | 20 | 0 | 0 | 20/20 | 20/20 | 1 | 0 | 0 | 31160.30/34365.00 | 0.900/1.200 | 0.400/0.500 | 1.600/2.100 | 15513 | 1743 | 0 |
| observer swap | hand-written baseline | 100.0% | 0 | 20 | 0 | 0 | 20/20 | 20/20 | 1 | 0 | 0 | 29996.80/34737.60 | 0.900/1.100 | 0.400/0.500 | 1.500/2.100 | 15494 | 1743 | 0 |

## Interpretation

Observer disagreements are proposals only; active authority alone determines commits and effects. A successful replay means the journal hash chain verified, replayed transition receipts matched, and the final state and receipt sequence were identical. Observer swap time measures implementation replacement itself; its durable registry write is included in task time.

## Crash protocol

The crash workload injects failure after a committed transition receipt, after action intent, after the simulator's durable effect, and after action completion. Resume replays active proposals, resolves incomplete intents with deterministic action IDs, and asks the simulator to deduplicate retries.

## Limits

The simulator models an idempotent action endpoint by durably recording action IDs. Exactly-once side effects require the real endpoint to honor the same idempotency key; a local journal cannot make an arbitrary non-idempotent external system exactly once. Timing is machine-local and includes filesystem synchronization.
