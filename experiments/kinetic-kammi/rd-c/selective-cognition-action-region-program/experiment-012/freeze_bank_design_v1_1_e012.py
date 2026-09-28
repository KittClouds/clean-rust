from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONSTRUCTION = ROOT / "bank" / "construction-01"
BASE_PLAN = ROOT / "bank-construction-plan-v1.md"
BASE_DESIGN = CONSTRUCTION / "family-design-v1.json"
BASE_LOCK = CONSTRUCTION / "family-design-lock-v1.json"
AMENDMENT_MD = ROOT / "amendments" / "bank-amendment-01.md"
AMENDMENT_JSON = ROOT / "amendments" / "bank-amendment-01.json"
OUTPUT_PLAN = ROOT / "bank-construction-plan-v1.1.md"
OUTPUT_DESIGN = CONSTRUCTION / "family-design-v1.1.json"
OUTPUT_LOCK = CONSTRUCTION / "family-design-lock-v1.1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for path in (OUTPUT_PLAN, OUTPUT_DESIGN, OUTPUT_LOCK):
        if path.exists():
            raise SystemExit(f"refusing to overwrite frozen bank-design artifact: {path}")
    amendment = json.loads(AMENDMENT_JSON.read_text(encoding="utf-8"))
    old_lock = json.loads(BASE_LOCK.read_text(encoding="utf-8"))
    if amendment.get("model_contact_authorized") is not False:
        raise SystemExit("bank amendment unexpectedly authorizes model contact")
    if old_lock.get("state") != "FROZEN_BEFORE_TASK_FIXTURES":
        raise SystemExit("base family design was not frozen before fixtures")

    plan = BASE_PLAN.read_text(encoding="utf-8")
    old = "derive-feature-compatibility` | context sensitive | `E_c.content + E_r` | Choose an implementation compatible with the frozen workspace feature/toolchain context."
    new = "help-color-capability` | context sensitive | `E_c.content + E_r` | Configure help color from the typed ANSI-capability context."
    if plan.count(old) != 1:
        raise SystemExit("old family row is absent or ambiguous in the v1 plan")
    effective_plan = plan.replace(old, new, 1)
    effective_plan += (
        "\n\n## Version 1.1 amendment\n\n"
        "`E012-BANK-A01` replaces the unqualified clap derive-feature family with "
        "`help-color-capability`. See the amendment for the failed feasibility trace, "
        "repair, and exact context contract. No other family or gate changed.\n"
    )
    OUTPUT_PLAN.write_text(effective_plan, encoding="utf-8", newline="")

    design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
    rows = [row for row in design["families"] if row["hidden_family_name"] == "derive-feature-compatibility"]
    if len(rows) != 1:
        raise SystemExit("expected exactly one derive-feature family")
    rows[0]["hidden_family_name"] = "help-color-capability"
    rows[0]["family_amendment"] = "E012-BANK-A01"
    rows[0]["predeclared_task_focus"] = "Configure ColorChoice from typed ANSI capability context"
    design["effective_bank_plan_version"] = "1.1"
    design["bank_design_amendment"] = "E012-BANK-A01"
    OUTPUT_DESIGN.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    feasibility = {
        "bytes_endian": CONSTRUCTION / "feasibility" / "bytes-endian" / "feasibility-summary.json",
        "bytes_prefix": CONSTRUCTION / "feasibility" / "bytes-prefix" / "feasibility-summary.json",
        "bytes_cursor": CONSTRUCTION / "feasibility" / "bytes-cursor" / "feasibility-summary.json",
        "bytes_composite": CONSTRUCTION / "feasibility" / "bytes-composite" / "feasibility-summary.json",
        "clap_repeat": CONSTRUCTION / "feasibility" / "clap-repeat" / "feasibility-summary.json",
        "clap_color_failed_check": CONSTRUCTION / "feasibility" / "clap-color" / "feasibility-summary.json",
        "clap_color_repaired": CONSTRUCTION / "feasibility" / "clap-color-repair-01" / "feasibility-summary.json",
    }
    missing = [str(path) for path in feasibility.values() if not path.is_file()]
    if missing:
        raise SystemExit("missing locked feasibility records: " + "; ".join(missing))
    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_SCORED_TASK_FIXTURES",
        "model_contact_authorized": False,
        "scored_task_frames_created": False,
        "effective_bank_plan_version": "1.1",
        "bank_amendment": {
            "id": amendment["amendment_id"],
            "markdown_sha256": sha256(AMENDMENT_MD),
            "json_sha256": sha256(AMENDMENT_JSON),
        },
        "sha256": {
            "effective_protocol_lock": sha256(ROOT / "protocol-lock-v0.3.json"),
            "base_bank_design_lock": sha256(BASE_LOCK),
            "effective_bank_plan": sha256(OUTPUT_PLAN),
            "effective_family_design": sha256(OUTPUT_DESIGN),
            "source_inventory": sha256(CONSTRUCTION / "repository-source-inventory.json"),
            "feasibility_records": {name: sha256(path) for name, path in feasibility.items()},
        },
    }
    OUTPUT_LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(lock, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
