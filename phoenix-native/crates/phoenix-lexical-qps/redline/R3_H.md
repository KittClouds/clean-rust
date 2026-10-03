# REDLINE R3-H: Sealed human negative authority

R3-H freezes a small human-judgment acquisition protocol before any judgments are read. It samples only train/dev queries. Test qrels are never opened by the packet generator.

Each selected query receives four blinded candidates:

1. `system_disagreement` — a candidate with the largest Phoenix/BM25F rank disagreement, recorded privately as the likely BM25F-high or Phoenix-high side.
2. `high_rarity` — the highest `rarest_matched_term` candidate available after removing judged positives.
3. `rarity_control` — an ordinary-rarity candidate matched near the high-rarity candidate's Phoenix rank.
4. `deep_reachable` — the first candidate below Phoenix rank 100 in the exhaustive literal universe.

Selection is deterministic using `blake3(dataset|split|query|document)`. Twelve queries are selected per split, producing 96 packets per dataset. The visible packet contains only an opaque packet id, query, title, document text, an empty judgment field, and an empty note. The hidden ledger contains document ids, split/query ids, stratum, system origin, Phoenix rank, BM25F rank/score, and rarity.

The reviewer should assign exactly one of:

```text
2 = clearly relevant
1 = plausibly or partially relevant
0 = clearly nonrelevant
? = cannot determine
```

Only explicit `2` versus `0` pairs become authoritative training pairs. `1` and `?` remain observation-only. The reviewer should not infer a label from rank, rarity, system identity, or the packet stratum.

## Packet artifacts

SciFact:

- [blinded packets](<D:/phoenix-evals/beir/r3h/scifact/packets.json>)
- [private ledger](<D:/phoenix-evals/beir/r3h/scifact/ledger.json>)
- [sampling receipt](<D:/phoenix-evals/beir/r3h/scifact/receipt.json>)

FiQA:

- [blinded packets](<D:/phoenix-evals/beir/r3h/fiqa/packets.json>)
- [private ledger](<D:/phoenix-evals/beir/r3h/fiqa/ledger.json>)
- [sampling receipt](<D:/phoenix-evals/beir/r3h/fiqa/receipt.json>)

Each dataset has 24 selected queries and 96 packets, balanced across the four strata.

## Validation

Source: `phoenix-native/apps/phoenix-memory-lock/src/bin/qps_v3_r3_h_packet.rs`

Build target: `D:\phoenix-builds\phoenix-qps-v3-r3h`

The release binary compiled successfully. Packet inspection confirmed that visible packets contain no document ids, Phoenix/BM25F scores, ranks, rarity values, or qrels. No serving code changed.

The next gate is to collect the blinded judgments, validate the packet ids and allowed labels, and materialize only `2` versus `0` as an authoritative R3-H pair set. The four rarity arms remain frozen until that validation succeeds.

## Judgment validation and pair materialization

The validator is `phoenix-native/apps/phoenix-memory-lock/src/bin/qps_v3_r3_h_validate.rs`. It checks that packet ids are unique, that the visible packet set exactly matches the private ledger, and that every judgment is one of `0`, `1`, `2`, or `?` (with `null` accepted only while review is incomplete). It never reads test qrels and never exposes the private ledger to the reviewer.

For each `(dataset, split, query_id)` group it materializes only the Cartesian product of explicitly labeled `2` packets and explicitly labeled `0` packets. Labels `1`, `?`, and unfilled packets cannot create update authority. The receipt records `labels_two`, `labels_one`, `labels_zero`, `labels_unknown`, `labels_unfilled`, `queries_with_two_and_zero`, and `authoritative_pairs`.

The release validator was built at `D:\phoenix-builds\phoenix-qps-v3-r3h-validate\release\qps_v3_r3_h_validate.exe` with SHA-256 `E0F9EFDE1E6B32727680D325329BD8522226FA2E9DD18FCB7B348D773139B5EA`.

The untouched packet sets currently produce these fail-closed receipts:

| dataset | packets | queries | 2 | 1 | 0 | ? | unfilled | queries with 2 and 0 | authoritative pairs | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| SciFact | 96 | 24 | 0 | 0 | 0 | 0 | 96 | 0 | 0 | `awaiting_judgments` |
| FiQA | 96 | 24 | 0 | 0 | 0 | 0 | 96 | 0 | 0 | `awaiting_judgments` |

Receipts and empty pair outputs are written to:

- `D:\phoenix-evals\beir\r3h\scifact\authority.json`
- `D:\phoenix-evals\beir\r3h\scifact\pairs.json`
- `D:\phoenix-evals\beir\r3h\fiqa\authority.json`
- `D:\phoenix-evals\beir\r3h\fiqa\pairs.json`

No R3 arm is eligible to run until the packets are filled, the IDs and labels validate, and at least one selected query has both an explicit `2` and an explicit `0`.

The validator's two unit tests pass. A separate four-packet smoke fixture also passed: two explicit `2` labels, one explicit `0`, one `?`, two query groups, one query with both authoritative labels, and exactly one within-query pair. This confirms that `?` does not create authority and that pairs do not cross query boundaries.

## Scientific sufficiency gate

Technical pair materialization is deliberately permissive, but it is not the scientific eligibility rule. The separate gate `phoenix-native/apps/phoenix-memory-lock/src/bin/qps_v3_r3_h_sufficiency.rs` reads validator receipts only and freezes a minimum of **8 query groups per dataset** containing both an explicit `2` and an explicit `0`. Pair count is reported but never substitutes for query-group count. A dataset may proceed independently; a mixed result is allowed when one dataset reaches the threshold and another remains underpowered.

The release gate binary is `D:\phoenix-builds\phoenix-qps-v3-r3h-sufficiency\release\qps_v3_r3_h_sufficiency.exe` with SHA-256 `2F981F7A83FACC2F61DF615731FA952E357A5BB29CA7E760EF68390DF85BEF17`.

The current gate receipt is [scientific_gate.json](<D:/phoenix-evals/beir/r3h/scientific_gate.json>). Both datasets are `awaiting_judgments`, with zero eligible datasets. The receipt is intentionally independent from the packet validator and does not authorize any R3 arm by itself.

Review must be performed by an independent blinded reviewer who receives only the visible packet file and the four-label rubric. The reviewer must not see the ledger, strata, rankings, rarity values, BM25F values, system identity, or this experiment description. After the first pass, a 10–15% repeat subset should be regenerated under fresh opaque ids. `2↔0` reversals are authority failures; `1↔2` and `?` disagreements remain uncertainty observations.
