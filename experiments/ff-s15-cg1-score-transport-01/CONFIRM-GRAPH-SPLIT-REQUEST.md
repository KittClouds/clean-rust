# Request: BANK-GRAPH-CONFIRM-1 — a fresh, sealed graph confirmation split (draft — not sent)

For whoever runs the BANK generator (a narrow data-production chore, not a research assignment for Lexi). The System 1.5 graph line has one surviving operation (`edge_existence`), a passed development gate (C-G0), and an open calibration question (C-G1).
Everything so far used TRAIN, DEV and TEST that helped select the operation, so none of it can confirm the frozen machine. Clean data needs to be sitting on disk, untouched, before any confirmation is designed.

## What to produce

- **New world seeds and new render seeds**, from the frozen generator contract. **No overlap** with any current TRAIN/DEV/TEST world (by world hash and, where practical, graph hash).
- **The same graph/task schema, entity/type ontology and rendering pipeline** as BANK-v1 and Lexi's Graph Surface v2 run, so the frozen extractor and observer can be applied unchanged later.
- **Paired renderers kept together** (a world's renderings stay in one partition), including **S7/S8/S9-equivalent renderer challenges** (S9 in particular: symbolic-ID spans), in numbers comparable to the current held partitions (about 220k ordered pairs and 22k edges per held renderer), so that per-renderer edge-loss can be measured to a fraction of a percent.
- **The natural full ordered-pair universe must be derivable** from the sealed worlds (canonical worlds with entities and `initial_state`), exactly as C-G0 enumerates it.

## What to do with it

**Generate, hash, seal.** Record a manifest with file hashes and the generator identity, and stop.

## What not to do

- **Do not run any observer or extractor on it**, score it, summarise it, or inspect outcome distributions. No class-balance reporting beyond generation sanity checks (counts of worlds and rows, files present, hashes).
- Do not use it to choose anything in C-G1. **Nobody touches it** until: the calibration scheme is chosen (C-G1), the runtime contract is frozen (C-G2), and then it is opened **once** (C-G3).
- Truth stays sealed alongside; the extraction pass over the fresh worlds is label-blind and belongs to the opening run, not to this chore.

## Why this order

Clean data on disk while C-G1 works, and a frozen machine at the moment it is opened, is what gives the confirmation teeth. Anything looked at earlier stops being confirmation.
