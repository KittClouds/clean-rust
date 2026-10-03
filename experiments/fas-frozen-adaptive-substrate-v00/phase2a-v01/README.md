# FAS-00 Phase 2A paperwork v01

This versioned sidecar seals the frozen feature-extraction packet and the Phase 3 sensor-qualification contract. It does not edit the sealed FAS root or Phase 1 v03 artifacts.

The Phase 2A packet is prepared for explicit authorization only. Its seal does not authorize model contact. At this checkpoint, the LFM remains unloaded; feature extraction, probe fitting, mechanism execution, and Phase 5 generation remain unauthorized.

The packet binds the pinned LFM revision, the existing `FAS_FEATURE_V1` contract, and only the Phase 1 v03 qualification corpus. It specifies a new FAS-only model snapshot location and feature cache location. Neither location is created by this paperwork step.

The Phase 3 contract freezes the data split, probe family, optimizer, normalization, task labels, transfer slices, negative controls, thresholds, and failure dispositions before feature extraction. Probe training still requires separate explicit authorization after Phase 2A extraction is complete.

Verify or create the paperwork seal from this directory:

```powershell
& .\scripts\seal-phase2a.ps1
& .\scripts\seal-phase2a.ps1 -Verify
```

The seal verifies the Phase 0 and Phase 1 v03 parent seals first, then hashes this sidecar's packet, contract, README, and seal script. It records readiness for a user authorization decision while keeping every model and learning authorization false.
