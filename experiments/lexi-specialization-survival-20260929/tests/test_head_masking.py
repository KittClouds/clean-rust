from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))
import head_masking as masking
import head_masking_protocol as protocol


class HeadMaskingTests(unittest.TestCase):
    def test_conditions_are_last_four_layers_and_kv_groups(self):
        model_shape = {
            "num_attention_heads": 16,
            "num_key_value_heads": 8,
            "full_attention_layers": [2, 4, 6, 8, 10, 12],
        }
        conditions = protocol.build_conditions(model_shape)
        self.assertEqual(len(conditions), 36)
        self.assertEqual(
            [item["layer"] for item in conditions if item["kind"] == "whole_layer"],
            [6, 8, 10, 12],
        )
        for layer in (6, 8, 10, 12):
            groups = [item["heads"] for item in conditions
                      if item["layer"] == layer and item["kind"] == "kv_group"]
            self.assertEqual(groups, [[i, i + 1] for i in range(0, 16, 2)])

    def test_graph_pair_sampling_is_independent_of_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            task_dir = Path(temporary)
            for split in protocol.TEST_SPLITS:
                path = task_dir / f"{split}.jsonl"
                records = [
                    {
                        "row_idx": i,
                        "a_idx": 1000 + i,
                        "b_idx": 2000 + i,
                        "family": "S7" if i % 2 else "S0",
                        "world_id": f"{split}:{i}",
                        "label": i % 2,
                    }
                    for i in range(48)
                ]
                path.write_text("".join(json.dumps(row) + "\n" for row in records),
                                encoding="utf-8")
            first = protocol.select_graph_pairs(task_dir)
            for path in task_dir.glob("*.jsonl"):
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                for row in records:
                    row["label"] = 1 - row["label"]
                path.write_text("".join(json.dumps(row) + "\n" for row in records),
                                encoding="utf-8")
            second = protocol.select_graph_pairs(task_dir)
        self.assertEqual(first, second)

    def test_group_hook_zeros_only_selected_head_dimensions(self):
        projection = torch.nn.Linear(8, 2, bias=False)
        fake_model = SimpleNamespace(layers=[
            SimpleNamespace(self_attn=SimpleNamespace(out_proj=projection))
        ])
        holder = {"condition": {"layer": 0, "heads": [1, 2]}}
        hooks = masking.install_hooks(fake_model, [0], q_heads=4, head_dim=2,
                                       holder=holder)
        captured = []
        observer = projection.register_forward_pre_hook(
            lambda _module, args: captured.append(args[0].clone())
        )
        projection(torch.ones((1, 1, 8)))
        observed = captured[0]
        self.assertTrue(torch.equal(observed[..., :2], torch.ones((1, 1, 2))))
        self.assertTrue(torch.equal(observed[..., 2:6], torch.zeros((1, 1, 4))))
        self.assertTrue(torch.equal(observed[..., 6:], torch.ones((1, 1, 2))))
        observer.remove()
        for handle in hooks:
            handle.remove()

    def test_spearman_rank_correlation_handles_ties(self):
        x = np.asarray([1, 1, 2, 3], dtype=np.float64)
        self.assertAlmostEqual(masking.rank_corr(x, x), 1.0)
        self.assertIsNone(masking.rank_corr(np.ones(4), np.arange(4)))


if __name__ == "__main__":
    unittest.main()
