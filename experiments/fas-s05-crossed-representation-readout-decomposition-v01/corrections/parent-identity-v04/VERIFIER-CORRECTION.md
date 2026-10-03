# S05 Parent Identity Binding Correction v04

This correction preserves the sealed S05 v01 protocol and all v02/v03
verification attempts. Each earlier preflight stopped before writing event
population or scientific result artifacts.

The v03 audit verified all parent seal roots and then found that the S05-local
expected SHA-256 for the FAS-00 Phase 2A feature tensor omitted one `3` in its
hexadecimal text. The existing Phase 2A seal, parent-binding packet, and file
agree on the correct tensor digest:

```text
6205b7d7a224b798b387886b43ec27103b37f091dccd9b623847cb7a52b0c8c2
```

The v04 bundle corrects only that local expected identity and uses a separate
run directory. It does not change any parent artifact, population, readout,
metric, arithmetic, or scientific scope. No model contact, feature
extraction, probe fitting, or adaptive mechanism is authorized or performed.
