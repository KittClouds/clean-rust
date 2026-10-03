# JEV v0.8P-R1 construction disposition

**Disposition: `TRAINING_PANEL_OVERLAP`.** The training identity replay and provisional panel generation both passed their own construction checks. The mandatory prior-panel overlap gate failed on exact rendered-input hashes. Under the frozen no-replacement rule, the provisional panel is non-promotable and R1 stops before LFM contact.

## What the run established

The corrected R1 generator replayed 12,000 training triplets and 132,000 occurrence identities. The three historical training streams passed exact byte-count, SHA-256, and BLAKE3 parity. The selected training scope contained 5,000 neighborhoods / 55,000 occurrences and had zero identity mismatches against the bound scope manifest. No targets or features were read by the sidecar reader; the source-access receipt is explicitly application-level path/read-site evidence, not OS-level file-open telemetry.

The prior-panel identity reconstruction produced 2,000 neighborhoods / 22,000 occurrences and exactly matched the v05 E1 neighborhood-ID denylist. The new provisional panel then generated 2,000 neighborhoods, exactly 500 per frozen family, and 22,000 occurrences. It passed exact-world semantic validation and had zero E1 neighborhood-ID collisions.

The five-field audit compared the new panel against the selected training scope and reconstructed prior panel. The complete field results were:

| Identity field | New panel unique | Selected training shared | Prior panel shared | Result |
| --- | ---: | ---: | ---: | --- |
| `world_id` | 2,000 | 0 | 0 | pass |
| `root_id` | 2,000 | 0 | 0 | pass |
| `episode_id` | 22,000 | 0 | 0 | pass |
| `full_rendered_input_hash` | 21,967 | 0 | **121** | **fail** |
| `selector_input_hash` | 22,000 | 0 | 0 | pass |

The 121 value is the number of **distinct rendered-input digests shared** by the provisional panel and prior panel, not a claim about the number of matching rows. The panel has 22,000 occurrence rows but 21,967 distinct rendered-input hashes; the reconstructed prior panel has 21,956 distinct rendered-input hashes. The 121 cross-panel digest intersections are about 0.55% of either panel's distinct rendered-input set. Any nonzero intersection violates the frozen gate.

All 132,000 replayed raw-training occurrences were also checked diagnostically: there were zero intersections for all five fields. The contract's training-scope gate uses the selected 55,000 occurrences; this additional raw-corpus check does not change the failure.

## Interpretation boundary

This is not a model result and says nothing about DUP, MATCHED, or SHAM learning behavior. It shows that distinct generated world/root/episode/selector identities did **not** guarantee distinct model-visible rendered inputs across the fresh panel and the prior held-out panel. The current candidate set cannot be promoted as the prospectively fresh panel because the original construction contract requires zero prior-panel overlap and prohibits replacement after audit.

The observed hash collisions establish the failure, not its mechanism. A finite context/rendering space is one plausible source, but this audit did not isolate why those identical rendered byte strings recur. Do not relabel the result as a successful fresh-world confirmation or repair it by dropping the 121 digests, changing the seed, or selecting replacements.

## Terminal state

```text
original v0.8P line          CLOSED_UNEXECUTABLE_UNDER_SEALED_OVERLAP_SCHEMA
R1 training identity replay PASS
prior identity reconstruction PASS
provisional panel generation PASS
five-field overlap           FAIL: 121 prior-panel rendered-input digests
promotable fresh panel       NO
LFM/model contact            NO
feature extraction           NO
head loading/training        NO
inference/evaluation         NO
scientific behavior result   NONE
Phoenix access               NO
```

## Forward direction

Close R1 without a replacement panel. If the late-transition question remains worth pursuing, make the next identity a prospective R2 construction revision that gives rendered inputs a collision-resistant, disjoint realization space across the prior-panel and new-panel partitions (or prospectively screens the frozen candidate stream against all bound identity sets before final admission). Freeze that rule before generating candidates, preserve the same four families and measurement surfaces unless a scientific redesign is explicitly intended, and retain a hard zero-overlap audit. Do not reuse this failed panel or select around its observed collisions.

The efficient lesson is concrete: panel freshness must be guaranteed at the exact model-visible byte level, not inferred from fresh world IDs.
