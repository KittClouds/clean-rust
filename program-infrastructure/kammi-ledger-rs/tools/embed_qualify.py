"""Four-layer qualification of a Phoenix embedding family against an independent reference.

Reference path (shares no code with the Rust runner): Python `tokenizers` on the same
tokenizer.json, Python `onnxruntime` on the same ONNX graph, one input per run (no padding),
pooling and L2 normalisation reimplemented here from the family descriptor.

  1. TOKENIZATION  identical ids, truncation at max_length, special tokens
  2. SEMANTICS     pooling, normalisation, dimension, empty/long/duplicate inputs
  3. NUMERICS      cosine and max-abs error vs reference, batch-vs-single, repeatability
  4. RETRIEVAL     frozen-corpus top-10 membership, order flips outside ties, threshold decisions

Usage: python embed_qualify.py <kammi-embed-dump output.json> [--out report.json]
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

POOLING = {"embeddinggemma-300m": "mean", "jina-embeddings-v5-text-nano-retrieval": "last", "mdbr-leaf-mt": "mean"}
TIE = 1e-3          # score gap below which an order swap is a tie
K = 10
BARS = {
    "tokens_identical": 1.0,
    "norm_error_max": 1e-3,
    "cosine_min": 0.999,
    "cosine_p50": 0.9999,
    "batch_single_cosine_min": 0.9999,
    "repeat_identical": 1.0,
    "top10_identical_fraction": 0.95,
    "top10_overlap_mean": 0.98,
    "order_flips_outside_ties": 0,
    "threshold_flips_outside_ties": 0,
}


def vec(text):
    return np.frombuffer(base64.b64decode(text), dtype="<f4").astype(np.float64)


class Reference:
    def __init__(self, dump):
        root = Path(dump["model_root"])
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(dump["max_length"], strategy="longest_first", direction="right")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(dump["model_path"], options, providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.session.get_inputs()]
        self.outputs = [o.name for o in self.session.get_outputs()]
        unknown = set(self.inputs) - {"input_ids", "attention_mask", "token_type_ids"}
        if unknown:
            raise SystemExit(f"reference cannot feed model inputs {sorted(unknown)}")
        self.pooling = POOLING[dump["family"]]

    def tokens(self, prompt):
        return self.tokenizer.encode(prompt, add_special_tokens=True).ids

    def embed(self, prompt):
        ids = np.array([self.tokens(prompt)], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": np.ones_like(ids)}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        feed = {k: v for k, v in feed.items() if k in self.inputs}
        if "sentence_embedding" in self.outputs:
            pooled = self.session.run(["sentence_embedding"], feed)[0][0].astype(np.float64)
            source = "sentence_embedding"
        else:
            name = "last_hidden_state" if "last_hidden_state" in self.outputs else self.outputs[0]
            hidden = self.session.run([name], feed)[0][0].astype(np.float64)
            pooled = hidden.mean(axis=0) if self.pooling == "mean" else hidden[-1]
            source = f"{name}:{self.pooling}"
        return pooled / max(np.linalg.norm(pooled), 1e-12), source


def cos(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def retrieval(queries, docs_rust, docs_ref, queries_rust, queries_ref):
    sr, sf = queries_rust @ docs_rust.T, queries_ref @ docs_ref.T
    identical = overlap = order_flips = 0
    detail = []
    for q in range(len(queries)):
        tr, tf = list(np.argsort(-sr[q])[:K]), list(np.argsort(-sf[q])[:K])
        common = set(tr) & set(tf)
        identical += set(tr) == set(tf)
        overlap += len(common) / K
        # A swapped pair counts only when the reference separates it by more than TIE.
        flips = 0
        for i in range(K):
            for j in range(i + 1, K):
                a, b = tr[i], tr[j]
                if a in common and b in common and sf[q, b] - sf[q, a] > TIE:
                    flips += 1
        order_flips += flips
        # Membership differences that are not near-ties at the K boundary.
        boundary = sf[q, tf[-1]]
        hard_misses = [int(d) for d in set(tf) - set(tr) if sf[q, d] - boundary > TIE]
        if set(tr) != set(tf) or flips:
            detail.append({"query": queries[q]["id"], "text": queries[q]["text"], "rust_only": sorted(int(x) for x in set(tr) - set(tf)),
                           "reference_only": sorted(int(x) for x in set(tf) - set(tr)), "hard_misses": hard_misses, "order_flips": flips})
    # Threshold decisions at three operating points taken from the reference distribution.
    flat = sf.flatten()
    thresholds = [float(np.quantile(flat, q)) for q in (0.5, 0.9, 0.99)]
    threshold_flips = sum(int(((sr >= t) != (sf >= t))[np.abs(sf - t) > TIE].sum()) for t in thresholds)
    return {"queries": len(queries), "top10_identical_fraction": identical / len(queries), "top10_overlap_mean": overlap / len(queries),
            "order_flips_outside_ties": order_flips, "threshold_flips_outside_ties": threshold_flips,
            "thresholds": thresholds, "differences": detail}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    dump = json.loads(args.dump.read_text(encoding="utf-8"))
    corpus = json.loads((Path(__file__).resolve().parents[1] / "crates/kammi-embed/fixtures/qualification-corpus-v1.json").read_text(encoding="utf-8"))
    ref = Reference(dump)
    sections = dump["sections"]

    token_rows = token_equal = 0
    token_mismatches = []
    cosines, abs_errors, batch_single, norms, repeats = [], [], [], [], []
    vectors = {}
    sources = set()
    for name, section in sections.items():
        for row in section["rows"]:
            ids = ref.tokens(row["prompt"])
            token_rows += 1
            if ids == row["tokens"]:
                token_equal += 1
            else:
                first = next((i for i, (a, b) in enumerate(zip(ids, row["tokens"])) if a != b), min(len(ids), len(row["tokens"])))
                token_mismatches.append({"row": f"{name}/{row['id']}", "first_difference": first, "reference_len": len(ids), "rust_len": len(row["tokens"])})
            rust, single = vec(row["vector"]), vec(row["single"])
            reference, source = ref.embed(row["prompt"])
            sources.add(source)
            vectors[(name, row["id"])] = (rust, reference, single)
            cosines.append(cos(rust, reference))
            abs_errors.append(float(np.abs(rust - reference).max()))
            batch_single.append(cos(rust, single))
            norms.append(abs(float(np.linalg.norm(rust)) - 1.0))
            repeats.append(row["repeat_identical"])

    def by(section, ident):
        return vectors[(section, ident)]
    long_row = next(r for r in sections["edge_cases:document"]["rows"] if r["id"] == "e-long")
    edge = {
        "long_input_tokens": len(long_row["tokens"]),
        "long_input_truncated_to_max_length": len(long_row["tokens"]) == dump["max_length"],
        "empty_input_finite": bool(np.isfinite(by("edge_cases:document", "e-empty")[0]).all()),
        "empty_input_cosine_vs_reference": cos(*by("edge_cases:document", "e-empty")[:2]),
        "duplicate_document_cosine": cos(by("edge_cases:document", "e-dup-a")[0], by("documents:document", corpus["edge_cases"][7]["text"] and "d3")[0]),
        "case_pair_cosine": cos(by("edge_cases:document", "e-case-a")[0], by("edge_cases:document", "e-case-b")[0]),
        "query_vs_document_prompt_cosine": cos(by("edge_cases:query", "e-case-b")[0], by("edge_cases:document", "e-case-b")[0]),
    }
    docs = corpus["documents"]
    queries = corpus["queries"]
    dr = np.stack([by("documents:document", d["id"])[0] for d in docs])
    df = np.stack([by("documents:document", d["id"])[1] for d in docs])
    ds = np.stack([by("documents:document", d["id"])[2] for d in docs])
    qr = np.stack([by("queries:query", q["id"])[0] for q in queries])
    qf = np.stack([by("queries:query", q["id"])[1] for q in queries])
    qs = np.stack([by("queries:query", q["id"])[2] for q in queries])
    layer4 = retrieval(queries, dr, df, qr, qf)
    layer4["batch_vs_single_top10_identical_fraction"] = retrieval(queries, dr, ds, qr, qs)["top10_identical_fraction"]

    cos_arr = np.array(cosines)
    measured = {
        "tokens_identical": token_equal / token_rows,
        "norm_error_max": max(norms),
        "cosine_min": float(cos_arr.min()),
        "cosine_p50": float(np.median(cos_arr)),
        "batch_single_cosine_min": min(batch_single),
        "repeat_identical": sum(repeats) / len(repeats),
        "top10_identical_fraction": layer4["top10_identical_fraction"],
        "top10_overlap_mean": layer4["top10_overlap_mean"],
        "order_flips_outside_ties": layer4["order_flips_outside_ties"],
        "threshold_flips_outside_ties": layer4["threshold_flips_outside_ties"],
    }
    lower_is_better = {"norm_error_max", "order_flips_outside_ties", "threshold_flips_outside_ties"}
    gates = {k: (measured[k] <= BARS[k] if k in lower_is_better else measured[k] >= BARS[k]) for k in BARS}
    edge_ok = edge["long_input_truncated_to_max_length"] and edge["empty_input_finite"] and edge["duplicate_document_cosine"] >= BARS["batch_single_cosine_min"]
    report = {
        "schema": "KAMMI_EMBED_QUALIFICATION_V1",
        "status": "PASS" if all(gates.values()) and edge_ok else "FAIL",
        "family": dump["family"], "identity": dump["identity"], "dims": dump["dims"], "model_path": dump["model_path"],
        "rust_ort": dump.get("ort_dylib"), "reference": {"onnxruntime": ort.__version__, "tokenizers": "python", "pooling_source": sorted(sources)},
        "corpus": {"documents": len(docs), "queries": len(queries), "edge_cases": len(corpus["edge_cases"]), "rows_checked": token_rows},
        "layer1_tokenization": {"identical_fraction": measured["tokens_identical"], "mismatches": token_mismatches[:20]},
        "layer2_semantics": {"dims": dump["dims"], "norm_error_max": measured["norm_error_max"], **edge},
        "layer3_numerics": {"cosine_min": measured["cosine_min"], "cosine_p01": float(np.quantile(cos_arr, 0.01)), "cosine_p50": measured["cosine_p50"],
                            "max_abs_error": max(abs_errors), "batch_single_cosine_min": measured["batch_single_cosine_min"],
                            "repeat_identical_fraction": measured["repeat_identical"]},
        "layer4_retrieval": layer4,
        "bars": BARS, "gates": gates, "edge_gate": edge_ok,
        "throughput_ms": {k: round(v["batch_ms"], 1) for k, v in sections.items()},
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
