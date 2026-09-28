# FAS-R1 Design Packet Amendment 01 and SHA256 Seal Receipt

**Disposition:** SEALED_FOR_STAGE0_CONSTRUCTION
**Date:** 2026-09-25
**Authority:** user approval in the current task authorizes Stage 0 construction only.
**State flags:** stage0_construction_authorized=true; construction_ready=not_asserted; model_contact=false; training=false; evaluation=false; scientific_result=false.

This is a design packet seal. It does not certify that Stage 0 construction is complete or that R1_CONSTRUCTION_READY has been achieved. Stage 0 remains strictly model-free. Model contact, training, and evaluation remain outside this authorization.

## Versioned amendment record

Amendment ID: FAS-R1-AMENDMENT-01 (design packet v0.2). It applies the following four approved changes consistently across the README, design audit, stage-zero seam inventory, and executor directive:

1. **Separate planning from terminal selection.** V_reach(X,b) estimates continuation reachability under the frozen learned proposal and is used for learned-proposal allocation/resampling and merge representative retention. Q_terminal(a,H) predicts validity of an already visited assignment, is trained from private validator labels, is frozen before evaluation, and is the same final selector for every arm. R(B)-S(B) now measures misses by this common terminal selector on the same trace.
2. **Gate sensor qualification on action relevance.** Qualification is hierarchical: semantic identity, entity/role binding, then prediction of sign(Delta C(a,e)). The action probe receives only H, h_global, a, e, and public incidence; labels come from the private typed validator offline. Failure at any stage stops the LFM-backed search claim. Stage 0 does not load or contact a model.
3. **Define measured-time reachability by trace prefixes.** Each arm runs its full prescribed maximum. Timestamp charged operations; derive R(C_active) and R(C_wall) by post-hoc prefix truncation on a prospectively selected and pre-evaluation frozen cutoff grid. The scheduler receives no time-stop signal. Report CPU/GPU active time and monotonic wall time separately.
4. **Name and instrument the proposal teacher accurately.** q(e|a) proportional to G(e|a) is the class-balanced one-step reachability teacher, not an optimal-edit teacher. Add training-only n_improved_classes(e,a) and Delta d_min telemetry without another loss or any inference-time access.

The amendment preserves assignment-level merging as a heuristic when latent states differ, with strict full-state identity only as a diagnostic. FAS-00 and S05 remain provenance references only; their artifacts are not copied into R1.

## SHA256 manifest

Algorithm: SHA-256 over the exact file bytes at seal time. The normative packet is the four files listed below. This receipt contains the amendment record and is excluded from its own manifest to avoid a self-referential digest. Stage 0 source/code, generated files, and build artifacts are excluded.

| File | SHA256 |
| --- | --- |
| README.md | 0236be3c15024b19f94966c21e2e5bc7495fd37fe8e41677890cb8fe4ddfbc1f |
| DESIGN-AUDIT.md | fcb5f51134fa9c6de7c7fd168dc395604a84ba0d8012ae959d88641276df363d |
| STAGE-ZERO-SEAMS.md | cc072f0a1bd43ab236e3c9e2fb6fe63c3e56b7057716a052e6f0e549086846d7 |
| EXECUTOR-DIRECTIVE.md | debbb84cc51d7d24d75f1656245a3bbfaac551134548386cf181a008a39f40b2 |

## Deferred run-manifest values

No conflicting design estimand remains among Amendment 01 changes. The numerical measured-time cutoff grid must be selected from development/runtime feasibility and frozen before protected evaluation. The exact Q_terminal training-assignment mixture and sensor-probe family/support manifest must be frozen before their respective fitting/extraction gates. These values do not extend this Stage 0 authorization.
