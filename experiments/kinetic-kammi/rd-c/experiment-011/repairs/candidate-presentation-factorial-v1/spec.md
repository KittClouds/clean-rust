# E011-R2 — Candidate Presentation Factorial

## Question

Did the E011 candidate-permutation fragility come from changing numeric action IDs, option order, or their combination?

## Paired conditions

Start from the exact E010 full-frame bank and E011 candidate-permuted frame. For each of 16 tasks, create two single-factor variants:

- **IDs only:** keep the E010 action order and assign each option the fresh ID it received in E011's combined permutation.
- **Order only:** use E011's shuffled option order and restore each option's original E010 ID.

The source mapping is by stable patch digest. No action content, evidence, prompt, task identity, threshold, model, or output contract changes.

## Frozen evaluation

Use the E009 v5 small and large weights, prompt, output schema, normalization, 850/150 thresholds, and E002 authority boundary. Both models run in shadow mode. Compare every condition per repository: E010 full frame, IDs only, order only, and E011 combined permutation. E011-R1 canonicalization is reported as a separate attempted repair.

E010 labels were opened before this diagnostic. This paired autopsy can localize the interface failure on this bank; it cannot establish independent generalization. No fitting or retuning is permitted.
