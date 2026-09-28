# Projection-free backup/restore v1

ledgerd.backup.backup takes custody and memory writer locks and copies objects/sha256,
journal, memory/journal and nonsecret configuration into a new external destination.
Policies/adapters/actors/grants are immutable journal facts, so the journal captures registries.
BACKUP.json binds path, size and SHA-256 plus custody/memory heads.

restore verifies every declared file and safe relative path before creating a new destination.
Never restore over a live store. Start a new daemon to reconstruct projections and compare
heads/counts/seals. Ladybug files are intentionally unnecessary.
Back up credentials/signing keys separately into an appropriately restricted secret store.
CAS orphans/staging bytes are not authoritative; committed referenced objects are essential.
