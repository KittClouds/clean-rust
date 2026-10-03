from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from run_extraction import extract_views, self_test
from run_geometry import all_pairwise_cosines, cosine_rows, distribution, validate_corpus_support


class SyntheticModel(torch.nn.Module):
    def forward(self, input_ids: torch.Tensor, use_cache: bool, return_dict: bool) -> SimpleNamespace:
        del use_cache, return_dict
        hidden = input_ids.to(torch.float32).unsqueeze(-1).expand(-1, -1, 2048)
        return SimpleNamespace(last_hidden_state=hidden)


def check_synthetic_view_extraction() -> None:
    assignments = {
        "view_assignments": {
            "V0_MEAN_FULL": {"position_range_half_open": [0, 4], "position_count": 4},
            "V1_FINAL_POSITION": {"positions": [3]},
            "V2_FIRST_POSITION": {"positions": [0]},
            "V3_CONTEXT_SPAN_MEAN": {"positions": [1, 2]},
            "V4_ENTITY_SPAN_MEAN": {"positions": [2]},
            "V5_RELATION_SPAN_MEAN": {"positions": [3]},
        }
    }
    views = extract_views(SyntheticModel(), [10, 20, 30, 40], assignments, torch.device("cpu"))
    expected_scalars = {
        "V0_MEAN_FULL": 25.0,
        "V1_FINAL_POSITION": 40.0,
        "V2_FIRST_POSITION": 10.0,
        "V3_CONTEXT_SPAN_MEAN": 25.0,
        "V4_ENTITY_SPAN_MEAN": 30.0,
        "V5_RELATION_SPAN_MEAN": 40.0,
    }
    for view, scalar in expected_scalars.items():
        assert tuple(views[view].shape) == (2048,)
        assert torch.all(views[view] == scalar)
    assert tuple(views["V6_FIXED_SPAN_CONCAT"].shape) == (6144,)
    assert torch.equal(
        views["V6_FIXED_SPAN_CONCAT"],
        torch.cat((views["V3_CONTEXT_SPAN_MEAN"], views["V4_ENTITY_SPAN_MEAN"], views["V5_RELATION_SPAN_MEAN"])),
    )


def check_geometry_helpers() -> None:
    summary = distribution(np.arange(1, 11, dtype=np.float64))
    assert summary == {
        "n": 10,
        "minimum": 1.0,
        "p10": 1.0,
        "p25": 3.0,
        "median": 5.0,
        "p75": 8.0,
        "p90": 9.0,
        "maximum": 10.0,
    }
    values = cosine_rows(
        np.asarray([[1.0, 0.0], [0.0, 0.0]], dtype=np.float64),
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64),
    )
    assert np.array_equal(values, np.asarray([1.0, 0.0]))
    vectors = np.eye(16, dtype=np.float64)
    assert all_pairwise_cosines(vectors).shape == (120,)
    assert np.all(all_pairwise_cosines(vectors) == 0.0)


def main() -> int:
    self_test()
    check_synthetic_view_extraction()
    check_geometry_helpers()
    corpus = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed\corpus\counterfactual-quartets-v01.jsonl")
    support = validate_corpus_support(corpus)
    assert support["quartets"] == 26624
    assert support["factorial_cells"] == 1536
    assert support["binding_context_cells"] == 64
    assert support["binding_entity_cells"] == 64
    assert support["template_pair_count"] == 64
    assert support["template_pair_support_min"] == support["template_pair_support_max"] == 384
    assert set(support["template_groups_per_factor"].values()) == {3072}
    assert support["pass"] is True
    print("synthetic_extraction_and_geometry_tests=PASS")
    print(f"sealed_corpus_support={support}")
    print("model_weights_loaded=false feature_extraction_performed=false geometry_on_features_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
