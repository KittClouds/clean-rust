# R&D-C / Experiment 003 — Disagreement Gate

Held-out synthetic workflow bank: 256 episodes; seed `0xE00320260924`; four paired lanes; same episode IDs and observation prefixes in every lane.

The task contract independently maps `(goal, authoritative world revision)` to one correct domain action. The label writer uses that contract; neither observer nor routing policy receives the labels. The frozen resolver reads the same recorded goal and revision and does not receive observer proposals. Observers, resolver, confidence threshold, and matched-random seed were fixed before scoring.

Candidate actions map to legal Experiment 002 transitions from `DECIDING` to `ACTING`: `Execute` = `use_primary`, `Verify` = `verify_record`, and `Observe` = `refresh_snapshot`. All three are accepted by the experiment's compiled schema; only the task-contract action advances the episode. Thus wrong-action counts are legal-but-unhelpful actions, while illegal commits are checked separately against the compiled schema.

## Outcomes and authority gate

| Policy | Completion | Wrong legal actions | Escalation precision | Resolver correct / calls | Resolver calls | Illegal commits | Rejected proposals | Duplicate / missing actions | Replay identity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| never | 140/256 (54.7%) | 116/256 (45.3%) | n/a | 0/0 | 0 | 0 | 0 | 0 / 0 | 256/256 |
| disagreement | 220/256 (85.9%) | 36/256 (14.1%) | 80/108 (74.1%) | 108/108 | 108 | 0 | 0 | 0 / 0 | 256/256 |
| confidence_threshold | 236/256 (92.2%) | 20/256 (7.8%) | 96/128 (75.0%) | 128/128 | 128 | 0 | 0 | 0 / 0 | 256/256 |
| random_matched | 190/256 (74.2%) | 66/256 (25.8%) | 50/108 (46.3%) | 108/108 | 108 | 0 | 0 | 0 / 0 | 256/256 |

Raw observer action disagreement: 108/256 episodes. When the observers agreed, the active observer was wrong in 36/148 cases (24.3%). When they disagreed, the active observer was wrong in 80/108 cases (74.1%). The random lane escalated exactly 108/108 episodes using `BLAKE3(seed || episode_id), ascending digest, first D episodes` with seed `0x524443035EED0001`; the schedule was formed without reading labels.

## Cost and runtime

Task wall time includes E002 task and action journal creation, every durable write, the complete workflow, close, and verification replay. Observer and routing time are reported separately. Resolver percentiles use escalated tasks only. This v0 resolver is deterministic local code, so it consumes zero model tokens and incurs `$0` model/API cost; wall time is the local compute cost proxy.

| Policy | p50/p95 task wall ms | p50/p95 observer A us | p50/p95 observer B us | p50/p95 routing us | p50/p95 resolver us/call | Mean ms / completed task | Journal / action bytes per task | Tokens / task | Model cost / completed task |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| never | 33.666/40.025 | 0.000/0.100 | 0.000/0.100 | 0.100/0.200 | n/a | 63.815 | 12392 / 1579 | 0 | $0.000000 |
| disagreement | 35.509/47.429 | 0.000/0.100 | 0.000/0.100 | 0.100/0.200 | 0.000/0.100 | 44.448 | 13215 / 1690 | 0 | $0.000000 |
| confidence_threshold | 35.866/41.587 | 0.000/0.100 | 0.000/0.100 | 0.100/0.200 | 0.000/0.100 | 39.812 | 13381 / 1713 | 0 | $0.000000 |
| random_matched | 34.799/41.024 | 0.000/0.100 | 0.000/0.100 | 0.100/0.200 | 0.000/0.100 | 48.628 | 12902 / 1648 | 0 | $0.000000 |

## Error breakdown, including observer agreement

| Held-out stratum | Episodes | Raw disagreement | Active observer wrong | Never completion | Disagreement completion | Confidence completion | Random matched completion |
|---|---:|---:|---:|---:|---:|---:|---:|
| fresh_agreement_correct | 80 | 0 | 0 | 80/80 | 80/80 | 80/80 | 80/80 |
| misleading_shared_wrong | 20 | 0 | 20 | 0/20 | 0/20 | 0/20 | 6/20 |
| stale_primary_disagreement | 48 | 48 | 48 | 0/48 | 48/48 | 48/48 | 23/48 |
| conflicting_audit_disagreement | 16 | 16 | 0 | 16/16 | 16/16 | 16/16 | 16/16 |
| low_confidence_agreement_correct | 32 | 0 | 0 | 32/32 | 32/32 | 32/32 | 32/32 |
| split_wrong_disagreement | 32 | 32 | 32 | 0/32 | 32/32 | 32/32 | 15/32 |
| stale_shared_wrong | 16 | 0 | 16 | 0/16 | 0/16 | 16/16 | 6/16 |
| active_correct_conflict | 12 | 12 | 0 | 12/12 | 12/12 | 12/12 | 12/12 |

## Promotion gate

Gate result: **PASS vs matched random** for this held-out synthetic bank. Disagreement routing selected 36 wrong legal actions and completed 220/256 tasks; matched-random selected 66 wrong legal actions and completed 190/256 tasks with the same 108 resolver calls. Confidence threshold used 128 calls and performed better in absolute outcomes (20 wrong actions; 236/256 complete), at 20 more calls than disagreement routing. All four lanes had zero illegal commits, duplicate actions, and missing actions, and every task replay identity matched.

This result applies only to the predeclared synthetic workflow bank and frozen deterministic proxy observers/resolver. It demonstrates whether the harness can distinguish targeted routing from call-matched random routing; it does not establish performance for learned observers or a large deliberator.

## Frozen components and provenance

- Observer A: `tool-follow/v1`; observer B: `audit-filter/v1`; resolver: `workflow-contract-resolver/v1`.
- Confidence threshold: `700` (escalate below threshold).
- Episode and label artifacts: `heldout-inputs.csv`, `heldout-labels.csv`; route schedule: `route-plan.csv`; every E002 lane journal and action ledger are retained under `journals/`.
- Run directory: `C:\rd-c\experiment-003\artifacts/runs\run-1790271659990-00`.
- Digests: inputs `bdda60b4b14eb619fadfcdddf38ae7e8a6e73d638693444fcda8ccce512f43ac`, labels `14042f14993acae72af2a630362868ebf3e2beb7140cc8ace35537c2ce659432`, route plan `db688f8240c827ab2fd82ccec277e5b5d50de9ad70ce2c320d1becea34e83bc2`, traces `f9c3755be8300ae0922a18a8037c74917f5eadbb38a5d940b252bcc9ea1526f1`.

## Limits

The lane journals use Experiment 002's compiled authority, mmap-backed replay, hash-chained journal, durable action intent/completion protocol, and idempotent simulator. The experiment schema adds two legal typed candidate actions at the decision state and removes the confidence guard from those three candidate transitions so confidence routing is evaluated as a policy rather than re-tested as authority. E002's legacy `illegal_commits` convenience counter assumes only the original standard schema; this report independently checks every accepted receipt against the compiled Experiment 003 schema.
