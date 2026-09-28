# E012 Audit Amendment A16 — Lock Verifier Type Repair

**State:** audit-only correction over the unchanged A14 bank; no model contact.

A15's audit process stopped in its lock verifier before any bank audit ran. The verifier passed script bytes to a helper that accepts a `Path`. No audit output was written. The A15 lock and launch trace are retained. A16 computes the script SHA-256 directly from bytes, keeps the A15 factorial/channel and Eₚ sequence checks unchanged, and writes a new audit result under a new name.
