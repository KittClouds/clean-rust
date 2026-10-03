# OBS-OPEN-DISC-02E checkpoint

Status: `PASS`

Authority: `OBS_OPEN_DISC02E_DISCOVERY_V1`

DISC-02E root:

`b626d058c5719d797e84848ed7141f2a0c0a3d3a5f28ad3b2f7b24b405e62697`

Parents:

- DISC-02P: `f6ab7b3f4ba95e70399367e4a16140549bea5e16fe9a58d460e5166ec4200877`
- MEAS-02: `f7abf12d1473a5e1eddc8a7efb84ff7224811eda83ad62ba4fe300a7648ce5ea`

## Population and firewall

- Discovery sessions admitted: 257
- Confirmation sessions read: 0
- Confirmation observations read: 0
- Confirmation state: `FROZEN_UNOPENED`

Twenty-two discovery sessions contain a post-construction M1 path gap. The
executor retained only each complete causal prefix, classified the open extreme
chain as `SOURCE_PATH_INCOMPLETE`, and masked unsupported later cells. It did
not interpolate, bridge, or delete those sessions.

## Corpus

- M1 causal-prefix bars: 96,396
- Range objects: 7,710
- Strict upper candidates: 4,372
- Strict lower candidates: 4,038
- Candidate-range relations: 252,300 / 252,300 expected
- Complete full-session paths: 235
- Terminal survivors: 470

## Frozen formal results

| Family | Supported cells | Max abs t | Monte Carlo p | Wilson 99% | Holm threshold | State |
|---|---:|---:|---:|---|---:|---|
| Upper vs mirrored-lower same-direction extension | 190 | 2.202699 | 0.5454 | [0.532548, 0.558192] | 0.025000 | `FAILS_OMNIBUS_EVIDENCE` |
| Upper vs mirrored-lower opposite displacement | 190 | 1.563702 | 0.6493 | [0.636913, 0.661489] | 0.050000 | `FAILS_OMNIBUS_EVIDENCE` |
| Signed range-relative close surface | 11,235 | 2.174696 | 0.4022 | [0.389638, 0.414891] | 0.016667 | `FAILS_OMNIBUS_EVIDENCE` |

Promoted discovery candidates: 0.

Prospective confirmation contracts: 0.

No localization or robustness gate was entered because no family passed its
frozen omnibus and Holm requirements.

## Reconstruction

- Independent builds: 2
- Thread configurations: 1 and 4
- Byte mismatches: 0
- Artifacts in each D-drive payload: 24
- Bytes in each D-drive payload: 250,571,269
- Physical artifact-set hash:
  `a26727aa98a682e588bc0701c129b1508bc1b7913391156c5fbbb32152aebfc5`
- Execution code hash:
  `7c75f51713a0d86bfb6661bbf4a96f378f63f5aa40e109bf749473e62de43ceb`

Bulk authority remains local on D:

- `D:\obs-open-01\discovery\disc02e-build-a`
- `D:\obs-open-01\discovery\disc02e-build-b`

The compact repository seal contains receipts, findings, manifests, and a
content-addressed pointer to the local bulk payload. No economic, trading,
mechanistic, or confirmation authority was earned.
