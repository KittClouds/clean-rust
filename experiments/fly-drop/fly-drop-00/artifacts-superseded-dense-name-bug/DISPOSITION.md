# Superseded pre-seal preparation attempt

Do not use this tree as an experiment artifact. During the first artifact audit,
the four dense-control seeds were found to target the same filename. The writer
overwrote the earlier three files, so that pass did not contain four distinct
dense controls and was not sealed. No learner training or outcome inspection
occurred. The corrected, authoritative output is in `../artifacts/` and is the
only artifact tree covered by `PRETRAINING-SEAL.json`.
