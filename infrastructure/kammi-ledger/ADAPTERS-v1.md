# Immutable adapters v1

Only registered, allowlisted implementations can transform a custody view.
Adapter identity binds source schema, target schema, version and exact implementation
source bytes. AdapterApplied binds source, derived view, implementation, actor,
authorization and purpose. Original source bytes and identity remain unchanged.

EVAL_CELLS_RENAME_V1 maps evaluation_checkpoint_cells to evaluation_cells and changes
evaluation-v1 to evaluation-v2. Missing or ambiguous source fields fail closed.
Independent verification implements the transformation separately.
New adapters require Library Lab code review and qualification, never arbitrary Cypher.
