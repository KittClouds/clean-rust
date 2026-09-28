# R&D-C / Experiment 001

A standalone deterministic workflow runtime demonstrating observation, replaceable typed observers, compiled guarded transitions, authorized actions, receipts, and journal replay.

The runtime has no model calls. The compiler produces a dense state/action dispatch table. Receipt journals use a versioned fixed-width zero-copy header followed by tab-delimited proposal rows; replay maps the journal read-only and verifies the full receipt hash chain.

## Run

From this directory, run cargo test with --target-dir D:\cargo-targets\rd-c-experiment-001. Run the demo and benchmark with --release and the same target directory.

The journal reader requires that no process modify a journal while it is being replayed.

## Scope

The baseline is a hand-written workflow controller. This prototype includes state guards, explicit rejections, bounded recovery, receipt identity, mapped replay, a smoke test, unit tests, and a benchmark report. Scratchpads, neural observers, model calls, writable memory, and context compilation are out of scope.
