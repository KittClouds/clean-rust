# Q10-GC0-GP1-PAR1: Parallel Full Raw-Group Palette

PAR1 is the execution-preserving continuation of the interrupted single-process
GP1 run. It uses the same sealed authority table, group set, candidate horizon,
beam widths, replay cutoff, exact sequential-f32 evaluator, and candidate
identity. The only execution change is four deterministic endpoint/set worker
processes; each worker owns its endpoint/set state and returns complete group
receipts to the parent stream.

This is engineering-only. It does not assemble groups globally, run GC1, probe
behavior, or promote science. Partial worker output is non-authoritative until
all 801 group receipts, hashes, and support gates are written.
