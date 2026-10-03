# Q10-DA1 engineering result

Q10-DA1 completed all 8 declared engineering events and 32 fixed structural
coalitions. No scientific seed bundle was opened and DH08B remains
unauthorized.

All 32 coalitions passed assembled-versus-full sequential f32 replay parity.
Every coalition reduced the target-readout mismatch count and squared error.
Mean mismatch reduction was 125.5 rows, with a range of 103--147. The mean
final-to-initial L2 ratio was 0.8747, with a range of 0.8132--0.9328. Each
coalition selected 448--508 coordinates from its stable-order maximal
support-disjoint set.

None of the 32 coalitions passed the broader geometry gate. The dominant
failure was movement along the acquisition axis; every coalition also exceeded
the inherited 64-move path diagnostic. This is therefore readout authority,
not a valid bounded geometric endpoint and not a DH08B result.

The main decision is positive but narrow: distributed support-disjoint local
changes have substantial target-readout authority, while the four-way fixed
selector choice is not sufficient to preserve the Q10-SM geometric contract.
The next experiment should impose the linear geometry contract during
distributed selection rather than search smaller nonlinear blocks.

Receipts:

- `qualification/sample-9731-9732/` — 8 event receipts and execution accounting.
- `PREEXECUTION.json` — sealed source, binary, and anatomy manifest.

Hashes: PREEXECUTION `F26EA84B291556B80232D9488C7F9791A34A60EF912BED59F00BA3F0891FB792`,
execution `3D9FD551F21E97F36A8CDF4F6675DA1B16FA2D314FBA4B906F9F17B680DE38E8`.
