"""Extract and cache V2-0 features and targets from the sealed BANK-v2 rows.

Two products:
  * dense: B2, B4 (text length decile edges fit on TRAIN only), B5, plus the six targets
  * sparse: B3 hashed 1-2 gram tf counts, with document frequency accumulated for TRAIN

Run:  python cache_features.py dev
      python cache_features.py train
"""

import glob
import gzip
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import read_targets, b2_features, b4_features, b5_features, b3_sparse

BANK = r"C:\code land\clean-rust\experiments\ff-s15-bank-02\out\full\data"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
TARGETS = ["disposition", "reason", "missing_cardinality", "requestability",
           "first_action_type", "conflict"]
# strata keys carried per row for reporting
STRATA = ["action_type", "reason", "query_slot", "m_card", "renderer_family"]


def iter_split(split):
    for fp in sorted(glob.glob(os.path.join(BANK, split, "part-*.jsonl.gz"))):
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                yield json.loads(line)


def row_strata(rec, t):
    """Stratum labels for reporting. Derived from the record, never from a target the baselines see."""
    WT = rec["WORLD_TRUTH"]
    T = rec["TARGETS"]
    mi = T["missing_information"]
    w = mi.get("witness") or {}
    unresolved = w.get("unresolved") or []
    slot = unresolved[0].get("slot") if unresolved else "NONE"
    if t["disposition"] == "EXECUTE":
        aid = T["executed_action"]["value"]
        by_id = {a.get("id"): a.get("type")
                 for a in rec["ACTION_POLICY"].get("available_actions", [])}
        atype = by_id.get(aid, "UNRESOLVED")
    else:
        atype = "NA"
    return [atype, str(t["reason"]), str(slot), t["missing_cardinality"],
            rec["OBSERVATION"].get("renderer_family_id") or "?"]


def main():
    which = sys.argv[1]
    os.makedirs(CACHE, exist_ok=True)

    b2, b4raw, b5, tg, st = [], [], [], {k: [] for k in TARGETS}, {k: [] for k in STRATA}
    lengths = []
    indptr = [0]
    # packed int32 rather than a Python list: TRAIN projects to ~125M non-zeros, and a list of
    # Python ints would need several GB before any training starts.
    from array import array
    indices = array("i")
    n = 0

    for rec in iter_split(which):
        t = read_targets(rec)
        b2.append(b2_features(rec))
        b5.append(b5_features(rec))
        txt = rec["OBSERVATION"].get("rendered_text") or ""
        lengths.append(len(txt))
        b4raw.append(b4_features(rec, None))          # raw length, decile applied later
        for k in TARGETS:
            tg[k].append(t[k])
        st["action_type"].append(row_strata(rec, t)[0])
        st["reason"].append(row_strata(rec, t)[1])
        st["query_slot"].append(row_strata(rec, t)[2])
        st["m_card"].append(row_strata(rec, t)[3])
        st["renderer_family"].append(row_strata(rec, t)[4])
        tf = b3_sparse(rec)
        for k in sorted(tf):
            indices.append(k)
        indptr.append(len(indices))
        n += 1
        if n % 20000 == 0:
            print(f"  {which}: {n} rows, nnz={len(indices)}", flush=True)

    b2 = np.asarray(b2, dtype=np.float32)
    b4raw = np.asarray(b4raw, dtype=np.float32)
    b5 = np.asarray(b5, dtype=np.float32)
    lengths = np.asarray(lengths, dtype=np.int32)

    np.save(os.path.join(CACHE, f"{which}_b2.npy"), b2)
    np.save(os.path.join(CACHE, f"{which}_b4raw.npy"), b4raw)
    np.save(os.path.join(CACHE, f"{which}_b5.npy"), b5)
    np.save(os.path.join(CACHE, f"{which}_lengths.npy"), lengths)
    for k in TARGETS:
        np.save(os.path.join(CACHE, f"{which}_t_{k}.npy"), np.asarray(tg[k], dtype=object), allow_pickle=True)
    for k in STRATA:
        np.save(os.path.join(CACHE, f"{which}_s_{k}.npy"), np.asarray(st[k], dtype=object), allow_pickle=True)
    np.save(os.path.join(CACHE, f"{which}_b3_indptr.npy"), np.asarray(indptr, dtype=np.int64))
    np.save(os.path.join(CACHE, f"{which}_b3_indices.npy"), np.asarray(indices, dtype=np.int32))

    print(f"{which}: rows={n} b2={b2.shape} b4raw={b4raw.shape} b5={b5.shape} nnz={len(indices)}")
    # TRAIN-only document frequency over the hashed buckets
    if which == "train":
        df = np.bincount(np.asarray(indices, dtype=np.int64), minlength=1 << 18).astype(np.float64)
        np.save(os.path.join(CACHE, "train_b3_df.npy"), df)
        print(f"train: distinct buckets used = {(df > 0).sum()} of {1 << 18}")


if __name__ == "__main__":
    main()
