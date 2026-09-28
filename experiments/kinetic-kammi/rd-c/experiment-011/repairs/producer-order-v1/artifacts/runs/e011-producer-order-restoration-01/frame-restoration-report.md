# Producer Order Restoration Check

- Classification: postrun deterministic input-adapter check; no model contact or labels.
- Exact E010 frame reconstructions: 16/16.
- Producer ordinals in this diagnostic come from each frozen E010 source-order sequence, matched by patch digest. Production assigns the ordinal when the candidate is created and carries it with the candidate.
- Reordering is done by producer ordinal. Patch-hash ordering is not used.

| Repository | Exact restored frames |
| --- | ---: |
| ripgrep | 8/8 |
| turbovec | 8/8 |
