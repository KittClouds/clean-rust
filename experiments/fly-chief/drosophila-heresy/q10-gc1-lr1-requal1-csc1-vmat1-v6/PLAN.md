# Q10-CSC1-VMAT1 v2: signed constraint materialization

This fresh current-lineage identity materializes the complete signed constraint
objects required for the CSC1 routing audit. It consumes the sealed 4,999-pair
REQUAL1 domain and performs exact replay only to reconstruct S, S_A, S_B, and
S_AB. It does not search, alter the pair domain, make a routing prediction,
open global assembly, or open any scientific endpoint.

The materialized constraint is the product of two scalar signed residual
intervals and one signed linear-drive residual L2 ball. Linear-drive values are
stored as a full ordered vector; the shared L2 gate is never converted into
componentwise bounds. Raw and gate-normalized vectors are both preserved.

The v1 setup attempt is preserved separately as a pre-execution setup blocker.
This v2 identity binds only current REQUAL1 parents and uses Python -B with
PYTHONDONTWRITEBYTECODE=1. Unexpected output paths fail promotion.
