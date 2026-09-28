# R&D-C / Experiment 009 — Real Semantic Observer

Status: exploratory local pilot; scoring begins only after the bank and model bundles are hashed.

## Question

Can a frozen small semantic observer choose a useful next coding action from actual repository evidence, while E002 deterministic authority retains control and the observer improves the completion/cost tradeoff on held-out task families?

## Frozen scope

- Source: frozen local commit snapshots selected by the user. The evaluation bank contains two task families: asynchronous GPU picking and embedding batch execution.
- No model training, scratchpad, paid inspection, memory, context compiler, or adaptive budget.
- The three output heads are constrained JSON fields (`action_choice`, `applicability_milli`, `abstention_milli`) plus fixed deterministic thresholds. They are not separately trained neural heads.
- Small model: MiniCPM5-2B-Q8_0, local llama.cpp runtime.
- Large resolver: Ternary-Bonsai-2-27B-PTQ1_0, local experimental Prism llama.cpp runtime. Its experimental status is retained in all reports.
- Temperature 0, top-p 1, seed 0, maximum 128 output tokens. Each model receives the same canonical frame and action-option order within a task.
- Thresholds are fixed before model contact: minimum applicability 700/1000; maximum abstention 600/1000. A failed schema parse or out-of-range value compiles to rejection/abstention.
- Paid inspection is disabled by default. E008 closeout and its flagged 9/9 offer signature are preserved without retuning.

## Lanes

1. Hand-written deterministic policy.
2. Frozen small observer.
3. Frozen small observer, then large resolver only if the small output abstains or fails typed validation.
4. Always-large resolver.

The hand-written lane tokenizes the task prompt and each offered action's summary/excerpt, removes a fixed list of generic terms, and scores exact content-word overlap. It proposes only when the top action is unique, has at least three overlapping terms, and leads the runner-up by at least two; otherwise it abstains. This rule is fixed in the runner before model contact.

First replay every model against each identical frame in shadow mode; these outputs cannot execute actions. Then run each lane in an isolated task copy. Apply only an action that passes typed validation. Run the task completion check on that patch and record the E002 state transition, stable action ID, intent/completion receipts, and replay identity.

## Authority and completion

The model can propose only an offered action ID. E002 owns legal transitions. A selected candidate patch is executed in a disposable copy of the frozen snapshot. The task-specific executable completion check decides success. The label ledger is unavailable to observers and policies.

An action is a wrong legal action when it is a valid offered choice but its frozen completion check fails. Abstention does not execute a patch. Each lane starts from the same snapshot and uses the same action receipt policy.

## Measures

Per task and lane: completion, wrong legal actions, abstention, small/large calls, prompt and completion tokens, observer wall time, task-check wall time, total wall time, local inference cost proxy, billed API dollars, illegal authority commits, unique action effects, duplicate effects, replay identity, and replayed state equality.

Local inference uses no billed API. Report billed dollars as zero and do not infer energy or monetary hardware cost. Report token counts and elapsed time as the measured local cost proxy.

## Promotion boundary

This two-task pilot cannot establish broad held-out generalization. A positive result is a lead for a larger repository-level bank, not promotion. Any confidently wrong agreement is reported explicitly. Do not tune thresholds, prompts, task frames, or action descriptions after opening model outputs; changes require a new versioned run.
