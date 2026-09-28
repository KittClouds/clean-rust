# E009 original pilot abstention diagnosis

Thresholds from the frozen pilot lock: minimum applicability **700 milli**; maximum abstention **600 milli**. The v1 wire contract defines both fields on a 0–1000 milli scale.

| Task | Action proposal | Applicability | Abstention | Compiler outcome | Trace diagnosis |
| --- | ---: | ---: | ---: | --- | --- |
| `coding-gpu-pick-01` | `null` | 0 milli | 0 milli | `Abstain(NotApplicable)` | Explicit no-action output; applicability is below 700. |
| `coding-embedding-batch-01` | `51` | 95 milli | 0 milli | `Abstain(NotApplicable)` | Action was proposed, but 95 milli is below 700. The value may reflect percent/milli confusion; the trace does not prove intended units. |

Both values passed the maximum-abstention test (`0 <= 600`); applicability rejected both. No pilot score was reinterpreted or used to fit the later development thresholds. v2 changed the wire field to percent and normalized percent × 10 into milli.

The JSON artifact records per-file hashes, token counts, latency, the frozen lock thresholds, and the exact typed result.
