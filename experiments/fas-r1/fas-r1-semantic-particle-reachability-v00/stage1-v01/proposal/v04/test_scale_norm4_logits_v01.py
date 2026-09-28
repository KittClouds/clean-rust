from __future__ import annotations

import copy
import math
import unittest

import scale_norm4_logits_v01 as scaling


def fixture() -> dict:
    return {
        "schema": scaling.SCHEMA,
        "architecture": scaling.ARCHITECTURE,
        "feature_schema": "r1-candidate-features-h-global-entity-role-load-v01-plus-semantic-adapter-expected-delta-v02",
        "input_dim": 10,
        "hidden_dim": 16,
        "w1": [[((i + j) % 7 - 3) / 10 for j in range(10)] for i in range(16)],
        "b1": [i / 20 for i in range(16)],
        "w2": [(i - 7) / 13 for i in range(16)],
        "b2": 0.37,
        "adapter_logit_bias": 0.2448,
    }


def base_scores(payload: dict, inputs: list[list[float]]) -> list[float]:
    result = []
    for row in inputs:
        hidden = [
            math.tanh(payload["b1"][i] + sum(w * x for w, x in zip(payload["w1"][i], row)))
            for i in range(16)
        ]
        result.append(payload["b2"] + sum(w * h for w, h in zip(payload["w2"], hidden)))
    return result


def norm4_scores(payload: dict, inputs: list[list[float]], deltas: list[float]) -> list[float]:
    base = base_scores(payload, inputs)
    delta_mean = sum(deltas) / len(deltas)
    base_mean = sum(base) / len(base)
    delta_sd = math.sqrt(sum((x - delta_mean) ** 2 for x in deltas) / len(deltas))
    base_sd = math.sqrt(sum((x - base_mean) ** 2 for x in base) / len(base))
    if delta_sd <= 1e-8 or base_sd <= 1e-8:
        return base
    return [b + ((d - delta_mean) / delta_sd) * base_sd * 4.0 for b, d in zip(base, deltas)]


class ScaleTests(unittest.TestCase):
    def test_norm4_logits_scale_without_changing_candidate_order(self) -> None:
        source = fixture()
        inputs = [[((i * 3 + j * 5) % 17 - 8) / 9 for j in range(10)] for i in range(40)]
        deltas = [((i * 11) % 23 - 11) / 7 for i in range(40)]
        factor = 5.597739321665666
        changed = scaling.scaled_payload(source, factor, scaling.MODE)
        original_scores = norm4_scores(source, inputs, deltas)
        changed_scores = norm4_scores(changed, inputs, deltas)
        for before, after in zip(original_scores, changed_scores):
            self.assertAlmostEqual(after, factor * before, places=12)
        self.assertEqual(max(range(40), key=original_scores.__getitem__), max(range(40), key=changed_scores.__getitem__))
        self.assertEqual(source, fixture(), "transform must not mutate its input")
        self.assertEqual(changed["adapter_logit_bias"], source["adapter_logit_bias"])

    def test_zero_delta_variance_falls_back_to_scaled_base(self) -> None:
        source = fixture()
        changed = scaling.scaled_payload(source, 2.5, scaling.MODE)
        inputs = [[float(i + j) / 20 for j in range(10)] for i in range(40)]
        before = norm4_scores(source, inputs, [0.25] * 40)
        after = norm4_scores(changed, inputs, [0.25] * 40)
        for left, right in zip(before, after):
            self.assertAlmostEqual(right, 2.5 * left, places=12)

    def test_rejects_invalid_scale_mode_and_architecture(self) -> None:
        with self.assertRaises(ValueError):
            scaling.scaled_payload(fixture(), 0.0, scaling.MODE)
        with self.assertRaises(ValueError):
            scaling.scaled_payload(fixture(), 1.0, "pinned_raw_v02")
        broken = copy.deepcopy(fixture())
        broken["hidden_dim"] = 15
        with self.assertRaises(ValueError):
            scaling.scaled_payload(broken, 1.0, scaling.MODE)


if __name__ == "__main__":
    unittest.main()
