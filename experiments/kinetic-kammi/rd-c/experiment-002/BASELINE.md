# Experiment 001 baseline snapshot

Experiment 002 vendors an immutable copy of the Experiment 001 runtime source. SHA-256 fingerprints at snapshot time:

- Cargo.toml: F259DF247C4D213085E657E29B427674F0B1156B2B11C75169E9BF8F3337D804
- Cargo.lock: CD2842A1724ABDAAA5A4C3454139A64108DEB0EFC6FD1491536B86BB51E162F1
- src/lib.rs: 0A470B281609B96900E9DE3A6F7E10290EABE1F2185EA8417B7BFCFD7603E040
- src/journal.rs: A467B8AC5A8F4AD7240797BCC748FDA89888CA6FB13EFDAAF7BA321CBB335757

The copy is under baseline/rdc-experiment-001 and is built as a local path dependency. Experiment 002 does not modify the Experiment 001 project.
