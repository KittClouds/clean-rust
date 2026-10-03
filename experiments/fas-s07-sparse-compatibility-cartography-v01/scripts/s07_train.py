from __future__ import annotations

import os

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from s07_common import (
    PARENT_BINDING, PROTOCOL_SEAL, RUN, SAE_CONTRACT, S01_CACHE, S01_HIDDEN,
    S01_PROBE_F, S01_PROBE_M, S01_ROWS, FailClosed, read_json, root_simple,
    sha256_file, standardize, verify_protocol, write_json,
)
from s07_model import SharedTopKSAE


def _verify_preflight() -> tuple[dict, np.ndarray]:
    seal = read_json(RUN / "preflight-seal-v01.json")
    if seal.get("seal_id") != "FAS_S07_PREFLIGHT_SEAL_V01" or root_simple(seal["entries"]) != seal["root_sha256"]:
        raise FailClosed("S07 preflight seal invalid")
    for entry in seal["entries"]:
        path = RUN / entry["path"]
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise FailClosed(f"S07 preflight artifact changed: {entry['path']}")
    receipt = read_json(RUN / "preflight-receipt-v01.json")
    if receipt.get("status") != "PASS" or receipt.get("heldout_s01_rows_opened") is not False or receipt.get("fas00_features_opened") is not False:
        raise FailClosed("S07 preflight firewall receipt invalid")
    indices = np.load(RUN / "train-row-indices-v01.npy", allow_pickle=False)
    if indices.dtype != np.uint32 or len(indices) != 85_224:
        raise FailClosed("S07 train row indices invalid")
    return receipt, indices


def _pooled_training_mean(indices: np.ndarray, mean_probe: dict, final_probe: dict, mean_features: np.memmap, final_features: np.memmap) -> np.ndarray:
    total = np.zeros(S01_HIDDEN, dtype=np.float64)
    count = 0
    for start in range(0, len(indices), 1024):
        rows = indices[start:start + 1024].astype(np.int64, copy=False)
        m = standardize(np.asarray(mean_features[rows]), mean_probe, precision="float32")
        f = standardize(np.asarray(final_features[rows]), final_probe, precision="float32")
        total += np.sum(m, axis=0, dtype=np.float64)
        total += np.sum(f, axis=0, dtype=np.float64)
        count += 2 * len(rows)
    return (total / count).astype(np.float32)


def _fit_seed(seed: int, train_rows: np.ndarray, mean_probe: dict, final_probe: dict, mean_features: np.memmap, final_features: np.memmap, decoder_bias_init: np.ndarray, output: Path, cfg: dict) -> dict:
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    model = SharedTopKSAE(
        input_width=cfg["input_dimension"],
        dictionary_width=cfg["dictionary_width"],
        k=cfg["activation"]["k"],
    ).cuda()
    model.initialize(torch.from_numpy(decoder_bias_init).cuda())
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=cfg["optimizer"]["learning_rate"],
        betas=tuple(cfg["optimizer"]["betas"]),
        eps=cfg["optimizer"]["epsilon"],
        weight_decay=cfg["optimizer"]["weight_decay"],
    )
    rng = np.random.default_rng(seed)
    epoch_losses: list[float] = []
    epoch_times: list[float] = []
    steps = 0
    started = time.perf_counter()
    pair_batch = cfg["training"]["paired_rows_per_batch"]
    for epoch in range(cfg["training"]["epochs"]):
        order = rng.permutation(train_rows)
        weighted_loss = 0.0
        seen_vectors = 0
        epoch_started = time.perf_counter()
        for start in range(0, len(order), pair_batch):
            rows = order[start:start + pair_batch].astype(np.int64, copy=False)
            mean_x = standardize(np.asarray(mean_features[rows]), mean_probe, precision="float32")
            final_x = standardize(np.asarray(final_features[rows]), final_probe, precision="float32")
            paired = np.empty((2 * len(rows), S01_HIDDEN), dtype=np.float32)
            paired[0::2] = mean_x
            paired[1::2] = final_x
            x = torch.from_numpy(paired).cuda()
            optimizer.zero_grad(set_to_none=True)
            reconstruction = model(x)
            loss = F.mse_loss(reconstruction, x, reduction="mean")
            if not torch.isfinite(loss):
                raise FailClosed(f"Nonfinite SAE loss at seed={seed}, epoch={epoch+1}, step={steps}")
            loss.backward()
            optimizer.step()
            model.normalize_decoder_columns()
            weighted_loss += float(loss.detach()) * len(paired)
            seen_vectors += len(paired)
            steps += 1
        epoch_losses.append(weighted_loss / seen_vectors)
        epoch_times.append(time.perf_counter() - epoch_started)
        print(f"S07_TRAIN seed={seed} epoch={epoch+1}/{cfg['training']['epochs']} mse={epoch_losses[-1]:.7f} seconds={epoch_times[-1]:.2f}", flush=True)

    decoder = model.decoder.detach().cpu().numpy().astype(np.float32, copy=True)
    encoder_weight = model.encoder.weight.detach().cpu().numpy().astype(np.float32, copy=True)
    encoder_bias = model.encoder.bias.detach().cpu().numpy().astype(np.float32, copy=True)
    decoder_bias = model.decoder_bias.detach().cpu().numpy().astype(np.float32, copy=True)
    norms = np.linalg.norm(decoder, axis=0)
    if not np.isfinite(decoder).all() or np.max(np.abs(norms - 1.0)) > 2e-5:
        raise FailClosed(f"Decoder norm or finite check failed at seed={seed}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        np.savez(
            stream,
            encoder_weight=encoder_weight,
            encoder_bias=encoder_bias,
            decoder=decoder,
            decoder_bias=decoder_bias,
            seed=np.asarray(seed, dtype=np.uint32),
        )
    del optimizer, model
    torch.cuda.empty_cache()
    return {
        "seed": seed,
        "epochs": cfg["training"]["epochs"],
        "steps": steps,
        "train_rows_per_surface": int(len(train_rows)),
        "pooled_vectors_per_epoch": int(2 * len(train_rows)),
        "epoch_mse": epoch_losses,
        "epoch_seconds": epoch_times,
        "elapsed_seconds": time.perf_counter() - started,
        "decoder_column_norm_min": float(norms.min()),
        "decoder_column_norm_max": float(norms.max()),
        "checkpoint_path": output.name,
        "checkpoint_bytes": output.stat().st_size,
        "checkpoint_sha256": sha256_file(output),
    }


def main() -> None:
    protocol = verify_protocol()
    receipt, train_rows = _verify_preflight()
    if protocol["root_sha256"] != receipt["protocol_root_sha256"]:
        raise FailClosed("Preflight and protocol roots differ")
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise FailClosed("S07 frozen CUDA device is unavailable or changed")
    if (RUN / "training-tree-seal-v01.json").exists():
        raise FailClosed("S07 training tree already sealed; refusing overwrite")
    seed_dir = RUN / "sae-seeds-v01"
    if seed_dir.exists() and any(seed_dir.iterdir()):
        raise FailClosed("S07 SAE output directory is not empty")
    seed_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    cfg = read_json(SAE_CONTRACT)
    binding = read_json(PARENT_BINDING)
    inputs = binding["direct_inputs"]
    mean_probe = {
        "mean": np.load(S01_PROBE_M, allow_pickle=False)["scaler_mean"].astype(np.float32),
        "scale": np.load(S01_PROBE_M, allow_pickle=False)["scaler_scale"].astype(np.float32),
    }
    final_probe = {
        "mean": np.load(S01_PROBE_F, allow_pickle=False)["scaler_mean"].astype(np.float32),
        "scale": np.load(S01_PROBE_F, allow_pickle=False)["scaler_scale"].astype(np.float32),
    }
    if mean_probe["mean"].shape != (S01_HIDDEN,) or final_probe["mean"].shape != (S01_HIDDEN,) or np.any(mean_probe["scale"] <= 0) or np.any(final_probe["scale"] <= 0):
        raise FailClosed("S01 sealed native scaler dimensions/values invalid")
    mean_features = np.memmap(inputs["s01_mean_features"]["path"], mode="r", dtype="<f4", shape=(S01_ROWS, S01_HIDDEN))
    final_features = np.memmap(inputs["s01_final_features"]["path"], mode="r", dtype="<f4", shape=(S01_ROWS, S01_HIDDEN))
    pooled_mean = _pooled_training_mean(train_rows, mean_probe, final_probe, mean_features, final_features)
    results = []
    for seed in cfg["seeds"]:
        checkpoint = seed_dir / f"shared-topk-seed-{seed}.npz"
        results.append(_fit_seed(seed, train_rows, mean_probe, final_probe, mean_features, final_features, pooled_mean, checkpoint, cfg))
    receipt_out = {
        "receipt_id": "FAS_S07_TRAINING_RECEIPT_V01",
        "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "preflight_root_sha256": read_json(RUN / "preflight-seal-v01.json")["root_sha256"],
        "training_contract_sha256": sha256_file(SAE_CONTRACT),
        "training_rows_sha256": sha256_file(RUN / "train-row-indices-v01.npy"),
        "train_rows": int(len(train_rows)),
        "pooled_vectors": int(2 * len(train_rows)),
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "evaluation_features_loaded": False,
        "fas00_features_loaded": False,
        "labels_loaded": False,
        "gpu": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "dtype": "float32",
        "tf32": False,
        "deterministic_algorithms": True,
        "seed_results": results,
    }
    receipt_path = RUN / "training-receipt-v01.json"
    write_json(receipt_path, receipt_out)
    paths = [receipt_path, *sorted(seed_dir.glob("*.npz"))]
    entries = []
    for path in paths:
        entries.append({"path": path.relative_to(RUN).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    entries.sort(key=lambda item: item["path"].casefold())
    seal = {
        "seal_id": "FAS_S07_TRAINING_TREE_SEAL_V01",
        "status": "SEALED",
        "protocol_root_sha256": protocol["root_sha256"],
        "preflight_root_sha256": read_json(RUN / "preflight-seal-v01.json")["root_sha256"],
        "entries": entries,
        "root_sha256": root_simple(entries),
    }
    write_json(RUN / "training-tree-seal-v01.json", seal)
    print(f"S07_TRAINING_SEALED seeds={len(results)} root={seal['root_sha256']}")


if __name__ == "__main__":
    try:
        main()
    except FailClosed as exc:
        print(f"S07_TRAINING_FAIL_CLOSED {exc}")
        raise SystemExit(2)
