# CANCEL1 longer-run execution plan

Status: **planning amendment, not an execution seal**. Prepared 2026-09-18.

## Decision

Complete the existing bounded cancellation question with a new checkpointed execution identity, provisionally **Q10-GC1-CANCEL1-LR1**. Prefer sequential case shards over an uninterrupted hour-long invocation. This is one logical campaign with one frozen selection policy, not eight independently tuned experiments. Do not extend the domain, loosen geometry, regenerate palettes, or move the fixed starting state S after success.

Do not patch or overwrite CANCEL1-v1. Its runner has evidence-retention gaps that a longer timeout would not fix. LR1 must qualify the execution and receipt changes before running. GC2 remains fresh-state constructor qualification; GA1, AG1 and behavior remain gated.

## 1. Immediate operational hold: an existing process was found

Read-only inspection found PID **37376**, command `python.exe -B experiments/drosophila-heresy/q10-gc1-cancel1-v1/scripts/run_cancel1.py`, created 2026-09-18 at 04:41:34 in the machine's reported local time. It had approximately 493 MiB working set at inspection. No qualification receipt was present then. This is a point-in-time observation, not a promise that it remains running.

Before any future launch:

1. Recheck exact command line, PID plus creation time, parent process, CPU progress, and receipt paths. PID alone is not a stable identity.
2. Do not start a competing run or kill the existing process automatically. The current request authorizes this written plan, not process termination.
3. If it finishes, preserve and audit its outputs under the original identity. Do not call its sparse receipts a complete pair-level audit. Reconstruct missing evidence under LR1 if needed.
4. If it exits without a terminal receipt, record an interrupted attempt with the observations actually available. Absence of receipts does not prove zero candidate evaluations or zero result exposure.
5. Preserve the historical PREEXECUTION document; its `execution_started=false` is a pre-run statement, not current process status. Write any reconciliation addendum in a new identity.

The pasted claim that background processes are killed by the harness is not treated as a universal fact: a live matching process exists. LR1 avoids dependence on detached-process survival regardless.

## 2. Verified workload and timing envelope

Counts below were derived read-only from the sealed PAR8 invalid-state flags and palette records. Pair counts become exact only after each case's singles determine its frozen shortlist; same-group pairs are excluded.

| Case | Groups | Single replacements | Pair upper bound | Maximum candidates |
|---|---:|---:|---:|---:|
| L / tau16 / set2 | 55 | 440 | 496 | 936 |
| L / tau4 / set3 | 62 | 496 | 496 | 992 |
| R / tau16 / set1 | 59 | 472 | 496 | 968 |
| R / tau16 / set3 | 54 | 432 | 496 | 928 |
| R / tau4 / set0 | 59 | 472 | 496 | 968 |
| R / tau4 / set1 | 55 | 440 | 496 | 936 |
| R / tau4 / set2 | 59 | 472 | 496 | 968 |
| R / tau4 / set3 | 59 | 472 | 496 | 968 |
| Total | 462 | **3,696** | **3,968** | **7,664** |

These are labeled candidate attempts, not necessarily distinct committed states. Reference-state replays, qualification, and success audits are additional work and must have separate counters.

At the supplied 0.52 s/candidate, the maximum candidate workload is 3,985 seconds, or **66.4 minutes**. Each complete case is approximately 8.0–8.6 minutes before loading and writing. The RQ1 receipt separately reports 200 synthetic replays in 38.20 seconds (about 0.191 s each); that is not the same workload and does not independently verify 0.52 s for the full CANCEL loop.

Planning allowance: **75–100 minutes for the campaign plus qualification**, subject to measured startup, caching and audit costs. Proposed operational cap: 120 minutes cumulative worker wall time for measured shards, with qualification/review time reported separately. If the bound is exceeded, retain incomplete coverage and stop; no silent top-up. Final cap is frozen after a bounded representative fixture benchmark, before LR1 candidate outcomes are examined.

## 3. Fix execution evidence before spending the budget

Inspection of CANCEL1-v1 shows:

- Results are accumulated in memory and written only after the complete campaign. Timeout can lose all unrecepted work.
- Pair negatives are discarded; successful pair records omit alternate candidate identities and full score/geometry. They cannot independently reconstruct the pair from their saved fields alone.
- Singles retain only part of the in-memory diagnostics; the complete shortlist is not saved.
- The script accepts `--force`, and atomic replacement by itself does not prevent overwriting a completed result.
- The collateral shortlist sort uses damaged count, mismatch count, ULP distance and excess, while the prose says damaged count, full Q, then excess. L2/max ties therefore need an explicit resolution.
- RQ1 caches result dictionaries by weight hash alone, even though readout/geometry/targets are state-specific, and retains full weight arrays. A multi-case long run needs context-safe keys and bounded cache memory.
- RQ1's duplicate-group assertion occurs after conversion to a dict; its labeled fixture tests a mismatched key set, not duplicate-record rejection. Validate source lists before dictionary conversion.

LR1 should preserve **the sealed runner's actual selector order and arithmetic** for operational continuity, explicitly documenting the collateral-sort discrepancy. A full-Q selector correction belongs to a different future comparison, not a silent amendment. Maintain legacy `sum` versus `fsum` conventions wherever they influence shortlist selection; changing near-zero opposition signs can change the pair domain. Full final geometry still uses the inherited qualified oracle.

Receipt, cache-isolation, duplicate-input checks and checkpoint changes must not change candidates or numerical results on valid inputs. If equivalence fails, stop and publish a semantic delta rather than calling the run a continuation.

## 4. Freeze LR1's contract

Bind complete hashes for CANCEL1 plan/contract/runner, RQ1 runner and execution, PAR8, palettes, PF0, PF5 gates and all transitive numerical helpers. Pin interpreter executable/version, dependencies and platform. Preserve all eight case identities in the canonical order shown above.

For each case freeze:

- Original repair baseline B, target T, saved invalid S and historical best-valid V, with committed weight and readout hashes.
- Complete per-group palette and S selection; all alternate choices including ZERO.
- Canonical singles list sorted by group ID then alternative identity, with count and hash.
- The exact legacy shortlist algorithm, stable tie semantics, sign/zero conventions and rule excluding same-group pairs.
- All final DA2 gates and hard support/bounds/boundary/reserve constraints.
- Work caps, chunk boundaries, counters, output schema, checksum algorithm, retry policy and aggregation requirements.

No global beam, additional prefixes, new seeds, new pair shortlist, or feedback from an earlier case may enter this run.

## 5. Qualification required before the long campaign

Use exposed engineering/synthetic fixtures, not scientific seeds. Qualify a new adapter without modifying RQ1 or CANCEL1 parents.

1. Compare old and new readout bytes, score components, geometry values, labels, single ordering and shortlist/pair identities on a frozen small fixture campaign. Include ties at each sort key.
2. Demonstrate identical results and record IDs for uninterrupted and interrupted/resumed execution, including interruption before chunk publication, after data publication and before completion marker.
3. Reject duplicate groups in input records, missing groups, same-group pairs, conflicting prefixes, illegal reserve and changed parents.
4. Test cache isolation with identical weight bytes but different target/readout/geometry contexts. Include context hashes in the key; cached results must never cross incompatible cases.
5. Verify target rediscovery, baseline identity, invalid improvement, bitwise signed-zero mismatch and exact distinct alternatives receive appropriate labels.
6. Verify every pair receipt contains enough information to reconstruct its map from B plus the frozen S selection and two replacements.
7. Check bounded-memory behavior and realistic per-candidate cost. Scope the cache to a case/chunk or bound it explicitly; cache eviction can affect time, not results. Preserve alias receipts when evaluation is reused.
8. Test terminal-output overwrite refusal and orphan temporary-file handling. Atomic publication and exclusivity are separate requirements.

Reference baseline/target readouts and immutable gates may be cached once per case only after equivalence checks. No reassociation of sequential f32 addition, FMA/SIMD substitution, or numeric-kernel rewrite in this execution amendment.

## 6. Shards, checkpoints and foreground orchestration

Use one worker initially. Avoid memory contention and hidden concurrency changes. Case order is fixed; no outcome-dependent priority.

Each case has two stages:

**A. Singles:** evaluate all alternatives around fixed S, without readout/geometry improvement filtering. Commit an immutable receipt chunk after every **32 labeled records**. The full singles index must pass count/hash coverage before shortlist construction.

**B. Pairs:** build and save the complete frozen shortlist, selection roles, excluded same-group pairs and exact pair list. Hash that list before pair replay. Evaluate each distinct-group pair simultaneously from S; never apply one replacement to the output of another trial. Commit every 32 records again.

An invocation may process at most **128 new records or 10 minutes**, stopping at a completed chunk boundary. At the supplied rate this is roughly one minute of candidate evaluation per 128-record invocation, plus startup. If state loading dominates, a qualified worker may process successive chunks up to the same 10-minute bound. Do not enlarge limits during the measured run.

Launch through the normal foreground execution-session mechanism. Poll its session in short intervals so progress remains visible; do not rely on `Start-Process` or one blocking 60-minute tool call. A tool response yielding a session is not a worker failure. Do not treat the model's monitoring timeout as permission to relaunch a duplicate.

At each resume, verify parent hashes, runtime identity, context, chunk checksums and completed record IDs. Resume only missing predetermined work. Discard no published records; an incomplete temporary chunk may be replayed because it has no authoritative completion marker. Repeated records caused by recovery get attempt counters but contribute once to domain coverage.

Completed case receipts are immutable. The aggregate has a separate identity and is emitted only after all eight cases complete. A partial campaign remains explicitly partial even if a successful candidate appears early.

## 7. Receipt layout and observability

Suggested fresh write layout:

```text
q10-gc1-cancel1-lr1-v1/
  PLAN.md, CONTRACT.json, PREEXECUTION.json
  inventory/cases.json, singles-domain.json, source-hashes.json
  qualification/runtime-equivalence.json, recovery-tests.json
  cases/<case-key>/references.json
  cases/<case-key>/singles/chunk-*.jsonl + completion/hash receipts
  cases/<case-key>/shortlist.json, pairs-domain.json
  cases/<case-key>/pairs/chunk-*.jsonl + completion/hash receipts
  cases/<case-key>/COMPLETE.json
  audit/success-reconstructions.json
  derived/SUMMARY.json, RESULT.md, STATUS.json
```

Every candidate record includes case/context hash, stage and domain index, group IDs, previous and replacement candidate IDs, canonical map reference/hash, weight/readout hashes, all four Q components, full geometry metrics and gate flags, legality, distinctness, repaired/damaged rows, S/V comparisons, outcome, and cache/attempt provenance. Preserve the signed diagnostic features actually used for the shortlist. Store large arrays once by content hash if needed; references must resolve offline.

Progress reports identify completed singles/pairs versus exact totals, current case/chunk, elapsed worker time, throughput, memory and last durable checkpoint. Report provisional discoveries as unverified until independent reconstruction. Do not claim a precise ETA from the synthetic benchmark or call missing receipts a negative result.

Write chunks to unique temporary files in the destination directory, flush and close, verify count/hash, publish atomically under exclusive ownership, then publish the completion marker. On restart, verify existing files rather than overwrite them. No `--force` path in the measured runner.

## 8. Success, failure and independent audit

`VALID_ADVANTAGE_PRESERVED` requires all hard legality and final geometry gates, W distinct from B/T, and Q(W) strictly better than Q(V). Fixing only axis or only linear drive is not success. An exact alternative additionally requires bit-for-bit equality to every target readout, including signed zero.

Keep valid ties/worse states, invalid improvements and all other failures, not just successes. Gap retention remains descriptive and is undefined when its denominator is zero. Do not infer that a lower mismatch count compensates for a failed gate.

Independently reconstruct every claimed success from frozen B, full S selection and replacement IDs, without trusting in-memory caches or classification flags. Also audit a predetermined sample of non-success and alias records. Verify full bytes, score, geometry, legal support, reserve, map uniqueness, and unchanged parents. Shared loader dependencies must remain disclosed.

Aggregation checks:

- Exactly 8 cases and 3,696 labeled singles, no missing or duplicated domain IDs.
- Exact per-case pair counts agree with the saved shortlisted distinct-group domain; total at most 3,968.
- Every shortlist derives reproducibly from its complete singles table under the frozen selector.
- Attempted calls, full oracle calls, unique contextual states, cache hits, aliases and recovery repeats are separately reconciled.
- All successes have independent audit receipts; unverified discoveries cannot support the final headline.

A complete negative single result is bounded to the one-group neighborhood of S. A pair negative applies only to the screened pair domain. Partial timeout coverage supports neither complete negative. No result alone establishes palette infeasibility, exact endpoint impossibility, or that geometry-aware assembly is unnecessary.

## 9. Stop conditions and next decision

Stop with a durable incomplete/failure receipt for parent drift, replay disagreement, missing/duplicate domain identities, illegal maps, cache-context mismatch, failed success reconstruction, output collision, memory cap or cumulative time cap. Do not change gate thresholds or substitute another case. A scheduler interruption is resumable only under the qualified checkpoint rules.

After full aggregation:

- If replacements yield valid advantage, quantify how many cases, singles versus pairs, all score changes and collateral. This motivates a separately frozen geometry/collateral routing constructor; it does not establish exact feasibility.
- If no screened correction succeeds, retain palette expressivity, other pair choices, larger coalitions and different trajectories as open alternatives.
- If an exact distinct endpoint appears, independently audit it first, then propose GC2 fresh-engineering-state validation. AG1 and behavior do not open automatically.

Do not strengthen the removal result into universal non-redundancy: it shows sensitivity to the tested leave-one-group-out operations in saved coalitions. Those are contextual interventions, not an additive allocation of causal credit across groups.

## 10. Execution handoff

On a later execution instruction, the supervisor first reconciles the existing process/output state. Luna xhigh implementation work can then be divided into the checkpointed runner and a separate read-only reviewer of domain/equivalence/recovery tests. One supervisor owns sealing and aggregation. No worker edits sealed parents or launches a competing campaign.

This turn creates the plan only. It does not launch LR1, modify the running CANCEL1 process, or amend an existing seal.
