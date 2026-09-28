# Q10-PF6-S1A: Receipt-Semantic Forensic Audit

Q10-PF6-S1A is a read-only audit of the immutable measured execution of
Q10-PF6-S1. It reconstructs what the saved receipts support without rerunning
PF6, replaying candidates, generating search states, or importing any new
scientific evidence.

The audit reads only the sealed S1 execution receipt, selected sample,
preexecution record, per-run lineage helpers, and the new S1A binding files.
The S1 parent directory and every parent artifact are inputs only. The audit
may write outputs only below this new S1A directory when explicitly run.

The physical-support domain is reconstructed from the immutable PF5 audited
group inventory and its PF5/RMT topology receipt manifest. S1A binds the PF5
audit results, PF5 contract, and the RMT `rows.json`, `moves.jsonl`,
`components.json`, and `endpoints.json` sources used by that lineage. Reading
these support sources is metadata reconstruction; it never reruns PF5/PF6 or
constructs a candidate.

## Questions

S1A answers four receipt-semantic questions:

1. What were the current-search, cumulative best-search, and cumulative
   best-final-gate-valid score streams at each recorded round?
2. Which historical late-round conclusions came from the original first-hit
   interpretation, and which conclusions follow from strict cumulative score
   changes under actual exposure?
3. Which spatial score domains are observable from the receipts: declared
   group rows, physical readout support, and the whole endpoint?
4. Which lineage and metadata claims can be bound to immutable hashes or
   reconstructed from source fields, and which must remain unavailable?

## Frozen inputs

The audit binds the following S1 inputs by SHA-256:

* `q10-pf6-s1-v1/qualification/execution/execution.json`;
* `q10-pf6-s1-v1/qualification/sample.json`;
* `q10-pf6-s1-v1/qualification/PREEXECUTION.json`;
* the Q10-PF6 runner used by S1;
* the Q10-PF5 runtime helper recorded by the Q10-PF6 lineage.

The measured execution is expected to contain 84 selected groups with the
sealed status counts. Hash mismatch is an audit refusal, not a warning.

## Stream definitions

Each trajectory point contains the retained current beam/search objective in
the top-level objective fields and in `best_search_state`. S1A treats those
fields as the current-search score and checks their agreement. The cumulative
best-search stream is the strict running minimum of current-search scores.
The cumulative best-valid stream is the strict running minimum of
`best_final_gate_valid_state` values, ignoring `null` points until a valid
candidate exists.

The score tuple is exactly:

```text
(mismatch_count, total_ulp_distance, residual_l2, max_residual)
```

Prefix values, state hashes, visitation position, and implementation tie
breakers never define improvement.

## Exposure

Round zero is exposed for every measured group. A positive round `r` is
exposed only when both conditions hold:

```text
r <= rounds_completed
r <= coordinates_total
```

Padded receipt points beyond actual exposure are retained for historical
comparison but cannot create corrected late-round events.

## Original versus corrected semantics

S1A preserves the old derivative interpretation: the first round at which the
best-valid stream beats baseline, with no exposure correction, and the old
late/post-round-8 predicates derived from that first round.

The corrected interpretation counts strict changes in the cumulative
best-valid stream at actually exposed rounds. Exposure-adjusted denominators
are `E_9` for post-round-8 events and `E_13` for rounds 13 through 16. The
original counts remain historical derivative semantics; they are not rewritten
in place.

## Spatial domains

The S1 receipts provide declared group row identifiers and whole-endpoint
objective tuples. The bound PF5 audited group inventory supplies the immutable
physical-support row set `P_G` for each selected group. S1A therefore reports:

* declared rows `D_G`: identifiers from the S1 group receipt;
* physical support `P_G`: rows from the bound PF5 group inventory, with an
  equality/overlap check against `D_G`;
* whole endpoint `G`: objective stream observable exactly from the S1
  receipts.

The bound sources do not carry per-row baseline residual sets, candidate
residual vectors, or candidate readout bit vectors for the S1 trajectory. S1A
therefore reports the `P_G` set and support topology exactly, but marks
per-row parity and per-row collateral attribution unavailable. If a bound
receipt ever contains row-level parity fields, the audit may report those
fields; it must not infer them from aggregate mismatch counts.

Collateral damage is reported as not attributable from these receipts. A
whole-endpoint score change is retained as a global diagnostic and is not
relabelled as declared-row repair or support collateral.

## Metadata firewall

`bridge_count` is unavailable because the sealed source marker says it was not
present in the PF5 group receipt. The copied scalar
`threshold_gated_fraction` is quarantined. Threshold metadata is reconstructed
only if row-level threshold records exist in the bound source documents; S1A
does not infer row-level thresholds from category labels or a scalar fraction.

`best_state_hash` is recorded only as a prefix identity. It is never treated
as a committed f32 weight-state hash, state diversity evidence, or adaptive
configuration evidence.

## Coverage and scope

The output must state:

```text
receipt_semantics_coverage = COMPLETE
numerical_replay_coverage = PARTIAL
historical_replay_scope = ONE_RETAINED_CANDIDATE_PER_GROUP
```

S1A does not make a numerical replay claim for all trajectory states. It does
not establish ranking failure, horizon failure, sparse or distributed
realization, endpoint infeasibility, behavioral effects, or DH08B readiness.

## Outputs

The audit script writes `qualification/audit/result.json` and
`qualification/audit/RESULT.md` only when it is run successfully. Tests use
temporary copies and do not modify the S1 parent or create measured artifacts.
