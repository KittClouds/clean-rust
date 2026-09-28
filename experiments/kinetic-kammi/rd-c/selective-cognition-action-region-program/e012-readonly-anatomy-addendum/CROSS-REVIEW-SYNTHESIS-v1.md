# E012 / E013 Cross-Review Synthesis v1

**Review cycle:** post-run read-only analysis and protocol design  
**Synthesis authority:** root task after independent reviewer reports  
**Model contact:** none; remains unauthorized.

## Cross-review agreement

Both reviewers verified artifact hashes and confirmed that no E012 source bytes changed. They agreed that semantic correctness remains distinct from authority/presentation/replay integrity, and that neither E012 nor the positive control supplies E013 outcomes.

## Review deltas and synthesis decisions

| Review finding | Synthesis decision | Versioned artifact |
|---|---|---|
| E012 pair report called absent raw action choices “abstentions,” conflating no proposal with a proposal rejected by the legacy acceptance threshold. | Preserve reviewed v1 bytes. Correct the metric in v1.1; report raw-choice absence, both-runtime-accepted, and one-or-both-runtime-not-accepted separately. | `E012-READONLY-ANATOMY-v1.1.*` |
| Uniform-choice arithmetic, pair membership, overlap counts, and task-completion linkage reconcile. | Retain the calculations; keep them descriptive and keep completion separate from proposal correctness. | `E012-READONLY-ANATOMY-v1.1.*` |
| Empty-valid-set proposals were outside the proposed primary risk-coverage denominator. | Include every non-null candidate proposal in primary routing risk, including guaranteed errors on empty-valid-set tasks. Keep candidate-selection-only analysis as a separately reported diagnostic, never the admission gate. | `E013-TRUST-SIGNAL-DEVELOPMENT-PROTOCOL-v0.2.md` |
| T3 margin and T4 pairwise coherence lacked fully specified scoring algorithms. | Freeze the exact teacher-forced mean token log-prob margin and the mirrored-pair decisive-edge, reversal, cycle, and direct-choice win-rate definitions. Require executable analysis code hashes before any later contact. | `E013-TRUST-SIGNAL-DEVELOPMENT-PROTOCOL-v0.2.md` |
| The 32-task positive control could not separate task difficulty from distribution shift. | Expand to a 64-task, two-cohort design on the same two fresh Rust repositories. Match cohorts on a predeclared outcome-blind difficulty rubric. Keep interpretation explicitly diagnostic, not causal. | `E012-POSITIVE-CONTROL-DESIGN-v1.1.md` |
| A pooled support count alone could be mistaken for per-repository portability. | Limit any pooled confirmation claim to its evaluated task mixture. Require 60 accepted actions and the exact 5% bound separately in every claimed repository before making a per-repository portability claim. | `E013-TRUST-SIGNAL-DEVELOPMENT-PROTOCOL-v0.2.md` |

## Final interpretation

E012 rejects the current v5 self-reported acceptance contract as a portable trust instrument on the sealed E012 bank. It does not falsify all small-observer capability. The data support the routing asymmetry: false acceptance can suppress a useful large fallback, while a false abstention generally spends another call.

The read-only anatomy establishes only that small was descriptively above the uniform-choice expectation on this small accepted subset (`6/16` observed; `3.5/16` expected; reference tail `0.112`), and that its raw selections tracked fixed-set answer changes less often than large's. It does not create a trusted subgroup.

E013 v0.2 is a protocol design, not a model-contact authorization. The 64-task positive control is also designed but unrun. No E013 bank or scoring code has been built; those must be separately sealed before any future model contact. E014 remains deferred.
