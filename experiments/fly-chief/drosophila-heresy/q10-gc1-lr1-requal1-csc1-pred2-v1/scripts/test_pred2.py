from __future__ import annotations

import importlib.util
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pred2_test_target", HERE / "audit_pred2.py")
assert spec is not None and spec.loader is not None
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

assert target.difficulty(0, 1) == "NO_SUCCESS_OBSERVED"
assert target.difficulty(1, 4) == "HARD"
assert target.difficulty(1, 2) == "MEDIUM"
assert target.difficulty(4, 4) == "EASY"
assert math.isclose(target.hypergeometric_hit(10, 0, 5), 0.0)
assert math.isclose(target.hypergeometric_hit(10, 10, 1), 1.0)

def cosine(a, b):
    left = math.sqrt(sum(x * x for x in a))
    right = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (left * right)

assert math.isclose(cosine((1.0, 2.0), (2.0, 4.0)), cosine((10.0, 20.0), (0.5, 1.0)))
observations = [
    {"success": False, "full_alignment": 0.1, "axis_alignment": 0.0, "partner_delta_norm": 1.0, "partner_score_key": (2, 0, 0.0, 0.0), "random_key": "b", "tie": (1, "B")},
]
failed = target.source_metrics(observations, "full_alignment")
assert failed["first_success_rank"] is None and failed["mrr"] == 0.0 and failed["stop_cost"] == 1
print("PRED2_TEST_PASS")
