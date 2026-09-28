# R&D-C / Experiment 001 benchmark report

Rust target: x86_64-windows; processors: 16; release profile; 7 samples x 20000 tasks per sample and controller.

The controller is single-threaded. Both lanes use the same observer and receipt hash function; the baseline uses a hand-written match dispatch, while the runtime uses the compiled dense table. Latency is wall-clock nanoseconds per task. Receipt memory is estimated from retained Receipt values; it excludes allocator metadata. Shared table bytes count the compiled table once.

| Workload | Controller | Completion | Rejections/task | Recoveries/task | Replay identity | p50 ns/task | p95 ns/task | p50 vs baseline | Receipt bytes/task | Shared table bytes |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| nominal | compiled runtime | 100.00% | 0.000 | 0.000 | pass | 1531 | 1896 | +8.27% | 520 | 2744 |
| nominal | hand-written baseline | 100.00% | 0.000 | 0.000 | pass | 1414 | 1516 | reference | 520 | 0 |
| one recovery | compiled runtime | 100.00% | 0.000 | 1.000 | pass | 2578 | 2732 | -3.66% | 936 | 2744 |
| one recovery | hand-written baseline | 100.00% | 0.000 | 1.000 | pass | 2676 | 2831 | reference | 936 | 0 |
| illegal proposal | compiled runtime | 0.00% | 1.000 | 0.000 | pass | 273 | 313 | -7.46% | 104 | 2744 |
| illegal proposal | hand-written baseline | 0.00% | 1.000 | 0.000 | pass | 295 | 319 | reference | 104 | 0 |

## Workloads

- **nominal**: observe, decide, execute, verify, complete.
- **one recovery**: action failure, bounded recovery, then successful completion.
- **illegal proposal**: observer requests DONE from IDLE; authority rejects and retains IDLE.

## Limits

This is a repeatable in-process controller microbenchmark, not a workload-level product claim. It measures no model calls, I/O latency, external action cost, or process RSS. The journal replay check is covered by the mapped-replay test and demo; replay identity in this table verifies repeated identical in-memory receipt sequences. Lower timing numbers can vary with OS scheduling and CPU frequency.
