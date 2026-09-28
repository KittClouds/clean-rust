from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
OLD_SOURCE = CONSTRUCTION / "scored-bank-v1" / "vault" / "task-source-fixtures-final-v1.json"
OUT_ROOT = CONSTRUCTION / "scored-bank-a12"
OUT = OUT_ROOT / "vault" / "task-source-fixtures-precheck-v2.json"
LOCK = CONSTRUCTION / "a13-retry-design-lock-v1.json"
PATCH_REPAIRS = {
    ("help-color-capability", "suppress_color_narrow_help"): (
        "ColorChoice::Never", "ColorChoice::Auto"
    ),
    ("map-order-feature-contract", "canonical_sort"): (
        "Some(object.keys().cloned().collect())",
        "Some(object.keys().skip(1).cloned().collect())",
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def verify_lock() -> dict[str, Any]:
    if not LOCK.is_file():
        raise SystemExit("A13 retry design lock is missing; freeze construction inputs first")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock.get("state") != "FROZEN_BEFORE_A13_RETRY" or lock.get("model_contact_authorized") is not False:
        raise SystemExit("A13 retry design lock state is invalid")
    for item in lock["files"]:
        path = ROOT / Path(item["path"])
        if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
            raise SystemExit(f"A13 frozen input drift: {item['path']}")
    return lock


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite {OUT}")
    lock = verify_lock()
    source_bytes = OLD_SOURCE.read_bytes()
    source = json.loads(source_bytes)
    if source.get("model_contact_authorized") is not False:
        raise SystemExit("source fixture unexpectedly authorizes model contact")
    repaired: dict[str, int] = {}
    for task in source["tasks_hidden"]:
        family = task["family_name_hidden"]
        for option in task["candidate_options_hidden"]:
            key = (family, option["hidden_candidate_role"])
            if key not in PATCH_REPAIRS:
                continue
            old, new = PATCH_REPAIRS[key]
            patch_text = str(option["hidden_patch_text"])
            if patch_text.count(old) != 1:
                raise SystemExit(f"expected one locked patch anchor in {family}/{key[1]}")
            excerpt = str(option["diff_excerpt"])
            if family == "map-order-feature-contract":
                header = "@@ -4,6 +4,7 @@\n"
                old_context = "     Some(object.keys().cloned().collect())\n"
                new_delta = (
                    "-    Some(object.keys().cloned().collect())\n"
                    "+    Some(object.keys().skip(1).cloned().collect())\n"
                )
                for label, text in (("patch", patch_text), ("excerpt", excerpt)):
                    if text.count(header) != 1 or text.count(old_context) != 1:
                        raise SystemExit(f"unexpected frozen diff shape in {family}/{key[1]} {label}")
                fixed_patch = patch_text.replace(header, "@@ -4,7 +4,8 @@\n", 1).replace(old_context, new_delta, 1)
                fixed_excerpt = excerpt.replace(header, "@@ -4,7 +4,8 @@\n", 1).replace(old_context, new_delta, 1)
                if "-    Some(object.keys().cloned().collect())" not in fixed_patch or "+    Some(object.keys().skip(1).cloned().collect())" not in fixed_patch:
                    raise SystemExit("map-order repair was not encoded as a removal/addition")
            else:
                fixed_patch = patch_text.replace(old, new, 1)
                fixed_excerpt = excerpt.replace(old, new, 1)
            if fixed_patch == patch_text:
                raise SystemExit(f"candidate patch repair was a no-op in {family}/{key[1]}")
            option["hidden_patch_text"] = fixed_patch
            option["patch_sha256"] = sha256(fixed_patch.encode("utf-8"))
            option["diff_excerpt"] = fixed_excerpt
            repaired[family] = repaired.get(family, 0) + 1
    if repaired != {"help-color-capability": 4, "map-order-feature-contract": 4}:
        raise SystemExit(f"unexpected candidate patch repair coverage: {repaired}")
    source["state"] = "A13_RETRY_TASK_FIXTURE_PREPARED_BEFORE_SCORING_NO_MODEL_CONTACT"
    source["source_fixture_version"] = "a13-precheck-v2"
    source["derived_from_a13_retry"] = {
        "prior_final_source_sha256": sha256(source_bytes),
        "design_lock_sha256": sha256(LOCK.read_bytes()),
        "preparation_script_sha256": sha256(Path(__file__).read_bytes()),
        "candidate_patch_repairs": repaired,
        "model_contact": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(json.dumps(source, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps({
        "state": source["state"], "tasks": source["task_count"],
        "candidate_patch_repairs": repaired, "sha256": sha256(OUT.read_bytes()),
        "output": str(OUT), "design_lock": lock["state"],
    }, indent=2))


if __name__ == "__main__":
    main()
