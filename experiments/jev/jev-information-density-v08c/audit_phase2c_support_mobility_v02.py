"""Corrected Phase 2C mobility run wrapper; pins both input-digest domains."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_phase2c_support_mobility as mobility  # noqa: E402


def profile_matches_audit(bank: str, profile: dict[str, Any], audit: dict[str, Any]) -> None:
    """Check shared counts, never equate the two differently defined input hashes."""
    expected = audit["banks"][bank]
    checks = {
        "group_count": profile["group_count"] == expected["group_count"],
        "unique_roots": profile["unique_roots"] == expected["unique_root_count"],
    }
    if not all(checks.values()):
        raise ValueError(f"bank profile differs from sealed signature audit: {bank} {checks}")


def build_census(contract: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    report = _ORIGINAL_BUILD_CENSUS(contract, out_dir)
    for bank, profile in report["banks"].items():
        profile["input_identity"] = {
            "profile_constraint_key": "selector_model_input_sha256",
            "profile_constraint_unique_count": profile["unique_inputs"],
            "signature_audit_key": "state_input_sha256",
            "signature_audit_unique_count": json.loads(
                Path(contract["inputs"]["training_equivalence_audit"]["path"]).read_text(encoding="utf-8")
            )["banks"][bank]["unique_state_query_input_count"],
            "counts_are_not_compared": True,
            "reason": "the frozen validator and signature-audit summary count distinct digest domains",
        }
    report["validation_correction"] = {
        "status": "PASS_WITH_DISTINCT_INPUT_DIGEST_DOMAINS",
        "v01_issue": "v01 compared selector_model_input_sha256 cardinality with state_input_sha256 cardinality",
        "v02_rule": "report each count under its own key; only compare shared group/root fields",
        "v01_output_promotable": False,
    }
    report_path = out_dir / "support-mobility-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


_ORIGINAL_BUILD_CENSUS = mobility.build_census
mobility.profile_matches_audit = profile_matches_audit
mobility.build_census = build_census


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--freeze-receipt", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\support-mobility-v02\freeze-receipt.json"))
    args, _unknown = parser.parse_known_args()
    mobility.DEFAULT_FREEZE = args.freeze_receipt
    if "--freeze-receipt" not in sys.argv:
        sys.argv.extend(("--freeze-receipt", str(args.freeze_receipt)))
    if "--out" not in sys.argv:
        sys.argv.extend(("--out", str(args.freeze_receipt.parent)))
    return mobility.main()


if __name__ == "__main__":
    raise SystemExit(main())
