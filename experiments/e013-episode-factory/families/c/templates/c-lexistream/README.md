# LexiStream

Small Rust crate for byte-oriented ingestion experiments. The stable task surface is under `src/families`; the `e013-check` binary reads an external tab-separated fixture and dispatches only the family selected by `E013_FAMILY_ID`.

The checker accepts fixture records as lowercase hexadecimal input and expected-output fields separated by one tab. It returns a nonzero exit code on malformed records or behavior mismatches. Hidden adjudicator files are supplied out of tree by the episode runner.
