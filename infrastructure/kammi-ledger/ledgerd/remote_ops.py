"""Remote bundle and worker-return operations for the single writer."""

from __future__ import annotations

from .identity import canonical, strict_json
from .remote import key_id, public_bytes, sign, validate_bundle, validated_signed_json


class RemoteOperations:
    def remote_input_allowed(self, artifact_id, actor_id, run_id, stage_id):
        protected = any(p["artifact_id"] == artifact_id for p in self.exposure.panels.values())
        return not protected or any(e["artifact_id"] == artifact_id and e["actor_id"] == actor_id
            and e["run_id"] == run_id and e["stage_id"] == stage_id for e in self.exposure.opened)

    def remote_worker_started(self, bundle_artifact_id, worker_actor_id, worker_token, request_id):
        with self.lock:
            record = self.remote.bundles.get(bundle_artifact_id)
            if record is None or not self.authority.verify_credential(worker_actor_id, worker_token):
                raise ValueError("unknown bundle or invalid worker credential")
            bundle = strict_json(self.cas.get(bundle_artifact_id))
            if bundle["worker_actor_id"] != worker_actor_id or not self.authorization_valid(
                bundle["authorization_id"], record["actor_id"], bundle["run_id"], bundle["stage_id"]
            ):
                raise ValueError("worker start lacks current authorization")
            if bundle["lease_id"] is not None and not self.leases.valid(
                bundle["lease_id"], bundle["lease_resource_id"], bundle["fencing_token"],
                record["actor_id"], bundle["run_id"],
            ):
                raise ValueError("worker start lease is stale")
            return self._emit("RemoteWorkerStarted", {"bundle_artifact_id": bundle_artifact_id,
                              "worker_actor_id": worker_actor_id, "run_id": bundle["run_id"]},
                              worker_actor_id, request_id)

    def register_worker_key(self, worker_actor_id: str, public_key_hex: str,
                            request_id: str) -> str:
        worker = self.authority.actors.get(worker_actor_id)
        if worker is None or worker["kind"] != "remote_worker":
            raise ValueError("worker actor must be registered as remote_worker")
        try:
            public_raw = bytes.fromhex(public_key_hex)
        except ValueError as exc:
            raise ValueError("invalid worker public key") from exc
        payload = {
            "worker_actor_id": worker_actor_id,
            "public_key_hex": public_key_hex,
            "key_id": key_id(public_raw),
        }
        with self.lock:
            return self._emit("WorkerKeyRegistered", payload,
                              "ledger-admin", request_id)

    def create_remote_bundle(self, bundle: dict, actor_id: str,
                             actor_token: str, request_id: str) -> tuple[str, dict]:
        validate_bundle(bundle)
        with self.lock:
            if self.signing_private is None:
                raise ValueError("daemon signing key not configured")
            run_id, stage_id = bundle["run_id"], bundle["stage_id"]
            current_policy = self.policy.current_policy_hash(stage_id)
            allowed = (
                run_id in self.runs
                and self.run_labs[run_id] == bundle["lab"]
                and self.authority.verify_credential(actor_id, actor_token)
                and self.authority.actors[actor_id]["lab"] == bundle["lab"]
                and current_policy is not None
                and self.authority.matching_grant(
                    actor_id, "execute_bundle", run_id, stage_id, current_policy
                ) is not None
                and self.authorization_valid(
                    bundle["authorization_id"], actor_id, run_id, stage_id
                )
            )
            if not allowed:
                raise ValueError("remote bundle lacks scoped authorization")
            if bundle["worker_actor_id"] not in self.remote.worker_keys:
                raise ValueError("remote worker key is not registered")
            if self.authority.actors[bundle["worker_actor_id"]]["lab"] != bundle["lab"]:
                raise ValueError("remote worker belongs to another lab")
            for name, kind in (("scientific_spec", "SCIENTIFIC"),
                               ("execution_spec", "EXECUTION")):
                bound = self.policy.specs.get((run_id, stage_id, kind))
                if bound is None or bound["artifact_id"] != bundle[name]:
                    raise ValueError("remote bundle spec identity mismatch")
            closure: set[str] = set()
            for root in bundle["input_roots"]:
                closure.update(self.verify_seal(root))
            if not set(bundle["input_artifacts"]).issubset(closure):
                raise ValueError("remote input is outside sealed roots")
            if any(not self.remote_input_allowed(i, actor_id, run_id, stage_id) for i in bundle["input_artifacts"]):
                raise ValueError("protected remote input requires guarded exposure first")
            if bundle["environment_lock"] not in self.artifacts:
                raise ValueError("remote environment lock unregistered")
            if bundle["lease_id"] is not None and not self.leases.valid(
                bundle["lease_id"], bundle["lease_resource_id"],
                bundle["fencing_token"], actor_id, run_id,
            ):
                raise ValueError("remote bundle lease is stale")
            if bundle["lease_id"] is not None and self.leases.leases[bundle["lease_id"]]["stage_id"] != stage_id:
                raise ValueError("remote bundle lease stage mismatch")
            raw = canonical(bundle)
            bundle_id, _ = self.register_bytes(
                raw, kind="remote-run-bundle", actor=actor_id,
                request_id=request_id + ":bundle",
            )
            pub = public_bytes(self.signing_private)
            payload = {
                "bundle_artifact_id": bundle_id, "run_id": run_id,
                "stage_id": stage_id, "actor_id": actor_id,
                "signature_hex": sign(self.signing_private, raw),
                "issuer_public_hex": pub.hex(), "issuer_key_id": key_id(pub),
            }
            event_id = self._emit("RemoteBundleCreated", payload,
                                  actor_id, request_id + ":created")
            return event_id, payload

    def accept_remote_return(
        self, bundle_artifact_id: str, receipt_raw: bytes,
        receipt_signature: str, worker_actor_id: str, worker_token: str,
        outputs: dict[str, bytes], stdout: bytes, stderr: bytes,
        request_id: str,
    ) -> tuple[str, dict]:
        from .identity import raw_id

        with self.lock:
            bundle_record = self.remote.bundles.get(bundle_artifact_id)
            public_hex = self.remote.worker_keys.get(worker_actor_id)
            if bundle_record is None or public_hex is None:
                raise ValueError("unknown bundle or worker key")
            if not self.authority.verify_credential(worker_actor_id, worker_token):
                raise ValueError("worker credential mismatch")
            receipt = validated_signed_json(
                receipt_raw, receipt_signature, bytes.fromhex(public_hex)
            )
            bundle = validate_bundle(strict_json(self.cas.get(bundle_artifact_id)))
            if receipt.get("schema") != "KAMMI_REMOTE_RETURN_V1" or receipt.get(
                "bundle_artifact_id"
            ) != bundle_artifact_id or receipt.get("run_id") != bundle["run_id"]:
                raise ValueError("remote receipt bundle identity mismatch")
            if worker_actor_id != bundle["worker_actor_id"]:
                raise ValueError("wrong worker returned bundle")
            if receipt.get("exit_code") != 0:
                raise ValueError("remote worker exited unsuccessfully")
            environment = receipt.get("worker_environment")
            if not isinstance(environment, dict) or environment.get("git_commit") != bundle["git_commit"]:
                raise ValueError("remote environment commit mismatch")
            if environment.get("dirty_tree") is not False:
                raise ValueError("remote return reports dirty tree")
            for category in ("runtime_requirements", "gpu_requirements"):
                for key, value in bundle[category].items():
                    if environment.get(key) != value:
                        raise ValueError("remote environment mismatch")
            if set(outputs) != set(bundle["expected_outputs"]) or set(
                receipt.get("outputs", {})
            ) != set(outputs):
                raise ValueError("remote output declaration mismatch")
            for name, data in outputs.items():
                if receipt["outputs"][name] != raw_id(data):
                    raise ValueError("remote output hash mismatch")
            if receipt.get("stdout_artifact_id") != raw_id(stdout) or receipt.get(
                "stderr_artifact_id"
            ) != raw_id(stderr):
                raise ValueError("remote stream hash mismatch")
            existing = self.remote.returns.get(bundle_artifact_id)
            if existing is not None:
                if existing["receipt_artifact_id"] != raw_id(receipt_raw):
                    raise ValueError("remote bundle already has a different return")
                return self.remote.return_events[bundle_artifact_id], existing
            if not self.authorization_valid(bundle["authorization_id"],
                                                    bundle_record["actor_id"], bundle["run_id"], bundle["stage_id"]):
                raise ValueError("remote return authorization is stale")
            if bundle["lease_id"] is not None and not self.leases.valid(
                bundle["lease_id"], bundle["lease_resource_id"], bundle["fencing_token"],
                bundle_record["actor_id"], bundle["run_id"],
            ):
                raise ValueError("remote return lease is stale")
            receipt_id, _ = self.register_bytes(
                receipt_raw, kind="remote-return-receipt", actor=worker_actor_id,
                request_id=request_id + ":receipt",
            )
            self._emit("RemoteWorkerReturned", {
                "bundle_artifact_id": bundle_artifact_id,
                "receipt_artifact_id": receipt_id,
                "worker_actor_id": worker_actor_id,
                "signature_hex": receipt_signature,
            }, worker_actor_id, request_id + ":returned")
            for name, data in sorted(outputs.items()):
                self.register_bytes(data, kind="remote-output", actor=worker_actor_id,
                                    request_id=request_id + ":output:" + name)
            self.register_bytes(stdout, kind="remote-stdout", actor=worker_actor_id,
                                request_id=request_id + ":stdout")
            self.register_bytes(stderr, kind="remote-stderr", actor=worker_actor_id,
                                request_id=request_id + ":stderr")
            payload = {
                "bundle_artifact_id": bundle_artifact_id,
                "receipt_artifact_id": receipt_id,
                "worker_actor_id": worker_actor_id,
                "outputs": receipt["outputs"],
                "stdout_artifact_id": receipt["stdout_artifact_id"],
                "stderr_artifact_id": receipt["stderr_artifact_id"],
                "status": "VERIFIED_NOT_HEAD_PROMOTED",
            }
            # Uploading/storing outputs may take longer than the remaining
            # lease. Recheck at acceptance, not only at receipt arrival.
            if not self.authorization_valid(bundle["authorization_id"], bundle_record["actor_id"], bundle["run_id"], bundle["stage_id"]):
                raise ValueError("remote return authorization expired during upload")
            if bundle["lease_id"] is not None and not self.leases.valid(
                bundle["lease_id"], bundle["lease_resource_id"], bundle["fencing_token"], bundle_record["actor_id"], bundle["run_id"]):
                raise ValueError("remote return lease expired during upload")
            def live_commit():
                return (self.authorization_valid(bundle["authorization_id"], bundle_record["actor_id"], bundle["run_id"], bundle["stage_id"])
                    and (bundle["lease_id"] is None or self.leases.valid(bundle["lease_id"], bundle["lease_resource_id"],
                        bundle["fencing_token"], bundle_record["actor_id"], bundle["run_id"])))
            event_id = self._emit("RemoteReceiptVerified", payload,
                                  "ledgerd", request_id + ":verified", guard=live_commit)
            return event_id, payload

