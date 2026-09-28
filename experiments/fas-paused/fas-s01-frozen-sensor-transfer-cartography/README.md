# FAS-S01 construction checkpoint

Project identity: `fas-s01-frozen-sensor-transfer-cartography`.

This is a new diagnostic project following the sealed FAS-00 sensor failure. The
Phase 0 seal binds its protocol, read-only cartography contract, and the FAS-00
terminal closure. It authorizes no analysis, probe fitting, or model contact.

The first prospective work item is descriptive cartography over explicitly
allowlisted, immutable FAS-00 features and Phase 3 diagnostics. Existing
features contain only FULL and QUERY_ONLY final-layer global means. Isolated
term vectors, span means, and token-position states require a new extraction
contract and separate model-contact authorization under FAS-S01.

Suggested workspace and run roots:

```text
C:/code land/clean-rust/experiments/fas-s01-frozen-sensor-transfer-cartography/
D:/codex-runs/fas-s01-frozen-sensor-transfer-cartography/
```

Seal or verify this construction checkpoint with:

```powershell
pwsh -NoProfile -File scripts/seal-project.ps1
pwsh -NoProfile -File scripts/seal-project.ps1 -Verify
```
