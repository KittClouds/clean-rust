"""Rescale a frozen proposal's final head for the norm-4 sampling diagnostic."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "r1-proposal-weights-v02"
ARCHITECTURE = "tanh_mlp_base_f10_h16_plus_adapter_bias_v02"
MODE = "incidence_masked_norm_4"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema") != SCHEMA or payload.get("architecture") != ARCHITECTURE:
        raise ValueError("proposal schema or architecture differs from the pinned v02 head")
    if payload.get("feature_schema") != "r1-candidate-features-h-global-entity-role-load-v01-plus-semantic-adapter-expected-delta-v02":
        raise ValueError("proposal feature schema differs from the pinned v02 head")
    if payload.get("input_dim") != 10 or payload.get("hidden_dim") != 16:
        raise ValueError("proposal dimensions differ from f10_h16")
    if len(payload.get("w1", [])) != 16 or any(len(row) != 10 for row in payload["w1"]):
        raise ValueError("proposal w1 shape differs from 16x10")
    if len(payload.get("b1", [])) != 16 or len(payload.get("w2", [])) != 16:
        raise ValueError("proposal hidden-layer shape differs from 16")
    values = [payload["b2"], payload["adapter_logit_bias"]]
    values.extend(payload["b1"])
    values.extend(payload["w2"])
    values.extend(value for row in payload["w1"] for value in row)
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        raise ValueError("proposal contains a non-finite parameter")


def scaled_payload(payload: dict[str, Any], scale: float, mode: str) -> dict[str, Any]:
    validate_payload(payload)
    if mode != MODE:
        raise ValueError(f"this transform is defined only for {MODE}")
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("logit scale must be finite and positive")
    result = copy.deepcopy(payload)
    result["w2"] = [float(value) * scale for value in payload["w2"]]
    result["b2"] = float(payload["b2"]) * scale
    return result


def transform(source: Path, output: Path, scale: float, mode: str) -> dict[str, Any]:
    source = source.resolve(strict=True)
    output = output.resolve()
    receipt_path = output.with_suffix(output.suffix + ".receipt.json")
    if output.exists() or receipt_path.exists():
        raise FileExistsError("refusing to overwrite a scaled proposal or receipt")
    source_bytes = source.read_bytes()
    payload = json.loads(source_bytes)
    result = scaled_payload(payload, scale, mode)
    output_bytes = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    receipt = {
        "schema": "FAS_R1_PROPOSAL_LOGIT_SCALE_V01",
        "status": "COMPLETE_ENGINEERING_DIAGNOSTIC",
        "mode": mode,
        "transformation": "multiply v02 MLP output weights and bias by one positive scalar; norm-4 adapter then scales by the same scalar because it is proportional to base-logit population SD",
        "scale": scale,
        "adapter_logit_bias_changed": False,
        "source_path": str(source),
        "source_sha256": sha256(source_bytes),
        "output_path": str(output),
        "output_sha256": sha256(output_bytes),
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--mode", choices=[MODE], required=True)
    args = parser.parse_args()
    receipt = transform(args.source, args.output, args.scale, args.mode)
    print(f"output_sha256={receipt['output_sha256']}")
    print(f"receipt={args.output.with_suffix(args.output.suffix + '.receipt.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
