from __future__ import annotations

import build_expanded_dev_bank as bank

bank.DEV_ROOT = bank.ROOT / "tasks" / "expanded" / "heldout-bank-v6"
bank.TASK_PREFIX = "heldoutv6"
bank.CASES = [
    {
        "family": "preset-json-version-integrity",
        "source": "src/preset.rs",
        "test": "preset::tests::json_round_trip_is_exact",
        "features": ["serde"],
        "base_mutate": lambda text: text.replace(
            "serde_json::to_string_pretty(self).map_err(GradientPresetError::Json)",
            "serde_json::to_string_pretty(&Self { version: self.version + 1, ..self.clone() }).map_err(GradientPresetError::Json)",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "serde_json::to_string_pretty(self).map_err(GradientPresetError::Json)",
            "serde_json::to_string_pretty(&Self { duration_ms: 0, ..self.clone() }).map_err(GradientPresetError::Json)",
            1,
        ),
        "keep_excerpt": "The current task snapshot changes the schema version while serializing a preset.",
        "keep_summary": "Keep serializing the original preset version.",
        "gold_summary": "Serialize every preset field without changing its value.",
        "gold_excerpt": "Pass `self` to `to_string_pretty` so the JSON round trip preserves the preset exactly.",
        "comment_summary": "Preserve the preset values during serialization and explain the round-trip contract.",
        "comment_excerpt": "Restores serialization from `self` and documents exact preset round trips.",
        "mutant_summary": "Write a zero duration into the serialized preset.",
        "mutant_excerpt": "Serialize a clone with `duration_ms: 0`, making the decoded preset invalid.",
        "source_evidence": (
            "The current snapshot serializes a clone with an altered version. The frozen serde test requires "
            "the decoded preset to equal the original value exactly."
        ),
        "easy_prompt": (
            "Repair preset JSON serialization. A preset encoded and decoded by the serde methods must remain "
            "exactly equal to the original. Choose a patch that passes the frozen test."
        ),
        "ambiguous_prompt": (
            "Repair the portable preset round trip. The frozen test compares every field after JSON decoding; "
            "preserve the version and all animation metadata through serialization."
        ),
    },
    {
        "family": "builtin-preset-duration-validation",
        "source": "src/preset.rs",
        "test": "preset::tests::builtins_are_valid_and_exportable",
        "base_mutate": lambda text: text.replace(
            "Duration::from_millis(4_600)", "Duration::ZERO", 1
        ),
        "alternate_mutate": lambda text: text.replace(
            "            1.0,\n            Duration::from_millis(4_600),",
            "            0.0,\n            Duration::from_millis(4_600),",
            1,
        ),
        "keep_excerpt": "The current task snapshot gives the Aurora built-in an invalid animation value.",
        "keep_summary": "Keep the current invalid Aurora metadata.",
        "gold_summary": "Keep all built-in presets valid and exportable.",
        "gold_excerpt": "Give Aurora a positive duration and cycle count so validation and export succeed.",
        "comment_summary": "Restore valid Aurora metadata and document the built-in preset invariant.",
        "comment_excerpt": "Restores the positive duration and notes that built-ins must pass preset validation.",
        "mutant_summary": "Set the Aurora cycle count to zero.",
        "mutant_excerpt": "Change Aurora's cycle count from `1.0` to `0.0`.",
        "source_evidence": (
            "The built-in preset test validates every preset through `to_palette` and exports each builder. "
            "Preset validation rejects a zero duration or non-positive cycle count."
        ),
        "easy_prompt": (
            "Repair the invalid built-in preset. Every preset returned by `builtins()` must validate and export "
            "a Rust builder expression. Choose a patch that passes the frozen test."
        ),
        "ambiguous_prompt": (
            "Repair built-in preset metadata using the frozen validation test. Preserve positive animation "
            "duration and cycle count for every preset."
        ),
    },
    {
        "family": "explicit-run-boundaries-under-budget",
        "source": "src/text.rs",
        "test": "text::tests::explicit_boundaries_survive_a_tiny_run_budget",
        "base_mutate": lambda text: text.replace(
            "            boundaries.push(self.grapheme_index(span.range.start));\n"
            "            boundaries.push(self.grapheme_index(span.range.end));",
            "            if self.max_color_runs > 1 {\n"
            "                boundaries.push(self.grapheme_index(span.range.start));\n"
            "                boundaries.push(self.grapheme_index(span.range.end));\n"
            "            }",
            1,
        ),
        "alternate_mutate": lambda text: text.replace(
            "            boundaries.push(self.grapheme_index(span.range.start));\n"
            "            boundaries.push(self.grapheme_index(span.range.end));",
            "            boundaries.push(self.grapheme_index(span.range.start));",
            1,
        ),
        "keep_excerpt": "The current task snapshot drops explicit fill endpoints when the run budget is tiny.",
        "keep_summary": "Keep merging explicit fill regions into the global region under tight budgets.",
        "gold_summary": "Preserve every explicit fill boundary regardless of the gradient run budget.",
        "gold_excerpt": "Add each fill span's start and end to the region boundaries before allocating runs.",
        "comment_summary": "Preserve explicit fill boundaries and document that the budget applies to gradient sampling.",
        "comment_excerpt": "Restores both boundary insertions and clarifies that explicit regions survive run limits.",
        "mutant_summary": "Retain fill starts but discard fill ends.",
        "mutant_excerpt": "Push the span start boundary without adding its end boundary.",
        "source_evidence": (
            "The frozen test uses two explicit solid fills with `max_color_runs(1)` and requires at least five "
            "runs while preserving the full source length."
        ),
        "easy_prompt": (
            "Repair run-region construction. Two explicit fills must retain their boundaries even when the global "
            "gradient run budget is one. Choose a patch that passes the frozen test."
        ),
        "ambiguous_prompt": (
            "Repair region construction under a tiny run budget. The frozen test checks that explicit fill regions "
            "remain separate and that all source bytes are represented."
        ),
    },
    {
        "family": "overlapping-fill-replacement-splits",
        "source": "src/fills.rs",
        "test": "fills::tests::replacement_splits_overlapping_spans_and_coalesces_neighbors",
        "base_mutate": lambda text: text.replace(
            "range: range.end..span.range.end,", "range: range.start..span.range.end,", 1
        ),
        "alternate_mutate": lambda text: text.replace(
            "if span.range.start < range.start {",
            "if span.range.start > range.start {",
            1,
        ),
        "keep_excerpt": "The current task snapshot creates the wrong residual spans when a new fill overlaps old spans.",
        "keep_summary": "Keep the current incorrect split boundaries for overlapping fills.",
        "gold_summary": "Preserve the left and right residual portions around the replacement span.",
        "gold_excerpt": "Use `range.start..range.start` for the left side and `range.end..span.range.end` for the right side.",
        "comment_summary": "Restore both residual intervals and document replacement splitting.",
        "comment_excerpt": "Restores the correct left and right ranges and explains how overlaps are split.",
        "mutant_summary": "Drop the left residual when replacing inside an existing span.",
        "mutant_excerpt": "Reverse the left-overlap condition so the prefix span is omitted.",
        "source_evidence": (
            "The frozen test assigns red to bytes 1..9 and blue to 3..7. It requires red residuals at 1..3 and "
            "7..9 around the replacement."
        ),
        "easy_prompt": (
            "Repair overlapping fill replacement. Replacing bytes 3..7 inside a red 1..9 span with blue must leave "
            "red spans 1..3 and 7..9. Choose a patch that passes the frozen test."
        ),
        "ambiguous_prompt": (
            "Repair interval splitting from the frozen test. Preserve the portions of an existing span that lie "
            "outside the new replacement range, then coalesce compatible neighbors."
        ),
    },
]

if __name__ == "__main__":
    bank.main()
