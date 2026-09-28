# E012 Protocol Amendment 01 — Repository Eligibility

- Base protocol: E012 protocol v0.
- Base pre-bank lock: `../protocol-lock-v0.json`.
- State: effective before any task construction; no tasks or model outputs exist in this lineage.
- Purpose: align the machine-readable repository minimum with the already-frozen human protocol and the user's new-lineage requirement.

## Change

The required three repositories must be absent as evaluation repositories from **all of E009, E010, and E011**. This is the controlling interpretation of the weaker `repositories_new_to_e010_e011` field in `channel-contract-v0.json`. No other bank minimum, task stratum, frame treatment, observer setting, or analysis rule changes.

## Authorization boundary

This correction only constrains repository selection. It does not authorize task construction by itself and does not authorize observer contact. E012 remains at protocol/bank-planning stage until the versioned combined lock is verified. The original v0 protocol and lock remain byte-for-byte preserved.
