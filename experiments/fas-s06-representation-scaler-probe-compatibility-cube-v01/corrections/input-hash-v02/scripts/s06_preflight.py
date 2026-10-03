from __future__ import annotations

from collections import Counter, defaultdict

from s06_common import (
    AUTHORIZATION,
    CONTRACT,
    DIRECT_INPUT_HASHES,
    RUN,
    S05_POPULATIONS,
    FailClosed,
    read_json,
    sha_file,
    verify_parents,
    verify_protocol,
    write_json,
)


def _validate_populations() -> dict:
    populations = read_json(S05_POPULATIONS)
    if (populations.get("model_contact") is not False or
            populations.get("feature_payloads_used_for_selection") is not False or
            populations.get("probe_parameters_used_for_selection") is not False):
        raise FailClosed("S05 population selection boundary is not intact")
    fas = populations["FAS00_ORIGINAL"]["rows"]
    s01 = populations["S01_CONTROLLED"]["rows"]
    if len(fas) != 512 or len({row["event_id"] for row in fas}) != 512:
        raise FailClosed("S06 FAS-00 population count or event uniqueness mismatch")
    if len(s01) != 19732 or len({row["event_id"] for row in s01}) != 19732:
        raise FailClosed("S06 S01 population count or event uniqueness mismatch")
    fas_slices = Counter(slice_id for row in fas for slice_id in row["slices"])
    if fas_slices != Counter({"CONTEXT_TERM_3": 412, "ENTITY_TERM_7": 212}):
        raise FailClosed(f"S06 FAS-00 slice membership mismatch: {fas_slices}")
    quartet_groups: dict[str, list[dict]] = defaultdict(list)
    for row in s01:
        if row.get("track_id") != "FACTORIAL_BALANCED" or row.get("variant_id") not in {"A", "C", "E", "P"}:
            raise FailClosed(f"Invalid S01 event identity: {row.get('event_id')}")
        mapping = {int(k): int(v) for k, v in row["state_by_candidate_identity"].items()}
        if set(mapping) != {0, 1, 2} or set(mapping.values()) != {0, 1, 2} or set(row["candidate_identity_order"]) != {0, 1, 2}:
            raise FailClosed(f"Invalid S01 class mapping: {row['event_id']}")
        if int(row["target_state_id"]) not in {0, 1, 2}:
            raise FailClosed(f"Invalid S01 target state: {row['event_id']}")
        quartet_groups[row["quartet_id"]].append(row)
    if len(quartet_groups) != 4933 or any(Counter(x["variant_id"] for x in group) != Counter({"A": 1, "C": 1, "E": 1, "P": 1}) for group in quartet_groups.values()):
        raise FailClosed("S06 S01 quartet cardinality/variant mapping mismatch")
    return {
        "FAS00_ORIGINAL": {"unique_events": len(fas), "slices": {"UNION": 512, **dict(fas_slices)}},
        "S01_CONTROLLED": {"unique_events": len(s01), "quartets": len(quartet_groups)},
    }


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    protocol = verify_protocol()
    parents = verify_parents()
    counts = _validate_populations()
    receipt = {
        "receipt_id": "FAS_S06_PREFLIGHT_V01",
        "status": "PASS",
        "protocol_root_sha256": protocol["root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT),
        "authorization_packet_sha256": sha_file(AUTHORIZATION),
        "s05_population_sha256": sha_file(S05_POPULATIONS),
        "parents": parents,
        "population_counts": counts,
        "cell_count": 16,
        "bundled_scaler_cells": 8,
        "center_scale_control_cells": 8,
        "direct_input_hashes": DIRECT_INPUT_HASHES,
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "analysis_executed": False,
    }
    write_json(RUN / "preflight-receipt-v01.json", receipt)
    print("S06_PREFLIGHT_PASS fas00=512 context=412 entity=212 s01_quartets=4933 s01_events=19732 cells=16")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S06_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
