from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Iterable

import numpy as np


PAIR_ORDER = ((0, 1), (0, 2), (1, 2))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def entry(path: Path, base: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": path.relative_to(base).as_posix(), "bytes": size, "sha256": digest}


def tree_root(entries: Iterable[dict[str, Any]]) -> str:
    rows = sorted(entries, key=lambda row: row["path"])
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seed_from_label(label: str) -> tuple[int, str]:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int.from_bytes(bytes.fromhex(digest)[:8], "little"), digest


def pair_normals(weights: np.ndarray, scale: np.ndarray) -> np.ndarray:
    w = np.asarray(weights, dtype=np.float64)
    sd = np.asarray(scale, dtype=np.float64)
    if w.shape != (3, 2048) or sd.shape != (2048,) or not np.isfinite(w).all() or not np.isfinite(sd).all() or np.any(sd <= 0):
        raise ValueError("invalid frozen observer arrays")
    normals = w / sd[None, :]
    return np.stack([normals[a] - normals[b] for a, b in PAIR_ORDER])


def orthonormal_row_basis(rows: np.ndarray, expected_rank: int = 2) -> tuple[np.ndarray, dict[str, Any]]:
    matrix = np.asarray(rows, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 2048 or not np.isfinite(matrix).all():
        raise ValueError("invalid row-space matrix")
    _, singular, vh = np.linalg.svd(matrix, full_matrices=False)
    tol = max(matrix.shape) * np.finfo(np.float64).eps * float(singular[0])
    rank = int(np.count_nonzero(singular > tol))
    if rank != expected_rank:
        raise ValueError(f"expected rank {expected_rank}, received {rank}")
    basis = np.ascontiguousarray(vh[:rank], dtype="<f8")
    residual = matrix - (matrix @ basis.T) @ basis
    relative_residual = float(np.linalg.norm(residual) / max(np.linalg.norm(matrix), np.finfo(np.float64).tiny))
    gram_error = float(np.max(np.abs(basis @ basis.T - np.eye(rank))))
    projector = basis.T @ basis
    symmetry_error = float(np.linalg.norm(projector - projector.T, ord="fro"))
    idempotence_error = float(np.linalg.norm(projector @ projector - projector, ord="fro"))
    if relative_residual > 1e-10 or gram_error > 1e-10 or symmetry_error > 1e-10 or idempotence_error > 1e-9:
        raise ValueError("source projector failed frozen geometry checks")
    return basis, {
        "rank": rank,
        "singular_values": singular.tolist(),
        "rank_tolerance": float(tol),
        "source_pair_normal_relative_residual": relative_residual,
        "basis_gram_max_abs_error": gram_error,
        "projector_symmetry_frobenius_error": symmetry_error,
        "projector_idempotence_frobenius_error": idempotence_error,
    }


def random_plane(seed_u64: int) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(seed_u64))
    gaussian = rng.standard_normal((2048, 2), dtype=np.float64)
    q, _ = np.linalg.qr(gaussian, mode="reduced")
    basis = np.ascontiguousarray(q.T, dtype="<f8")
    if float(np.max(np.abs(basis @ basis.T - np.eye(2)))) > 1e-10:
        raise ValueError("random plane is not orthonormal")
    return basis


def projected(basis: np.ndarray, vector: np.ndarray) -> np.ndarray:
    u = np.asarray(basis, dtype=np.float64)
    q = np.asarray(vector, dtype=np.float64)
    if u.shape != (2, 2048) or q.shape != (2048,):
        raise ValueError("invalid projection dimensions")
    return u.T @ (u @ q)


def matched_random_delta(target_delta: np.ndarray, random_basis: np.ndarray, q: np.ndarray) -> np.ndarray:
    delta = np.asarray(target_delta, dtype=np.float64)
    if delta.shape != (2048,):
        raise ValueError("invalid target displacement")
    target_norm = float(np.linalg.norm(delta))
    if target_norm == 0.0:
        return np.zeros(2048, dtype=np.float64)
    random_projection = projected(random_basis, q)
    random_norm = float(np.linalg.norm(random_projection))
    q_norm = float(np.linalg.norm(q))
    if random_norm <= 1e-12 * max(q_norm, 1.0):
        raise ValueError("nonzero target displacement with numerically zero random-plane projection")
    return target_norm * random_projection / random_norm


def draw_bootstrap_plan(labels_by_quartet: np.ndarray, seed_u64: int, replicates: int = 10_000) -> np.ndarray:
    labels = np.asarray(labels_by_quartet, dtype=np.int64)
    if labels.ndim != 1 or not np.array_equal(np.unique(labels), np.asarray([0, 1, 2])):
        raise ValueError("bootstrap strata must contain exact targets 0, 1, and 2")
    strata = [np.flatnonzero(labels == cls).astype(np.uint32) for cls in (0, 1, 2)]
    rng = np.random.Generator(np.random.PCG64(seed_u64))
    plan = np.empty((replicates, len(labels)), dtype="<u4")
    for replicate in range(replicates):
        offset = 0
        for indices in strata:
            count = len(indices)
            sampled = rng.choice(indices, size=count, replace=True).astype("<u4", copy=False)
            plan[replicate, offset:offset + count] = sampled
            offset += count
    return plan
