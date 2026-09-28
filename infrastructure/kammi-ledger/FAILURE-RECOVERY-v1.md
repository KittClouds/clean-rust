# Failure recovery v1

An incomplete journal tail is quarantined by digest before truncation to a valid prefix.
Complete checksum/chain corruption fails closed; it is not repaired by truncating history.
CAS writes stage/fsync/rename before events. An orphan CAS object may survive a crash;
it gains authority only through committed events. Projection errors return the committed
event identity so a retry/rebuild can converge without duplicating the action.

Single-writer locks are held by the OS and released on process death. A PID file is diagnostic.
Kill the owned Windows process tree, not merely its launcher. Preserve stopped attempts,
failed acceptance logs and any recovered tail before retrying.

Qualified durability is process-crash prefix recovery on this pinned Windows runtime.
File fsync calls request OS flushing; rename/open-handle behavior is characterized.
No physical power-cut/reboot test or storage-controller persistence certification was performed.
Directory metadata durability after power loss is not guaranteed by this release's evidence.
Maintain backups; do not claim stronger power-loss guarantees from process-kill tests.
