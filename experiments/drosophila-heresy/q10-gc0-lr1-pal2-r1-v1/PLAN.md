# Q10-GC0-LR1-PAL2-R1: PAL2 Entry-Count Reconciliation

Read-only derived audit of sealed PAL2. It reconciles source attempt counts with the unique canonical library entries without rerunning or modifying PAL2.

The source receipt counts attempted records. PAL2 stores entries keyed by the canonical full coordinate-to-prefix selection, so repeated ZERO substitutions that leave the full selection unchanged are deduplicated. No global assembly, pair expansion, or scientific promotion is permitted.
