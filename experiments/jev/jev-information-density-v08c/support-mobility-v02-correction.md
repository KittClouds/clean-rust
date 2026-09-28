# Support-mobility census v0.2 correction

The first sealed census attempt stopped before report emission because it compared `selector_model_input_sha256` cardinality against the training-signature audit's `state_input_sha256` cardinality. Those are different digest domains: the former is the input key used by the frozen Phase 2 profile constraints; the latter is a state/query-text summary used by the signature audit.

The v0.1 freeze receipt and partial external output are preserved as a failed, non-promotable run. The corrected v0.2 wrapper reports both counts under their own names, compares only fields that share a definition, and otherwise leaves the frozen support-mobility definitions unchanged. No model, optimizer, or training path was reached in v0.1 or v0.2.
