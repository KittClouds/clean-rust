# Gate 16.7 OSV1 Final Evidence and Mathematics Report

**Audit date:** 2026-08-16  
**Audited source root:** C:/Users/shuga/AppData/Local/Temp/northstar-regression-10dc04428bc74210a5830a07d402010c/research/market-objects  
**Release repository:** C:/Users/shuga/AppData/Local/Temp/northstar-regression-10dc04428bc74210a5830a07d402010c  
**Purpose:** trace the data, contracts, reports, calculations, receipts, hashes, source code, and release checks from the supplied root through Gate 16.7.

## 1. Audit result

The supplied root contains the complete recorded chain from the RG3 raw corpus through Gate 14, Gate 15, Gate 15.5, Gate 16, Gate 16.5, Gate 16.6 closure, and Gate 16.7 release packaging.

The final release record is internally consistent:

| Item | Recorded value |
|---|---|
| OSV1 scientific root | 6e18e10fc0fb3571aa21b4e20105f783dafe2872812d217d672ab5e959bb890d |
| Release identifier | OSV1_V1_0_0 |
| Annotated tag | osv1-v1.0.0 |
| Tag target | 9ced26cb3a7ae6aeefe6c1a2f63a493e28ceca48 |
| Release pack bytes | 56,789,311 |
| Release pack SHA-256 | 502d55a37e0592901906f3aa46f6298fb3f5d0614a4150b9e61fecb8d480d980 |
| Release payload tree SHA-256 | 20d27c6e7f2b8d420b2fbe0f3391c4097a27880725a44ac18634a08eab6fdd90 |
| Release entries | 93 |
| Cold rehydration | PASS |
| Consumer smoke | PASS |
| Hash mismatches | 0 |
| Undeclared authoritative reads | 0 |
| Absolute resolution attempts | 0 |
| Source mutations | 0 |
| Gate 16.8 | not present / not implied |

The tag target is written exactly as observed from the local annotated tag and the remote peeled tag. The local checkout itself is clean at commit 8980236bea7a842ea2d9ea18ecd59ced668026ce, and its branch is synchronized with its upstream at 0 ahead / 0 behind. The release tag remains a named historical release point at 9ced26cb3a7ae6aeefe6c1a2f63a493e28ceca48.

Exact tag target:

9ced26cb3a7ae6aeefe6c1a2f63a493e28ceca48

For unambiguous machine use, the exact value is also recorded in the source tag and release receipts. No source file in the release checkout was modified by this report; the report is stored outside that checkout.

## 2. Audit boundaries

The audit used these evidence classes:

1. Markdown reports in the supplied root.
2. Frozen JSON contracts.
3. Machine receipts and exit reports.
4. TSV, Zstandard, NSMOR, and packed data artifacts.
5. Rust and MQL5 source files present in the root.
6. PowerShell generation and verification tools present in the root.
7. Local Git status, tag, branch, and remote tag evidence.

Build output under target was counted separately and was not treated as authority. No result was reconstructed from build output when a sealed receipt existed.

The report preserves the distinction between:

- raw observations;
- deterministic derived records;
- machine-declared limits;
- release transport records;
- read-only consumer records;
- source regeneration that is not evaluable because the external source capsule is absent.

## 3. Root inventory

### 3.1 Files outside target

The supplied root contains 896 files outside target, totaling 228,983,595 bytes.

| Top-level area | Files | Bytes |
|---|---:|---:|
| artifacts | 814 | 228,223,561 |
| campaigns | 3 | 4,789 |
| contracts | 11 | 34,775 |
| crates | 36 | 458,285 |
| mql5 | 5 | 45,581 |
| tools | 16 | 163,293 |
| Markdown and root control files | 11 | 53,311 |
| **Total** | **896** | **228,983,595** |

### 3.2 Extension inventory outside target

| Extension | Files | Bytes |
|---|---:|---:|
| .json | 308 | 5,262,046 |
| .tsv | 413 | 70,273,943 |
| .zst | 3 | 111,648,137 |
| .nsmor | 43 | 39,942,939 |
| .rs | 34 | 456,747 |
| .ps1 | 16 | 163,293 |
| .md | 8 | 39,038 |
| .ini | 43 | 29,775 |
| .mq5 | 2 | 13,117 |
| .mqh | 3 | 32,464 |
| other control/text/binary | 23 | 1,297,011 |

### 3.3 Artifact-family inventory

| Artifact family | Files | Bytes |
|---|---:|---:|
| Gate 14 build proof | 1 | 553 |
| RG3 qualification | 96 | 9,451,013 |
| RG3 production batches | 565 | 69,060,804 |
| Gate 15 discovery and replay variants | 24 | 2,364,772 |
| Gate 15 sealed corpus variants | 16 | 376,236 |
| Gate 15.5 atlas | 19 | 6,878,168 |
| Gate 16 geometry | 18 | 21,586,880 |
| Gate 16.5 loss census | 21 | 59,179,284 |
| Gate 16.6 closure preparation | 18 | 801,905 |
| OSV1 release payload and proof | 7 | 56,849,655 |

The family table is a navigation summary. The exact per-file hashes are retained in the sealed manifests and the release manifest. Family totals are byte counts from the audited directory, not rounded estimates.

## 4. Report and contract files

### 4.1 Markdown report hashes

| File | Bytes | SHA-256 |
|---|---:|---|
| README.md | 5,448 | e764f7bffa19d59fc6eeb56c802cf8c6591bf5beaeb0938158890f14b390d7cc |
| GATE15_5_TRI_INSTRUMENT_ATLAS.md | 3,573 | 6c21fc6ce7f8b007c0e6bd82602ac3de7c3b4300b9c48ce47de409edd6238cfc |
| GATE16_REPRESENTATION_DISTANCE_LAB.md | 4,026 | 36c72445d8cc9265d6ed27381e38ff82a9c87bb1a052f9a00255a8879a90faf6 |
| GATE16_5_REPRESENTATION_LOSS_CENSUS.md | 6,427 | ba3a2ecd5c527764deae0abec8cda5ec96d46130c74a32cda8e603d30566f596 |
| GATE16_6_OSV1_CLOSURE.md | 11,770 | 483cb3d606c630f7624fbe6aa88b9c0e6c5236359f44c6807de51e17f9af69d8 |
| GATE16_7_OSV1_RELEASE.md | 3,680 | 207121e7bc681649a4ed2ca0d08d2f9d79a0976331ab339a8209671cd50bb62d |
| OSV1_BRANCH_POINT.md | 2,765 | 532c8eec064a86137d09f63aa096a0c3d0881365aa18a91a933f0ee41b5fef26 |
| contracts/object_ontology.md | 1,349 | 15900eebaae3474d9b67ce8a95db3e4a36da9088bb99f3925ca5e050221d6065 |

### 4.2 Frozen contract hashes

| Contract | Bytes | SHA-256 |
|---|---:|---|
| rg3_identity.json | 708 | 1e60c4ac76ed5164e7d9ee67621c6894f4f0117fb4a3c53c6b2dca619fa8f5e4 |
| raw_authority.json | 1,037 | fc1256deee802b218fddbab5f4b085e85cd33953997b41a957f039a6d82ac651 |
| schema_dictionary.json | 1,858 | 82cef8c0ce1fe2aa4cda3a46cc3b8814669efd07f60974ed097e5b0ca745cbf3 |
| gate15_discovery_protocol.json | 1,485 | 72e0a135785561cffd8b33a194381cdf3f37943c5355f3c38013ce70a4f6df02 |
| gate15_discovery_adjudication_v2.json | 2,203 | 6dec951680245ca8da603c7a3370b9a23b213e6a2975c7542dfb594c7e27989 |
| gate15_5_tri_instrument_atlas.json | 3,020 | 76a12432bd3fadbd3e0dc3df035b69ccaf09d8fdb9a4267210588f5baba17875 |
| gate16_representation_distance_laboratory.json | 4,912 | f4a48b15264c0e2a193947d3093f484dcc54ea26cd9bda0ca5e4d1d83eeadb5b |
| gate16_5_representation_loss_census.json | 2,305 | aa8894dedd689ac9ff593d30d7801eb62b8d594cf2825f80bbf70683cfcd77fd |
| gate16_6_osv1_closure.json | 11,038 | d7009cf6862632f3dba7535ab4316148892657b9cce996bfb05f6e3948210587 |
| gate16_7_osv1_release.json | 4,860 | bcd2b645aa2257c9808811454bfd53995382f866c1eea6966041b72a3968463d |

## 5. Raw data authority and schema

The raw authority contract declares immutable closed-bar records containing:

- closed-bar timestamp;
- open, high, low, close;
- origin ATR;
- origin seed and containment geometry;
- raw displacement, maximum displacement, opposite displacement, and return depth;
- close-path length;
- velocity and acceleration per bar;
- state and event codes;
- terminal and censor reasons;
- structural snapshot hash;
- node geometry at observation.

The raw schema uses the explicit null token \N. Primary keys are:

| Dataset | Primary key |
|---|---|
| measurement_runs | run_key, invocation_id, record_type |
| compression_objects | run_key, compression_id |
| compression_samples | run_key, compression_id, bar_time |
| compression_events | run_key, sequence |
| expansion_objects | run_key, expansion_id |
| expansion_samples | run_key, expansion_id, bar_time |
| expansion_events | run_key, sequence |
| object_relations | run_key, relation_id |
| structural_samples | run_key, bar_time |

Foreign-key checks bind samples and events to their parent object, and destination identifiers are nullable only when the destination is not yet available.

Raw invariants include strict sample ordering, no sample after terminal time, terminal summaries reduced from raw samples, explicit final censoring of active objects, and prohibition of derived values in authoritative datasets.

Derived records bind the raw corpus hash and a deterministic recipe hash. The raw corpus is append-only until sealed; derived records are replaceable from the sealed raw corpus and the recipe.

## 6. Gate 14: initial RG3 qualification

### 6.1 Qualification population

The qualification report is PASS for six instruments:

| Instrument | Compression objects | Compression samples | Expansion objects | Expansion samples | Relations | Structural samples |
|---|---:|---:|---:|---:|---:|---:|
| DE40 | 12 | 332 | 11 | 724 | 89 | 1,055 |
| FRA40 | 13 | 416 | 13 | 694 | 94 | 1,104 |
| JPN225 | 11 | 285 | 11 | 742 | 66 | 1,096 |
| US30 | 12 | 390 | 12 | 718 | 55 | 1,104 |
| US500 | 13 | 379 | 13 | 731 | 74 | 1,104 |
| USTEC | 14 | 367 | 14 | 745 | 53 | 1,104 |
| **Total** | **75** | **2,169** | **74** | **4,354** | **431** | **6,567** |

The qualification corpus verification records 78 sealed files and six instrument roots. Every instrument row carries a raw corpus hash, packed hash, derived-recipe hash, and PASS status.

### 6.2 Gate 14 build evidence

The Gate 14 build receipt records:

- MQL5 compiler: MetaEditor64 X64 Regular.
- MQL5 errors: 0.
- MQL5 warnings: 0.
- Rust target directory: D:/northstar-target-gate14.
- Rust format: PASS.
- Rust tests: 4 passed, 0 failed.
- Explicit performance lane: 1.
- Clippy with warnings denied: PASS.
- Release build: PASS.
- Memory-mapped validation rows: 100,000.
- Observed memory-mapped validation time: 84,053 microseconds on the recorded workstation.

Gate 14 is therefore the first sealed data-and-build boundary in the supplied root.

## 7. Gate 15: sealed 42-run corpus and three derived views

### 7.1 Corpus

Gate 15 seals 42 runs and 1,091 objects:

| Instrument | Objects |
|---|---:|
| DE40 | 160 |
| FRA40 | 165 |
| JPN225 | 182 |
| US30 | 183 |
| US500 | 199 |
| USTEC | 202 |
| **Total** | **1,091** |

Object counts are 553 compression and 538 expansion. The minimum per instrument is 160.

The sealed corpus totals are:

| Record group | Count |
|---|---:|
| compression objects | 553 |
| expansion objects | 538 |
| compression samples | 14,972 |
| expansion samples | 38,458 |
| object relations | 4,408 |
| structural samples | 55,150 |

The canonical corpus root is:

68ed0ad0059390b683faaf2b7d607c0e1e763dcbf9b8368a8ae5a1e85d8684b8

The Gate 15 manifest verifies 546 sealed files and records two quarantined artifacts. Quarantine is retained as evidence and is not admitted into the sealed 42-run population.

### 7.2 Censoring and missingness

| Object kind | Censored count | Rate |
|---|---:|---:|
| compression | 15 | 0.027124773960216998 |
| expansion | 28 | 0.05204460966542751 |

Terminal reason counts are recorded as:

- compression: reason 1 = 300, reason 2 = 238, reason 6 = 15;
- expansion: reason 4 = 510, reason 5 = 1, reason 6 = 27.

Destination compression is unavailable before handoff and remains null for censored expansions. The source reports this as availability-time missingness, not as an absent object.

### 7.3 View construction recipe

Three view recipes are retained for each object kind:

- summary geometry;
- resampled shape;
- mirrored hybrid geometry.

The discovery contract uses deterministic k-means with:

- k from 2 through 8;
- 8 initializations;
- maximum 100 iterations;
- selection value = silhouette × stability × support penalty;
- minimum samples per object = 4.

V2 uses empirical 1st and 99th percentile winsorization, z-score standardization after winsorization, and clamping to [-6, 6]. Support requires at least 30 objects, four instruments, and four windows; unsupported partitions remain an explicit null assignment.

The V1 result is retained as COLLECT_MORE. V2 does not overwrite V1.

### 7.4 Family-system counts and stability

| Kind | View | Supported | Noise | Noise rate | Common families | Mean seed ARI |
|---|---|---:|---:|---:|---:|---:|
| compression | summary | 538 | 0 | 0.000000 | 2 | 0.8976769151 |
| compression | shape | 538 | 0 | 0.000000 | 2 | 0.9957747926 |
| compression | hybrid | 538 | 0 | 0.000000 | 2 | 0.9740790155 |
| expansion | summary | 498 | 12 | 0.023529 | 2 | 0.9108144052 |
| expansion | shape | 510 | 0 | 0.000000 | 2 | 0.8309302687 |
| expansion | hybrid | 510 | 0 | 0.000000 | 3 | 0.9787750066 |

Maximum family concentration is 24.0% by instrument and 23.8095238% by window. Mean raw cross-view ARI is 0.0090842658 for compression and 0.2828735194 for expansion.

## 8. Gate 15.5: relational atlas

### 8.1 Bridge operator

For each object event time t, the bridge chooses:

1. the exact structural snapshot at t, when present;
2. otherwise the latest snapshot s satisfying s ≤ t;
3. failure when the gap exceeds one source closed-bar interval.

The bridge therefore records a causal as-of relation rather than a future lookup. Every bridge receipt stores object event time, selected snapshot time, age in seconds, join mode, generation, snapshot hash, and regional-basis hash.

The interval operator is closed temporal intersection:

```text
overlap_start = max(object_start, interval_start)
overlap_end   = min(object_end, interval_end)
overlap_seconds = max(0, overlap_end - overlap_start)
```

The interval source is not co-collected for the 42 RG3 run identities, so the receipt uses unavailable-authority status rather than converting absence into a zero intersection.

### 8.2 Atlas data

| Record | Count |
|---|---:|
| objects | 1,091 |
| lineages | 538 |
| lineages with destination | 510 |
| bridge receipts | 2,735 |
| exact bridge receipts | 2,690 |
| as-of bridge receipts | 5 |
| structural-context null receipts | 40 |
| typed graph nodes | 3,236 |
| typed graph edges | 10,106 |
| global correspondence records | 6 |
| conditioned correspondence records | 69 |
| constraint-to-motion correspondence records | 108 |
| object phenotypes | 131 |
| lineage phenotypes | 470 |

Null and availability counts are distinct:

| State | Count |
|---|---:|
| auction authority unavailable | 1,091 |
| censored destination | 28 |
| data gap | 0 |
| not applicable | 3,273 |
| null family | 12 |
| null structural context | 40 |

The atlas receipt records 42 source runs, 1,091 source objects, unchanged Gate 15 view hashes, complete bridge receipts, monotonicity, namespace qualification, and unopened confirmation windows.

## 9. Gate 16: frozen data views and distance calculations

### 9.1 View contracts

Gate 16 freezes raw and canonical variants of four view classes:

| Class | Raw/canonical variants | Main contents | Distance contracts |
|---|---|---|---|
| summary | 2 | counts, duration, ATR-normalized widths/displacements, categories | robust L1, robust L2, mixed Gower |
| trajectory | 2 | 21 common-grid samples, continuous channels, state as-of values | pointwise L2, derivative-aware L2, bounded DTW |
| event sequence | 2 | event, direction, state, terminal code, bar/second deltas | typed edit with duration |
| process graph | 2 | typed nodes, directed edges, WL round 1 and 2 multisets | typed multiset Jaccard, WL2 multiset Jaccard |

The eight view variants are evaluated through nine distance contracts. Summary continuous channels use per-kind median/IQR scaling and clipping at ±12 IQR. Trajectory comparison uses 21 points over a common admitted interval, linear interpolation for continuous channels, and left-continuous as-of sampling for state channels.

Reflection M is checked as an involution:

```text
M(M(x)) = x
```

Conditional canonicalization C is checked as idempotent:

```text
C(C(x)) = C(x)
```

Censored suffixes are never filled, extended, or extrapolated. Shared-prefix comparison uses the common horizon:

```text
horizon = min(observed_bars_left, observed_bars_right)
```

### 9.2 Gate 16 population and output counts

| Measure | Count |
|---|---:|
| source runs | 42 |
| source objects | 1,091 |
| completed objects | 1,048 |
| censored objects | 43 |
| representation variants | 8 |
| distance contracts | 9 |
| comparison receipts | 6,546 |
| partial distance vectors | 1,091 |
| neighborhood rows | 64,150 |
| packed vector bytes | 1,049,848 |
| available values | 6,415 |
| censored suffix values | 43 |
| not-comparable values | 131 |

Gate 16 canonical laboratory SHA-256:

49937da6b2f3abac1f6426a15b40525ec614b74052446437bbb484c93aefe833

### 9.3 Exact distance functions in the Rust source

The implementation records these calculations:

Robust L1 over n channels:

```text
d_L1(x,y) = (1 / max(n,1)) * Σ_i |x_i - y_i|
```

Robust L2:

```text
d_L2(x,y) = sqrt((1 / max(n,1)) * Σ_i (x_i - y_i)^2)
```

Mixed Gower:

```text
d_G = (Σ_i min(|x_i-y_i| / 12, 1) + category_mismatches)
      / max(number_continuous + number_categorical, 1)
```

State mismatch is the fraction of unequal state positions. Pointwise trajectory distance is:

```text
d_point = d_L2(continuous) + 0.25 * state_mismatch
```

Derivative-aware distance is:

```text
d_derivative = d_point + 0.5 * d_L2(first_differences)
```

Bounded DTW uses a window of 2. Its point cost is continuous L2 plus 0.25 for a state mismatch, and the accumulated path cost is divided by max(number of rows, number of columns).

Shared-prefix pointwise distance uses 21 samples over the common horizon and computes:

```text
d_prefix = sqrt(squared_channel_error / (21 * channel_count))
            + 0.25 * (state_difference_count / 21)
```

Event-token substitution is:

```text
0.75 * event_code_mismatch
+ 0.25 * direction_mismatch
+ 0.25 * state_mismatch
+ 0.25 * terminal_reason_mismatch
+ 0.1 * |ln(delta_seconds_left + 1) - ln(delta_seconds_right + 1)|
```

Typed edit distance uses insertion cost 1, deletion cost 1, the substitution cost above, dynamic programming, and normalization by max(left length, right length, 1).

For multiset graph distance, the Rust implementation uses:

```text
d_J(A,B) = 1 - Σ_k min(count_A(k), count_B(k))
              / Σ_k max(count_A(k), count_B(k))
```

An empty union returns 0.0.

### 9.4 Gate 16 deterministic and performance evidence

- Rust tests: 19 passed.
- Clippy with warnings denied: PASS.
- Frozen distance probes: 24 passed.
- One-thread/four-thread output files: 18 compared, 0 mismatches.
- Input ordering: canonical identity sort before derived construction.
- Scalar/SIMD parity: PASS.
- Censored suffix fabrication: false.
- Confirmation windows opened: false.

The 100,000-record computational fixture is explicitly non-scientific. Recorded measurements:

| Operation | Microseconds |
|---|---:|
| packed construction | 959 |
| scalar scan | 574 |
| parallel scan | 493 |
| top-10 selection | 83 |
| memory-mapped traversal | 15,210 |

Fixture dimensions are 100,000 records × 10 dimensions, packed bytes 4,000,000, four threads. Scalar and parallel distance hashes are both d078db2cca2fca1ead345b14c9c8ff69a5c038fbf454f78767082b138824ed16. Maximum scalar/SIMD error is 2.9496848583221436E-05.

## 10. Gate 16.5: exhaustive loss census

### 10.1 Pair arithmetic

The same-kind population is 553 compression objects and 538 expansion objects. The exhaustive unordered-pair count is:

```text
C(553,2) + C(538,2)
= (553 * 552 / 2) + (538 * 537 / 2)
= 152,628 + 144,453
= 297,081 pairs
```

The loss census evaluates 20 frozen contracts:

```text
297,081 pairs * 20 contracts = 5,941,620 evaluations
```

### 10.2 Census results

| Result | Count |
|---|---:|
| contract-qualified evaluations | 5,941,620 |
| exact-zero relations | 498,115 |
| unique affected object pairs | 161,957 |
| compression affected pairs | 31,811 |
| expansion affected pairs | 130,146 |
| epsilon-near relations | 0 |
| typed not-comparable relations | 276,174 |

Exact zero means the frozen finite distance value equals exactly 0.0. Numeric near-zero uses 1E-06; edit and graph contracts use 0.0. Exact and near-zero records are never merged.

### 10.3 Raw distinctions retained beside zero records

For event records:

| Kind | Raw zero | Canonical zero |
|---|---:|---:|
| compression | 753 | 1,521 |
| expansion | 2,918 | 4,767 |

For graph records:

| Kind and graph distance | Raw | Canonical |
|---|---:|---:|
| compression typed multiset | 15,955 | 31,811 |
| compression WL2 | 15,945 | 31,785 |
| expansion typed multiset | 66,184 | 130,146 |
| expansion WL2 | 66,184 | 130,146 |

Canonical expansion graph class sizes are 510, 27, and 1. Raw expansion graph class sizes are 290, 220, 18, 9, and 1.

Every event/graph exact-zero pair has a raw-history and continuous-trajectory difference receipt. The pair census therefore records the distinction that was not carried by the tested view.

### 10.4 Neighborhood turnover

| Kind | Mean top-10 Jaccard | Mean shared-rank correlation |
|---|---:|---:|
| compression | 0.3814 | 0.9800 |
| expansion | 0.4271 | 0.8583 |

The Gate 16 report separately records event/graph top-10 overlap of 0.185 for compression and 0.064 for expansion.

### 10.5 Point-state pressure calculation

The declared unit is the anchor-record median distance to records in the same versus a different available grouping. The uncertainty record is a deterministic instrument-grouped run-block bootstrap with 4,096 replicates and seed 16520260813.

| Quantity | Value |
|---|---:|
| same-stratum pooled median | 1.272146 |
| different-stratum pooled median | 1.298012 |
| pooled difference | 0.025866 |
| anchor median delta | 0.005597 |
| bootstrap p10 | 0.002665 |
| bootstrap p50 | 0.005597 |
| bootstrap p90 | 0.008806 |
| positive run blocks | 25 / 42 |
| positive instrument blocks | 5 / 6 |
| positive calendar-window blocks | 6 / 7 |
| exact bridge joins | 1,049 |
| as-of bridge joins | 5 |
| unavailable contexts | 37 |

The US30 instrument aggregate is negative in this diagnostic. Interval conditioning remains unavailable in the recorded source lineage.

### 10.6 Gate 16.5 replay and performance

- One-thread elapsed time: 49,113 ms.
- Four-thread elapsed time: 44,437 ms.
- 16 artifact files compared.
- Byte mismatches: 0.
- Logical census SHA-256: f88bbdffa5c6579617b1ade8ca6c1361da0aba3cc681a6a04e89c5be0c9c5cda.
- Physical artifact-set SHA-256: 8d8ab934fa9cf4a352a0bb51ee6fd8455ae7a55c4a4110408147727295abe731.
- Zstandard level: 9 for the two compact census streams.
- Release profile: opt-level 3, fat LTO, one codegen unit, aborting panic, D:/northstar-target-gate165.

## 11. Gate 16.6: OSV1 closure

### 11.1 Composite identity

The closure contract records four named components:

- stage-qualified implementation matrix;
- admitted composite configuration census;
- sealed RG2 and RG3 empirical branches;
- immutable artifact and receipt DAG through Gate 16.5.

### 11.2 Stage matrix

| Stage range | MT5 status | Rust status | Parity/status |
|---|---|---|---|
| C1 raw producers | authoritative | not implemented for independent parity | OPEN |
| C2 through D3 | behavioral oracle | independent reconstruction | PASS on bounded oracle |
| RG3 object derivation | raw observational authority | deterministic derivation and sealing | rebuild determinism PASS |

The PASS rows are bound to the five-session US30 M5 oracle containing 5,155 frames. The stage matrix has 13 rows and 11 evidence records. Adjacent evidence types remain separately labeled and are not merged into the stage matrix.

### 11.3 Theta0 census

The admitted composite clock vector is recorded as:

| Component | Clock |
|---|---|
| Master | M5 |
| VolKitt | H1 |
| Profile | H1 |
| Day Swings | M5 |
| Wayne | D1 |

The completed census contains 134 fields across 42 admitted runs. Every field carries a typed value summary, evidence class, run binding, consumption status, configuration-hash membership, and exact provenance locators.

All 42 run ledgers carry configuration hash 11558041990222457072. The evidence classes are RUN_RECORDED, CAMPAIGN_CONFIGURED, COMPILED_DEFAULT, RECOVERED_FROM_COLLECTION_ENVIRONMENT, DECLARED_HASHED_NOT_OPERATIONAL, and UNAVAILABLE.

The source-recovered count is 84. Those fields are explicitly not run-bound when the exact source binary or expanded configuration text is absent from the admitted run receipt.

### 11.4 Machine findings and insufficiencies

The machine findings ledger contains:

| Record | Count |
|---|---:|
| sealed machine evidence nodes | 8 |
| findings | 24 |
| explicit insufficiencies | 18 |
| human-summary sources | 0 |
| Markdown sources | 0 |
| unsealed machine sources | 0 |

Allowed source kinds are MACHINE_DERIVED, ARTIFACT_DECLARED, and HUMAN_SUMMARY. The last kind is represented in the type system but has canonical authority count 0.

### 11.5 Ancestry and closure rebuild

The ancestry is a two-branch directed acyclic graph:

```text
RG2 -> Phase 10 -> Phase 10.5 -> Phase 11 -> Gate 13R
RG3 -> Gate 14 -> Gate 15 -> Gate 15.5 -> Gate 16 -> Gate 16.5
```

Gate 16.6 root receipt:

| Field | Value |
|---|---|
| root manifest SHA-256 | e7f54f73d20fcf784e7920fad1a8688835fa85705f3a23357a474e6a120eef31 |
| logical OSV1 SHA-256 | 6e18e10fc0fb3571aa21b4e20105f783dafe2872812d217d672ab5e959bb890d |
| logical ancestry SHA-256 | 30ed4e61b090e96e56f20f096d420bb9cfa87aef9ddc88876bc8579bf7acb4cc |
| physical child-set SHA-256 | a8986e4a21645d4c4a05b942847d63740e65692d3af0a5d72bd8057f9f4266b5 |
| child artifact count | 15 |
| receipt written last | true |
| confirmation windows opened | false |

The double-rebuild proof records two executions, 17 compared closure artifacts, zero byte mismatches, canonical match true, acyclic ancestry true, verified root receipt true, source-kind requirement true, and human-summary authority count 0.

Source dependency closure records:

- MT5 recursive source files: 26.
- MT5 include edges: 36.
- unresolved MT5 includes: 0.
- auction-parity local Rust files: 53.
- auction-parity local crates: 10.
- auction-parity locked packages: 52.
- market-objects local Rust files: 40.
- market-objects local crates: 1.
- market-objects locked packages: 65.
- logical closure SHA-256: ef21a72a0109c179469e8b4fd7820a8db218d687622a21c5bb932792e07d42fa.

## 12. Gate 16.7: release payload and consumer boundary

### 12.1 Release manifest

The release manifest is NORTHSTAR_GATE16_7_OSV1_RELEASE_MANIFEST_V1 with status SEALED.

| Manifest field | Value |
|---|---|
| release ID | OSV1_V1_0_0 |
| OSV1 root | 6e18e10fc0fb3571aa21b4e20105f783dafe2872812d217d672ab5e959bb890d |
| Theta0 hash | fbcbfdfb79e91cbb70e3e39b673d2cfa15164000c28002b6f76f2e9ce98a2fa7 |
| ancestry hash | 30ed4e61b090e96e56f20f096d420bb9cfa87aef9ddc88876bc8579bf7acb4cc |
| findings hash | d2fa9783ee7a75b5748e3dd6c1241d340f8b443b623c8f8b5ccdfaa7a473f697 |
| parity matrix hash | 82e44071b792f206da9b1c3fdb0c60a9c7b454ca87a3f4a0da5f10af6c656eae |
| logical manifest hash | af25c11951262a74764fe3127e12f9b8ec4184dff1075b5b6065370101d384d9 |
| source capsule | absent optional adjunct |

The release manifest binds 93 immutable entries. It includes Gate 16.6 closure records, Gate 15 through Gate 16.5 authorities, findings, insufficiencies, provenance, and the two-branch ancestry artifacts.

### 12.2 Packed transport layout

The release archive is a deterministic content-addressed transport container.

| Layout field | Value |
|---|---:|
| magic | NSOSV1R1 |
| format version | 1 |
| header bytes | 96 |
| entry bytes | 96 |
| entries | 93 |
| raw bytes | 88,620,911 |
| packed bytes | 56,789,311 |
| compression | Zstandard level 19 per entry, no timestamp |

Each packed member stores canonical relative path, kind, compressed length, raw length, and raw SHA-256. The reader validates header identity, table bounds, member bounds, UTF-8 paths, relative-path safety, duplicate paths, decompressed length, and member SHA-256.

### 12.3 Read-only consumer contract

The consumer namespace is NORTHSTAR_AUTHORITY. Derived sidecars use PHOENIX_DERIVED and are written outside the release payload directory.

Permitted operations are READ, FILTER, PROJECT, VISUALIZE, and DERIVE_SIDECAR.

The consumer transports nine tagged states:

1. NULL
2. CENSORED
3. NOT_APPLICABLE
4. NOT_EVALUABLE
5. INSUFFICIENT_SUPPORT
6. OPEN
7. FROZEN_UNOPENED
8. SOURCE_RECOVERED
9. NOT_RUN_BOUND

The Rust type rejects null, empty string, zero, false, unknown, and unknown enum variants. The consumer smoke verified all nine states, all three source kinds, and 84 source-recovered Theta0 fields.

### 12.4 Cold rehydration proof

Two cold runs were recorded: one against a detached prerelease snapshot and one against the release commit. Both produced byte-identical proof artifacts.

| Check | Result |
|---|---|
| original Gate 16.6 preparation reachable | false |
| release entries read | 93 |
| extracted entries | 93 |
| hash mismatches | 0 |
| declared authoritative reads | 93 |
| undeclared authoritative reads | 0 |
| absolute resolution attempts | 0 |
| OSV1 root exact | PASS |
| payload tree before/after | identical |
| source mutation count | 0 |
| sidecar outside payload | true |

Cold source regeneration is NOT_EVALUABLE because the external MT5 source capsule is absent. Portability without that capsule is NOT_PORTABLE_WITHOUT_EXTERNAL_SOURCE_CAPSULE. The optional capsule is outside OSV1 scientific identity.

## 13. Exact release and receipt hashes

| File | SHA-256 |
|---|---|
| osv1_release.pack.zst | 502d55a37e0592901906f3aa46f6298fb3f5d0614a4150b9e61fecb8d480d980 |
| osv1_release_manifest.json | 817550ab5233aae6fbc3e33f7607d96345f2e9234df47a74b3ad939e7c9f0b78 |
| osv1_consumer_contract.json | 92306d4cc8ea53fc4e2e98b42feef40a718223f95a9ed7b187cd14c8adc0b426 |
| osv1_release_pack_receipt.json | 8e05cb62e3adfb259ade311ed4a1a30583b04891af0dd103d371c59f1e7ee7d4 |
| osv1_cold_release_proof.json | 03375d8559516dca85af6cd6a673ea1a774b5c7a91cff49aa763e1928c15a84c |
| osv1_cold_rehydration_receipt.json | 5020e733e1593c4eebdad0272eae57b8792ed88bbe66e774e1feaf505310cf6e |
| osv1_phoenix_consumer_smoke_receipt.json | 445b95ca2906c6020d21cc66138e319d8477b86dbecd9b0e5ebd5cd45e767733 |

## 14. Source implementation evidence

### 14.1 Release crate

The isolated release crate uses:

- memmap2 for the archive mapping;
- zerocopy for fixed-layout header and entry reads;
- SHA-256 for member and release checks;
- Zstandard for deterministic per-entry frames;
- hashbrown for duplicate-path checks;
- memchr for evidence-token scans;
- serde and serde_json for typed contracts;
- thiserror for explicit failure records.

The fixed structures are 96-byte header and 96-byte entry records. Header validation checks magic, version, file length, table end, name offset, data offset, and bounds. Entry validation checks path bounds and compressed-data bounds.

Read validation checks decompressed length and SHA-256. Path validation rejects absolute paths, parent traversal, roots, and prefixes. Duplicate packed paths are rejected.

The consumer smoke checks namespace agreement, required permissions, tagged-state transport, evidence-token presence, source-recovered field count, the OPEN parity marker, human-summary count zero, and unchanged pack SHA-256 before and after consumption.

Unit tests in the release crate cover fixed layout sizes, parent traversal rejection, and illegal tagged-state coercions.

### 14.2 Market-object crate

The market-object crate contains dedicated binaries for sealing, discovery, atlas generation, Gate 16 geometry, Gate 16 performance, and Gate 16.5 loss census. It uses BLAKE3, Zstandard, hashbrown, memchr, memmap2, Rayon, serde, SHA-256, zerocopy, and wide SIMD support.

The source tree contains the raw reader, packed view, Gate 15, Gate 15.5, Gate 16, and Gate 16.5 modules. The data calculations reported above are implemented in the source rather than reconstructed from the reports.

### 14.3 Source tools

The root contains generators and checks for:

- RG3 corpus confirmation;
- Gate 15 confirmation and replay;
- OSV1 ancestry;
- OSV1 machine findings;
- OSV1 parity matrix;
- OSV1 release packing;
- OSV1 source closure;
- OSV1 Theta0 census;
- OSV1 authority artifacts;
- OSV1 closure;
- OSV1 cold release;
- parity matrix;
- source closure.

## 15. Branch point and external source companion

The branch-point report records OSV1 as the immutable parent of subsequent named branches. It separately records the MT5 authority companion:

| Field | Value |
|---|---|
| repository | https://github.com/KittClouds/northstar-mt5-authority |
| tag | mt5-authority-v1.0.0 |
| commit | 390ea55e9834ea739996c3e533f1e0025dcfcea9 |
| local storage policy | D_DRIVE_ONLY_NOT_REMOTE |
| local root | D:/northstar-mt5-corpus/osv1-mt5-freeze-v1 |
| payload files | 590 |
| payload bytes | 11,986,996,702 |
| manifest SHA-256 | 58d13f99985a3256c00a0b2a4ed895cd8dc778db969dae6f20da8e54f18cf768 |
| remote payload storage | false |

The companion manifest and receipt are separate from OSV1 scientific identity. The external source capsule required for source regeneration is absent from the Gate 16.7 release payload.

## 16. Pass, open, and not-evaluable states

### PASS records

- Gate 14 MQL5 compile and Rust build proof.
- RG3 six-instrument qualification.
- Gate 15 sealed corpus and replay checks.
- Gate 15.5 bridge and atlas receipt.
- Gate 16 frozen view contracts and replay proof.
- Gate 16.5 exhaustive pair accounting and replay proof.
- Gate 16.6 root, ancestry, source closure, findings, Theta0, and double-rebuild proof.
- Gate 16.7 pack, cold rehydration, typed consumer, and payload-unchanged proof.

### OPEN or deferred source states

- Independent C1 Rust producer parity is OPEN.
- The exact external MT5 source capsule is absent.
- Alternative composite configurations are not admitted to OSV1.
- The expanded source defaults recovered from the collection environment remain not run-bound when exact run receipts do not contain them.

### NOT_EVALUABLE states

- Cold source regeneration without the external source capsule.
- Interval conditioning because the required RG2 and RG3 interval identifiers are not co-collected.
- Intrinsic branch/merge topology not emitted by the admitted RG3 source.
- Attempt identity not present in the admitted source.
- Pair-dependent shared-prefix quotient unless transitivity is separately proven.

### Frozen and unopened states

- The twelve Gate 15 confirmation runs remain FROZEN_UNOPENED.
- Gate 16.8 is not created by the release.
- No release consumer may alter authority, identity, provenance, findings, insufficiencies, or the Theta0 record.

## 17. Final trace

The evidence path is:

```text
closed-bar raw records
  -> Gate 14 RG3 qualification
  -> Gate 15 42-run sealed corpus
  -> Gate 15.5 timestamp/as-of bridge and atlas
  -> Gate 16 eight view variants and nine distance contracts
  -> Gate 16.5 297,081-pair / 20-contract census
  -> Gate 16.6 OSV1 root, Theta0, ancestry, findings, insufficiencies, source closure
  -> Gate 16.7 content-addressed release pack
  -> cold rehydration
  -> read-only typed consumer and external sidecar
```

The numerical identity chain is:

```text
RG3 canonical corpus
  68ed0ad0059390b683faaf2b7d607c0e1e763dcbf9b8368a8ae5a1e85d8684b8

Gate 16 laboratory
  49937da6b2f3abac1f6426a15b40525ec614b74052446437bbb484c93aefe833

Gate 16.5 logical census
  f88bbdffa5c6579617b1ade8ca6c1361da0aba3cc681a6a04e89c5be0c9c5cda

OSV1 root
  6e18e10fc0fb3571aa21b4e20105f783dafe2872812d217d672ab5e959bb890d

Release pack
  502d55a37e0592901906f3aa46f6298fb3f5d0614a4150b9e61fecb8d480d980
```

## 18. Final conclusion

Gate 16.7 is complete as a release and consumer-boundary operation. The sealed root is unchanged by packing, the release pack rehydrates to the same root, all declared members verify, no undeclared authoritative read occurs, typed states remain typed, the consumer writes only an external derived sidecar, and the payload hash remains unchanged after consumption.

The source root therefore provides a complete, hash-traceable record of the data population, deterministic transformations, mathematical comparison contracts, limitations, receipts, and release checks through OSV1. The next work begins on a separately named branch with separate authority inputs and receipts.
