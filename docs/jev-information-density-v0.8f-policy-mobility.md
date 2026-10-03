# v0.8F — Policy Mobility and Training-Equivalence Audit

## Boundary

This is a metadata-only audit over the sealed v0.8E P* support. It does not
change P*, any profile tolerance, the 100,000-group target, eligibility,
held-out exclusions, either frozen selector, or the `D_train >= 0.10` arm gate.
No model, feature extractor, training job, or Phoenix data was accessed.

## Training-equivalence result

The class key is `supervised_signature_sha256`, the frozen per-group
loss-relevant identity. The bank-selected directed invariance-pair context is
arm-dependent and remains separately measured by `exact_training_distance`.

Across 416,672 eligible groups there are 25,788 supervised-signature classes:

- 25,528 classes are repeated; 416,412 groups belong to repeated classes.
- Median class size is 12, p90 is 34, and the largest class has 168 members.
- No class crosses a P* stratum, state signature, selector-input signature, or
  ordered signature.
- Root identity varies within 25,268 classes, covering 415,892 groups
  (99.813%). Thus a single representative per loss class would erase a
  required root-profile contribution.

The frozen curation score is **not mostly ranking loss-equivalent rows**:

| Score variance component | Share |
|---|---:|
| Between supervised-signature classes | 85.539% |
| Within supervised-signature classes | 14.461% |

The within-class contribution is concentrated in local discrimination (22.654%
of that axis's variance) and redundancy (14.873%). It is negligible for
semantic novelty (0.124%), probability geometry (approximately zero), and
structural coverage (approximately zero).

The pairwise-rank denominator matters: 83.286% of pairs *within the same
signature class* receive different curation scores, but those comprise only
0.005773% of all strictly score-ordered pairs across the full eligible
universe. Most global score variation is therefore between training-loss
identities, even though member-level score variation is common inside repeated
classes.

## Class-indexed policy implementation

The audit groups rows by supervised signature, retains each member's original
stratum, root, score, and deterministic hash rank, and performs an exact
k-way merge of the member queues. It reproduces both frozen raw selectors
ID-for-ID. This is a semantics-preserving indexing strategy; replacing a class
with one representative or its maximum score is not.

Exact replay does not repair the profile mismatch:

| Candidate direction | `D_train` | State TV | Other result |
|---|---:|---:|---|
| Capacity witnesses A vs B | 0.25935 | 0.019765 | A, B, and pair pass P*; curated mean-score delta B−A is −0.00003171 |
| Frozen raw random vs curated selectors | 0.63875 | 0.038605 / 0.235411 | Both fail P* matching |
| Common-reservoir candidate | 0.36933 | 0.091873 | Selector/root TV 0.052470 / 0.054236; fails |
| Best passing witness-pair prefix, 500 swaps | 0.00503 | 0.013984 | Passes profile; score gain +14.696 total |
| Next tested prefix, 1,000 swaps | — | 0.022788 | Fails state-TV limit |

The capacity witness proves that P* permits substantial learner-visible
movement, but that direction is not favored by the frozen curation score. The
large score-positive selector movements violate profile constraints. The best
profile-valid score-positive prefix is only 5.03% of the required treatment
distance.

## Decision

```text
training-equivalence audit       COMPLETE
frozen class-indexed replay      EXACT
P* profile                       UNCHANGED
matched random/curated arms      NOT READY
model contact                    NOT AUTHORIZED
```

This is a bounded construction result, not an infeasibility proof. A future
metadata-only engineering attempt may use root-aware exchange cycles or a
constrained optimizer over signature/member queues, while keeping the frozen
curation score and random priority unchanged. Any attempt that needs to change
those policies or P* semantics must stop for review.

## Artifacts and verification

- Audit implementation: `experiments/jev-information-density-v08e/audit_policy_mobility.py`
- Unit tests: `experiments/jev-information-density-v08e/tests/test_policy_mobility.py`
- External report: `D:\codex-runs\jev-information-density-v08e\policy-mobility-v04\policy-mobility-audit.json`
- External integrity receipt: `D:\codex-runs\jev-information-density-v08e\policy-mobility-v04\integrity-receipt.json`

At the initial v0.8E audit freeze, seven unit tests passed; the expanded suite
is reported in the follow-up below. The class queue replay is checked against
the raw frozen selectors before the original report is written.

## Hierarchical variance and mobility follow-up

A follow-up metadata-only audit decomposed the frozen curation score through
the nested structure `stratum → state signature → supervised signature →
member`. The population-variance components close to numerical error
(`2.2e-19` absolute error):

| Component | Share of total score variance |
|---|---:|
| Between strata | 30.522% |
| Between states within strata | 47.650% |
| Between supervised signatures within state | 7.367% |
| Within supervised signature | 14.461% |

Thus the earlier 85.539% “between supervised-signature” component resolves
mostly into between-stratum and between-state score variation. Across the 192
strata, the median within-stratum between-state share is 64.587% (p10 13.313%,
p90 76.885%); 145 strata have a majority of their local score variance between
states. The median within-state between-signature share is 11.706% (p90
30.426%).

This is evidence that the frozen curation score is strongly state-/stratum-
selective. It is not yet evidence that P* prohibits state selection. The sealed
profile fixes exact stratum counts and controls the **histogram of per-state
multiplicities** (plus its unique-state tolerance); it does not require the
same count for each specific state ID. Whether selecting different state IDs
while preserving that multiplicity histogram counts as “holding state exposure
geometry fixed” is a scientific interpretation, not an implementation choice.
No class-count optimizer was run past this decision point.

The class-mobility census adds:

- 25,788 selector-input identities map one-to-one to 25,788 supervised-loss
  signatures; no selector input has conflicting loss signatures.
- Of 8,640 state×stratum cells, 5,758 contain multiple supervised signatures,
  covering 312,498 eligible groups (75.0%); median class count is four.
- The capacity witnesses expose 59,723 / 59,671 directed class-count
  exchange opportunities that preserve state identity counts and stratum
  counts locally, before selector-histogram and other profile checks.
- No single exchange was found that also fixes the same root and every other
  profile contribution exactly. This is not a proof against multi-row cycles;
  it is why a root/member-repair cycle is needed if the existing profile
  semantics are retained.

Follow-up implementation and report:

- `experiments/jev-information-density-v08e/analyze_policy_mobility_v05.py`
- `D:\codex-runs\jev-information-density-v08e\policy-mobility-v05\policy-mobility-hierarchical-audit.json`
- `D:\codex-runs\jev-information-density-v08e\policy-mobility-v05\integrity-receipt.json`

The follow-up used no model/features/training or Phoenix data. The v0.4 audit,
P* profile, and policy definitions remain unchanged. All nine tests in the
expanded v0.8E test directory pass, including hierarchical-variance closure
and the profile-cell identity check.

## State-identity interpretation and balanced-cycle continuation

The ambiguity recorded above was resolved without changing P*:

> State-exposure matching means matching the selected state-multiplicity
> distribution and the declared unique-state tolerance, not matching the
> identities of the states occupying those multiplicities. State-ID
> reassignment is permitted and is part of the selection-policy treatment.

The P* profile, 100k target, eligibility/held-out firewall, curation score,
random-priority rule, profile tolerances, and `D_train >= 0.10` gate remain
unchanged. No protected evaluation data informed construction.

The bounded continuation uses complementary two-edge cycles. Each edge swaps
one selected and one unselected group within an exact P* stratum. The two edges
are paired so the selected state counts exchange adjacent occupancy levels;
the state-multiplicity histogram is therefore preserved exactly while state
identities can change. Sparse incremental checks enforce the frozen selector,
root, family, topology, query-view, candidate-cardinality, and coverage
constraints against the sealed profile before a cycle is accepted. The frozen
policy objective is the search objective; `D_train` is telemetry and a
downstream acceptance gate, not an optimization term.

Implementation and tests:

- `experiments/jev-information-density-v08e/balanced_policy_cycles_v06.py`
- `experiments/jev-information-density-v08e/tests/test_balanced_policy_cycles_v06.py`
- Focused and regression suite: 15 tests passed before the full metadata run.

The first launch stopped before search because a checkpoint call referenced
the writer on the wrong module. The issue was corrected to use the existing
atomic writer; the run-start-only directory is preserved as an implementation
failure, not a scientific result. The corrected run is recorded under
`D:\codex-runs\jev-information-density-v08e\policy-mobility-v06-balanced-cycles-v02`.
No model, feature extraction, training, or Phoenix access is authorized by this
construction stage.

### v03 seeded continuation result

The v03 continuation started from the independently reloaded v02 random and
curated candidates. Its curated arm accepted 2,751 balanced cycles (11,004 row
replacements) and improved the frozen curation objective by `0.0015302149`
per group relative to the P* anchor. It passed the P* profile checks, with
state-exposure histogram TV exactly zero and selector/root histogram TVs just
below `0.02`.

The random arm's incumbent passed P* individually, but its first paired
neighborhood examined 250,000 cycles and accepted none: every proposed result
failed the cross-arm profile constraint against the advanced curated arm. The
final independently reconstructed `D_train` was `0.10674`, above the treatment
threshold, but the paired profile failed narrowly:

- selector-occurrence TV: `0.0202219712` (limit `0.02`)
- root-occurrence TV: `0.0237413392` (limit `0.02`)

All other listed profile comparisons passed, and held-out overlap remained
zero. Therefore v03 is **not** a matched treatment pair and did not authorize
model contact. This is a bounded construction result, not infeasibility. The
v04 continuation starts again from the v02 pair and constrains curated search
against the random seed profile before optimizing the random arm. That changes
search ordering/feasible-path enforcement only; P*, both frozen policies, and
all thresholds remain unchanged.

### v04 pair-constrained continuation result

The v04 run began from the v02 candidates, verified both seed arms against the
sealed P* profile and against each other, and constrained every curated move
against both P* and the random seed profile. The random arm was then optimized
against both P* and the resulting curated profile. Independent source reload
and validation completed successfully.

| Check | Result |
| --- | ---: |
| Arm sizes | 100,000 / 100,000 |
| Exact training-signature distance | `0.13489` (gate `>= 0.10`) |
| R vs P* selector / root occurrence TV | `0.008601` / `0.010591` |
| C vs P* selector / root occurrence TV | `0.019991` / `0.019944` |
| R vs C selector / root occurrence TV | `0.019792` / `0.019867` |
| State-multiplicity histogram TV | `0.000000` for both arms |
| Held-out group-ID overlap | `0` |
| State-ID Jaccard | `0.991893` |
| Curated accepted cycles / row replacements | `2,710` / `10,840` |
| Random accepted cycles / row replacements | `3,072` / `12,288` |
| Curated objective gain per group vs P* anchor | `0.00151855` |
| Random-priority quality gain per group vs P* anchor | `0.08645141` |

All P* and cross-arm profile checks passed. The independent integrity receipt
matches both the result hash and the executed source hash. The resulting arms
are marked `POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED`: no model contact,
feature extraction, training, or Phoenix access occurred, and none is
authorized by this construction result alone.

External run directory:
`D:\\codex-runs\\jev-information-density-v08e\\policy-mobility-v06-balanced-cycles-v04`.
