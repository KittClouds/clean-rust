"""Render a compact human-readable paired result from sealed score receipts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ENDPOINTS = (
    "context_identity", "entity_identity", "relation", "observed_state",
    "exact_target_in_domain", "exact_target_context_novel",
    "exact_target_entity_novel", "exact_target_both_novel",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: float) -> str:
    return f"{value * 100:.3f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--fit-a", type=Path, required=True)
    parser.add_argument("--fit-b", type=Path, required=True)
    parser.add_argument("--test-extract-a", type=Path, required=True)
    parser.add_argument("--test-extract-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("report output already exists")
    score, fit_a, fit_b = (load(args.score), load(args.fit_a), load(args.fit_b))
    ext_a, ext_b = load(args.test_extract_a), load(args.test_extract_b)
    metrics = score["metrics"]
    lines = [
        "# E4 230M versus 1.2B paired capability comparison",
        "",
        "Both frozen Base backbones used identical E1 FIT-derived TRAIN/DEV identities and the same",
        "independent 74,668-row E4-shaped TEST. Five linear observers were refit for each model.",
        "The protected E4-0 panel was not used. This is a synthetic capability comparison,",
        "not a lexical-transport or serving qualification.",
        "",
        f"TEST population seal: `{score['population_seal_sha256']}`.",
        f"230M TEST prediction seal: `{score['a_prediction_seal_sha256']}`.",
        f"1.2B TEST prediction seal: `{score['b_prediction_seal_sha256']}`.",
        "",
        "| Endpoint | 230M balanced | 1.2B balanced | 230M 5th percentile | 1.2B 5th percentile | 1.2B minus 230M paired 90% interval |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for endpoint in ENDPOINTS:
        row = metrics[endpoint]
        boot = row["paired_bootstrap"]
        interval = f"[{percent(boot['b_minus_a_5th_percentile'])}, {percent(boot['b_minus_a_95th_percentile'])}]"
        lines.append(
            f"| `{endpoint}` | {percent(row['a']['balanced_accuracy'])} | "
            f"{percent(row['b']['balanced_accuracy'])} | {percent(boot['a_5th_percentile'])} | "
            f"{percent(boot['b_5th_percentile'])} | {interval} |"
        )
    lines.extend(["", "| Integrated on in-domain rows | 230M | 1.2B |", "|---|---:|---:|"])
    for field, label in (("route_accuracy_four_heads", "All four route heads correct"),
                         ("end_to_end_all_five_heads", "Route and exact target correct")):
        lines.append(f"| {label} | {percent(metrics['integrated_a'][field])} | {percent(metrics['integrated_b'][field])} |")
    lines.extend([
        "", "| Cost diagnostic | 230M | 1.2B |", "|---|---:|---:|",
        f"| Hidden dimension | {ext_a['dimension']} | {ext_b['dimension']} |",
        f"| Frozen model bytes | {Path(ext_a['model_path']).joinpath('model.safetensors').stat().st_size:,} | {Path(ext_b['model_path']).joinpath('model.safetensors').stat().st_size:,} |",
        f"| Five-head trainable parameters | {fit_a['total_trainable_parameters']:,} | {fit_b['total_trainable_parameters']:,} |",
        f"| Five-head fit time (s) | {fit_a['total_fit_seconds']:.2f} | {fit_b['total_fit_seconds']:.2f} |",
        f"| TEST feature bytes | {ext_a['feature_bytes']:,} | {ext_b['feature_bytes']:,} |",
        f"| TEST extraction loop time (s) | {ext_a['extraction_seconds_this_invocation']:.2f} | {ext_b['extraction_seconds_this_invocation']:.2f} |",
        f"| TEST extraction loop ms/row | {1000 * ext_a['extraction_seconds_this_invocation'] / ext_a['row_count']:.2f} | {1000 * ext_b['extraction_seconds_this_invocation'] / ext_b['row_count']:.2f} |",
        "",
        "The extraction runs may overlap on one GPU, so loop timings are workload diagnostics rather than",
        "a clean isolated latency benchmark. The linear heads force a prediction and have zero abstentions.",
        "Inference cost here includes the frozen backbone, not a serving-optimized batch path.",
        "",
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
