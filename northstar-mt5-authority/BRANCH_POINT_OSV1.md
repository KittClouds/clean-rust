# OSV1 Branch Point — MT5 Authority Freeze

Date: 2026-08-14

This note freezes the MT5-side state at the point where the completed
observational program stops being one linear road and branches into new research
programs.

## Closed authority

Northstar Gate 16.6 closed the observational science and Gate 16.7 released it
through a read-only consumer boundary.

```text
OSV1 scientific root
6e18e10fc0fb3571aa21b4e20105f783dafe2872812d217d672ab5e959bb890d

Northstar release tag
osv1-v1.0.0

Northstar release commit
9ced26cb3a7ae6aeefe6c1a2f63a493e28ceca48
```

Git identity locates a repository state. It does not replace the OSV1 scientific
identity.

## Local-only corpus boundary

The bulky MT5 observation payloads are deliberately excluded from remote
storage.

```text
storage policy     D_DRIVE_ONLY_NOT_REMOTE
local root         D:/northstar-mt5-corpus/osv1-mt5-freeze-v1
payload files      590
payload bytes      11986996702
payload GiB        11.163761
manifest SHA-256   58d13f99985a3256c00a0b2a4ed895cd8dc778db969dae6f20da8e54f18cf768
remote storage     false
```

The repository contains the deterministic manifest and receipt, not the payload
bytes. Missing access to the D-side payload is `LOCAL_AUTHORITY_UNAVAILABLE`, not
evidence that the observations are absent or invalid.

## Frozen boundaries

- OSV1 remains immutable and content-addressed.
- Gate 15, 15.5, 16, 16.5, 16.6, and 16.7 artifacts retain their declared
  epistemic limits.
- `COLD_REHYDRATION` is not `COLD_SOURCE_REGENERATION`.
- `NULL`, `CENSORED`, `NOT_EVALUABLE`, `INSUFFICIENT_SUPPORT`, `OPEN`, and
  `FROZEN_UNOPENED` remain distinct typed states.
- Downstream products may read, filter, project, visualize, and derive sidecars.
  They may not rewrite sealed authority.
- No sealed observational artifact carries trading or economic authority.

## Branches after this freeze

```text
OBS-*   new observational and representation research
PHX-*   Phoenix visualization and graph analytics sidecars
FIN-*   financial research kept downstream of observational authority
```

Future work begins from these receipts. It does not silently extend OSV1 or
rewrite the path that produced it.
