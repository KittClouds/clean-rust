# Phase 6C — transition-consequence acquisition

Prospective planner-distillation trial. One construction, fixed epoch8. Qwen
BF16 backbone, bridge/E, BANK-v3-core, paired renderings, candidate menu, and
goal heads remain immutable. CPU/FP32 four-thread sidecar; no shared-GPU work.
F parked. No comparator, recurrence, LoRA, adaptation, or hidden-surface search.

Population: the same 1,333 TRAIN /333 DEV canonical EXECUTE-eligible roots
audited in Phase6B. Both observable renderings stay grouped. All candidates,
including other action types, remain exhaustive. This is not acquisition over
the entire non-EXECUTE bank; that generalization is explicitly unmeasured.
Eligibility is inherited before this trial. Selected IDs never supervise the
organ or construct its ordering examples. They are used only by reporting.

Target: exact pinned canonical counterfactual remaining distance after a legal
action, tick1, depth cap8/state cap40,000. Codes0..8 are certified SOLVED,
9 UNSAT_EXHAUSTED,10 cap/state-limit UNKNOWN,11 ILLEGAL. No category merger.
Existing Phase6B labels are replayed with the simulator in a fresh process.

ABI: existing observable action type9; four positional qualified Qwen entity
vectors1024 plus typed observable roles9 and presence; two E goal-role vectors
1024 plus count/empty/multiple flags; six TRAIN-normalized global vectors1024;
frozen E c256/e32/s64. Existing E and observable coordinates only. CPU replay
of both renderings uses the same frozen E checkpoint. Primary cache alignment
against original FP16 cache allows .02 absolute arithmetic error, prospectively,
not target-dependent tolerances. Missing/ambiguous bindings stay missing/ambiguous.
No candidate-ID embedding, gold facts, legality, distance, or policy mask in ABI.

Architecture: shared entity projection1024→32, world projection1024→16;
explicit argument × mean-goal product; concatenate qualified typed pieces and
frozen states (823 dimensions), LayerNorm,128-GELU,64-GELU. Status head4 and
one distance location with eight strictly ordered learned cutpoints. The
conditional distance distribution covers all 0..8 regardless of TRAIN support.
P(d>k) is monotone. Status and distance are separate outputs. Ranking uses
p_solved E[d]+9p_exhausted+10p_unknown+11p_illegal. These three penalties are
a declared inference convention, not certified ordinal distances for unknown
or exhausted/illegal states. Conditional legal-vs-legal ordering is mandatory
to prevent apparent success coming only from predicted illegality separation.

TRAIN: eight epochs, seed0,16 canonical-root batches, both renderings, AdamW
lr.001/wd.01, norm clipping1. Status CE uses clipped inverse-square-root TRAIN
frequencies; ordinal BCE uses TRAIN threshold prevalence clipped [.02,.98].
Each term is canonical-row normalized. Solved-only SmoothL1 /8 weight.25;
same-type solved unequal-distance softplus margin1 ordering weight.25;
paired cost invariance /121 weight.05. At most64 deterministic evenly spaced
TRAIN ordering pairs/root. No selected identity, no protected truth, no DEV fit,
no checkpoint selection or architecture sweep. DEV scoring only init and epoch8
after specification freeze; no interim DEV feedback. Fixed linear/MLP Phase6A
references and gold oracle retained separately from own-init acquisition delta.

Survival rule, primary rendering only: legal macro recall gain≥.05 AND solved
conditional MAE reduction≥.25 vs own-init; same-type top1 gain≥.05 versus frozen
E-linear independent scorer with paired-root CI95 lower>0; conditional same-type
legal certified ordering root mean≥.60 and gain≥.05 versus own-init with CI95
lower>0. Bootstrap2,000,seed20261002. All gains/panels reported, not composites.
Per-class/action/candidate-band claims with<200 DEV roots remain descriptive.
Ordering support<200 is explicitly a pilot support limitation, never converted
to a reliability-level claim. Failed factor/order/ranking gates dispose the
construction; no automatic escalation. Factor-only acquisition is distinguished
from operational survival and illegality-only ranking improvement.

Recorder: primary/paired class supports; legal multiclass accuracy and macro
recall; certified conditional distance MAE and ordinal error; all unequal
certified same-type ordering, selected-type subset; selected and optimal rank,
MRR/top1/top3/top5 separately under full/same-type/diagnostic gold-legal masks;
candidate-count and renderer slices; paired renderer disagreement. Existing
E goal/binding/globalization full-bank recorder is preserved byte-for-byte,
before/after, by sidecar isolation and checkpoint/logit hashes. Candidate
permutation equivariance tested. No claim of a new goal acquisition experiment.

Known-solvable controls, simulator replay, exact input/model/metric fresh-process
replay, cost/parameter/latency/memory observations and sealed hashes required.
Protected EVAL remains unopened. No result can establish a Qwen information ceiling.
