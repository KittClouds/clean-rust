# REQUAL1-SREPLACE-PAIRS: exact fresh S-replacement pair replay

This engineering-only identity replays the sealed geometry-screened pair
domain with the real learner-order sequential f32 readout. Both replacements
are applied simultaneously to the same fresh invalid `S` state. The runner
independently reconstructs and records `S_A`, `S_B`, and `S_AB`; it never
forms `S_AB` by mutating `S_A`.

Every context is written as an immutable shard and the final receipt is
atomic. Exact target parity, valid improvement over fresh `V`, pair validity,
and pair interaction are engineering diagnostics only. No behavior or
scientific seed is opened.


## Rerun hygiene contract

This is a fresh execution identity with the same sealed 4,999-pair domain,
selector, ordering, contexts, inputs, geometry gates, and finalizer semantics
as the superseded pair replay. The only execution change is write hygiene:

- Python is launched with `-B` and `PYTHONDONTWRITEBYTECODE=1`.
- `sys.dont_write_bytecode` must be true before imports.
- Preflight requires no `scripts/__pycache__` and no orphan temporary outputs.
- The measured write surface is limited to eight shard JSONL files,
  `execution.json`, and `STATUS.json`; unexpected paths fail promotion.
- The prior pair replay remains an immutable non-promotable artifact and is
  not used as evidence.
