from __future__ import annotations

import build_expanded_dev_bank as bank

bank.DEV_ROOT = bank.ROOT / "tasks" / "expanded" / "heldout-bank-v5"
bank.TASK_PREFIX = "heldout"
bank.CASES = [
    {
        "family": "hard-stop-ordering",
        "source": "src/palette.rs",
        "test": "palette::tests::explicit_hard_stop_uses_the_last_duplicate",
        "base_mutate": lambda text: text.replace(
            ".partition_point(|stop| stop.stop.position <= position)",
            ".partition_point(|stop| stop.stop.position < position)",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            ".partition_point(|stop| stop.stop.position <= position);",
            ".partition_point(|stop| stop.stop.position <= position).saturating_sub(2);",
            1,
        ),
        "keep_excerpt": "The current task snapshot excludes stops exactly equal to the requested position.",
        "keep_summary": "Keep the current strict upper-stop lookup.",
        "gold_summary": "Include stops at the requested position so the last duplicate wins.",
        "gold_excerpt": "Use `<= position` in the upper-stop partition point.",
        "comment_summary": "Include equal-position stops and document the hard-stop tie rule.",
        "comment_excerpt": "Restores `<= position` and explains that the final duplicate wins at an exact boundary.",
        "mutant_summary": "Back the upper-stop index up by two positions before sampling.",
        "mutant_excerpt": "Use `partition_point(...).saturating_sub(2)` to select an earlier segment.",
        "source_evidence": (
            "The current task snapshot uses a strict less-than lookup, so a stop exactly at 0.5 is excluded. "
            "The frozen test creates duplicate stops at 0.5 and requires the last duplicate's blue color."
        ),
        "easy_prompt": (
            "Repair hard-stop lookup. When two stops share position 0.5, sampling exactly at 0.5 must return the "
            "last duplicate. Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair a palette lookup at a duplicated stop position. Use the frozen test to determine how the search "
            "boundary should treat equal positions and which duplicate supplies the sampled color."
        ),
    },
    {
        "family": "fill-clear-intervals",
        "source": "src/fills.rs",
        "test": "fills::tests::inherit_clears_only_the_requested_interval",
        "base_mutate": lambda text: text.replace(
            "if fill != TextFill::Inherit {\n            normalized.push(FillSpan { range, fill });\n        }",
            "normalized.push(FillSpan { range, fill });",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "if fill != TextFill::Inherit {",
            "if fill == TextFill::Inherit {",
            1,
        ),
        "keep_excerpt": "The current task snapshot stores an explicit Inherit span instead of leaving a gap.",
        "keep_summary": "Keep storing the requested span even when it is Inherit.",
        "gold_summary": "Omit the Inherit span so only the assigned interval is cleared.",
        "gold_excerpt": "Push a new FillSpan only when `fill != TextFill::Inherit`.",
        "comment_summary": "Omit the Inherit span and document that it represents a cleared interval.",
        "comment_excerpt": "Restores the conditional push and adds a note that Inherit removes explicit fill.",
        "mutant_summary": "Store spans only when the new fill equals Inherit.",
        "mutant_excerpt": "Change the push condition to `fill == TextFill::Inherit`.",
        "source_evidence": (
            "The current task snapshot always pushes a FillSpan, including when the requested fill is Inherit. "
            "The frozen test assigns red to 1..7, clears 3..5, and expects only 1..3 and 5..7 to remain."
        ),
        "easy_prompt": (
            "Repair interval clearing. Inherit at 3..5 inside a fill at 1..7 must remove only 3..5, leaving spans "
            "1..3 and 5..7. Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair fill normalization. Inherit represents absence of an explicit fill, so inspect the frozen test's "
            "expected spans after clearing the middle interval before choosing a push condition."
        ),
    },
    {
        "family": "inherited-style-preservation",
        "source": "src/text.rs",
        "test": "text::tests::inherited_font_style_and_selection_background_are_preserved",
        "base_mutate": lambda text: text.replace(
            "let mut run = style.to_run(byte_len);",
            "let mut run = TextStyle::default().to_run(byte_len);",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "run.color = color;",
            "run.font.weight = gpui::FontWeight::NORMAL;\n                run.color = color;",
            1,
        ),
        "keep_excerpt": "The current task snapshot starts runs from the default style and drops inherited bold weight.",
        "keep_summary": "Keep constructing each text run from the default style.",
        "gold_summary": "Create each run from the inherited TextStyle before assigning gradient color.",
        "gold_excerpt": "Use `style.to_run(byte_len)` so the caller's font weight remains intact.",
        "comment_summary": "Preserve inherited font style and document the gradient-color override.",
        "comment_excerpt": "Restores `style.to_run(byte_len)` and adds a short inheritance note.",
        "mutant_summary": "Force normal font weight after constructing the run.",
        "mutant_excerpt": "Set `run.font.weight` to NORMAL before assigning the fill color.",
        "source_evidence": (
            "The current task snapshot constructs text runs from TextStyle::default, discarding the caller's bold "
            "weight. The frozen test requires all runs to remain bold and requires a selection background."
        ),
        "easy_prompt": (
            "Repair text-run style inheritance. Preserve the caller's bold font weight while applying gradient color, "
            "and keep the selection background. Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair run construction. Gradient fill may replace the run's text color, but the frozen test separately "
            "checks inherited font weight and selection background. Preserve both constraints."
        ),
    },
    {
        "family": "draft-cardinality-transitions",
        "source": "src/palette.rs",
        "test": "palette::tests::draft_supports_empty_solid_and_gradient_states",
        "base_mutate": lambda text: text.replace(
            "if stops.len() < 2 {\n            return Err(GradientPaletteError::TooFewColors {",
            "if stops.len() < 1 {\n            return Err(GradientPaletteError::TooFewColors {",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "if stops.len() < 2 {\n            return Err(GradientPaletteError::TooFewColors {",
            "if stops.len() < 3 {\n            return Err(GradientPaletteError::TooFewColors {",
            1,
        ),
        "keep_excerpt": "The current task snapshot accepts a one-stop draft as a palette.",
        "keep_summary": "Keep allowing a one-stop draft to become a palette.",
        "gold_summary": "Require at least two stops before creating a gradient palette.",
        "gold_excerpt": "Reject with TooFewColors when `stops.len() < 2`.",
        "comment_summary": "Require two stops and document the empty, solid, and gradient states.",
        "comment_excerpt": "Restores the two-stop minimum and adds a note about draft cardinality.",
        "mutant_summary": "Require three stops before resolving a gradient.",
        "mutant_excerpt": "Change the minimum from two stops to three.",
        "source_evidence": (
            "The current task snapshot permits a one-stop GradientPalette. The frozen test requires an empty and "
            "one-color draft to remain non-gradient and a two-color draft to produce a two-stop palette."
        ),
        "easy_prompt": (
            "Repair draft cardinality. Empty and one-color drafts must not resolve as gradients; two colors must "
            "produce a two-stop palette. Choose a patch that makes the frozen test pass."
        ),
        "ambiguous_prompt": (
            "Repair the transition from draft state to palette. Read the frozen test's three checkpoints—zero, one, "
            "and two colors—and choose the minimum stop count that satisfies all of them."
        ),
    },
]

if __name__ == "__main__":
    bank.main()
