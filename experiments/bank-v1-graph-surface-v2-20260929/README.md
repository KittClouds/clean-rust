# BANK-v1 Graph Surface Extraction v2

Rung 1 is a bounded engineering readout of graph-local structure in the frozen LFM2.5-230M-Base checkpoint. Rung 0 remains read-only: this experiment uses its four locked surface definitions, its cached whole-row vectors, and its first-token dead control. It does not search new pooling surfaces, tune the backbone, generate text, change authority, or touch retrieval.

## What the fresh pass exposes

The single new backbone pass reads only each BANK `input_text`. A fast-tokenizer offset map aligns exact `bindings[].mention` strings to rendered token spans. It writes entity mention-span means, final mention-endpoint vectors, and separate goal-field mention vectors. When an entity string appears repeatedly, occurrence vectors are pooled deterministically into one entity vector for that rendered row. Missing exact spans are recorded and omitted from task examples. Structured graph IDs and labels are not supplied as side-channel features. Renderer S9 itself contains symbolic argument-ID strings; where these are the only available local spans, they remain in the model input and are called out in the report against identifier-type controls.

The local surfaces are fixed derivations of those span primitives:

| Surface | Local view |
|---|---|
| `middle_plus_final` | midpoint span mean concatenated with final-layer span mean |
| `final_plus_mean` | final-layer last mention subtoken concatenated with final-layer span mean |
| `layer_m4_final` | layer four transformer blocks before final, span mean |
| `full_mean` | final-layer span mean |

Rung 0's corresponding whole-row views and `first_token` are loaded read-only as controls. The separate goal vectors pool only occurrences in the rendered `Goal:` field; they are scored as a goal-argument slice of node-type prediction.

## Fixed graph tasks

Canonical BANK `worlds/*.jsonl` truth is joined only after extraction. The runner evaluates node type, binary edge existence, binary-fact predicate label, exact one-hop and exact two-hop membership on the undirected `CONNECTED` graph, and link completion by ranking candidate objects for each directed binary fact. Binary tasks use fixed seeded within-world negatives. Train examples come from canonical TRAIN worlds; DEV and TEST stay at world level. Renderer breakdowns include held-out `S7/S8/S9` and available same-world paired renderers.

Each local surface uses the same linear, rank-128 factorized bilinear, and 128-unit one-hidden-layer MLP readouts. Cached whole-row and first-token controls use linear heads. Controls include majority/frequency, mention-string type rules, symbolic identifier-type rules, and lexical/identifier-type-pair-conditioned train frequencies. The fixed engineering gate and all task definitions are in `spec.json`; if no graph-local task clears it, stop this lane without another surface sweep.

## Run

The target-drive shorthand `G:` from the workspace instructions is mounted as `D:` in this environment.

```powershell
$exp = 'experiments/bank-v1-graph-surface-v2-20260929'
$bank = 'C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1'
$model = 'D:\phoenix-models\lfm2.5-230m-base-9d2be55'
$r0 = 'D:\phoenix-target-overgraph\bank-v1-surface-extremes-20260929'
$out = 'D:\phoenix-target-overgraph\bank-v1-graph-surface-v2-20260929'
python "$exp\extract_local.py" --bank-root $bank --model $model --r0-output $r0 --output $out --batch-size 64 --microbatch-size 16
python "$exp\derive_graph_data.py" --bank-root $bank --output $out
python "$exp\fit_graph.py" --bank-root $bank --r0-output $r0 --output $out
```

The extraction is checkpointed by input row. Preserve the output folder and rerun the exact command after interruption. The experiment is synthetic BANK engineering evidence only; it does not establish natural-language graph reasoning or production readiness.
