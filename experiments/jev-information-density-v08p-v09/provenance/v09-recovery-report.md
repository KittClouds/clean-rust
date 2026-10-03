# JEV v0.8P-v09: bounded historical source recovery

## Disposition

**Exact historical source bytes were recovered; the original training-scope overlap rule remains not evaluable.** This is a construction/provenance disposition, not a scientific result. The fresh P panel was not generated.

The recovery located the hash-bound v0.8N Road-A chain and the exact training artifacts it named. However, the recovered rows do not provide a frozen mapping for all five required overlap dimensions. Only `episode_id` has a direct, contract-bound field match. Treating similarly named or derivable fields as equivalent would change the original rule and could manufacture a false overlap pass.

## Recovered objects

| Object | Rows / size | SHA-256 | Result |
|---|---:|---|---|
| Common primary occurrence manifest | 10,000 rows: 5,000 anchors + 5,000 fact flips; 6,776,884 bytes | `773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06` | Exact bound bytes recovered |
| Training-only feature-scope manifest | 55,000 rows, 5,000 neighborhoods, 11 roles per neighborhood; 30,195,630 bytes | `aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3` | Exact bound bytes recovered |
| Full training canonical stream | 1,313,795,720 bytes | `212a6caae513b53f014569c9d07aa0aac64b94b2a90f0b01b70aa9b3f6d1e3ff` | Exact source SHA matched the cache receipt; generator receipt also names BLAKE3 `9a4dc01d563e586ffe9c91dd4fac01bf94d9cafb4b9568c1e164de06105313fd` |
| Road-A local fallback seal | 3,493 bytes | `9e971f3cee11e6d662b965e27fa3752f93ea49006d3e8fa3c0b73b1119155ab9` | Exact seal reached through the hash-bound synthesis lineage |

The scope manifest’s declared row fields are `index`, `neighborhood_id`, `family_id`, `role`, `episode_id`, `text`, and `input_sha256`. The canonical stream’s identity object includes `episode_id` and `world_instance_id`; its generator certificate uses `world_id`. Those are observations about the recovered schemas, **not** authority to equate them to different P overlap fields.

## Frozen rule versus recovered schema

The original P/v07 rule requires separate exact-set comparisons for:

| Required dimension | Frozen mapping status | Evidence-based disposition |
|---|---|---|
| `world_id` | Missing | `neighborhood_id`, `world_instance_id`, and generator-certificate `world_id` are not bound by the original overlap contract as interchangeable training identity values. |
| `root_id` | Missing | No direct field or frozen derivation was found in the recovered identity rows. |
| `episode_id` | Present | Direct exact field in the training scope. |
| `full_rendered_input_hash` | Ambiguous | The named builder computes `input_sha256` from rendered text, but the original overlap contract never binds that field to `full_rendered_input_hash`. Similar bytes are not a frozen mapping. |
| `selector_input_hash` | Missing | No direct field or frozen derivation was found in the recovered scope/canonical identity schema. |

Consequently, the training-side set **T** cannot be materialized under the frozen five-field definition. There is no legitimate overlap result—neither `PASS` nor `FAIL`—and no reason to generate provisional candidates. The v05 E1 identity denylist was not consumed.

## Scope note

During a one-record schema check of the hash-verified training canonical stream, a generic JSON parser transiently materialized the co-located `gold_targets` property. No target value was inspected, displayed, retained, or used. This is recorded as a parser-level deviation from the identity-only extraction boundary; the record does not claim zero target acquisition. No evaluation data, model features, head outputs, training, inference, or metrics were accessed or produced in v09.

## Terminal state

```text
historical source bytes             RECOVERED
training identity manifest          NOT CREATED
five-field overlap                  NOT EVALUABLE
candidate staging                   NOT STARTED
fresh P panel                       NOT CONSTRUCTED
LFM/model contact                   NO
training / head loading             NO
inference / evaluation              NO
scientific result                   NONE
```

Earlier v0.8P identities were not modified. v09 is the single bounded historical recovery pass; do not start another historical hunt or retrofit field mappings into the old protocol.

## Direction for the research program

Close the old P construction line as **unexecutable under its sealed overlap schema, despite recovery of the exact bytes**. If dense transition timing remains worth testing, proceed only as a new prospective identity, **v0.8P-R1**. At source generation time, emit and hash the five overlap fields explicitly for every training and panel occurrence, with frozen definitions for `world_id`, `root_id`, `full_rendered_input_hash`, and `selector_input_hash`. Add a schema-completeness test before panel generation. Then stage candidate identities, run the unchanged five-field overlap predicate, and promote the panel only on a genuine pass. Do not reuse v09’s schema inspection as an implicit mapping or present R1 as completion of the original P chain.

## Machine provenance

- [Recovery disposition receipt](v09-recovery-terminal-disposition-v01.json) — SHA-256 `043da9b4f4838f041dad9a29fc7881aeb1c0e370f6f410d76b45fe69a372a5a5`.
- [Terminal root](v09-terminal-root-v01.json) — binds the disposition receipt; its hash is recorded separately by the sealing workflow.
