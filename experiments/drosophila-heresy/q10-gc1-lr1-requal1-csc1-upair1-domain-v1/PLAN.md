# Q10-CSC1-UPAIR1: deterministic unscreened pair replay domain

This identity freezes the replay subset from the complete current-lineage
Q10-CSC1-UVD0 census. It performs no pair replay and reads no pair outcome.

The parent census contains every structurally eligible same-context pair. Exact
replay of all 840,704 pairs is outside the measured runtime budget, so this
identity applies a deterministic coverage rule before any pair geometry or
readout result is consulted:

* select the eight lowest SHA-256-ranked eligible partners for every singleton
  action in each context;
* take the union of those directed selections;
* retain rows in the original UVD0 order;
* assign a new sample index while preserving the UVD0 source pair index.

The resulting sample is the only pair domain opened to UPAIR1 replay. The full
UVD0 census remains bound as the structural parent and is never relabeled as a
replay result. Per-action coverage is a required gate; missing coverage blocks
promotion. No success, geometry, readout, validity, or historical pair result
is consulted during selection.

This is an engineering-only domain artifact. ALG1 must consume this sealed
domain and seal its prospective predictions before UPAIR1 replay begins.
