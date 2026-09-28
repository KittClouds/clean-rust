"""Stage verified MaleCNS columns as read-only-friendly little-endian arrays."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEPS = ROOT / "experiments" / "drosophila-heresy" / ".deps"
if str(DEPS) not in sys.path:
    sys.path.insert(0, str(DEPS))

import pyarrow as pa  # noqa: E402
import pyarrow.ipc as ipc  # noqa: E402

RAW = pathlib.Path("D:/drosophila-heresy/data")
SOURCE = RAW / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
RECEIPTS = RAW / "sources.json"
STAGE = pathlib.Path("D:/fly-drop-00-stage/columns")


def digest(path: pathlib.Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    started = time.perf_counter()
    if STAGE.exists():
        raise RuntimeError(f"staging directory already exists; refusing overwrite: {STAGE}")
    receipt_rows = json.loads(RECEIPTS.read_text(encoding="utf-8"))
    source_receipt = next(row for row in receipt_rows if pathlib.Path(row["path"]).name == SOURCE.name)
    actual_source_hash = digest(SOURCE)
    if actual_source_hash != source_receipt["sha256"]:
        raise RuntimeError("MaleCNS weights source hash does not match its receipt")

    STAGE.mkdir(parents=True)
    names = {"body_pre": "pre.i64le", "body_post": "post.i64le", "weight": "weight.i64le"}
    counts = {name: 0 for name in names}
    handles = {name: (STAGE / file_name).open("wb", buffering=1024 * 1024) for name, file_name in names.items()}
    try:
        with pa.memory_map(str(SOURCE), "r") as source:
            reader = ipc.open_file(source)
            schema_names = reader.schema.names
            for required in names:
                if required not in schema_names:
                    raise RuntimeError(f"missing required source column: {required}")
            column_indices = {name: schema_names.index(name) for name in names}
            for batch_id in range(reader.num_record_batches):
                batch = reader.get_batch(batch_id)
                for name, column_index in column_indices.items():
                    values = batch.column(column_index).to_numpy(zero_copy_only=False)
                    if values.dtype != np.dtype("int64"):
                        raise RuntimeError(f"unexpected dtype for {name}: {values.dtype}")
                    values.tofile(handles[name])
                    counts[name] += int(values.size)
                if batch_id % 100 == 0:
                    print(
                        f"batch {batch_id + 1}/{reader.num_record_batches}; "
                        f"rows staged {counts['body_pre']:,}",
                        flush=True,
                    )
            schema = str(reader.schema)
    finally:
        for handle in handles.values():
            handle.close()

    if len(set(counts.values())) != 1:
        raise RuntimeError(f"source columns have different row counts: {counts}")

    files = []
    for name, file_name in names.items():
        path = STAGE / file_name
        files.append(
            {
                "source_column": name,
                "file": file_name,
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
        )
    output = {
        "artifact_kind": "verified_source_column_stage",
        "source_file": SOURCE.name,
        "source_bytes": SOURCE.stat().st_size,
        "source_sha256": actual_source_hash,
        "source_rows": counts["body_pre"],
        "source_schema": schema,
        "column_format": "contiguous little-endian signed int64; source row order preserved",
        "columns": files,
        "elapsed_seconds": time.perf_counter() - started,
    }
    receipt_path = STAGE / "columns-receipt.json"
    receipt_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
