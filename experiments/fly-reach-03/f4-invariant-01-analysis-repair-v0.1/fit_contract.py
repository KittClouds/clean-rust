"""Pure F4-INVARIANT-01 manifest, prediction, and scoring primitives."""
from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Mapping, Sequence


BLOCKS = tuple(range(306000, 306012))
REPLICATES = (0, 1, 2)
ARMS = ("D", "S")
PRED_MAGIC = b"F4INV01PREDv1\0\0\0"
PRED_RECORD_BYTES = 22
FIT_HEADER = (
    "fit_id", "arm", "fold_index", "heldout_block", "replicate_index",
    "train_rows", "heldout_rows", "contract_sha256", "source_manifest_sha256",
    "executable_sha256", "analysis_sha256", "base_stream_sha256",
    "normalized_tuple_stream_sha256", "paired_source_input_sha256",
    "normalization_sha256", "training_row_hash", "training_order_hash",
    "initializer_seed_manifest_sha256", "initial_tensor_hash",
    "expected_prediction_path",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def expected_fit_ids() -> list[str]:
    return [
        f"{arm}-H{block}-I{replicate}"
        for replicate in REPLICATES
        for arm in ARMS
        for block in BLOCKS
    ]


def validate_fit_grid(rows: Sequence[Mapping[str, object]]) -> None:
    expected = expected_fit_ids()
    actual = [str(row["fit_id"]) for row in rows]
    if actual != expected:
        raise ValueError("fit manifest is missing, duplicated, extra, or out of frozen order")
    for row, fit_id in zip(rows, expected, strict=True):
        arm, holdout, replicate_token = fit_id.split("-")
        block = int(holdout[1:])
        replicate = int(replicate_token[1:])
        if (
            str(row["arm"]) != arm
            or int(row["heldout_block"]) != block
            or int(row["replicate_index"]) != replicate
            or int(row["fold_index"]) != block - BLOCKS[0]
        ):
            raise ValueError(f"fit manifest identity fields disagree with fit_id {fit_id}")
    if sum(str(row["arm"]) == "D" for row in rows) != 36 or sum(str(row["arm"]) == "S" for row in rows) != 36:
        raise ValueError("fit manifest must contain exactly 36 D and 36 S rows")


def manifest_row_hashes(csv_bytes: bytes) -> tuple[str, dict[str, str]]:
    if not csv_bytes.endswith(b"\n") or b"\r" in csv_bytes:
        raise ValueError("FIT-MANIFEST must use LF line endings and end in LF")
    lines = csv_bytes.splitlines(keepends=True)
    if len(lines) != 73:
        raise ValueError("FIT-MANIFEST must contain one header plus exactly 72 rows")
    row_hashes: dict[str, str] = {}
    for line in lines[1:]:
        fields = line[:-1].decode("utf-8").split(",")
        if len(fields) != len(FIT_HEADER):
            raise ValueError("FIT-MANIFEST row has wrong column count")
        fit_id = fields[0]
        if fit_id in row_hashes:
            raise ValueError("duplicate fit id in FIT-MANIFEST")
        row_hashes[fit_id] = sha256_bytes(line)
    return sha256_bytes(csv_bytes), row_hashes


def encode_prediction_stream(
    *, block: int, arm: str, replicate: int, manifest_row_sha256: str,
    records: Sequence[tuple[bytes, float]],
) -> bytes:
    if len(PRED_MAGIC) != 16 or arm not in ARMS or replicate not in REPLICATES:
        raise ValueError("invalid frozen prediction identity")
    if len(manifest_row_sha256) != 64:
        raise ValueError("manifest row SHA must be a 32-byte digest")
    header = PRED_MAGIC + struct.pack(
        "<IQBB2xQ", 1, block, ARMS.index(arm), replicate, len(records)
    ) + bytes.fromhex(manifest_row_sha256)
    if len(header) != 72:
        raise ValueError("prediction header is not 72 bytes")
    output = bytearray(header)
    seen: set[bytes] = set()
    for key, logit in records:
        if len(key) != 18 or key in seen or not math.isfinite(float(logit)):
            raise ValueError("invalid, duplicate, or nonfinite prediction record")
        seen.add(key)
        output.extend(key)
        output.extend(struct.pack("<f", float(logit)))
    return bytes(output)


def decode_prediction_stream(
    raw: bytes, *, block: int, arm: str, replicate: int,
    manifest_row_sha256: str, expected_keys: Sequence[bytes],
) -> tuple[list[bytes], list[float]]:
    if len(raw) < 72 or raw[:16] != PRED_MAGIC:
        raise ValueError("prediction stream magic/header mismatch")
    version, actual_block, arm_id, actual_rep, count = struct.unpack_from("<IQBB2xQ", raw, 16)
    if (version, actual_block, arm_id, actual_rep, count) != (1, block, ARMS.index(arm), replicate, len(expected_keys)):
        raise ValueError("prediction stream identity or count mismatch")
    if raw[40:72] != bytes.fromhex(manifest_row_sha256):
        raise ValueError("prediction stream manifest-row hash mismatch")
    if len(raw) != 72 + count * PRED_RECORD_BYTES:
        raise ValueError("prediction stream byte length mismatch")
    keys: list[bytes] = []
    logits: list[float] = []
    seen: set[bytes] = set()
    for index in range(count):
        offset = 72 + index * PRED_RECORD_BYTES
        key = raw[offset:offset + 18]
        logit = struct.unpack_from("<f", raw, offset + 18)[0]
        if key in seen or not math.isfinite(logit):
            raise ValueError(f"duplicate key or nonfinite logit at prediction record {index}")
        seen.add(key)
        keys.append(key)
        logits.append(logit)
    if keys != list(expected_keys):
        raise ValueError("prediction row keys differ from frozen held-out order")
    return keys, logits


def weighted_balanced_error(signs: Sequence[int], targets: Sequence[int], q: Sequence[float]) -> float | None:
    if not (len(signs) == len(targets) == len(q)):
        raise ValueError("scoring vectors have inconsistent lengths")
    rates: list[float] = []
    for label in (-1, 1):
        selected = [i for i, target in enumerate(targets) if int(target) == label]
        denom = math.fsum(float(q[i]) for i in selected)
        if not selected or denom <= 0.0:
            return None
        numerator = math.fsum(float(q[i]) for i in selected if int(signs[i]) != label)
        rates.append(numerator / denom)
    return 0.5 * math.fsum(rates)


def prediction_signs(logits: Sequence[float]) -> list[int]:
    """Frozen classifier threshold: only logits strictly above zero predict +1."""
    values = [float(value) for value in logits]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("prediction logits must be finite")
    return [1 if value > 0.0 else -1 for value in values]


def weighted_accuracy(signs: Sequence[int], targets: Sequence[int], q: Sequence[float]) -> float | None:
    if not (len(signs) == len(targets) == len(q)):
        raise ValueError("scoring vectors have inconsistent lengths")
    denom = math.fsum(float(value) for value in q)
    if len(targets) == 0 or denom <= 0.0:
        return None
    correct = math.fsum(float(q[i]) for i in range(len(q)) if int(signs[i]) == int(targets[i]))
    return correct / denom


def signed_margin(logits: Sequence[float], targets: Sequence[int], q: Sequence[float]) -> float | None:
    if not (len(logits) == len(targets) == len(q)):
        raise ValueError("margin vectors have inconsistent lengths")
    labels = sorted(set(int(value) for value in targets))
    if not labels:
        return None
    class_means: list[float] = []
    for label in labels:
        selected = [i for i, target in enumerate(targets) if int(target) == label]
        denom = math.fsum(float(q[i]) for i in selected)
        if denom <= 0.0:
            return None
        numerator = math.fsum(float(q[i]) * int(targets[i]) * float(logits[i]) for i in selected)
        class_means.append(numerator / denom)
    return math.fsum(class_means) / len(class_means)


def polarity_metrics(
    signs: Sequence[int], targets: Sequence[int], q: Sequence[float],
    native_delta: Sequence[float], reference: Sequence[float], row_keys: Sequence[bytes],
) -> dict[str, object]:
    lengths = {len(signs), len(targets), len(q), len(native_delta), len(reference), len(row_keys)}
    if len(lengths) != 1:
        raise ValueError("polarity vectors have inconsistent lengths")
    leverage = [float(q[i]) * abs(float(native_delta[i])) * abs(float(reference[i])) for i in range(len(q))]
    total = math.fsum(leverage)
    if total <= 0.0:
        return {"psi_prop": None, "weighted_sign_agreement": None, "leverage_sum": 0.0, "leverage_ess": None, "top_1pct_share": None, "top_5pct_share": None, "top_20pct_share": None}
    agreement = math.fsum(leverage[i] for i in range(len(q)) if int(signs[i]) == (1 if float(reference[i]) > 0.0 else -1)) / total
    square_sum = math.fsum(value * value for value in leverage)
    ranked = sorted(range(len(q)), key=lambda i: (-leverage[i], row_keys[i]))
    concentration: dict[str, float] = {}
    for pct in (1, 5, 20):
        count = math.ceil(pct * len(q) / 100)
        concentration[f"top_{pct}pct_share"] = math.fsum(leverage[i] for i in ranked[:count]) / total
    return {
        "psi_prop": 2.0 * agreement - 1.0,
        "weighted_sign_agreement": agreement,
        "leverage_sum": total,
        "leverage_ess": total * total / square_sum if square_sum > 0.0 else None,
        **concentration,
    }


def delivery_alignment(signs: Sequence[int], native_delta: Sequence[float], preweight: Sequence[float], reference: Sequence[float]) -> float | None:
    if not (len(signs) == len(native_delta) == len(preweight) == len(reference)):
        raise ValueError("delivery vectors have inconsistent lengths")
    delivered = [
        min(2.0, max(0.0, float(preweight[i]) + abs(float(native_delta[i])) * int(signs[i]))) - float(preweight[i])
        for i in range(len(signs))
    ]
    dot = math.fsum(delivered[i] * float(reference[i]) for i in range(len(signs)))
    norm_u = math.sqrt(math.fsum(value * value for value in delivered))
    norm_g = math.sqrt(math.fsum(float(value) * float(value) for value in reference))
    if norm_u == 0.0 or norm_g == 0.0:
        return None
    return dot / (norm_u * norm_g)


def expected_update_count(training_rows: int, *, epochs: int = 200, batch_size: int = 2048) -> int:
    if training_rows <= 0:
        raise ValueError("training rows must be positive")
    return epochs * ((training_rows + batch_size - 1) // batch_size)
