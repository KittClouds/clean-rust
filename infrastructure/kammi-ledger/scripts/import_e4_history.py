"""Versioned E4 legacy adapter. It emits only shared custody facts.

Reads the previously verified CAS import, not mutable source paths. A fact says
what its cited legacy file asserts; it is not fresh observation or permission.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ledgerd.core import Ledger
from ledgerd.identity import require_id, strict_json

HERE = Path(__file__).resolve().parents[1]
STORE = HERE / ".kammi-dev/e4-import"
AUDIT = HERE / "acceptance/e4-0/legacy-flat-verification-v1.json"
PRIOR = HERE / "acceptance/e4-0/merkle-import-v1.json"
SUPPLEMENT = HERE / "acceptance/e4-0/history-supplement-v1.json"
OUTPUT = HERE / "acceptance/e4-0/history-import-v3.json"
RUN_ID = "E4-0-legacy-history-complete-v1"
ACTOR = "chief-kammi"
SCOPE = "E4_LEGACY_SEALED_SNAPSHOT_V1"
ACCESS_FIELDS = {
    "population_truth_files_opened": "population_truth",
    "template_or_joint_truth_opened": "template_or_joint_truth",
    "labels_opened": "labels",
    "eval_panel_opened": "evaluation_panel",
    "population_truth_opened": "population_truth",
    "truth_payloads_opened": "truth_payloads",
}
CONTACT_FIELDS = {
    "model_contact": "model",
    "tokenizer_contact": "tokenizer",
    "cuda_contact": "cuda",
    "cuda_initialized": "cuda_initialized",
    "cuda_initialized_by_this_task": "cuda_initialized",
    "model_or_tokenizer_contacted": "model_or_tokenizer",
    "model_tokenizer_cuda_contact": "model_tokenizer_cuda",
}


def request(label: str) -> str:
    return "e4-history-" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def outcome(data: dict) -> str:
    status = data.get("status", "")
    if not isinstance(status, str):
        return "UNKNOWN"
    if data.get("stop_class") or "STOP" in status.upper():
        return "STOP"
    if data.get("pass") is True or "PASS" in status.upper():
        return "PASS"
    return "UNKNOWN"


def add_fact(ledger: Ledger, facts: list[dict], *, kind: str, subject: str,
             target: str, value: str, evidence: str, scope: str = SCOPE) -> str:
    fact = {
        "run_id": RUN_ID,
        "kind": kind,
        "subject": subject,
        "object": target,
        "value": value,
        "evidence_artifact": evidence,
        "scope": scope,
    }
    fact_id, _ = ledger.record_fact(fact, ACTOR, request(json.dumps(fact, sort_keys=True)))
    facts.append({"fact_id": fact_id, **fact})
    return fact_id


def nested_outcome(data: dict) -> str:
    if isinstance(data.get("errored"), int) and data["errored"] > 0:
        return "STOP"
    if any(value == "PASS" for key, value in data.items() if key.endswith("suite")):
        return "PASS"
    return outcome(data)


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    supplement = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
    if audit["status"] != "PASS" or audit["verified_entries"] != 447:
        raise ValueError("legacy closure verification missing")
    ledger = Ledger(STORE)
    if len(ledger.verify_seal(prior["successor_root"])) != 433:
        raise ValueError("Merkle successor closure mismatch")
    if supplement["parent_merkle_root"] != prior["successor_root"]:
        raise ValueError("supplement is not parent-bound to legacy import")
    if len(ledger.verify_seal(supplement["supplement_root"])) != supplement["verified_total_closure"]:
        raise ValueError("supplement closure mismatch")
    seal_bytes = ledger.cas.get("sha256:" + audit["seal_file_sha256"])
    seal = strict_json(seal_bytes)
    if seal["entry_count"] != 447:
        raise ValueError("legacy seal entry count changed")
    ledger.create_run(RUN_ID, "Frozen-Fabrique", ACTOR, request("run:" + RUN_ID))
    facts: list[dict] = []
    counts = Counter()
    unresolved_predecessors: list[str] = []
    examined = 0
    seen_artifacts: set[str] = set()
    sources = [(entry["path"], "sha256:" + entry["sha256"]) for entry in seal["entries"]]
    sources.extend((entry["path"], entry["artifact"]) for entry in supplement["entries"])
    for source_path, source_artifact in sources:
        artifact = require_id(source_artifact)
        if artifact not in ledger.artifacts or not ledger.cas.verify(artifact):
            raise ValueError(f"sealed source not registered or corrupt: {artifact}")
        if artifact in seen_artifacts:
            continue
        seen_artifacts.add(artifact)
        path = source_path.replace("\\", "/")
        if not path.endswith(".json") or "/source/" in path:
            continue
        try:
            data = strict_json(ledger.cas.get(artifact))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        examined += 1
        if "/contracts/e4-0-contract-" in path and path.endswith("-final.json"):
            predecessor = data.get("supersedes", {}).get("contract")
            if isinstance(predecessor, dict) and isinstance(predecessor.get("sha256"), str):
                previous = require_id("sha256:" + predecessor["sha256"])
                add_fact(ledger, facts, kind="SUPERSESSION", subject=artifact,
                         target=previous, value="DECLARED", evidence=artifact)
                counts["supersession"] += 1
                if previous not in ledger.artifacts:
                    unresolved_predecessors.append(previous)
        audit_record = "/audits/" in path and "e4-0" in path
        receipt = audit_record and any(
            tag in path.rsplit("/", 1)[-1]
            for tag in ("receipt", "stop", "attempt", "failure", "test")
        )
        if receipt and ("status" in data or "pass" in data):
            result = outcome(data)
            add_fact(ledger, facts, kind="ATTEMPT", subject=artifact,
                     target="legacy_audit_receipt", value=result, evidence=artifact)
            counts["attempt_" + result.lower()] += 1
            for stage in ("initial_attempt", "retest"):
                nested = data.get(stage)
                if not isinstance(nested, dict):
                    continue
                nested_value = nested_outcome(nested)
                nested_id = add_fact(
                    ledger, facts, kind="ATTEMPT", subject=artifact,
                    target=stage, value=nested_value, evidence=artifact,
                    scope="LEGACY_NESTED_ATTEMPT_RECEIPT",
                )
                counts["nested_attempt_" + nested_value.lower()] += 1
                for field, contact_class in CONTACT_FIELDS.items():
                    if type(nested.get(field)) is bool:
                        value = "YES" if nested[field] else "NO_ATTESTED"
                        add_fact(ledger, facts, kind="CONTACT", subject=nested_id,
                                 target=contact_class, value=value, evidence=artifact,
                                 scope="LEGACY_NESTED_ATTEMPT_SELF_ATTESTATION")
                        counts["nested_contact_" + value.lower()] += 1
        if audit_record:
            scopes = [(data, "LEGACY_AUDIT_SELF_ATTESTATION")]
            if isinstance(data.get("runtime_access"), dict):
                scopes.append((data["runtime_access"], "LEGACY_RUNTIME_ACCESS_SELF_ATTESTATION"))
            for fields, assertion_scope in scopes:
                for field, contact_class in CONTACT_FIELDS.items():
                    if type(fields.get(field)) is bool:
                        value = "YES" if fields[field] else "NO_ATTESTED"
                        add_fact(ledger, facts, kind="CONTACT", subject=artifact,
                                 target=contact_class, value=value, evidence=artifact,
                                 scope=assertion_scope)
                        counts["contact_" + value.lower()] += 1
                for field, evidence_class in ACCESS_FIELDS.items():
                    if type(fields.get(field)) is bool:
                        value = "YES" if fields[field] else "NO_ATTESTED"
                        add_fact(ledger, facts, kind="EVIDENCE_ACCESS", subject=artifact,
                                 target=evidence_class, value=value, evidence=artifact,
                                 scope=assertion_scope)
                        counts["evidence_" + value.lower()] += 1
    final_contract = "sha256:" + audit["contract_sha256"]
    final = strict_json(ledger.cas.get(final_contract))
    if final.get("status") != "SEALED" or final.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16":
        raise ValueError("legacy final contract identity/status mismatch")
    add_fact(ledger, facts, kind="HEAD", subject="contract", target=final_contract,
             value="SEALED", evidence=final_contract,
             scope="VERIFIED_LEGACY_FIXTURE_HEAD_ONLY")
    counts["head"] += 1
    history = ledger.history(RUN_ID)
    if len(history) != len(facts):
        raise ValueError("graph history and journal fact count disagree")
    status = ledger.status()
    report = {
        "schema": "KAMMI_E4_HISTORY_IMPORT_V3",
        "status": "PASS",
        "run_id": RUN_ID,
        "source_legacy_root": "sha256:" + audit["legacy_root_sha256"],
        "source_merkle_root": supplement["supplement_root"],
        "original_merkle_root": prior["successor_root"],
        "source_entries": seal["entry_count"],
        "supplemental_paths": supplement["source_path_count"],
        "examined_json_entries": examined,
        "fact_counts": dict(sorted(counts.items())),
        "fact_count": len(facts),
        "history_graph_count": len(history),
        "unresolved_declared_predecessors": sorted(set(unresolved_predecessors)),
        "model_contact_global_conclusion": "UNKNOWN_OUTSIDE_EXPLICIT_RECEIPT_SCOPES",
        "evidence_access_global_conclusion": "UNKNOWN_OUTSIDE_EXPLICIT_RECEIPT_SCOPES",
        "flight_authorization_conferred": False,
        "projection": status,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "facts": len(facts), "counts": report["fact_counts"]}))


if __name__ == "__main__":
    main()
