"""Read-only traced-subgraph diagnostic against the full MaleCNS v1.0 source."""

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

import pyarrow.feather as feather  # noqa: E402
import pyarrow.ipc as ipc  # noqa: E402
import pyarrow as pa  # noqa: E402

RAW = pathlib.Path("D:/drosophila-heresy/data")
OUT = pathlib.Path(__file__).resolve().parents[1] / "preflight" / "source-census.json"


def sha256(path: pathlib.Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def degree_summary(values: np.ndarray) -> dict[str, int | float]:
    return {
        "zero_count": int(np.count_nonzero(values == 0)),
        "p50": float(np.quantile(values, 0.50)),
        "p90": float(np.quantile(values, 0.90)),
        "p99": float(np.quantile(values, 0.99)),
        "maximum": int(values.max(initial=0)),
    }


def traced_positions(ids: np.ndarray, body_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positions = np.searchsorted(ids, body_ids)
    valid = positions < len(ids)
    safe_positions = np.minimum(positions, len(ids) - 1)
    valid &= ids[safe_positions] == body_ids
    return positions, valid


def main() -> None:
    started = time.perf_counter()
    receipts = json.loads((RAW / "sources.json").read_text(encoding="utf-8"))
    verified_sources = []
    for receipt in receipts:
        source_path = pathlib.Path(receipt["path"])
        actual_hash = sha256(source_path)
        if actual_hash != receipt["sha256"]:
            raise RuntimeError(f"source hash mismatch: {source_path.name}")
        verified_sources.append(
            {
                "name": source_path.name,
                "bytes": int(receipt["bytes"]),
                "sha256": actual_hash,
                "url": receipt["url"],
            }
        )

    annotations_path = RAW / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    annotations = feather.read_table(annotations_path, memory_map=True).to_pandas()
    if not annotations["bodyId"].is_unique:
        raise RuntimeError("annotation bodyId is not unique")
    traced = annotations.loc[annotations["status"].eq("Traced"), "bodyId"]
    traced_ids = np.sort(traced.to_numpy(dtype=np.int64, copy=True))
    if len(traced_ids) == 0 or np.unique(traced_ids).size != len(traced_ids):
        raise RuntimeError("traced neuron ID universe is empty or non-unique")
    annotated_ids = set(
        annotations["bodyId"].to_numpy(dtype=np.int64, copy=True).tolist()
    )
    endpoint_ids: set[int] = set()

    indegree = np.zeros(len(traced_ids), dtype=np.uint64)
    outdegree = np.zeros(len(traced_ids), dtype=np.uint64)
    instrength = np.zeros(len(traced_ids), dtype=np.uint64)
    outstrength = np.zeros(len(traced_ids), dtype=np.uint64)

    path = RAW / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
    with pa.memory_map(str(path), "r") as source:
        reader = ipc.open_file(source)
        names = reader.schema.names
        required = {"body_pre", "body_post", "weight"}
        if not required.issubset(names):
            raise RuntimeError(f"unexpected connectome schema: {reader.schema}")
        pre_column = names.index("body_pre")
        post_column = names.index("body_post")
        weight_column = names.index("weight")

        all_rows = 0
        all_weight = 0
        internal_rows = 0
        internal_weight = 0
        incoming_boundary_rows = 0
        incoming_boundary_weight = 0
        outgoing_boundary_rows = 0
        outgoing_boundary_weight = 0

        for batch_id in range(reader.num_record_batches):
            batch = reader.get_batch(batch_id)
            pre = batch.column(pre_column).to_numpy(zero_copy_only=False)
            post = batch.column(post_column).to_numpy(zero_copy_only=False)
            weights = batch.column(weight_column).to_numpy(zero_copy_only=False).astype(
                np.uint64, copy=False
            )
            endpoint_ids.update(np.unique(pre).tolist())
            endpoint_ids.update(np.unique(post).tolist())
            if np.any(weights == 0):
                raise RuntimeError(f"zero connection weight in batch {batch_id}")

            pre_index, pre_traced = traced_positions(traced_ids, pre)
            post_index, post_traced = traced_positions(traced_ids, post)
            internal = pre_traced & post_traced
            incoming = ~pre_traced & post_traced
            outgoing = pre_traced & ~post_traced

            all_rows += len(pre)
            all_weight += int(weights.sum(dtype=np.uint64))
            internal_rows += int(np.count_nonzero(internal))
            internal_weight += int(weights[internal].sum(dtype=np.uint64))
            incoming_boundary_rows += int(np.count_nonzero(incoming))
            incoming_boundary_weight += int(weights[incoming].sum(dtype=np.uint64))
            outgoing_boundary_rows += int(np.count_nonzero(outgoing))
            outgoing_boundary_weight += int(weights[outgoing].sum(dtype=np.uint64))

            if np.any(internal):
                src = pre_index[internal]
                dst = post_index[internal]
                w = weights[internal]
                outdegree += np.bincount(src, minlength=len(traced_ids)).astype(
                    np.uint64, copy=False
                )
                indegree += np.bincount(dst, minlength=len(traced_ids)).astype(
                    np.uint64, copy=False
                )
                outstrength += np.bincount(
                    src, weights=w, minlength=len(traced_ids)
                ).astype(np.uint64)
                instrength += np.bincount(
                    dst, weights=w, minlength=len(traced_ids)
                ).astype(np.uint64)

            if batch_id % 100 == 0:
                print(
                    f"batch {batch_id + 1}/{reader.num_record_batches}; "
                    f"rows scanned {all_rows:,}",
                    flush=True,
                )

        schema = str(reader.schema)

    result = {
        "artifact_kind": "read_only_traced_subgraph_diagnostic",
        "scientific_outcome": False,
        "dataset": "MaleCNS v1.0, min confidence 0.5",
        "operator_rule_candidate": (
            "the complete source connection table without annotation filtering; "
            "see DESIGN.md"
        ),
        "diagnostic_node_rule": (
            "every annotation row with status=Traced; no class or hemisphere filter"
        ),
        "diagnostic_edge_rule": (
            "count source rows whose pre and post body IDs are both traced"
        ),
        "operator_orientation": "body_pre -> body_post",
        "source_schema": schema,
        "verified_sources": verified_sources,
        "annotation_sha256": sha256(annotations_path),
        "annotation_rows": int(len(annotations)),
        "annotation_status_counts": {
            str(key): int(value)
            for key, value in annotations["status"].value_counts(dropna=False).items()
        },
        "traced_nodes": int(len(traced_ids)),
        "connectome_rows": int(all_rows),
        "connectome_weight_sum": int(all_weight),
        "source_endpoint_body_ids": len(endpoint_ids),
        "endpoint_ids_without_annotation": len(endpoint_ids - annotated_ids),
        "annotated_ids_without_source_edges": len(annotated_ids - endpoint_ids),
        "full_source_node_universe": len(endpoint_ids | annotated_ids),
        "traced_to_traced_edge_rows": int(internal_rows),
        "traced_to_traced_weight_sum": int(internal_weight),
        "nontraced_to_traced_boundary_rows": int(incoming_boundary_rows),
        "nontraced_to_traced_boundary_weight_sum": int(incoming_boundary_weight),
        "traced_to_nontraced_boundary_rows": int(outgoing_boundary_rows),
        "traced_to_nontraced_boundary_weight_sum": int(outgoing_boundary_weight),
        "edge_row_degree": {
            "in": degree_summary(indegree),
            "out": degree_summary(outdegree),
        },
        "weighted_degree": {
            "in": degree_summary(instrength),
            "out": degree_summary(outstrength),
        },
        "elapsed_seconds": time.perf_counter() - started,
        "scope_note": (
            "Preflight metadata for the traced-only induced-subgraph diagnostic. "
            "It does not construct a model, select a host task, train, or read "
            "evaluation outcomes. The design default uses every source row."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
