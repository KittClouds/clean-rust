# E004 input baseline

E004 uses Experiment 002 as a read-only path dependency. These SHA-256 fingerprints identify the source inputs audited before E004 implementation. E002's own `BASELINE.md` fingerprints its nested E001 snapshot.

- `Cargo.toml`: `507D8769C7FD203E417289FEC781EAF0C7BE804C7CD746C0657983E6C77C143B`
- `Cargo.lock`: `76F2692CBF624116A605C9FC10144C84F6642995B8AE62F9477E2B317E647C99`
- `src/lib.rs`: `1CC533259760D72A8DB3061BE7FEB7E94C60505419FBB59775CF805E302D0B8F`
- `src/controller.rs`: `43E216676BFE1E1EE67CF79E7CC545FFF5199F41DF51B391C034C52F0BFAC406`
- `src/journal.rs`: `566FD34B6D86022583A41F391CE18B0293D07B58DBA1C37F45C0A64D79B28349`
- `src/model.rs`: `29D784FD499CC7FF7C8F824DC2D7D03D30A97B97A8441BD398AF71DDBE8491C5`
- `src/observer.rs`: `66FD0DB3B0EE452413C8CF37439F73E5751FBDD3D81FA605EE7B94958F8F6F29`
- `src/runtime.rs`: `716C11DEE65023EFF3A4FBA124E095B3DFAE5A6BF93AD2947E7821B519502DC1`
- `src/action.rs`: `E41F68B3BD4DB3324AD6501F3D6F8B3626FF3BFAD70E4D1DAA9632385468598A`
- `tests/switchboard.rs`: `EFB291FA29DA16AA31388CB469FA72DC5ABE9CC4A83EE9E7D7E00B3FC83FBDF2`

The E002 source still matches these fingerprints at E004 start. E004 adds no changes to E001, E002, E003, Phoenix, Northstar, or research branches. SHA-256 was used for source-baseline comparability; each E004 run also records BLAKE3 hashes for its source and generated artifacts.

## Revision visibility audit

`CompiledAuthority` wraps the E001 workflow `Runtime`. That runtime's stored fields are compiled transition schema, explicit workflow state, recovery count, and transition receipts. Its `Authority` trait exposes `apply`, `state`, `recovery_count`, `receipts`, and `reset`; it has no trusted task revision field or revision argument. E003's revision was packed into `Observation.evidence`. E004 therefore keeps truth revision in the evaluator label file and does not add an authority revision guard that the production contract cannot support.
