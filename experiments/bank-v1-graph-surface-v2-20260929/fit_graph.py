"""Fixed-schedule readouts and renderer evaluation for graph-local BANK tasks."""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from common import (ENTITY_TYPES, PREDICATES, SEED, SURFACES, WORLD_SPLITS,
                    cached_surface_arrays, local_surface_arrays, read_jsonl,
                    sha256, write_json)
from graph_metrics import (aggregate_control_renderer, aggregate_control_splits,
                           aggregate_over_splits, aggregate_renderer, classification_metrics,
                           link_metrics, matrix_rank, metric_bundle, random_link_metrics,
                           write_report)
from graph_link import candidates_with_target
from graph_scaling import (calculate_node_scaler, calculate_row_scaler,
                           load_scaler_cache, make_scalers, scaler_basis,
                           seal_scalers)

TASKS = ("node_type", "edge_existence", "edge_label", "one_hop_membership",
         "two_hop_membership", "link_completion")
HEADS = ("linear", "bilinear", "tiny_mlp")
EPOCHS = 5
BATCH = 2048
LR = 1e-3
WEIGHT_DECAY = 1e-4
MLP_WIDTH = 128
BILINEAR_RANK = 128
PRED_COUNT = len(PREDICATES)


def load_records(path: Path):
    return list(read_jsonl(path))


def output_count(task: str) -> int:
    if task == "node_type":
        return len(ENTITY_TYPES)
    if task == "edge_label":
        return len(PREDICATES) + 1
    if task == "link_completion":
        return 1
    return 2


def feature_vectors(records, task, surface, local_arrays, row_arrays, scalers,
                    representation="local", source_surface=None):
    if representation == "row":
        surface = source_surface or surface
        mean, scale = scalers["row"][surface]
        indexes = np.asarray([r["row_idx"] for r in records], dtype=np.int64)
        values = cached_surface_arrays(row_arrays, indexes, surface).astype(np.float32, copy=False)
        return (values - mean) / scale
    if representation == "first_token":
        mean, scale = scalers["row"]["first_token"]
        indexes = np.asarray([r["row_idx"] for r in records], dtype=np.int64)
        values = cached_surface_arrays(row_arrays, indexes, "first_token").astype(np.float32, copy=False)
        return (values - mean) / scale
    local_mean, local_scale = scalers["local"][surface]
    if task == "node_type":
        output = np.zeros((len(records), len(local_mean)), dtype=np.float32)
        for kind in ("entity", "goal"):
            positions = [i for i, row in enumerate(records) if row["feature_kind"] == kind]
            if not positions:
                continue
            indexes = np.asarray([records[i]["feature_idx"] for i in positions], dtype=np.int64)
            vals = local_surface_arrays(local_arrays[kind], indexes, surface).astype(np.float32, copy=False)
            output[np.asarray(positions, dtype=np.int64)] = (vals - local_mean) / local_scale
        return output
    left = np.asarray([r["a_idx"] for r in records], dtype=np.int64)
    right = np.asarray([r.get("b_idx", r.get("target_idx")) for r in records], dtype=np.int64)
    a = local_surface_arrays(local_arrays["entity"], left, surface).astype(np.float32, copy=False)
    b = local_surface_arrays(local_arrays["entity"], right, surface).astype(np.float32, copy=False)
    return (a - local_mean) / local_scale, (b - local_mean) / local_scale


def build_head(torch, task, kind, dim, outputs):
    import torch.nn as nn

    class Readout(nn.Module):
        def __init__(self):
            super().__init__()
            self.task = task
            self.kind = kind
            self.output_count = outputs
            if task == "node_type":
                if kind == "linear":
                    self.linear = nn.Linear(dim, outputs)
                elif kind == "tiny_mlp":
                    self.mlp = nn.Sequential(nn.Linear(dim, MLP_WIDTH), nn.GELU(),
                                             nn.Dropout(0.1), nn.Linear(MLP_WIDTH, outputs))
                else:
                    self.u = nn.Linear(dim, BILINEAR_RANK, bias=False)
                    self.v = nn.Linear(dim, BILINEAR_RANK * outputs, bias=False)
                    self.bias = nn.Parameter(torch.zeros(outputs))
            elif kind == "linear":
                in_dim = dim * 2 + (PRED_COUNT if task == "link_completion" else 0)
                self.linear = nn.Linear(in_dim, outputs)
            elif kind == "tiny_mlp":
                in_dim = dim * 2 + (PRED_COUNT if task == "link_completion" else 0)
                self.mlp = nn.Sequential(nn.Linear(in_dim, MLP_WIDTH), nn.GELU(),
                                         nn.Dropout(0.1), nn.Linear(MLP_WIDTH, outputs))
            else:
                if task == "link_completion":
                    self.u = nn.Linear(dim, BILINEAR_RANK, bias=False)
                    self.v = nn.Linear(dim, BILINEAR_RANK, bias=False)
                    self.relation = nn.Embedding(PRED_COUNT, BILINEAR_RANK)
                    self.bias = nn.Parameter(torch.zeros(()))
                else:
                    self.u = nn.Linear(dim, BILINEAR_RANK, bias=False)
                    self.v = nn.Linear(dim, BILINEAR_RANK * outputs, bias=False)
                    self.bias = nn.Parameter(torch.zeros(outputs))

        def forward(self, a, b=None, predicate=None):
            if task == "node_type":
                if kind == "linear":
                    return self.linear(a)
                if kind == "tiny_mlp":
                    return self.mlp(a)
                left = self.u(a)
                right = self.v(a).view(-1, outputs, BILINEAR_RANK)
                return (left.unsqueeze(1) * right).sum(-1) + self.bias
            if kind == "linear" or kind == "tiny_mlp":
                pieces = [a, b]
                if task == "link_completion":
                    pieces.append(torch.nn.functional.one_hot(predicate.long(), PRED_COUNT).float())
                inputs = torch.cat(pieces, dim=1)
                return self.linear(inputs) if kind == "linear" else self.mlp(inputs)
            left = self.u(a)
            right = self.v(b)
            if task == "link_completion":
                rel = self.relation(predicate.long())
                return (left * right * rel).sum(-1) + self.bias
            return (left.unsqueeze(1) * right.view(-1, outputs, BILINEAR_RANK)).sum(-1) + self.bias

    return Readout().to(device="cuda:0", dtype=torch.float32)


def labels_from(records):
    return np.asarray([int(row.get("label", 0)) for row in records], dtype=np.int64)


def epoch_batches(sample_count, rng, locality_order=None):
    """Shuffle bounded record blocks to keep memory-mapped feature reads local."""
    block_width = BATCH * 4
    order = (np.arange(sample_count, dtype=np.int64) if locality_order is None
             else locality_order)
    if len(order) != sample_count:
        raise ValueError("locality order must cover every training record")
    block_starts = np.arange(0, sample_count, block_width, dtype=np.int64)
    rng.shuffle(block_starts)
    for start in block_starts:
        block = order[start:min(start + block_width, sample_count)].copy()
        rng.shuffle(block)
        for offset in range(0, len(block), BATCH):
            yield block[offset:offset + BATCH]


def model_logits(torch, model, records, task, surface, local_arrays, row_arrays,
                 scalers, representation="local", source_surface=None):
    if task == "node_type" or representation in ("row", "first_token"):
        x = feature_vectors(records, task, surface, local_arrays, row_arrays, scalers,
                            representation, source_surface)
        a = torch.from_numpy(np.ascontiguousarray(x)).to("cuda:0")
        with torch.inference_mode():
            result = model(a).detach().cpu().numpy()
        return result
    a_np, b_np = feature_vectors(records, task, surface, local_arrays, row_arrays,
                                 scalers, representation)
    a = torch.from_numpy(np.ascontiguousarray(a_np)).to("cuda:0")
    b = torch.from_numpy(np.ascontiguousarray(b_np)).to("cuda:0")
    pred = None
    if task == "link_completion":
        pred = torch.as_tensor([int(r["predicate"]) for r in records], dtype=torch.long, device="cuda:0")
    with torch.inference_mode():
        result = model(a, b, pred).detach().cpu().numpy()
    return result


def fit_model(torch, train_records, task, surface, kind, arrays, row_arrays, scalers,
              seed, representation="local", source_surface=None,
              precomputed_features=None):
    import torch.nn.functional as F
    if task == "node_type" or representation in ("row", "first_token"):
        dim = (len(scalers["row"][source_surface or surface][0]) if representation == "row" else
               len(scalers["row"]["first_token"][0]) if representation == "first_token" else
               len(scalers["local"][surface][0]))
    else:
        dim = len(scalers["local"][surface][0])
    outputs = output_count(task)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    builder_task = "node_type" if representation in ("row", "first_token") else task
    model = build_head(torch, builder_task, kind, dim, outputs)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY,
                                  foreach=False)
    order_rng = np.random.default_rng(seed)
    labels = labels_from(train_records)
    key_name = "feature_idx" if task == "node_type" else "row_idx"
    locality_keys = np.fromiter((int(row[key_name]) for row in train_records),
                                dtype=np.int64, count=len(train_records))
    locality_order = np.argsort(locality_keys, kind="stable")
    losses = []
    start_time = time.perf_counter()
    for epoch in range(EPOCHS):
        model.train()
        running = 0.0
        seen = 0
        for ids in epoch_batches(len(train_records), order_rng, locality_order):
            batch_rows = [train_records[int(i)] for i in ids]
            if precomputed_features is not None:
                if isinstance(precomputed_features, tuple):
                    av, bv = precomputed_features
                    a = torch.from_numpy(np.ascontiguousarray(av[ids])).to("cuda:0")
                    b = torch.from_numpy(np.ascontiguousarray(bv[ids])).to("cuda:0")
                else:
                    xb = precomputed_features[ids]
                    a = torch.from_numpy(np.ascontiguousarray(xb)).to("cuda:0")
                pred = None
                if task == "link_completion":
                    pred = torch.as_tensor([int(r["predicate"]) for r in batch_rows],
                                           dtype=torch.long, device="cuda:0")
                logits = model(a) if task == "node_type" or representation in ("row", "first_token") else model(a, b, pred)
            elif task == "node_type" or representation in ("row", "first_token"):
                xb = feature_vectors(batch_rows, task, surface, arrays, row_arrays,
                                     scalers, representation, source_surface)
                a = torch.from_numpy(np.ascontiguousarray(xb)).to("cuda:0")
                logits = model(a)
            else:
                av, bv = feature_vectors(batch_rows, task, surface, arrays, row_arrays, scalers)
                a = torch.from_numpy(np.ascontiguousarray(av)).to("cuda:0")
                b = torch.from_numpy(np.ascontiguousarray(bv)).to("cuda:0")
                pred = None
                if task == "link_completion":
                    pred = torch.as_tensor([int(r["predicate"]) for r in batch_rows],
                                           dtype=torch.long, device="cuda:0")
                logits = model(a, b, pred)
            y = torch.as_tensor(labels[ids], dtype=torch.long, device="cuda:0")
            if task == "link_completion":
                loss = F.binary_cross_entropy_with_logits(logits.reshape(-1), y.float())
            else:
                loss = F.cross_entropy(logits, y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            running += float(loss.detach()) * len(ids)
            seen += len(ids)
        losses.append(running / max(1, seen))
    model.eval()
    return model, {"epochs": EPOCHS, "batch_size": BATCH, "learning_rate": LR,
                   "weight_decay": WEIGHT_DECAY, "losses": losses,
                   "fit_seconds": time.perf_counter() - start_time,
                   "parameters": sum(p.numel() for p in model.parameters())}


def lexical_control_predictions(records, task, counts_by_key, global_counts):
    classes = len(global_counts)
    outputs = np.zeros((len(records), classes), dtype=np.float32)
    for i, row in enumerate(records):
        if task == "node_type":
            mode = counts_by_key.get("mode")
            label = row.get("lex_type") if mode == "lex" else row.get("id_type")
            if label in ENTITY_TYPES:
                outputs[i, ENTITY_TYPES.index(label)] = 1.0
            else:
                outputs[i] = global_counts
            continue
        key_type = "id_type" if counts_by_key.get("mode") == "id" else "lex"
        if task == "link_completion":
            # Query-ranking control is evaluated by link_control_metrics.
            outputs[i] = global_counts
            continue
        key = ((row.get(f"{key_type}_a"), row.get(f"{key_type}_b")))
        table = counts_by_key.get("table", {})
        outputs[i] = table.get(key, global_counts)
    return outputs


def train_frequency_tables(train_records, task, classes):
    global_counts = np.ones(classes, dtype=np.float64)
    lexical = defaultdict(lambda: np.ones(classes, dtype=np.float64))
    identifiers = defaultdict(lambda: np.ones(classes, dtype=np.float64))
    for row in train_records:
        label = int(row.get("label", 0))
        global_counts[label] += 1
        if task == "node_type":
            lexical[(row.get("lex_type"),)][label] += 1
            identifiers[(row.get("id_type"),)][label] += 1
        elif task != "link_completion":
            lexical[(row.get("lex_a"), row.get("lex_b"))][label] += 1
            identifiers[(row.get("id_type_a"), row.get("id_type_b"))][label] += 1
    return global_counts, {"mode": "lex", "table": dict(lexical)}, {"mode": "id", "table": dict(identifiers)}


def link_control_table(train_records, mode):
    table = Counter()
    for row in train_records:
        label = int(row.get("label", 0))
        if label != 1:
            continue
        candidate_type = row.get("id_type_b") if mode == "id" else row.get("lex_b")
        subject_type = row.get("id_type_a") if mode == "id" else row.get("lex_a")
        table[(int(row["predicate"]), subject_type, candidate_type)] += 1
    return table


def link_control_metrics(records, table, mode):
    ranks = []
    candidate_counts = []
    families = defaultdict(lambda: ([], []))
    for query in records:
        candidates, lexical_types, identifier_types = candidates_with_target(query)
        scores = []
        for i, candidate_type in enumerate(identifier_types if mode == "id" else lexical_types):
            key = (int(query["predicate"]), query["id_type_a" if mode == "id" else "lex_a"], candidate_type)
            scores.append(float(table.get(key, 0)))
        target_pos = candidates.index(int(query["target_idx"]))
        rank = matrix_rank(np.asarray(scores), target_pos)
        ranks.append(rank)
        candidate_counts.append(len(scores))
        family_ranks, family_sizes = families[str(query.get("family", "UNKNOWN"))]
        family_ranks.append(rank)
        family_sizes.append(len(scores))
    result = link_metrics(ranks, candidate_counts)
    result["by_renderer"] = {family: link_metrics(values[0], values[1])
                             for family, values in families.items()}
    return result


def score_link(torch, model, records, surface, arrays, row_arrays, scalers, batch_candidates=256):
    ranks, sizes = [], []
    families = defaultdict(lambda: ([], []))
    for query in records:
        cand, _, _ = candidates_with_target(query)
        target_pos = cand.index(int(query["target_idx"]))
        all_scores = []
        subject = int(query["a_idx"])
        relation = int(query["predicate"])
        for start in range(0, len(cand), batch_candidates):
            block = cand[start:start + batch_candidates]
            rows = [{"a_idx": subject, "b_idx": x, "predicate": relation} for x in block]
            av, bv = feature_vectors(rows, "link_completion", surface, arrays, row_arrays, scalers)
            a = torch.from_numpy(np.ascontiguousarray(av)).to("cuda:0")
            b = torch.from_numpy(np.ascontiguousarray(bv)).to("cuda:0")
            pred = torch.full((len(block),), relation, dtype=torch.long, device="cuda:0")
            with torch.inference_mode():
                score = model(a, b, pred).reshape(-1).detach().cpu().numpy()
            all_scores.extend(score.tolist())
        rank = matrix_rank(np.asarray(all_scores, dtype=np.float32), target_pos)
        ranks.append(rank)
        sizes.append(len(cand))
        family_ranks, family_sizes = families[str(query.get("family", "UNKNOWN"))]
        family_ranks.append(rank)
        family_sizes.append(len(cand))
    result = link_metrics(ranks, sizes)
    result["by_renderer"] = {family: link_metrics(values[0], values[1])
                             for family, values in families.items()}
    return result


def evaluate_classifier(torch, model, task, surface, path, arrays, row_arrays,
                        scalers, representation="local", source_surface=None, chunk=2048):
    truths, scores, family_codes, kind_codes = [], [], [], []
    family_to_code = {}
    kind_to_code = {}
    pending = []
    def flush():
        if not pending:
            return
        batch = pending.copy()
        logits = model_logits(torch, model, batch, task, surface, arrays, row_arrays,
                              scalers, representation, source_surface)
        truths.extend(int(r["label"]) for r in batch)
        scores.append(logits)
        family_codes.extend(family_to_code.setdefault(str(r.get("family", "UNKNOWN")),
                                                        len(family_to_code)) for r in batch)
        kind_codes.extend(kind_to_code.setdefault(str(r.get("feature_kind", "")),
                                                   len(kind_to_code)) for r in batch)
        pending.clear()
    for row in read_jsonl(path):
        pending.append(row)
        if len(pending) >= chunk:
            flush()
    flush()
    if not truths:
        return {"n": 0}
    y = np.asarray(truths, dtype=np.int64)
    logits = np.concatenate(scores, axis=0)
    classes = output_count(task)
    result = classification_metrics(y, logits, classes)
    family_array = np.asarray(family_codes, dtype=np.int16)
    result["by_renderer"] = {
        name: classification_metrics(y[family_array == code], logits[family_array == code], classes)
        for name, code in family_to_code.items()}
    if task == "node_type":
        kind_array = np.asarray(kind_codes, dtype=np.int8)
        result["by_feature_kind"] = {
            name: classification_metrics(y[kind_array == code], logits[kind_array == code], classes)
            for name, code in kind_to_code.items() if name}
    return result


def evaluate_task_model(torch, model, task, surface, output_dir, arrays,
                        row_arrays, scalers, representation="local", source_surface=None,
                        split_names=None):
    evaluations = {}
    splits = split_names or ("DEV", *[s for s in WORLD_SPLITS if s.startswith("TEST")])
    for split in splits:
        path = output_dir / "task-examples" / task / f"{split}.jsonl"
        if task == "link_completion":
            evaluations[split] = score_link(torch, model, read_jsonl(path), surface, arrays,
                                            row_arrays, scalers)
        else:
            evaluations[split] = evaluate_classifier(torch, model, task, surface, path,
                arrays, row_arrays, scalers, representation, source_surface)
        metric_name = "mrr" if task == "link_completion" else (
            "roc_auc" if task in ("edge_existence", "one_hop_membership", "two_hop_membership")
            else "macro_f1")
        print(json.dumps({"phase": "split_scored", "task": task, "surface": surface,
                          "split": split, "metric": metric_name,
                          "value": evaluations[split].get(metric_name)}), flush=True)
    return evaluations


def load_saved_head(torch, path, task, head, dim, representation="local"):
    builder_task = task if representation == "local" else "node_type"
    model = build_head(torch, builder_task, head, dim, output_count(task))
    checkpoint = torch.load(path, map_location="cuda:0", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model


def saved_result_valid(record):
    path = Path(record.get("model_path", ""))
    return path.is_file() and sha256(path) == record.get("model_sha256")


def load_rung0_primitives(r0_output: Path, extraction_receipt: dict):
    seal_path = r0_output / "features" / "extraction-seal.json"
    if sha256(seal_path) != extraction_receipt["source"]["r0_feature_seal_sha256"]:
        raise RuntimeError("Rung-0 feature seal changed after local extraction")
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    primitives = {}
    for name in ("final_token", "full_mean", "first_token", "layer_m4_final", "middle_final"):
        path = r0_output / "features" / f"{name}.npy"
        spec = seal["primitives"][name]
        if sha256(path) != spec["sha256"]:
            raise RuntimeError(f"Rung-0 primitive changed: {name}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(array.shape) != spec["shape"] or array.dtype != np.dtype("<f4"):
            raise RuntimeError(f"invalid Rung-0 primitive: {name}")
        primitives[name] = array
    return primitives


def load_local_features(output: Path, receipt: dict):
    groups = {"entity": {}, "goal": {}}
    for name in ("final_mean", "final_last", "middle_mean", "m4_mean"):
        for group in groups:
            key = f"{group}_{name}"
            spec = receipt["features"][key]
            path = output / "features" / f"{key}.npy"
            if sha256(path) != spec["sha256"]:
                raise RuntimeError(f"local feature hash mismatch: {key}")
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            if list(array.shape) != spec["shape"] or array.dtype != np.dtype("<f2"):
                raise RuntimeError(f"invalid local feature file: {key}")
            groups[group][name] = array
    return groups


def train_indexes(output: Path, rowmap_path: Path):
    train_rows = []
    with rowmap_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["split"] == "TRAIN" and row.get("paired_world") is None:
                train_rows.append(int(row["idx"]))
    entity_indexes, goal_indexes = [], []
    for row in read_jsonl(output / "row-mentions.jsonl"):
        if row["split"] != "TRAIN" or row.get("paired_world") is not None:
            continue
        entity_indexes.extend(int(x["entity_index"]) for x in row["mentions"] if x.get("matched"))
        goal_indexes.extend(int(x["goal_index"]) for x in row["goals"] if x.get("matched"))
    return (np.asarray(train_rows, dtype=np.int64),
            np.asarray(entity_indexes, dtype=np.int64),
            np.asarray(goal_indexes, dtype=np.int64))


def prepare_control_state(task, train_records, classes):
    if task == "link_completion":
        return {"lexical": link_control_table(train_records, "lex"),
                "identifier": link_control_table(train_records, "id")}
    global_counts, lexical, identifiers = train_frequency_tables(train_records, task, classes)
    return {"global_counts": global_counts, "lexical": lexical, "identifier": identifiers}


def controls_for_split(task, train_records, path, state):
    classes = output_count(task)
    if task == "link_completion":
        queries = list(read_jsonl(path))
        return {"random_rank": random_link_metrics(queries),
                "lexical_frequency": link_control_metrics(queries, state["lexical"], "lex"),
                "id_frequency": link_control_metrics(queries, state["identifier"], "id")}
    rows = list(read_jsonl(path))
    if not rows:
        return {"n": 0}
    y = labels_from(rows)
    global_counts = state["global_counts"]
    outputs = {}
    for name, table in (("frequency", {"mode": "lex", "table": {}}),
                        ("lexical", state["lexical"]),
                        ("identifier", state["identifier"])):
        if name == "frequency":
            scores = np.tile(global_counts.astype(np.float32), (len(rows), 1))
        else:
            scores = lexical_control_predictions(rows, task, table, global_counts)
        outputs[name] = metric_bundle(y, scores, classes, rows)
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--r0-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    receipt = json.loads((out / "features" / "extraction-seal.json").read_text(encoding="utf-8"))
    graph_data_report = json.loads((out / "graph-task-data-report.json").read_text(encoding="utf-8"))
    if graph_data_report.get("extraction_seal_sha256") != sha256(out / "features" / "extraction-seal.json"):
        raise RuntimeError("graph targets are not bound to the current extraction seal")
    if receipt.get("truth_joined") is not False:
        raise RuntimeError("backbone extraction was not label-blind")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 required for readout fitting")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True

    local_arrays = load_local_features(out, receipt)
    row_arrays = load_rung0_primitives(args.r0_output, receipt)
    train_rows, entity_ids, goal_ids = train_indexes(out, out / "rowmap.jsonl")
    scaler_dir = out / "scalers"
    scaler_dir.mkdir(exist_ok=True)
    scaler_code = (calculate_node_scaler, calculate_row_scaler, make_scalers)
    basis = scaler_basis(out, receipt, graph_data_report, train_rows, entity_ids,
                         goal_ids, scaler_code)
    scalers, scaler_seal_sha = load_scaler_cache(scaler_dir, basis, SURFACES)
    if scalers is None:
        scalers = make_scalers(local_arrays, row_arrays, train_rows, entity_ids,
                               goal_ids, SURFACES)
        scaler_seal_sha = seal_scalers(scaler_dir, basis, scalers, SURFACES)
        print(json.dumps({"phase": "scalers_fitted", "seal_sha256": scaler_seal_sha}), flush=True)
    else:
        print(json.dumps({"phase": "scaler_cache_verified", "seal_sha256": scaler_seal_sha}), flush=True)

    result = {"schema": "phoenix.bank-v1-graph-readouts/v2", "run_id": "BANK-v1-GRAPH-SURFACE-V2-2026-09-29",
              "extraction_seal_sha256": sha256(out / "features" / "extraction-seal.json"),
              "graph_task_data_sha256": sha256(out / "graph-task-data-report.json"),
              "extractor_script_sha256": sha256(Path(__file__).with_name("extract_local.py")),
              "readout_script_sha256": sha256(Path(__file__)),
              "metrics_script_sha256": sha256(Path(__file__).with_name("graph_metrics.py")),
              "spec_sha256": sha256(Path(__file__).with_name("spec.json")),
              "scaler_seal_sha256": scaler_seal_sha,
              "normalization": "mean/std fit on matched canonical TRAIN entity and goal mention vectors for local views and canonical TRAIN row vectors for whole-row controls",
              "training": {"epochs": EPOCHS, "batch_size": BATCH, "learning_rate": LR,
                           "weight_decay": WEIGHT_DECAY, "train_cap_per_task": graph_data_report["train_cap_per_task"]},
              "runtime": {"torch": torch.__version__, "numpy": np.__version__,
                          "device": torch.cuda.get_device_name("cuda:0")},
              "models": {}, "controls": {}, "task_summary": {}, "gate": {"status": "SCORING_IN_PROGRESS"}}
    partial_path = out / "graph-readout-results.partial.json"
    if partial_path.is_file():
        prior = json.loads(partial_path.read_text(encoding="utf-8"))
        for key in ("extraction_seal_sha256", "graph_task_data_sha256", "scaler_seal_sha256", "spec_sha256"):
            if prior.get(key) != result[key]:
                raise RuntimeError(f"partial readout identity mismatch: {key}")
        result.update({key: prior.get(key, value) for key, value in result.items()})
        result["readout_script_sha256"] = sha256(Path(__file__))
        print(json.dumps({"phase": "resume_partial", "tasks": list(result["models"])}), flush=True)
    models_dir = out / "models"
    models_dir.mkdir(exist_ok=True)
    splits = ("DEV", *[x for x in WORLD_SPLITS if x.startswith("TEST")])
    started = time.perf_counter()
    for task_index, task in enumerate(TASKS):
        train_path = out / "task-examples" / task / "TRAIN.jsonl"
        train_records = load_records(train_path)
        if not train_records:
            raise RuntimeError(f"no training examples for {task}")
        locality_key = "feature_idx" if task == "node_type" else "row_idx"
        train_records.sort(key=lambda row: int(row[locality_key]))
        classes = output_count(task)
        result["controls"].setdefault(task, {})
        control_state = prepare_control_state(task, train_records, classes)
        for split in splits:
            if split in result["controls"][task]:
                continue
            path = out / "task-examples" / task / f"{split}.jsonl"
            result["controls"][task][split] = controls_for_split(
                task, train_records, path, control_state)
            print(json.dumps({"phase": "controls_scored", "task": task, "split": split}), flush=True)
        result["models"].setdefault(task, {})
        for surface_index, surface in enumerate(SURFACES):
            result["models"][task].setdefault(surface, {})
            missing_heads = [head for head in HEADS if head not in result["models"][task][surface]]
            for head in HEADS:
                if head in result["models"][task][surface] and not saved_result_valid(result["models"][task][surface][head]):
                    raise RuntimeError(f"saved model receipt failed validation: {task}/{surface}/{head}")
            if not missing_heads:
                continue
            print(json.dumps({"phase": "training_features_started", "task": task,
                              "surface": surface, "rows": len(train_records)}), flush=True)
            cached_features = feature_vectors(train_records, task, surface, local_arrays,
                                              row_arrays, scalers)
            print(json.dumps({"phase": "training_features_ready", "task": task,
                              "surface": surface}), flush=True)
            for head_index, head in enumerate(missing_heads):
                seed = SEED + task_index * 1009 + surface_index * 97 + head_index * 13
                print(json.dumps({"phase": "model_started", "task": task,
                                  "surface": surface, "head": head}), flush=True)
                model, fit_receipt = fit_model(torch, train_records, task, surface, head,
                    local_arrays, row_arrays, scalers, seed,
                    precomputed_features=cached_features)
                model_path = models_dir / f"{task}-{surface}-{head}.pt"
                torch.save({"task": task, "surface": surface, "head": head, "seed": seed,
                            "state_dict": model.state_dict()}, model_path)
                evaluations = evaluate_task_model(torch, model, task, surface, out,
                    local_arrays, row_arrays, scalers, split_names=("DEV",))
                model_key = f"{task}/{surface}/{head}"
                result["models"][task][surface][head] = {
                    **fit_receipt, "model_path": str(model_path.resolve()),
                    "model_sha256": sha256(model_path), "evaluations": evaluations}
                print(json.dumps({"phase": "model_complete", "task": task, "surface": surface,
                                  "head": head, "dev": evaluations.get("DEV")}), flush=True)
                # Persist after each fitted candidate so a long run is inspectable.
                result["elapsed_seconds"] = time.perf_counter() - started
                write_json(out / "graph-readout-results.partial.json", result)
                del model
            del cached_features
        if task != "link_completion":
            result["models"][task].setdefault("whole_row_controls", {})
            for source_surface in (*SURFACES, "first_token"):
                if source_surface in result["models"][task]["whole_row_controls"]:
                    if not saved_result_valid(result["models"][task]["whole_row_controls"][source_surface]):
                        raise RuntimeError(f"saved row model receipt failed validation: {task}/{source_surface}")
                    continue
                seed = SEED + task_index * 2003 + (113 if source_surface == "first_token" else SURFACES.index(source_surface))
                representation = "first_token" if source_surface == "first_token" else "row"
                cached_features = feature_vectors(train_records, task, source_surface,
                    local_arrays, row_arrays, scalers, representation=representation,
                    source_surface=source_surface)
                model, fit_receipt = fit_model(torch, train_records, task, source_surface, "linear",
                    local_arrays, row_arrays, scalers, seed,
                    representation=representation, source_surface=source_surface,
                    precomputed_features=cached_features)
                model_path = models_dir / f"{task}-{source_surface}-whole_row_linear.pt"
                torch.save({"task": task, "representation": source_surface,
                            "head": "whole_row_linear", "seed": seed,
                            "state_dict": model.state_dict()}, model_path)
                evaluations = evaluate_task_model(torch, model, task, source_surface, out,
                    local_arrays, row_arrays, scalers,
                    representation="first_token" if source_surface == "first_token" else "row",
                    source_surface=source_surface, split_names=("DEV",))
                result["models"].setdefault(task, {}).setdefault("whole_row_controls", {})[source_surface] = {
                    **fit_receipt, "model_path": str(model_path.resolve()),
                    "model_sha256": sha256(model_path), "evaluations": evaluations}
                del model
                del cached_features
                write_json(out / "graph-readout-results.partial.json", result)
        write_json(out / "graph-readout-results.partial.json", result)

    test_splits = tuple(s for s in splits if s.startswith("TEST"))
    selected = {}
    for task in TASKS:
        metric = "mrr" if task == "link_completion" else ("roc_auc" if task in (
            "edge_existence", "one_hop_membership", "two_hop_membership") else "macro_f1")
        local_candidates = [(record["evaluations"].get("DEV", {}).get(metric), surface, head, record)
                            for surface in SURFACES for head, record in
                            result["models"][task][surface].items()]
        local_candidates = [row for row in local_candidates if row[0] is not None]
        row_candidates = []
        if task != "link_completion":
            row_candidates = [(record["evaluations"].get("DEV", {}).get(metric), surface, record)
                              for surface, record in
                              result["models"][task]["whole_row_controls"].items()
                              if surface in SURFACES]
            row_candidates = [row for row in row_candidates if row[0] is not None]
        if not local_candidates:
            raise RuntimeError(f"no local DEV candidate for {task}")
        local_score, local_surface, local_head, local_record = max(local_candidates, key=lambda x: x[0])
        dim = len(scalers["local"][local_surface][0])
        model = load_saved_head(torch, local_record["model_path"], task, local_head, dim)
        held = evaluate_task_model(torch, model, task, local_surface, out,
            local_arrays, row_arrays, scalers, split_names=test_splits)
        local_record["evaluations"].update(held)
        del model
        selected[task] = {"local": {"surface": local_surface, "head": local_head,
                                      "dev_metric": local_score}}
        if row_candidates:
            row_score, row_surface, row_record = max(row_candidates, key=lambda x: x[0])
            dim = len(scalers["row"][row_surface][0])
            model = load_saved_head(torch, row_record["model_path"], task,
                                    "linear", dim, representation="row")
            held = evaluate_task_model(torch, model, task, row_surface, out,
                local_arrays, row_arrays, scalers, representation="row",
                source_surface=row_surface, split_names=test_splits)
            row_record["evaluations"].update(held)
            del model
            selected[task]["whole_row"] = {"surface": row_surface, "head": "linear",
                                             "dev_metric": row_score}
        result["selected_by_dev"] = selected
        write_json(out / "graph-readout-results.partial.json", result)

    summaries = {}
    for task in TASKS:
        metric = "mrr" if task == "link_completion" else ("roc_auc" if task in (
            "edge_existence", "one_hop_membership", "two_hop_membership") else "macro_f1")
        chosen = selected[task]["local"]
        best = result["models"][task][chosen["surface"]][chosen["head"]]
        test_values = {k: v for k, v in best["evaluations"].items() if k.startswith("TEST-")}
        all_score = aggregate_over_splits(test_values, metric)
        held = aggregate_renderer(test_values, metric, held_out=True)
        in_family = aggregate_renderer(test_values, metric, held_out=False)
        row_result = None
        if "whole_row" in selected[task]:
            row_choice = selected[task]["whole_row"]
            row_result = result["models"][task]["whole_row_controls"][row_choice["surface"]]
            row_tests = {k: v for k, v in row_result["evaluations"].items() if k.startswith("TEST-")}
            row_result = {"surface": row_choice["surface"],
                          "test_metric": aggregate_over_splits(row_tests, metric),
                          "held_renderer_metric": aggregate_renderer(row_tests, metric, held_out=True),
                          "in_family_metric": aggregate_renderer(row_tests, metric, held_out=False)}
        controls = result["controls"][task]
        control_names = (("random_rank", "lexical_frequency", "id_frequency")
                         if task == "link_completion" else ("frequency", "lexical", "identifier"))
        control_avg = {name: controls.get("DEV", {}).get(name, {}).get(metric)
                       for name in control_names}
        control_avg = {name: value for name, value in control_avg.items() if value is not None}
        best_control_name, best_control_score = (
            max(control_avg.items(), key=lambda item: item[1]) if control_avg else (None, None))
        control_test = aggregate_control_splits(controls, best_control_name, metric) if best_control_name else None
        held_control_score = aggregate_control_renderer(controls, best_control_name, metric,
                                                        held_out=True) if best_control_name else None
        margin = all_score - control_test if all_score is not None and control_test is not None else None
        renderer_margin = held - held_control_score if held is not None and held_control_score is not None else None
        summaries[task] = {"metric": metric, "selection_split": "DEV",
                           "best_model": f"{chosen['surface']}/{chosen['head']}",
                           "selected_dev_metric": chosen["dev_metric"],
                           "test_metric": all_score, "held_renderer_metric": held,
                           "in_family_metric": in_family,
                           "whole_row_control": row_result,
                           "best_control": best_control_name,
                           "dev_control_metric": best_control_score,
                           "test_control_metric": control_test,
                           "held_renderer_control_metric": held_control_score,
                           "test_margin_over_control": margin,
                           "held_renderer_margin_over_control": renderer_margin,
                           "renderer_drop": in_family - held if in_family is not None and held is not None else None}
    eligible = [v for v in summaries.values() if v["test_margin_over_control"] is not None
                and v["held_renderer_margin_over_control"] is not None]
    passed = any(v["test_margin_over_control"] >= 0.05
                 and v["held_renderer_margin_over_control"] > 0.0
                 and (v["renderer_drop"] is None or v["renderer_drop"] <= 0.10)
                 for v in eligible)
    result["task_summary"] = summaries
    result["gate"] = {"status": "PASS" if passed else "FAIL_STOP_GRAPH_LANE",
                      "rule": "at least one graph-local task +0.05 over best lexical/frequency control, positive S7/S8/S9 advantage, and <=0.10 in-family to held-renderer drop",
                      "passing_tasks": [name for name, value in summaries.items()
                                        if value["test_margin_over_control"] is not None
                                        and value["test_margin_over_control"] >= 0.05
                                        and value["held_renderer_margin_over_control"] is not None
                                        and value["held_renderer_margin_over_control"] > 0.0
                                        and (value["renderer_drop"] is None or value["renderer_drop"] <= 0.10)]}
    result["elapsed_seconds"] = time.perf_counter() - started
    write_json(out / "graph-readout-results.json", result)
    (out / "graph-readout-results.partial.json").unlink(missing_ok=True)
    write_report(out / "RESULTS.md", result)
    print(json.dumps({"phase": "fit_complete", "gate": result["gate"],
                      "task_summary": result["task_summary"],
                      "elapsed_seconds": result["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    import os
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    main()
