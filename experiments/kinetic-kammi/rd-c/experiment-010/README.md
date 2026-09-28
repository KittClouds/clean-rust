# R&D-C / Experiment 010

Cross-repository transfer of the frozen E009 v5 observer switchboard.

The held-out bank was frozen before observer contact. No E010 thresholds or observer bundles were fitted.

## Result

The preregistered gate passed independently on both repositories. Repo A (ripgrep) had 8/8 small actions correct, retained 8/8 hybrid completion, and displaced all 8 large calls. Repo B (turbovec) had 5/5 small actions correct at 5/8 coverage; the hybrid completed 8/8 using 3 large calls, compared with 5/8 completion for always-large.

Pooled totals are descriptive: hybrid completion was 16/16 versus 13/16 always-large, with 13 large calls avoided. Hybrid used 27,652 tokens versus 26,342 always-large tokens. Illegal commits, duplicate action effects, and replay mismatches were all zero.

The bank has four controlled regression families per repository, each shown in two paired prompt variants. This is a bounded transfer result on the two frozen snapshots, not a general repository-wide estimate.

Three failed fixture-builder attempts are preserved in sibling `tasks/heldout-bank-v1-precontact-failed-fixture-*` folders. They were repaired before model contact and are not part of the scored bank.

Reports and locks are under [`artifacts/runs/e010-20260925-cross-repo-01`](artifacts/runs/e010-20260925-cross-repo-01):

- [`repository-level-report.md`](artifacts/runs/e010-20260925-cross-repo-01/repository-level-report.md) — per-repository gate and efficiency outcomes.
- [`benchmark-report.md`](artifacts/runs/e010-20260925-cross-repo-01/benchmark-report.md) — paired lane, family, latency, token, and authority results.
- [`frozen-input-lock.json`](artifacts/runs/e010-20260925-cross-repo-01/frozen-input-lock.json) and [`score-replay-input-lock.json`](artifacts/runs/e010-20260925-cross-repo-01/score-replay-input-lock.json) — precontact and scoring replay inputs.
