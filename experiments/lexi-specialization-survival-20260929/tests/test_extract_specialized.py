from pathlib import Path
import sys
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extract_specialized


class SpecializedSpanPoolingTests(unittest.TestCase):
    def test_exact_entity_spans_pool_from_shared_row_tokens(self):
        metadata = [{
            "mentions": [
                {"entity_index": 10, "spans": [[0, 1]]},
                {"entity_index": 11, "spans": [[2, 4]]},
            ],
            "goals": [],
        }]
        offsets = np.asarray([[[0, 1], [2, 3], [3, 4], [0, 0]]], dtype=np.int64)
        ranges, owners, count, base = extract_specialized.batch_entity_spans(metadata, offsets)
        self.assertEqual((ranges, owners, count, base),
                         ([(0, 0, 1), (0, 1, 3)], [0, 1], 2, 10))
        state = torch.tensor([[[1.0, 0.0], [3.0, 2.0], [5.0, 4.0], [99.0, 99.0]]])
        pooled = extract_specialized.aggregate_spans(
            torch, state, ranges, owners, count, hidden_size=2
        )
        torch.testing.assert_close(pooled, torch.tensor([[1.0, 0.0], [4.0, 3.0]]))


if __name__ == "__main__":
    unittest.main()
