from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

QTERM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QTERM_DIR))

from model import H_FIELDS, QTerminal  # noqa: E402
from qterminal import (  # noqa: E402
    ContractError,
    family_split,
    load_manifest,
    read_candidate_records,
    select_balanced_mixture,
    validate_feature_bank,
)


MANIFEST = load_manifest(QTERM_DIR / "manifest-v02.json")


def candidate(family_id: str, source: str, label: int, suffix: str) -> dict:
    row = {
        "schema": "R1_QTERMINAL_CANDIDATE_V01",
        "sample_id": f"sample-{family_id}-{source}-{label}-{suffix}",
        "feature_id": f"feature-{family_id}-{suffix}",
        "task_id": f"task-{family_id}-{suffix}",
        "family_id": family_id,
        "source_kind": source,
        "assignment": [0, 1] if label else [0, 0],
        "posthoc_valid": bool(label),
        "label_source": "independent_typed_validator_v1",
    }
    if source == "policy_visited":
        row.update(
            policy_checkpoint_id="R1_QTERMINAL_BASELINE_VISITATION_V1",
            policy_training_split="train",
            policy_trace_id=f"trace-{family_id}",
            trace_event_index=1,
        )
    else:
        row.update(
            random_sampler_id="R1_QTERMINAL_CLASS_CONDITIONED_ASSIGNMENTS_V1",
            random_replicate_index=label,
        )
    return row


def balanced_fixture() -> list[dict]:
    families: dict[str, str] = {}
    index = 0
    while any(sum(split == target for split in families.values()) < 30 for target in ("train", "validation", "test")):
        family = f"fixture-family-{index:05d}"
        families[family] = family_split(family, MANIFEST)
        index += 1
    records: list[dict] = []
    for family, split in families.items():
        if split == "train":
            for source in ("random_complete", "policy_visited"):
                for label in (0, 1):
                    records.append(candidate(family, source, label, "train"))
        else:
            for label in (0, 1):
                records.append(candidate(family, "random_complete", label, split))
    return records


class QTerminalContractTests(unittest.TestCase):
    def test_family_split_is_stable_and_disjoint_by_construction(self) -> None:
        values = [family_split(f"family-{index}", MANIFEST) for index in range(100)]
        self.assertEqual(values, [family_split(f"family-{index}", MANIFEST) for index in range(100)])
        self.assertTrue(set(values).issubset({"train", "validation", "test"}))
        for family in ("same-family-surface-a", "same-family-surface-b"):
            self.assertEqual(family_split(family, MANIFEST), family_split(family, MANIFEST))

    def test_mixture_is_deterministic_balanced_and_family_disjoint(self) -> None:
        records = balanced_fixture()
        first = select_balanced_mixture(records, MANIFEST)
        second = select_balanced_mixture(list(reversed(records)), MANIFEST)
        for split in ("train", "validation", "test"):
            self.assertEqual(
                [row["sample_id"] for row in first[split]],
                [row["sample_id"] for row in second[split]],
            )
        train_cells = {
            (source, label): sum(
                row["source_kind"] == source and int(row["posthoc_valid"]) == label
                for row in first["train"]
            )
            for source in ("random_complete", "policy_visited")
            for label in (0, 1)
        }
        self.assertEqual(len(set(train_cells.values())), 1)
        for split in ("validation", "test"):
            self.assertTrue(all(row["source_kind"] == "random_complete" for row in first[split]))
            labels = [int(row["posthoc_valid"]) for row in first[split]]
            self.assertEqual(labels.count(0), labels.count(1))
        family_sets = {
            split: {row["family_id"] for row in rows} for split, rows in first.items()
        }
        self.assertFalse(family_sets["train"] & family_sets["validation"])
        self.assertFalse(family_sets["train"] & family_sets["test"])
        self.assertFalse(family_sets["validation"] & family_sets["test"])
        self.assertTrue(
            all(family_split(row["family_id"], MANIFEST) == "train" for row in first["train"] if row["source_kind"] == "policy_visited")
        )

    def test_incomplete_cell_fails_closed(self) -> None:
        rows = balanced_fixture()
        rows = [row for row in rows if not (row["source_kind"] == "policy_visited" and row["posthoc_valid"])]
        with self.assertRaises(ContractError):
            select_balanced_mixture(rows, MANIFEST)

    def test_policy_trace_label_on_heldout_family_is_rejected(self) -> None:
        family = next(
            f"candidate-heldout-{index}"
            for index in range(10000)
            if family_split(f"candidate-heldout-{index}", MANIFEST) == "test"
        )
        row = candidate(family, "policy_visited", 1, "heldout")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(ContractError):
                read_candidate_records(path, MANIFEST)

    def test_feature_contract_rejects_padding_and_hidden_shape_violations(self) -> None:
        arrays = {
            "feature_ids": np.asarray(["feature-a"], dtype="U16"),
            "task_ids": np.asarray(["task-a"], dtype="U16"),
            "family_ids": np.asarray(["family-a"], dtype="U16"),
            "n_by_feature": np.asarray([2], dtype=np.uint16),
            "k_by_feature": np.asarray([2], dtype=np.uint8),
            "h_constraints": np.asarray([[[1.0] * 8, [0.0] * 8, [0.0] * 8]], dtype=np.float32),
            "constraint_mask": np.asarray([[True, False, False]], dtype=np.bool_),
            "h_global": np.zeros((1, 8), dtype=np.float32),
            "entity_incidence": np.asarray([[[True, False, False, False], [False] * 4, [False] * 4]], dtype=np.bool_),
            "role_incidence": np.asarray([[[True, False, False], [False] * 3, [False] * 3]], dtype=np.bool_),
        }
        validate_feature_bank(arrays, hidden_dim=8, max_constraints=4, max_entities=4, max_roles=3)
        corrupted = dict(arrays)
        corrupted["h_constraints"] = arrays["h_constraints"].copy()
        corrupted["h_constraints"][0, 1, 0] = 1.0
        with self.assertRaises(ContractError):
            validate_feature_bank(corrupted, hidden_dim=8, max_constraints=4, max_entities=4, max_roles=3)

    def test_selector_surface_has_no_state_or_budget_argument(self) -> None:
        parameters = list(inspect.signature(QTerminal.forward).parameters)
        self.assertEqual(parameters, ["self", "H", "h_global", "a"])
        self.assertEqual(
            H_FIELDS,
            {
                "constraint_embeddings",
                "constraint_mask",
                "entity_incidence",
                "role_incidence",
                "entity_mask",
                "role_mask",
            },
        )
        self.assertNotIn("latent_state", parameters)
        self.assertNotIn("remaining_budget", parameters)

    def test_empty_constraint_world_is_supported_and_finite(self) -> None:
        import torch

        arrays = {
            "feature_ids": np.asarray(["feature-empty"], dtype="U16"),
            "task_ids": np.asarray(["task-empty"], dtype="U16"),
            "family_ids": np.asarray(["family-empty"], dtype="U16"),
            "n_by_feature": np.asarray([2], dtype=np.uint16),
            "k_by_feature": np.asarray([2], dtype=np.uint8),
            "h_constraints": np.zeros((1, 1, 8), dtype=np.float32),
            "constraint_mask": np.zeros((1, 1), dtype=np.bool_),
            "h_global": np.zeros((1, 8), dtype=np.float32),
            "entity_incidence": np.zeros((1, 1, 4), dtype=np.bool_),
            "role_incidence": np.zeros((1, 1, 3), dtype=np.bool_),
        }
        validate_feature_bank(arrays, hidden_dim=8, max_constraints=4, max_entities=4, max_roles=3)

        model = QTerminal(hidden_dim=8, hidden_size=16, max_roles=3)
        H = {
            "constraint_embeddings": torch.zeros((1, 1, 8)),
            "constraint_mask": torch.zeros((1, 1), dtype=torch.bool),
            "entity_incidence": torch.zeros((1, 1, 4), dtype=torch.bool),
            "role_incidence": torch.zeros((1, 1, 3), dtype=torch.bool),
            "entity_mask": torch.tensor([[True, True, False, False]]),
            "role_mask": torch.tensor([[True, True, False]]),
        }
        score = model(H, torch.zeros((1, 8)), torch.zeros((1, 4, 3)))
        self.assertEqual(tuple(score.shape), (1,))
        self.assertTrue(bool(torch.isfinite(score).all()))


if __name__ == "__main__":
    unittest.main()
