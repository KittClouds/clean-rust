# Threads

Each agent thread's work lives in one place. Thread ids are Codex desktop thread ids; sub-agent threads spawned by a thread are counted under it.

| Folder key | Thread | Thread id | Location in this branch | Scope | Files | MB kept | Files left in place | GB left in place | Conflicts |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| phoenix-product | Golden Path Close Out; Audit Breeze TTS integration; Claude Code Phoenix sessions | 01a0cf53-2df4-7123-9237-82bcdf8f9148; 01a06ed5-a0d4-7ad2-98a7-1fe26a15e96c | `crates/, apps/, vendor/, tools/, docs/` | Phoenix Native product, Reader/TTS, graph, vault adapter, analysis bridge | 1666 | 68.9 | 257 | 0.03 | 15 |
| chief-kammi | Chief Kammi | 01a0de04-f3a7-7bb0-9dbe-e7e1a38bb339 | `infrastructure/` | Kammi Library service (kammi-ledger) and governance; custody and bookkeeping | 349 | 6.1 | 187241 | 5.64 | 0 |
| kinetic-kammi | Kinetic Kammi | 01a0d426-04dc-7941-b0b0-30b1e5a09442 | `experiments/kinetic-kammi/rd-c/` | R&D-C selective-cognition program, experiments 001-013 (C:\rd-c) | 2874 | 17.0 | 698012 | 41.45 | 0 |
| fly-chief | Fly Chief (+ Drosophila Heresy deputy) | 01a09283-4813-7fc0-93e1-e6db6b0d75b4 | `experiments/fly-chief/` | drosophila-heresy Q-series | 4558 | 38.5 | 40288 | 22.28 | 0 |
| fly-drop | Design FLY-DROP experiment | 01a0c502-4556-7051-8865-faa2d7289164 | `experiments/fly-drop/` | FLY-DROP-00, FLY-REACH-00..03, FLY-PHENO-00 | 3865 | 13.3 | 6639 | 35.42 | 0 |
| jev | JEV (+ v0.8 audit, curation and deputy threads) | 01a0baf4-677a-7a41-a42c-be4b10bd2dda | `experiments/jev/, docs/jev/` | JEV information-density and frozen-readout series | 719 | 8.1 | 6434 | 2.38 | 0 |
| fas-paused | FAS paused | 01a0cc60-31a9-7222-88b6-8529ea56162b | `experiments/fas-paused/` | FAS frozen adaptive substrate, S01-S12 | 690 | 5.2 | 849 | 0.13 | 0 |
| fas-r1 | FAS-R1 | 01a0d986-610d-78e1-bb7b-7590d41a3f1c | `experiments/fas-r1/` | semantic particle reachability; bend-ac-00 | 256 | 3.2 | 2275 | 0.69 | 7 |
| frozen-fabrique | Frozen Fabrique (formerly Liquid Lab) | 01a0da51-f0a8-7dd0-94f7-a7e424e77021 | `experiments/frozen-fabrique/` | frozen observer bundle engineering; E013 episode factory | 1016 | 22.4 | 326 | 0.01 | 2 |
| ar04 | AR04 (adaptive runtime) | 01a0bba0-2621-7ad1-addc-b27100855117 | `experiments/ar04/` | adaptive runtime AR-03C..AR-04E | 587 | 5.3 | 256 | 0.55 | 0 |
| lab-shared | cross-lab notes (Frozen Fabrique, Kinetic Kammi) |  | `docs/lab/` | day research-state notes, onboarding, flight-recorder schema | 6 | 0.1 | 0 | 0.00 | 0 |

## Sources

| Source | Thread | Location | Kind | Commit | State | Note |
| --- | --- | --- | --- | --- | --- | --- |
| vault-adapter-wip | phoenix-product | `D:\phoenix-vault-product-20260927` | working-tree | 356002192382 | includes uncommitted/untracked | Golden Path Close Out: uncommitted vault adapter on codex/phoenix-vault-product-20260927 |
| phoenix-product | phoenix-product | `D:\phoenix-product-snapshot-20260923` | git | 8dfa1af06d64 | committed | codex/phoenix-graph-gate3b-20260924 (KittClouds/phoenix-native) |
| gliner25-bridge-worker | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed | origin/codex/phoenix-product-gliner25-bridge-20260923 |
| gliner25-bridge-contract | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed |  |
| gliner25-bridge-workspace | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed |  |
| gliner25-bridge-cargo | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed |  |
| gliner25-bridge-scope | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed |  |
| gliner25-worktree-check | phoenix-product | `C:\code land\clean-rust\rust-native\phoenix-gliner25` | working-tree | 9a88547372cd | includes uncommitted/untracked | shared checkout copy; conflicts only |
| gliner25-contract-worktree-check | phoenix-product | `C:\code land\clean-rust\rust-native\phoenix-gliner25-contract` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| phoenix-product:gliner25-eval | phoenix-product | `C:\code land\clean-rust\experiments\phoenix-gliner25-eval` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| kammi-ledger | chief-kammi | `C:\code land\clean-rust\program-infrastructure\kammi-ledger` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| governance | chief-kammi | `C:\code land\clean-rust\program-infrastructure\governance` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-chief:drosophila-heresy | fly-chief | `C:\code land\clean-rust\experiments\drosophila-heresy` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-chief:stray-root-q10-pred1 | fly-chief | `C:\code land\clean-rust\q10-gc1-lr1-requal1-csc1-pred1-v1` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-drop-00 | fly-drop | `C:\code land\clean-rust\experiments\fly-drop-00` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-drop-00-runner | fly-drop | `C:\code land\clean-rust\experiments\fly-drop-00-runner` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-pheno-00 | fly-drop | `C:\code land\clean-rust\experiments\fly-pheno-00` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-pheno-00-v0.2-qcomp | fly-drop | `C:\code land\clean-rust\experiments\fly-pheno-00-v0.2-qcomp` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-pheno-00-v0.3-qtask | fly-drop | `C:\code land\clean-rust\experiments\fly-pheno-00-v0.3-qtask` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-pheno-00-v0.4-qreal | fly-drop | `C:\code land\clean-rust\experiments\fly-pheno-00-v0.4-qreal` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-reach-00 | fly-drop | `C:\code land\clean-rust\experiments\fly-reach-00` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-reach-01 | fly-drop | `C:\code land\clean-rust\experiments\fly-reach-01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-reach-02 | fly-drop | `C:\code land\clean-rust\experiments\fly-reach-02` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-reach-02-v0.1b | fly-drop | `C:\code land\clean-rust\experiments\fly-reach-02-v0.1b` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:fly-reach-03 | fly-drop | `C:\code land\clean-rust\experiments\fly-reach-03` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fly-drop:close-branch | fly-drop | `C:\code land\clean-rust` | git | a3cb9ddb002a | committed | sealed close commit; differences recorded as conflicts |
| fly-drop:close-branch-runner | fly-drop | `C:\code land\clean-rust` | git | a3cb9ddb002a | committed |  |
| jev:jev-corpus-bridge-v01 | jev | `C:\code land\clean-rust\experiments\jev-corpus-bridge-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-decision-world-v01 | jev | `C:\code land\clean-rust\experiments\jev-decision-world-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-decision-world-v02 | jev | `C:\code land\clean-rust\experiments\jev-decision-world-v02` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-frozen-readout-v01 | jev | `C:\code land\clean-rust\experiments\jev-frozen-readout-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-frozen-saturation-v04 | jev | `C:\code land\clean-rust\experiments\jev-frozen-saturation-v04` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-frozen-scaling-v05 | jev | `C:\code land\clean-rust\experiments\jev-frozen-scaling-v05` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-frozen-scaling-v06 | jev | `C:\code land\clean-rust\experiments\jev-frozen-scaling-v06` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08b | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08b` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08c | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08c` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08d | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08d` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08e | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08e` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08g | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08g` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08h | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08h` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08i | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08i` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08j | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08j` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08k | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08k` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08l | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08l` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08m | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08m` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08n | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08n` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-r1 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-r1` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-r2 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-r2` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v02 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v02` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v03 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v03` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v04 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v04` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v05 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v05` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v06 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v06` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v07 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v07` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v08 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v08` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08p-v09 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08p-v09` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08q | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08q` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08q-r1 | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08q-r1` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08q-r2-late-branch | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08q-r2-late-branch` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-information-density-v08q-r3-selectivity | jev | `C:\code land\clean-rust\experiments\jev-information-density-v08q-r3-selectivity` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-lfm-variable-v07 | jev | `C:\code land\clean-rust\experiments\jev-lfm-variable-v07` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-semantic-stress-v03 | jev | `C:\code land\clean-rust\experiments\jev-semantic-stress-v03` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:jev-zero-training-recon-v01 | jev | `C:\code land\clean-rust\experiments\jev-zero-training-recon-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| jev:curated-c100 | jev | `C:\Users\shuga\.codex\worktrees\3c8a\clean-rust\experiments\jev-curated-c100-v01` | working-tree | e5a84994da60 | includes uncommitted/untracked |  |
| jev:docs | jev | `C:\code land\clean-rust\docs` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-frozen-adaptive-substrate-v00 | fas-paused | `C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s01-frozen-sensor-transfer-cartography | fas-paused | `C:\code land\clean-rust\experiments\fas-s01-frozen-sensor-transfer-cartography` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s02-original-corpus-readout-surface-attribution-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s02-original-corpus-readout-surface-attribution-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s03-factor-competition-decision-geometry-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s03-factor-competition-decision-geometry-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s04-controlled-factor-to-decision-transfer-geometry-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s04-controlled-factor-to-decision-transfer-geometry-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s05-crossed-representation-readout-decomposition-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s05-crossed-representation-readout-decomposition-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s05-s11-observer-geometry-synthesis-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s05-s11-observer-geometry-synthesis-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s06-representation-scaler-probe-compatibility-cube-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s06-representation-scaler-probe-compatibility-cube-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s07-sparse-compatibility-cartography-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s07-sparse-compatibility-cartography-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s08-exact-decision-surface-attribution-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s08-exact-decision-surface-attribution-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s08-exact-decision-surface-attribution-v02 | fas-paused | `C:\code land\clean-rust\experiments\fas-s08-exact-decision-surface-attribution-v02` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v02 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v02` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v03 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v03` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v04 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v04` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v05 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v05` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v06 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v06` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v07 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v07` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v08 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v08` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s09-depthwise-decision-subspace-emergence-v09 | fas-paused | `C:\code land\clean-rust\experiments\fas-s09-depthwise-decision-subspace-emergence-v09` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s10-cross-depth-observer-transport | fas-paused | `C:\code land\clean-rust\experiments\fas-s10-cross-depth-observer-transport` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s10-cross-depth-observer-transport-v02 | fas-paused | `C:\code land\clean-rust\experiments\fas-s10-cross-depth-observer-transport-v02` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s10-cross-depth-observer-transport-v03 | fas-paused | `C:\code land\clean-rust\experiments\fas-s10-cross-depth-observer-transport-v03` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s11-cross-depth-observer-transport-replication-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s11-cross-depth-observer-transport-replication-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s12-accessibility-necessity-dissociation-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s12-accessibility-necessity-dissociation-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-paused:fas-s12-observer-plane-causal-dependence-v01 | fas-paused | `C:\code land\clean-rust\experiments\fas-s12-observer-plane-causal-dependence-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-r1:bend-ac-00 | fas-r1 | `C:\code land\clean-rust\experiments\bend-ac-00` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-r1:fas-r1-semantic-particle-reachability-v00 | fas-r1 | `C:\code land\clean-rust\experiments\fas-r1-semantic-particle-reachability-v00` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| fas-r1:stage0-worktree | fas-r1 | `C:\Users\shuga\.codex\worktrees\fas-r1-stage0-20260925\clean-rust\experiments\fas-r1-semantic-particle-reachability-v00` | working-tree | fb984e362a20 | includes uncommitted/untracked | codex/fas-r1-stage0-20260925 worktree; adds files missing from shared checkout |
| frozen-fabrique:e013-episode-factory | frozen-fabrique | `C:\code land\clean-rust\experiments\e013-episode-factory` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| frozen-fabrique:fas-frozen-observer-bundle-engineering-v01 | frozen-fabrique | `C:\code land\clean-rust\experiments\fas-frozen-observer-bundle-engineering-v01` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| frozen-fabrique:e4-0-worktree | frozen-fabrique | `C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust\experiments\fas-frozen-observer-bundle-engineering-v01` | working-tree | e5a84994da60 | includes uncommitted/untracked |  |
| frozen-fabrique:e4-0-audits | frozen-fabrique | `C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust\audits` | working-tree | e5a84994da60 | includes uncommitted/untracked |  |
| frozen-fabrique:e013-worktree | frozen-fabrique | `C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory` | working-tree | e5a84994da60 | includes uncommitted/untracked |  |
| ar04:adaptive-runtime | ar04 | `C:\code land\clean-rust` | git | 4109350e37c9 | committed | linear chain adaptive-runtime-cleanroom-20260920 -> ar-03c -> ar-03d -> ar-03d-r1 -> ar-04a..04e; tip carries all |
| kinetic-kammi:rd-c | kinetic-kammi | `C:\rd-c` | working-tree |  | includes uncommitted/untracked | C:
d-c is not a git repository |
| lab:docs | lab-shared | `C:\code land\clean-rust\docs` | working-tree | 9a88547372cd | includes uncommitted/untracked |  |
| gliner25-bridge-esaxx | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed | vendored patch crate required by the bridge workspace |
| gliner25-bridge-scirs2 | phoenix-product | `C:\code land\clean-rust` | git | b50d3c78e145 | committed | vendored patch crate required by the bridge workspace |
