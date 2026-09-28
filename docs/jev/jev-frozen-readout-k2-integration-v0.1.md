# K2-Horizon frozen-readout integration v0.1

This note adds IFM/K2-Horizon-0.9B as a third frozen causal backbone for the
compatibility readout probe. It does not authorize extraction, head training,
Uno loading, adapter training, or any Phoenix change.

## Pinned model entry

The probe uses the following local model key and immutable Hub revision:

| local key | Hub repository | revision | custom code | tokenizer adjustment |
| --- | --- | --- | --- | --- |
| k2-horizon-0.9b | IFM/K2-Horizon-0.9B | 9fa6faa55fe1c9eb008bb241cc6fb7e4536d0e91 | required | remove token_type_ids |

The revision was resolved from the Hub model metadata on 2026-09-19. The model
card documents a Transformers loading path with trust_remote_code=true and
removal of token_type_ids; both behaviors are isolated to this model entry.

The existing MiniCPM and Qwen entries retain their prior revisions, do not opt
into remote code, and retain their prior tokenizer batch behavior.

## Local snapshot convention

When the parent runs extraction, the pinned K2 snapshot should be available at:

~~~text
D:\codex-runs\jev-zero-training-recon-v01\models\k2-horizon-0.9b
~~~

The probe remains local-only during extraction. It will not download weights or
resolve a floating Hub revision. The directory must contain the complete model
snapshot, including the custom Python files required by the checkpoint.

## Loader boundary

experiments/jev-frozen-readout-v01/probe.py now records a MODEL_SPECS entry for
each backbone. K2 alone sets:

~~~text
trust_remote_code = true
drop_token_type_ids = true
~~~

The tokenizer and model receive trust_remote_code from that spec. Before the
forward call, the K2 batch drops token_type_ids; if a model exposes a forward
signature without a kwargs catch-all, unsupported named inputs are filtered at
the same boundary. Hidden-state extraction, pooling, candidate encoding, and
all compatibility-head behavior remain unchanged.

K2's custom causal-LM wrapper does not populate the generic
`hidden_states` tuple. For final-layer extraction only, the probe calls the
wrapper's base model and reads `last_hidden_state`; internal-layer probes remain
unsupported until the model exposes a validated hidden-state interface. This
is an adapter boundary, not a change to the canonical semantics.

The feature cache and manifest retain:

~~~text
model_name
repo_id
revision
trust_remote_code
~~~

so K2 results cannot be confused with an unpinned or differently configured
checkpoint.

## Scope boundary

K2 is a same-scale, high-capability frozen comparison point alongside MiniCPM5
and Qwen3. The Uno repository and any conditional LoRA are intentionally not
part of this slice. No model weights are modified by this integration.

## Parent-run command shape

After the snapshot is independently materialized, the parent may use the
existing extraction command with only the model key changed:

~~~powershell
$py = 'D:\codex-runs\jev-zero-training-recon-v01\venv\Scripts\python.exe'
& $py experiments/jev-frozen-readout-v01/probe.py extract --model-name k2-horizon-0.9b --models D:\codex-runs\jev-zero-training-recon-v01\models --output D:\codex-runs\jev-frozen-readout-v01\features
~~~

This integration worker does not run that command.
