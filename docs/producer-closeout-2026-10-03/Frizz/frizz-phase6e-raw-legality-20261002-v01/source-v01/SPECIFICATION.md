# Phase6E bounded raw legality audit

Freeze four raw views: local only; local+mf24; local+ms24; local+mf18.
Local = nine type coordinates, four ordered 1024-wide final-depth observable
entity mention means, four role one-hots (9 roles), four binding-present flags.
Missing bindings stay zero; no canonical name repair. Argument vectors use
parameter-free LayerNorm; global surfaces retain inherited TRAIN normalization.
No new depth or token selection. Identity is observable roles/bindings, no IDs.
E e32 is an additional matched reference, not a raw surface. No bilinear arm.

Every view: linear and 64-unit GELU tiny MLP; seed0, 8 epochs, epoch8 only,
AdamW .001 wd .01, clip1, root16 batches with grouped paired renderings.
Root-balanced class-normalized BCE legality only, no margin/selection/distance.
TRAIN fits only, fixed strict logit>0. Matched 1333 TRAIN/333 DEV canonical
EXECUTE eligible roots; all types/all exhaustive candidates. No E training.
FP32 CUDA, TF32 off, deterministic algorithms, memory budget45% GPU;
immutable CPU mmap entity bank, microbatch-local transfers. GPU allocation
failure is engineering restart, not evidence against a surface.

Report init/trained every arm, no post-hoc best-readout capability score.
Primary: full/same-type exact sets, Jaccard, precision, recall, FP/FN/root,
selected retention; secondary BA, frozen consequence filtered rankings.
Gate rejection remains error, empty sets abstain; eligibility never shrinks.
Renderer, candidate-count, legal-count slices; supports below200 descriptive.

Material precise grounding requires full exact>=.50, same-type exact>=.75,
Jaccard>=.80, precision>=.95, recall>=.90, retention>=.95, full exact gain
over Phase6D>=.10 with paired bootstrap lower>0 (2000,seed20261002).
Only raw arms qualify an adapter. If multiple qualify: highest full exact,
then precision, then listed view order and linear before MLP, no new fit.
Adapter exports separate grounding coordinates; E untouched, no consequence
retraining. If none qualifies, raw panel is flattened for PRECISE grounding
at this dose, even if classification BA improves. That earns one rank4
micro-LoRA run at a justified late q_proj/v_proj boundary; exact pilot
boundary/design frozen in a second receipt after raw audit, before training.
No rank/layer sweep. Adaptation result is never prior frozen accessibility.

TRAIN-only error census: type, role/present binding, positive preconditions,
negative preconditions, missing preconditions, permission, candidate count,
legal-set size. Latent canonical truth only diagnostic, never raw features.
Preserve Qwen, bridge, E, goals, consequence, gate and corpus bytes.
Protected EVAL never opened. Raw logits/metrics and final artifacts require
fresh-process exact replay and hash verification. Preserve engineering failures.
