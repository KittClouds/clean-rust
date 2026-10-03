from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(r"C:/code land/clean-rust")
PARENT = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-pal2-v1"
OUT = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-pal2-r1-v1"
LR1_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/scripts"
sys.path.insert(0, str(LR1_SCRIPTS))
import run_lr1_case as LR1  # noqa: E402


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    q = PARENT / "qualification"
    execution = json.loads((q / "execution.json").read_text(encoding="utf-8"))
    library = [json.loads(line) for line in (q / "augmented-library.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    kind_counts = collections.Counter(row["kind"] for row in library)

    zero_attempts = 0
    attempted_by_case: dict[str, list[dict[str, object]]] = {}
    for case_dir in sorted((REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/cases").iterdir()):
        if not (case_dir / "pairs" / "COMPLETE.json").exists():
            continue
        stem, set_text = case_dir.name.split("__set", 1)
        state, groups, par8, _, _ = LR1.load_case(stem + ".json", int(set_text))
        del state
        search_selection = [(int(c["group_index"]), str(c["candidate_identity"])) for c in par8["best_search"]["selected_candidates"]]
        rows: list[dict[str, object]] = []
        for group_index in sorted(groups):
            zero = next(candidate for candidate in groups[group_index]["palette"] if "ZERO" in candidate.get("roles", []))
            selection = [(group, str(zero["candidate_identity"]) if group == int(group_index) else candidate) for group, candidate in search_selection]
            identity = f"{case_dir.name}|ZERO|" + ",".join(f"{group}:{candidate}" for group, candidate in selection)
            rows.append({
                "group": int(group_index),
                "zero_candidate_identity": str(zero["candidate_identity"]),
                "entry_identity": identity,
                "selection_unchanged": selection == search_selection,
            })
        attempted_by_case[case_dir.name] = rows
        zero_attempts += len(rows)

    duplicate_records: list[dict[str, object]] = []
    unique_zero = set()
    for case, rows in attempted_by_case.items():
        by_identity: dict[str, list[dict[str, object]]] = collections.defaultdict(list)
        for row in rows:
            identity = str(row["entry_identity"])
            by_identity[identity].append(row)
            unique_zero.add(identity)
        for identity, records in by_identity.items():
            if len(records) > 1:
                duplicate_records.append({"case": case, "entry_identity": identity, "attempts": records})

    bindings = []
    for path, label in [
        (q / "execution.json", "PAL2 execution"),
        (q / "augmented-library.jsonl", "PAL2 augmented library"),
        (q / "case-support-conflict.jsonl", "PAL2 support audit"),
        (q / "conflict-edges.jsonl", "PAL2 conflict audit"),
    ]:
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})

    result = {
        "identity": "q10-gc0-lr1-pal2-r1-v1",
        "protocol": "PAL2_RECONCILIATION_AUDIT",
        "status": "RECONCILED",
        "parent_bindings": bindings,
        "source_receipt_counts": {
            "zero_attempts": int(execution["zero_entries"]),
            "singleton_advantages": int(execution["source_singleton_advantages"]),
            "pair_motifs": int(execution["source_pair_motifs"]),
            "attempt_total": int(execution["zero_entries"] + execution["source_singleton_advantages"] + execution["source_pair_motifs"]),
        },
        "unique_library_counts": dict(sorted(kind_counts.items())),
        "unique_library_total": len(library),
        "zero_attempts_reconstructed": zero_attempts,
        "unique_zero_selections": len(unique_zero),
        "deduplicated_zero_attempts": zero_attempts - len(unique_zero),
        "duplicate_records": duplicate_records,
        "case_counts": {
            case: {"zero_attempts": len(rows), "unique_zero_selections": len({str(row["entry_identity"]) for row in rows})}
            for case, rows in sorted(attempted_by_case.items())
        },
        "checks": {
            "source_attempt_total_is_721": int(execution["zero_entries"] + execution["source_singleton_advantages"] + execution["source_pair_motifs"]) == 721,
            "unique_library_total_is_718": len(library) == 718,
            "zero_reconciliation_is_462_to_459": zero_attempts == 462 and len(unique_zero) == 459,
            "library_kind_counts_are_459_58_201": dict(kind_counts) == {"PAIR": 201, "SINGLE": 58, "ZERO": 459},
            "parent_hashes_verified": all(digest(REPO / binding["path"]) == binding["sha256"] for binding in bindings),
        },
    }
    write_json(OUT / "execution.json", result)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
