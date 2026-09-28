# Q10-PF6: Oversize Distributed Beam Qualification

Q10-PF6 is an engineering-only continuation of the audited Q10-PF5 run. It
targets the 1,457 raw-support groups that PF5 correctly left as
`OVERSIZE_UNTESTED`. It does not reopen the 28 endpoint reconstruction, alter
the PF5 receipt, use Q10-NA findings, apply a repair, or open DH08B.

The question is narrow:

> Can a deterministic, target-aware distributed beam search produce valid
> f32 candidate endpoints for PF5 groups whose full prefix Cartesian domain
> is too large for PF5 exact enumeration?

The PF5 audited receipt is the sole measured parent. Its counts are frozen:

* 28 reconstructed primary endpoints;
* 1,596 augmented raw-support groups;
* 1,457 oversized groups;
* 102 partial-feasibility groups;
* 37 complete-domain blocked groups;
* 406,119 missing-prefix replays and 22,364 raw-row bridges.

## Candidate ordering

PF6 reconstructs the endpoint state from the hash-bound PF5 inputs and uses
the exact learner-order sequential binary32 replay. Let `M_G` be the baseline
mismatched readout rows for group `G`, let `R_i` be the rows that coordinate
`i`'s raw-support rows can influence under the augmented PF5 topology, and let
`e_j` be the baseline residual on row `j`. Coordinates are ranked before beam
expansion by this frozen lexicographic key:

1. descending `S_i`, where `S_i = sum(e_j^2 for j in R_i intersect M_G)`;
2. descending count of mismatched raw-support rows in `R_i intersect M_G`;
3. descending replayed-raw-prefix count;
4. ascending coordinate id.

The ranking is a search order only. It does not discard coordinates or
declare a coordinate irrelevant. A coordinate whose rank is beyond the
16-round horizon is labeled `unselected_zero_by_horizon`, never `ineffective`
or `no-authority`.

## Complete endpoint semantics

For a group with ranked coordinates `c_1,...,c_n`, every beam state is a
complete legal endpoint `p in D_1 x ... x D_n`. After round `r`, choices for
`c_1,...,c_r` are taken from their legal PF5 prefix domains and every
unvisited coordinate `c_(r+1),...,c_n` is fixed at its legal zero choice.
Thus a state after round 16 is a valid full endpoint, with at most 16 ranked
coordinates allowed to depart from zero; the round limit is a
coordinate-selection horizon, not an incomplete endpoint representation. A
zero choice considered during expansion is `tested_zero`; a coordinate never
reached by the horizon is `unselected_zero_by_horizon`.

## Search contract

Each coordinate still receives exactly one legal prefix endpoint from the PF5
domain. Every accepted candidate is replayed from a cloned committed f32
state. The beam has an exploit lane of 24 states and an exploration lane of 8
states. It runs at most 16 coordinate rounds and 32,768 candidate replays per
group. Ties use stable hashes. Intermediate geometry debt is permitted within
the inherited PF5 guardrails; only completed candidates face the inherited
DA2 axis, norm, linear cue-drive, support, bounds, boundary, and reserve
gates.

For every group, PF6 records round trajectory diagnostics for rounds `0..16`
inclusive: `mismatch_count`, `total_ulp_distance`, `residual_l2`,
`max_residual`, `geometry_debt`, `active_coordinate_count`,
`selected_coordinate_ids`, and `unselected_coordinate_ids`. These are
diagnostic receipts only; they do not
change the search objective, stopping rule, beam membership, endpoint validity,
or final gates. The receipt keeps tested zero choices distinct from
coordinates that retained zero solely because the horizon did not reach them.

PF6 may report `INCONCLUSIVE_BOUNDED_SEARCH` or `OVERSIZE_UNTESTED` whenever
its declared budget is exhausted. Neither status is an impossibility claim.
No individual no-helpful row becomes a blocker without complete joint-domain
coverage, and bounded-search failure remains inconclusive.

If a bounded search fails to improve or to produce a final-gate-valid endpoint,
that is a result under the declared horizon and budget. It is not a claim that
the unvisited coordinates lack authority.

## Outputs and firewall

PF6 emits engineering receipts only: parent hashes, ranked search domains,
candidate replay counts, geometry audits, and feasibility classifications. It
does not emit accuracy, reward, action, memory-margin, behavioral, scientific
seed, canonical-update, or DH08B findings. A separate scientific protocol is
required even if PF6 finds an exact isofunctional endpoint.
