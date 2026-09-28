# E012 Audit Amendment A17 — Nuisance Feature Row Adapter

**State:** audit-only implementation repair over the unchanged A14 bank; no model contact.

The A14 nuisance audit stopped before writing a report. Candidate feature rows intentionally store the selected category under `value`, but the leave-one-family-out helper indexed them by the original feature name. A17 reads either representation and hashes the unchanged source, labels, frames, and truth index before reporting. The failed A14 launch is retained.
