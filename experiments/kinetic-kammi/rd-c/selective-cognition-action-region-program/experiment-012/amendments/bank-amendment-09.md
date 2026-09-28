# E012 bank amendment A09 — reverse-control audit predicate

**State:** audit-only repair frozen before rerun. **Model contact remains prohibited.**

Pre-contact audit attempt 01 stopped because the checker compared the ordered valid-candidate counts of the producer schedule and its row-wise reverse as though they should be identical. The reverse schedule should mirror the vector: control count at position `p` must equal producer count at position `3-p`. The projected frames, truth index, and receipts were not changed.

Audit v1.2 corrects that predicate and retains the same bank membership, expected schedules, channel checks, donor checks, and receipt replay procedure. The failed audit attempt and the original audit source remain preserved.
