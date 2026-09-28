# E012 Bank Design Amendment 01 — Context-Sensitive Family

- Base: bank construction plan v1 and family design v1.
- State: effective before any scored task frame or label construction; no observer output was consulted.
- Scope: replace one proposed context-sensitive family after an offline executable-feasibility check.

The proposed `clap/derive-feature-compatibility` family did not establish a clean completion contract. The first feasibility attempt checked ANSI escapes in `render_help().to_string()`. That API returns a style-free string, so changing `ColorChoice` could not produce the expected intervention. The failed feasibility artifacts remain preserved under `bank/construction-01/feasibility/clap-color`.

Replace that family with `clap/help-color-capability`, keeping the same repository, four-task allocation, `E_c.content + E_r` support set, task count, candidate count, and intervention matrix. The task contract is: configure help coloring to `Always` when the typed runtime context says ANSI is supported, and `Never` when it is not. `E_r` alone changes between paired worlds; task text, candidate IDs, `E_c.content`, and `E_x` remain fixed. The executable completion check compares `Command::get_color()` to the required `ColorChoice`.

The repaired feasibility run passed the intended context/action pairs: `Always` for ANSI-capable contexts and `Never` for redirected/no-ANSI contexts. `Auto` passed neither pair because it returned the ambient process policy rather than the task's typed context. The test measures the runtime configuration contract; it makes no claim about actual terminal rendering.

No scored E012 frames, labels, treatment outputs, or observer calls existed when this amendment was written. All remaining v1 family assignments and gates remain unchanged. This amendment does not alter the E012 v0.3 protocol or authorize model contact.
