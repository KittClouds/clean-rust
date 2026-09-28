# Fenced resources v1

Exclusive resource kinds: GPU, CPU_POOL, HOST, REMOTE_WORKER, DATASET_LOCK,
PANEL_LOCK, FILESYSTEM_EXCLUSIVE. Pools are coarse exclusive units in v1;
register separate resource IDs for independently reservable units.

Leases bind actor/run/stage/purpose, constraints, expiry and a monotonically increasing
resource fencing token. Acquire/renew/release carry request IDs. Expiry permits a new
holder; a stale token cannot execute through a qualified executor.

Local and remote executors check at launch and during execution. They terminate their
owned process tree on expiry. Arbitration fixtures use logical GPU resources and CPU
commands: they prove fencing semantics without consuming CUDA or scientific observers.
Direct CUDA launches that bypass the executor are outside qualified operation.

Clock is the host UTC clock; admin clock rollback is outside the trusted-host boundary.
Lease TTL is 1..3600 seconds. Clients must renew before expiry and stop after denial.
