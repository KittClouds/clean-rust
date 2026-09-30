import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train_nli import JsonlMap, LoRALinear
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lfm-230m-specialization-atlas-20260929"))
import train_specialist as ner_train
from train_nli import attach_lora as attach_nli_lora, export_state_dict as export_nli


class DummyAttention(nn.Module):
    def __init__(self):
        super().__init__()
        self.q_proj = nn.Linear(5, 5)
        self.v_proj = nn.Linear(5, 5)


class DummyLayer(nn.Module):
    def __init__(self):
        super().__init__()
        self.self_attn = DummyAttention()


class DummyBackbone(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.ModuleList([DummyLayer() for _ in range(4)])
        self.config = SimpleNamespace(layer_types=["full_attention"] * 4)


class NliTrainingPrimitives(unittest.TestCase):
    def test_lora_starts_as_identity_and_trains_adapter(self):
        torch.manual_seed(4)
        base = nn.Linear(5, 3)
        x = torch.randn(2, 5)
        expected = base(x)
        layer = LoRALinear(base, rank=2)
        self.assertTrue(torch.allclose(layer(x), expected))
        layer(x).square().sum().backward()
        self.assertIsNotNone(layer.b.grad)
        self.assertIsNone(layer.base.weight.grad)

    def test_mmap_reader_returns_exact_jsonl_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.jsonl"
            path.write_text('{"idx":1}\n{"idx":2}\n', encoding="utf-8")
            mapped = JsonlMap(path)
            try:
                self.assertEqual(len(mapped), 2)
                self.assertEqual(mapped[0], {"idx": 1})
                self.assertEqual(mapped[1], {"idx": 2})
            finally:
                mapped.close()

    def test_ner_lora_export_loads_as_equivalent_plain_model(self):
        self.assert_lora_export_equivalent(ner_train.attach_lora, ner_train.export_state_dict)

    def test_nli_lora_export_loads_as_equivalent_plain_model(self):
        self.assert_lora_export_equivalent(attach_nli_lora, export_nli)

    def assert_lora_export_equivalent(self, attach, export):
        torch.manual_seed(17)
        adapted = DummyBackbone()
        plain = DummyBackbone()
        plain.load_state_dict(adapted.state_dict())
        layers = attach(adapted, rank=2)
        with torch.no_grad():
            for _, _, module in layers:
                module.b.normal_(mean=0.0, std=0.05)
        merged = export(adapted, layers)
        result = plain.load_state_dict(merged, strict=True)
        self.assertEqual(result.missing_keys, [])
        self.assertEqual(result.unexpected_keys, [])
        values = torch.randn(4, 5)
        for index, name, module in layers:
            expected = module(values)
            actual = getattr(plain.layers[index].self_attn, name)(values)
            self.assertTrue(torch.allclose(actual, expected, atol=0.02, rtol=0.01),
                            f"merged BF16 export mismatch: max_abs="
                            f"{(actual - expected).abs().max().item():.6f}")


if __name__ == "__main__":
    unittest.main()
