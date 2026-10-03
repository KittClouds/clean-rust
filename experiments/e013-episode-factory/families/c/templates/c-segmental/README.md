# Segmental

A small Rust crate for compact interval and range indexing. The stable task surface is under `src/families`; the checker binary reads external tab-separated fixtures and dispatches only the family selected by `E013_FAMILY_ID`.

Fixture records use lowercase hexadecimal input and expected-output fields separated by one tab. Hidden adjudicator files are supplied out of tree by the episode runner.