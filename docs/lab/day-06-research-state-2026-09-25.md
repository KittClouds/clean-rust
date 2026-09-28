# Day 6 Research State

**Snapshot:** 2026-09-25 20:58 UTC. “Day 6” follows the supplied framing; the exact Day 0 date is not pinned in the inspected records. This is the baseline for the Day 20 comparison, not a replacement for sealed run artifacts.

**Starting line to preserve**

- **FAS:** S08–S10 observer geometry was exploratory on the already-revealed S01 population.
- **JEV:** Q left open whether halving the SHAM auxiliary-event weight was a useful, repeatable control.
- **R&D-C:** E001 began with explicit workflow state, guarded transitions, deterministic authority, receipts, and replay; E010 moved that base to a small/large compute router.

## FAS observer geometry

- **Strongest claim:** Fresh S11 quartets confirm higher off-diagonal transport for the fixed F observers than M observers, with negative raw-accuracy distance slopes for both. D_off = +0.106489, simultaneous 95% CI [+0.105512, +0.107466]. This is conditional on the admitted panel, fixed generator, and frozen observer bank.
- **Failed branch:** The tested S07 SAE recipe failed all 24 behavioral-fidelity checks despite high reconstruction R². This closes that recipe’s compatibility branch, not sparse structure in general.
- **Next authorized experiment:** None. S12’s equal-energy random-plane causal intervention is a proposal; it needs its own identity, seal, and execution authorization.
- **Not established:** Native LFM causal necessity, circuits or semantic features, model-seed or generator-family generalization. The separate FAS-00 substrate disposition remains SENSOR_FAIL_NO_SIGNAL.
- **Seal/root:** S11 result root 23758806537df1895772025e97824393dd4cd79ede7956360cd93f341c30740a; panel root 9011d425faaac7c6c1bee0f619a696a4469816ebeae1c0df2c6d4f8516fde824; sealed S05–S11 synthesis root b0a64d7c1befe925d50f34bdc5e6a73859b1d6a5c5d90152002feeac71898f3e. Run: D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01.
- **Compute/storage:** 5,318 quartets / 21,272 event rows; 512 replay cells; 10,000 bootstrap replicates; result tree 6,012,107,761 bytes. CPU/GPU-hours are not recorded in the cited result.
- **Stop rule:** If a separately authorized S12 fails its frozen selective-effect comparison with the equal-energy random-plane control, close that causal branch and retain S11 as a transport result only.

## JEV v0.8Q

- **Strongest claim:** Q-R1 tested 12 paired seeds. SHAM-LOW passed the joint gain/direction/locality/preservation rule in 1/12, below the 8/12 threshold; stiff-coupling passed 0/12 and the separate MAP-response label passed 4/12. The tested half-weight change is heterogeneous, not a reliable scalar gain/locality control.
- **Failed hypothesis:** A fixed half-dose is a repeatable operating-point knob under this recipe.
- **Next authorized experiment:** None after Q-R1. The common-history step-80 fork (SHAM weight 1.0 versus 0.5 for steps 81–120) is a proposed follow-up, not an authorized run.
- **Not established:** A population-wide optimizer law, a state-conditioned causal controller, or a predictor from these 12 seeds. The step-80 associations are post-exposure descriptions.
- **Seal/root:** Panel root f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53; completion-artifacts root 2947c8449892e092b2f334035e3fd044e33750d1e71a502c80947de13395fd53; completion-seal file SHA-256 4e63e379671d7641cb174f1ed3db6ac8395b6c49e4c644392d55996eab1df68c. Run root: D:\codex-runs\jev-information-density-v08q-r1\training-v01. The original packet seal still says pending execution because it is the pre-run authorization record; use the completion seal for current execution status.
- **Compute/storage:** 48 runs, 192 trained checkpoints, 1,632,000 prediction rows; panel plus training trees 4,499,844,374 bytes. Failed evaluation and analysis-binding attempts remain preserved; training was not rerun and the panel was opened once.
- **Stop rule:** If the common-history late-dose interaction does not recur under a fresh panel and new seeds, stop promoting state-conditioned dose control and report recipe-bounded heterogeneity.

## R&D-C Adaptive Runtime

- **Strongest claim:** E001’s deterministic authority base now supports a bounded fast-action region. E010 passed its gate separately on ripgrep and turbovec: 13/16 tasks were handled directly at 100% observed precision; hybrid completion was 16/16 versus 13/16 for always-large, avoiding 13 large calls. This is a two-repository, eight-prompt-per-repository result.
- **Current failure:** E011-R2’s same-bank, shadow-only order intervention produced wrong accepted small actions on ripgrep (1/8) and turbovec (2/7). Candidate-order robustness is not established. E010 also used more total tokens (27,652 vs. 26,342), despite fewer large calls and lower measured elapsed time (145.2s vs. 242.1s).
- **Next authorized experiment:** None found after E011-R2. A fresh independent task bank, after the presentation-sensitivity issue is addressed, is a candidate follow-up; it is not authorized here.
- **Not established:** General transfer beyond these two frozen repositories, token savings, a model-internal mechanism, or safe performance on broader live coding work. E011 reused opened E010 labels and executed no actions.
- **Seal/root:** E010 run C:\rd-c\experiment-010\artifacts\runs\e010-20260925-cross-repo-01; frozen-input lock SHA-256 323f14b07c698d289af6f11a2e894014538bd6be0644de8786b30b1e954f8165; score-replay lock SHA-256 0d0e8bbee1f5fb42d50219bb342e1b6d82d7eb45af38f6a94938c6875bcd5c6a. Latest diagnostic E011-R2 output-seal SHA-256 8850a19b7580d2b5baabe942acc0f3c0722c2ac8417147e33deb0ad5cf7acb63; score SHA-256 21db5937034016065a5ecfc694ff0207871acfff51876dcf8fb770cf1a3e5157.
- **Compute/storage:** E010 ran four lanes over 16 tasks; E011-R2 adds 64 shadow observer outputs. E010, E011, E011-R1, and E011-R2 frontier trees total 5,032,075 bytes, excluding model caches, repository snapshots, and build targets.
- **Stop rule:** Any wrong accepted direct action, authority/replay invariant failure, or per-repository hybrid completion below always-large stops expansion of the direct-action region.

## Questions answered by Day 6

1. **Does the S10 transport pattern replicate on fresh worlds?** Yes, within S11’s fixed generator and observer scope.
2. **Is half-weight a reliable gain/locality knob?** No, under the registered Q-R1 recipe and threshold.
3. **Can the frozen switchboard use a safe direct-action region on other repositories?** Yes on these two snapshots; its robustness to candidate ordering remains open.

**Resource snapshot:** Current frontier output trees only: FAS 6.012 GB; JEV 4.500 GB; R&D-C E010/E011 5.032 MB. At capture, C: had 356,865,495,040 bytes free and D: (the project’s :G target volume) had 772,241,625,088 bytes free. These are not whole-project or model-cache totals. No comparable CPU/GPU-hour ledger was found for FAS or JEV.

**For all agents:** Treat this file as an immutable historical anchor. For the next checkpoint, create a new dated snapshot and carry forward these same fields. Keep “executed,” “authorized,” and “proposed” separate; retain failed attempts and their receipts; do not combine claims across labs.

**Canonical history pointers:** [FAS synthesis](../experiments/fas-s05-s11-observer-geometry-synthesis-v01/FAS-S05-S11-OBSERVER-GEOMETRY-SYNTHESIS-V01.md) · [JEV Q-R1 readout](../experiments/jev-information-density-v08q-r1/Q-R1-RESEARCH-READOUT-V01.md) · [R&D-C E001 baseline](C:/rd-c/experiment-001/README.md) · [E010 result](C:/rd-c/experiment-010/README.md) · [E011 causal diagnostic](C:/rd-c/experiment-011/artifacts/runs/e011-20260925-causal-evidence-01/experiment-011-report.md) · [E011-R2 report](C:/rd-c/experiment-011/repairs/candidate-presentation-factorial-v1/artifacts/runs/e011-r2-20260925-presentation-factorial-01/factorial-report.md)
