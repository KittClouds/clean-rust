"""Signed portable bundles and independently checkable worker receipts."""

from __future__ import annotations

import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .graph import SAFE
from .identity import canonical, require_id, strict_json


def public_bytes(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(raw_public: bytes) -> str:
    if len(raw_public) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return "sha256:" + hashlib.sha256(raw_public).hexdigest()


def sign(private: Ed25519PrivateKey, raw: bytes) -> str:
    return private.sign(raw).hex()


def verify(public_raw: bytes, raw: bytes, signature_hex: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            bytes.fromhex(signature_hex), raw
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def validate_bundle(bundle: dict) -> dict:
    required = {
        "schema", "run_id", "lab", "stage_id", "scientific_spec",
        "execution_spec", "git_commit", "dirty_tree_policy", "input_roots",
        "input_artifacts", "environment_lock", "runtime_requirements",
        "gpu_requirements", "seeds", "command", "expected_outputs",
        "authorization_id", "lease_id", "lease_resource_id", "fencing_token",
        "worker_actor_id",
    }
    if set(bundle) != required or bundle["schema"] != "KAMMI_REMOTE_BUNDLE_V1":
        raise ValueError("remote bundle schema mismatch")
    for key in ("run_id", "lab", "stage_id", "worker_actor_id"):
        if not isinstance(bundle[key], str) or not SAFE.fullmatch(bundle[key]):
            raise ValueError(f"invalid {key}")
    for key in ("scientific_spec", "execution_spec", "environment_lock",
                "authorization_id"):
        require_id(bundle[key])
    for key in ("input_roots", "input_artifacts"):
        if not isinstance(bundle[key], list) or len(set(bundle[key])) != len(bundle[key]):
            raise ValueError(f"invalid {key}")
        for item in bundle[key]:
            require_id(item)
    if bundle["dirty_tree_policy"] != "CLEAN_REQUIRED":
        raise ValueError("remote dirty-tree policy must require clean state")
    commit = bundle["git_commit"]
    if not isinstance(commit, str) or len(commit) != 40 or any(
        char not in "0123456789abcdef" for char in commit
    ):
        raise ValueError("expected full lowercase Git commit")
    if not isinstance(bundle["seeds"], list) or any(
        not isinstance(seed, int) or seed < 0 for seed in bundle["seeds"]
    ):
        raise ValueError("invalid seed list")
    if not isinstance(bundle["command"], list) or not bundle["command"] or any(
        not isinstance(arg, str) or not arg for arg in bundle["command"]
    ):
        raise ValueError("invalid exact command")
    outputs = bundle["expected_outputs"]
    if not isinstance(outputs, list) or len(set(outputs)) != len(outputs) or any(
        not isinstance(name, str) or not SAFE.fullmatch(name) for name in outputs
    ):
        raise ValueError("invalid declared outputs")
    if not isinstance(bundle["runtime_requirements"], dict) or not isinstance(
        bundle["gpu_requirements"], dict
    ):
        raise ValueError("runtime/GPU requirements must be objects")
    if bundle["lease_id"] is not None:
        if not isinstance(bundle["lease_id"], str) or not SAFE.fullmatch(bundle["lease_id"]):
            raise ValueError("invalid lease ID")
        if not isinstance(bundle["lease_resource_id"], str) or not SAFE.fullmatch(
            bundle["lease_resource_id"]
        ) or not isinstance(bundle["fencing_token"], int):
            raise ValueError("invalid lease fence")
    elif bundle["lease_resource_id"] is not None or bundle["fencing_token"] is not None:
        raise ValueError("lease fields must be all present or all null")
    return bundle


class RemoteState:
    def __init__(self) -> None:
        self.worker_keys: dict[str, str] = {}
        self.bundles: dict[str, dict] = {}
        self.returns: dict[str, dict] = {}
        self.return_events: dict[str, str] = {}

    def apply(self, kind: str, payload: dict, event_id: str) -> None:
        if kind == "WorkerKeyRegistered":
            self.worker_keys[payload["worker_actor_id"]] = payload["public_key_hex"]
        elif kind == "RemoteBundleCreated":
            self.bundles[payload["bundle_artifact_id"]] = payload
        elif kind == "RemoteReceiptVerified":
            bundle_id = payload["bundle_artifact_id"]
            if bundle_id in self.returns and self.returns[bundle_id] != payload:
                raise ValueError("remote bundle has conflicting verified returns")
            self.returns[bundle_id] = payload
            self.return_events[bundle_id] = event_id


def validated_signed_json(raw: bytes, signature_hex: str,
                          public_raw: bytes) -> dict:
    if not verify(public_raw, raw, signature_hex):
        raise ValueError("remote signature invalid")
    parsed = strict_json(raw)
    if canonical(parsed) != raw:
        raise ValueError("signed JSON is not canonical")
    return parsed
