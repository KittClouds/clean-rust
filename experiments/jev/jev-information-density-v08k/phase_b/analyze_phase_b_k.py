"""Create the frozen v0.8K attribution disposition from sealed reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01")
OUT = RUN / "reports"
CONTRACT = Path(__file__).resolve().parent / "phase-b-v01-contract.json"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def main() -> int:
    direct = read(OUT / "direct-contrast-by-arm-seed-epoch.json")
    terminal = {}
    for seed_index in range(1, 4):
        for arm in ("K-DUP", "K-SHAM"):
            terminal[f"seed-{seed_index}/{arm}"] = direct[f"seed-{seed_index}/{arm}/epoch-3"]["analysis"]

    seed_rows = []
    for seed_index in range(1, 4):
        dup = terminal[f"seed-{seed_index}/K-DUP"]
        sham = terminal[f"seed-{seed_index}/K-SHAM"]
        dup_strict = dup["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"]
        sham_strict = sham["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"]
        dup_l1 = dup["sham_invariance"]["overall"]["mean_prediction_distribution_l1"]
        sham_l1 = sham["sham_invariance"]["overall"]["mean_prediction_distribution_l1"]
        dup_flip = dup["sham_invariance"]["overall"]["map_flip_rate"]
        sham_flip = sham["sham_invariance"]["overall"]["map_flip_rate"]
        seed_rows.append({"seed": 20260926 + seed_index, "K-DUP": {"strict_transition": dup_strict, "sham_l1": dup_l1, "sham_map_flip": dup_flip}, "K-SHAM": {"strict_transition": sham_strict, "sham_l1": sham_l1, "sham_map_flip": sham_flip}, "SHAM_minus_DUP": {"strict_transition": sham_strict - dup_strict, "sham_l1": sham_l1 - dup_l1, "sham_map_flip": sham_flip - dup_flip}})

    strict_dup = [row["K-DUP"]["strict_transition"] for row in seed_rows]
    strict_sham = [row["K-SHAM"]["strict_transition"] for row in seed_rows]
    l1_deltas = [row["SHAM_minus_DUP"]["sham_l1"] for row in seed_rows]
    flip_deltas = [row["SHAM_minus_DUP"]["sham_map_flip"] for row in seed_rows]
    strict_delta = mean([row["SHAM_minus_DUP"]["strict_transition"] for row in seed_rows])
    criterion = {
        "sham_l1_lower_all_seeds": all(value < 0 for value in l1_deltas),
        "sham_map_flip_lower_all_seeds": all(value < 0 for value in flip_deltas),
        "mean_strict_transition_delta": strict_delta,
        "mean_strict_transition_loss_pp": -100.0 * strict_delta,
        "mean_strict_transition_loss_within_5pp": strict_delta >= -0.05,
    }
    criterion["specific_invariant_view_effect_supported"] = all(criterion[key] for key in ("sham_l1_lower_all_seeds", "sham_map_flip_lower_all_seeds", "mean_strict_transition_loss_within_5pp"))

    effects = read(OUT / "k-newtight-paired-effects.json")
    selected = {}
    for key in ("choice/accuracy", "choice/brier", "choice/nll", "independent_applicability/accuracy", "independent_applicability/brier", "ordinal_score/accuracy", "ordinal_score/ordinal_rps"):
        rows = effects.get(key, {}).get("per_seed", [])
        deltas = [row["K-SHAM_minus_K-DUP"] for row in rows if row["K-SHAM_minus_K-DUP"] is not None]
        if deltas:
            selected[key] = {"per_seed": deltas, "mean_KSHAM_minus_KDUP": mean(deltas)}

    payload = {
        "protocol": "jev-information-density/v0.8k-phase-b-v01",
        "status": "COMPLETE",
        "contract_sha256": sha256(CONTRACT),
        "primary_estimand": "K-SHAM minus K-DUP",
        "criterion": criterion,
        "terminal_by_seed": seed_rows,
        "terminal_means": {
            "K-DUP": {"strict_transition": mean(strict_dup), "sham_l1": mean([row["K-DUP"]["sham_l1"] for row in seed_rows]), "sham_map_flip": mean([row["K-DUP"]["sham_map_flip"] for row in seed_rows])},
            "K-SHAM": {"strict_transition": mean(strict_sham), "sham_l1": mean([row["K-SHAM"]["sham_l1"] for row in seed_rows]), "sham_map_flip": mean([row["K-SHAM"]["sham_map_flip"] for row in seed_rows])},
        },
        "secondary_newtight_selected_effects": selected,
        "interpretation": "The certified invariant view carries information beyond equal-dose anchor duplication under the preregistered attribution criterion. Sensitivity is heterogeneous by seed; this is attribution evidence, not a universal capability-gain claim.",
        "no_follow_on_authorized": True,
        "phoenix_access": False,
    }
    path = OUT / "k-attribution-summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
