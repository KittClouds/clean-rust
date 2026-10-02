"""Fit and freeze per-surface normalisation statistics on TRAIN ONLY.

The user-facing requirement, audited before any science: every normalisation statistic must be
fitted from TRAIN and then frozen for DEV. That audit FAILED on the first implementation, which
standardised each surface by its own batch mean and std. Two consequences: DEV information
entered the DEV representation, and the cache depended on batch composition, so replay was not
reproducible. This module fixes that properly.

Procedure:
  * read the TRAIN cache only. This module never opens a DEV file, and says so in the receipt;
  * restrict to CANONICAL rows, since paired renderer rows are the same world twice and would
    double-weight them in the statistics;
  * record the RAW per-surface scale as permanent substrate metadata. MiniCPM's hidden scale
    varies ~6x with depth, so raw magnitudes are never comparable across surfaces and are kept
    only as documentation;
  * freeze mean/std to a file that src/data.py loads for every split.

Determinism: statistics are computed in float64 from fp16 inputs and rounded to float32 on
write, so re-running produces bit-identical statistics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

PRIM = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm\primitives")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="TRAIN")
    ap.add_argument("--suffix", default="-full")
    args = ap.parse_args()
    if args.split != "TRAIN":
        raise SystemExit("surface statistics may only be fitted on TRAIN")

    src = PRIM / f"{args.split}{args.suffix}.pt"
    prim = torch.load(src, map_location="cpu", weights_only=False)
    canonical = [i for i, w in enumerate(prim["row_ids"]) if "@" not in w]

    stats, raw_meta = {}, {}
    for name, t in prim["surfaces"].items():
        v = t[canonical].double()                      # [n, H]
        mu = v.mean(0)
        sd = v.std(0, unbiased=False).clamp(min=1e-6)
        stats[name] = {"mean": mu.float(), "std": sd.float()}
        raw_meta[name] = {
            "raw_mean": round(float(v.mean()), 6),
            "raw_std": round(float(v.std(unbiased=False)), 6),
            "raw_std_over_final_layer": None,
            "canonical_rows_used": len(canonical),
            "hidden": int(v.shape[1]),
        }
    # raw scale relative to the final-depth surface, which is the substrate property that made
    # per-surface standardisation mandatory rather than cosmetic
    ref = raw_meta["mf@24"]["raw_std"]
    for k in raw_meta:
        raw_meta[k]["raw_std_over_final_layer"] = round(raw_meta[k]["raw_std"] / ref, 4)

    out = PRIM / "surface-stats.pt"
    torch.save({"stats": stats, "fitted_on": "TRAIN", "suffix": args.suffix,
                "canonical_rows": len(canonical), "source_sha256": sha_file(src)}, out)

    rec = {
        "abi": "s15-lepori-minicpm/surface-stats-v0.1",
        "status": "FROZEN",
        "fitted_on_split": "TRAIN",
        "dev_files_opened_by_this_module": [],
        "rows_used": len(canonical),
        "row_selection": "canonical rows only; paired renderer rows excluded so a world is not "
                         "double-weighted in the statistics",
        "source_cache": str(src), "source_sha256": sha_file(src),
        "applied_to": "every split, by src/data.py, from this one frozen file",
        "precision": "float64 accumulation from fp16 inputs, stored float32",
        "raw_scale_metadata": raw_meta,
        "why_per_surface_standardisation_is_mandatory": {
            "raw_std_by_surface": {k: v["raw_std"] for k, v in raw_meta.items()},
            "max_ratio_to_final": round(max(v["raw_std_over_final_layer"]
                                            for v in raw_meta.values()), 3),
            "consequence": "raw magnitudes are not comparable across surfaces, so a shared "
                           "projector or any unnormalised cross-surface mixing would be "
                           "dominated by whichever surface happens to have the larger scale",
        },
        "supersedes": {
            "bug": "per-batch standardisation in the first extractor",
            "why_it_was_wrong": ["DEV rows were standardised using DEV batch statistics, so DEV "
                                 "information entered the DEV representation",
                                 "statistics depended on batch composition, so the cache was not "
                                 "replayable"],
            "fixed_by": "raw surfaces stored; statistics fitted once on TRAIN and frozen here",
        },
        "file": str(out), "sha256": sha_file(out),
    }
    (OUT / "surface-stats.json").write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({"status": rec["status"], "rows_used": rec["rows_used"],
                      "raw_std_by_surface": rec["why_per_surface_standardisation_is_mandatory"]
                      ["raw_std_by_surface"],
                      "max_ratio_to_final": rec["why_per_surface_standardisation_is_mandatory"]
                      ["max_ratio_to_final"],
                      "written": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
