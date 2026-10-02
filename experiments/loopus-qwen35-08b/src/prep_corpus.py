"""Build the experiment corpora.

* WikiText-103 parquet shards -> article-level jsonl. Articles start at a level-1 heading line
  (" = Title = "). Official train/validation/test are disjoint articles, so held-out evaluation
  never shares a document with training.
* BANK-v1 TRAIN input_text -> jsonl, with a world_hash-disjoint held-out slice. DEV and the
  protected split are never read.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1] / "corpus" / "wikitext-103-raw-v1"
H1 = re.compile(r"^ = [^=].* = $")
BANK_TRAIN = Path(r"C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1\inputs\TRAIN.jsonl")


def articles(parquet_path: Path):
    lines = pq.read_table(parquet_path).column("text").to_pylist()
    cur: list[str] = []
    for ln in lines:
        if H1.match(ln.rstrip("\n")) and cur:
            yield "".join(cur)
            cur = []
        cur.append(ln)
    if cur:
        yield "".join(cur)


def prep_bank(max_rows: int = 60000):
    """Held-out = 1 in 20 by world_hash, so no generated world straddles the split."""
    tr = ROOT.parent / "bank_train.jsonl"
    va = ROOT.parent / "bank_val.jsonl"
    n_tr = n_va = 0
    with BANK_TRAIN.open(encoding="utf-8") as src, tr.open("w", encoding="utf-8") as ftr, \
            va.open("w", encoding="utf-8") as fva:
        for line in src:
            if n_tr + n_va >= max_rows:
                break
            r = json.loads(line)
            held = int(r["world_hash"][:8], 16) % 20 == 0
            (fva if held else ftr).write(json.dumps({"text": r["input_text"]}) + "\n")
            n_va += held
            n_tr += not held
    print(f"bank: train {n_tr} rows, val {n_va} rows (world_hash-disjoint)")


def main():
    jobs = {"wiki_train": "train-00000-of-00002.parquet", "wiki_val": "validation-00000-of-00001.parquet",
            "wiki_test": "test-00000-of-00001.parquet"}
    for name, fn in jobs.items():
        out = ROOT.parent / f"{name}.jsonl"
        n = chars = 0
        with out.open("w", encoding="utf-8") as fh:
            for a in articles(ROOT / fn):
                a = a.strip()
                if len(a) < 200:
                    continue
                fh.write(json.dumps({"text": a}) + "\n")
                n += 1
                chars += len(a)
        print(f"{name}: {n} articles, {chars/1e6:.1f}M chars -> {out.name}")
    prep_bank()


if __name__ == "__main__":
    sys.exit(main())
