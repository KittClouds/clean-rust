# v0.8D runner adapter v0.2

## Scope

The v0.8D scientific contract and support builder remain unchanged. The first sealed launcher identity (`common-support-v01`) failed before loading signature-index rows because the builder treated `outputs.external_run_directory`—a path locator—as a file output and correctly refused to overwrite that existing directory. The directory contains only its freeze receipt. It is preserved as a non-executed, non-promotable attempt.

This adapter creates a fresh external identity (`common-support-v02`). It re-verifies the v01 freeze, all source/input hashes, the upstream firewall/eligibility audits, and the pinned v0.8C receipt. It removes only the `external_run_directory` locator from the in-memory output-artifact map, selects a new run directory, and calls the exact frozen v0.8D builder. It does not edit the v0.8D contract or builder and does not change any scientific parameter, quota, threshold, or data selection rule.

## Run sequence

1. `execute_v08d_runner_v02.py freeze` validates the original v01 freeze and seals the adapter plus its sources into a new v02 receipt.
2. `execute_v08d_runner_v02.py run` verifies that receipt and delegates to the frozen builder.

The v02 receipt is an execution-layer correction, not a new statistical design. Result artifacts retain the parent v0.8D protocol ID and carry the adapter identity through the v02 freeze/integrity receipts.

## Boundaries

No model, tokenizer, feature cache, training process, Phoenix data, or prior bank is accessed or modified. The only intended outputs are metadata census, a profile, capacity-witness ID manifests, and integrity receipts.
