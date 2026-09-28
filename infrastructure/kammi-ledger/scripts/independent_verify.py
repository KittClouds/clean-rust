"""Read-only authority reconstruction; no imports from ledgerd decisions."""
from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime
from pathlib import Path

import jcs


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value):
    return jcs.canonicalize(value)


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify_store(root: Path) -> dict:
    def object_bytes(identity):
        if len(identity) != 71 or not identity.startswith("sha256:"):
            raise ValueError("invalid content identity")
        raw = (root / "objects" / "sha256" / identity[7:9] / identity[9:]).read_bytes()
        if digest(raw) != identity:
            raise ValueError("CAS digest mismatch")
        return raw

    def journal(path):
        events, previous = [], "sha256:" + "0" * 64
        if not path.exists():
            return events, previous
        with path.open("rb") as stream:
            while header := stream.read(4):
                if len(header) != 4:
                    raise ValueError("truncated journal")
                size = struct.unpack(">I", header)[0]
                if not 0 < size <= 16 * 1024 * 1024:
                    raise ValueError("invalid frame size")
                raw, checksum = stream.read(size), stream.read(32)
                if hashlib.sha256(raw).digest() != checksum:
                    raise ValueError("frame checksum mismatch")
                event = json.loads(raw)
                if canonical(event) != raw or event["prev"] != previous or event["seq"] != len(events) + 1:
                    raise ValueError("event chain/canonical mismatch")
                identity = digest(b"kammi-event-v1\0" + raw)
                payload = json.loads(object_bytes(event["payload_artifact"]))
                events.append((event, identity, payload))
                previous = identity
        return events, previous

    events, head = journal(root / "journal" / "events.log")
    requests, seals, artifacts, grants, policies, auths = {}, {}, set(), {}, {}, {}
    leases, active, fences, bindings, contacts, exposures = {}, {}, {}, {}, [], []
    facts, checks = [], []
    actors, runs, verified_seals, adapters, bundles, worker_keys = {}, {}, set(), {}, {}, {}
    resources, panels, returned = {}, {}, set()
    def valid_authorization(identity, actor, run, stage, timestamp):
        auth = auths.get(identity)
        bound = {k: v for (r, s, k), v in bindings.items() if r == run and s == stage}
        identity_valid = (auth is not None and auth["actor_id"] == actor and auth["run_id"] == run
                and auth["stage_id"] == stage and stamp(auth["expires_utc"]) > stamp(timestamp)
                and auth["policy_hash"] == policies[stage]["policy_hash"]
                and auth.get("spec_bindings", {}) == bound)
        if not identity_valid:
            return False
        policy = json.loads(object_bytes(policies[stage]["artifact_id"]))
        if "truth_label_contact" in policy["forbids"] and any(c["run_id"] == run and c["contact_class"] == "TRUTH_LABEL" for c in contacts):
            return False
        if "eval_panel_opened" in policy["forbids"] and any(e["run_id"] == run for e in exposures):
            return False
        if "resource.gpu" in policy["requires"] and not any(
            resources[l["resource_id"]]["kind"] == "GPU" and l["actor_id"] == actor and l["run_id"] == run and l["stage_id"] == stage
            and stamp(l["expires_utc"]) > stamp(timestamp) for i, l in leases.items() if active.get(l["resource_id"]) == i):
            return False
        return True
    for event, identity, payload in events:
        if event["request_id"] in requests:
            raise ValueError("duplicate request event")
        requests[event["request_id"]] = identity
        kind = event["type"]
        if kind == "ActorRegistered":
            actors[payload["actor_id"]] = payload
        elif kind == "RunCreated":
            runs[payload["run_id"]] = payload["lab"]
        elif kind == "ResourceRegistered":
            resources[payload["resource_id"]] = payload
        elif kind == "PanelRegistered":
            panels[payload["panel_id"]] = payload
        elif kind == "ArtifactRegistered":
            if len(object_bytes(payload["artifact_id"])) != payload["byte_count"]:
                raise ValueError("artifact byte count mismatch")
            artifacts.add(payload["artifact_id"])
        elif kind == "SealCreated":
            raw = object_bytes(payload["seal_artifact"])
            seal = json.loads(raw)
            if digest(b"kammi-seal-v1\0" + canonical(seal)) != payload["root"]:
                raise ValueError("Merkle root mismatch")
            if seal["direct_members"] != sorted(set(seal["direct_members"])) or seal["parents"] != sorted(set(seal["parents"])):
                raise ValueError("noncanonical seal membership")
            if any(p not in seals for p in seal["parents"]):
                raise ValueError("unknown parent seal")
            for member in seal["direct_members"]:
                object_bytes(member)
            seals[payload["root"]] = seal
        elif kind == "PolicyRegistered":
            if digest(object_bytes(payload["artifact_id"])) != payload["policy_hash"]:
                raise ValueError("policy identity mismatch")
            policies[payload["stage_id"]] = payload
        elif kind == "GrantIssued":
            grants[payload["grant_id"]] = payload
        elif kind == "SpecBound":
            bindings[(payload["run_id"], payload["stage_id"], payload["spec_kind"])] = payload["artifact_id"]
        elif kind == "SealVerified":
            if payload["root"] not in seals:
                raise ValueError("verified seal missing")
            verified_seals.add((payload["run_id"], payload["stage_id"]))
        elif kind == "ContactRecorded":
            contacts.append(payload)
        elif kind == "AuthorizationIssued":
            grant = grants.get(payload["grant_id"])
            if grant is None or any(grant[k] != payload[k] for k in ("actor_id", "run_id", "stage_id", "policy_hash")):
                raise ValueError("authorization scope lacks grant")
            if stamp(payload["expires_utc"]) > stamp(grant["expires_utc"]):
                raise ValueError("authorization outlives grant")
            if payload["policy_hash"] != policies[payload["stage_id"]]["policy_hash"]:
                raise ValueError("stale policy authorization")
            if payload["decision"] != "AUTHORIZED" or not all(c["pass"] for c in payload["prerequisites"]):
                raise ValueError("issued authorization contains failed predicate")
            expected_bindings = {k: v for (r, s, k), v in bindings.items()
                                 if r == payload["run_id"] and s == payload["stage_id"]}
            if payload.get("spec_bindings", {}) != expected_bindings:
                raise ValueError("authorization spec binding mismatch")
            if actors[payload["actor_id"]]["lab"] != runs[payload["run_id"]]:
                raise ValueError("authorization crosses lab boundary")
            if stamp(grant["expires_utc"]) <= stamp(event["utc"]):
                raise ValueError("expired grant issued authorization")
            policy = json.loads(object_bytes(policies[payload["stage_id"]]["artifact_id"]))
            predicates = {"actor": True, "scientific_spec": "SCIENTIFIC" in expected_bindings,
                          "execution_spec": "EXECUTION" in expected_bindings,
                          "predecessor_seal": (payload["run_id"], payload["stage_id"]) in verified_seals,
                          "resource.gpu": any(resources[l["resource_id"]]["kind"] == "GPU"
                                              and l["actor_id"] == payload["actor_id"] and l["run_id"] == payload["run_id"]
                                              and l["stage_id"] == payload["stage_id"] and stamp(l["expires_utc"]) > stamp(event["utc"])
                                              for i, l in leases.items() if active.get(l["resource_id"]) == i)}
            forbidden = {"truth_label_contact": any(c["run_id"] == payload["run_id"] and c["contact_class"] == "TRUTH_LABEL" for c in contacts),
                         "eval_panel_opened": any(e["run_id"] == payload["run_id"] for e in exposures)}
            if not all(predicates[k] for k in policy["requires"]) or any(forbidden[k] for k in policy["forbids"]):
                raise ValueError("independent authorization predicates failed")
            auths[identity] = payload
            checks.append("authorization_scope")
        elif kind == "ExposureOpened":
            auth = auths.get(payload["authorization_id"])
            if not valid_authorization(payload["authorization_id"], payload["actor_id"],
                                       payload["run_id"], payload["stage_id"], event["utc"]):
                raise ValueError("exposure lacks actor/run/stage authorization")
            if stamp(auth["expires_utc"]) <= stamp(event["utc"]):
                raise ValueError("exposure after authorization expiry")
            if event["request_id"].removesuffix(":opened") + ":requested" not in requests:
                raise ValueError("exposure request missing")
            if payload["lab"] != runs[payload["run_id"]] or panels[payload["panel_id"]]["lab"] != payload["lab"]:
                raise ValueError("exposure crosses lab boundary")
            exposures.append(payload)
            checks.append("guarded_exposure")
        elif kind == "LeaseGranted":
            resource, token = payload["resource_id"], payload["fencing_token"]
            old = active.get(resource)
            if old is not None and stamp(leases[old]["expires_utc"]) > stamp(payload["issued_utc"]):
                raise ValueError("overlapping exclusive lease")
            if token <= fences.get(resource, 0):
                raise ValueError("nonmonotonic fence")
            leases[payload["lease_id"]] = payload
            active[resource], fences[resource] = payload["lease_id"], token
            checks.append("exclusive_fence")
        elif kind == "LeaseRenewed":
            leases[payload["lease_id"]] = {**leases[payload["lease_id"]], **payload}
        elif kind in {"LeaseReleased", "LeaseExpired"}:
            if active.get(payload["resource_id"]) == payload["lease_id"]:
                del active[payload["resource_id"]]
        elif kind == "AdapterRegistered":
            if digest(object_bytes(payload["implementation_artifact"])) != payload["implementation_hash"]:
                raise ValueError("adapter implementation identity mismatch")
            checks.append("adapter_identity")
            adapters[payload["adapter_id"]] = payload
        elif kind == "AdapterApplied":
            adapter = adapters[payload["adapter_id"]]
            if payload["implementation_hash"] != adapter["implementation_hash"]:
                raise ValueError("adapter application identity mismatch")
            source = json.loads(object_bytes(payload["source_artifact_id"]))
            derived = json.loads(object_bytes(payload["derived_view_id"]))
            expected = dict(source)
            expected["evaluation_cells"] = expected.pop("evaluation_checkpoint_cells")
            expected["schema"] = "evaluation-v2"
            if derived != expected:
                raise ValueError("adapter view differs from independent transformation")
        elif kind == "WorkerKeyRegistered":
            worker_keys[payload["worker_actor_id"]] = payload["public_key_hex"]
        elif kind == "RemoteBundleCreated":
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            raw = object_bytes(payload["bundle_artifact_id"])
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(payload["issuer_public_hex"])).verify(bytes.fromhex(payload["signature_hex"]), raw)
            bundle = json.loads(raw)
            if actors[bundle["worker_actor_id"]]["lab"] != runs[bundle["run_id"]]:
                raise ValueError("remote worker crosses lab boundary")
            for input_id in bundle["input_artifacts"]:
                if any(p["artifact_id"] == input_id for p in panels.values()) and not any(
                    e["artifact_id"] == input_id and e["actor_id"] == payload["actor_id"]
                    and e["run_id"] == bundle["run_id"] and e["stage_id"] == bundle["stage_id"] for e in exposures):
                    raise ValueError("protected remote input bypasses exposure")
            bundles[payload["bundle_artifact_id"]] = bundle
            checks.append("remote_bundle_signature")
        elif kind == "RemoteWorkerReturned":
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            raw = object_bytes(payload["receipt_artifact_id"])
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(worker_keys[payload["worker_actor_id"]])).verify(bytes.fromhex(payload["signature_hex"]), raw)
            checks.append("remote_return_signature")
        elif kind == "RemoteReceiptVerified":
            bundle = bundles[payload["bundle_artifact_id"]]
            receipt = json.loads(object_bytes(payload["receipt_artifact_id"]))
            if payload["bundle_artifact_id"] in returned or receipt["exit_code"] != 0:
                raise ValueError("remote duplicate acceptance or failed execution")
            returned.add(payload["bundle_artifact_id"])
            if receipt["bundle_artifact_id"] != payload["bundle_artifact_id"] or set(receipt["outputs"]) != set(bundle["expected_outputs"]):
                raise ValueError("remote receipt declaration mismatch")
            for output in [*receipt["outputs"].values(), receipt["stdout_artifact_id"], receipt["stderr_artifact_id"]]:
                object_bytes(output)
            if payload["worker_actor_id"] != bundle["worker_actor_id"]:
                raise ValueError("remote return worker identity mismatch")
            environment = receipt["worker_environment"]
            if environment["git_commit"] != bundle["git_commit"] or environment["dirty_tree"] is not False:
                raise ValueError("remote return Git/environment mismatch")
            for category in ("runtime_requirements", "gpu_requirements"):
                if any(environment.get(k) != v for k, v in bundle[category].items()):
                    raise ValueError("remote requirements mismatch")
            auth = auths[bundle["authorization_id"]]
            if not valid_authorization(bundle["authorization_id"], auth["actor_id"], bundle["run_id"], bundle["stage_id"], event["utc"]):
                raise ValueError("remote acceptance has stale authorization")
            if bundle["lease_id"] is not None:
                lease = leases[bundle["lease_id"]]
                if (active.get(bundle["lease_resource_id"]) != bundle["lease_id"]
                        or lease["fencing_token"] != bundle["fencing_token"]
                        or stamp(lease["expires_utc"]) <= stamp(event["utc"])):
                    raise ValueError("remote acceptance has stale lease")
        elif kind == "FactRecorded":
            object_bytes(payload["evidence_artifact"])
            facts.append(payload)
    memory_events, memory_head = journal(root / "memory" / "journal" / "events.log")
    memories = {}
    memory_requests = set()
    event_ids = {identity for _, identity, _ in events}
    for event, identity, payload in memory_events:
        if event["request_id"] in memory_requests:
            raise ValueError("duplicate memory request")
        memory_requests.add(event["request_id"])
        if event["type"] == "MemoryRecorded":
            record = json.loads(object_bytes(payload["record_artifact_id"]))
            if digest(canonical({k: v for k, v in record.items() if k != "memory_id"})) != record["memory_id"]:
                raise ValueError("memory identity mismatch")
            for ref in record["custody_refs"]:
                if ref not in artifacts and ref not in event_ids:
                    raise ValueError("memory custody reference missing")
                if ref in artifacts:
                    object_bytes(ref)
            if len(object_bytes(record["embedding_artifact_id"])) != 1536:
                raise ValueError("memory embedding malformed")
            if record["authority"] != "CONTEXTUAL_NOT_CUSTODY":
                raise ValueError("memory promoted authority")
            memories[record["memory_id"]] = record
            checks.append("memory_custody_reference")
        elif event["type"] == "MemoryRetrieved":
            response = json.loads(object_bytes(payload["response_artifact_id"]))
            if response["authority"] != "CONTEXTUAL_NOT_CUSTODY":
                raise ValueError("retrieval promoted authority")
    object_count = 0
    for shard in (root / "objects/sha256").iterdir():
        for path in shard.iterdir():
            object_bytes("sha256:" + shard.name + path.name)
            object_count += 1
    return {"schema": "KAMMI_INDEPENDENT_VERIFY_V1", "status": "PASS",
            "journal_head": head, "journal_events": len(events), "seal_count": len(seals),
            "artifact_count": len(artifacts), "fact_count": len(facts),
            "cas_objects_verified": object_count,
            "memory_head": memory_head, "memory_count": len(memories),
            "checks": sorted(set(checks))}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_store(args.root), indent=2))
