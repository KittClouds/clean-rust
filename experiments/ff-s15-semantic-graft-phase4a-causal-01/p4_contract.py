"""Causal Phase 4A identity checks. Earlier phase outputs are read-only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
P3_SOURCE = SOURCE.parent / "ff-s15-semantic-graft-phase3-causal-01"
sys.path.insert(0, str(P3_SOURCE))
import p3_contract as p3
from p3_contract import (OUTPUT as P3_OUTPUT, P2_OUTPUT, PHASE1_OUTPUT, NVME, SUBSTRATE,
                         default_config, pad_candidates, sha_file, write_json,
                         supervision_abi, canon_hash)

OUTPUT = Path(r"C:\phoenix-target-overgraph\semantic-graft-phase4a-causal-20261001-v02")
P2_SEED = P2_OUTPUT / "P2-CONSIST" / "best-graft.pt"
P3_REFERENCE = P3_OUTPUT / "P3-BALANCED" / "best-graft.pt"
P2_SEED_SHA = "e6d2e7ec3c8aeedd3a42a5a8f649525e593f9fff79cc960648ed51139e2b808b"
P3_REFERENCE_SHA = "9c748305b0cfcdae73b3aec1b414a27b6129f5b8b116117fc0bbeceea8eb475b"
ARM = "R4-CAUSAL"


def verify_inherited():
    p2_receipt, p2_spec = p3.verify_prior()
    if sha_file(P2_SEED) != P2_SEED_SHA:
        raise ValueError("Frozen P2-CONSIST seed hash changed")
    p2_seal = json.loads((P2_OUTPUT / "FINAL-SEAL.json").read_text())
    for name, digest in p2_seal["bindings"].items():
        if sha_file(P2_OUTPUT / name) != digest:
            raise ValueError("Phase 2 final seal changed: " + name)
    if sha_file(P3_REFERENCE) != P3_REFERENCE_SHA:
        raise ValueError("Frozen P3-BALANCED reference hash changed")
    p3_seal = json.loads((P3_OUTPUT / "FINAL-SEAL.json").read_text())
    for name, digest in p3_seal["bindings"].items():
        if sha_file(P3_OUTPUT / name) != digest:
            raise ValueError("Phase 3 final seal changed: " + name)
    p3_receipt = json.loads((P3_OUTPUT / "PHASE3-RECEIPT.json").read_text())
    return p2_receipt, p2_spec, p3_receipt


def state_hash(model):
    h = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous().numpy()
        h.update(name.encode()); h.update(str(value.dtype).encode())
        h.update(str(value.shape).encode()); h.update(value.tobytes())
    return h.hexdigest()


def freeze(spec):
    if (OUTPUT / "PHASE4A-SPEC.json").exists():
        raise ValueError("Phase 4A identity already frozen")
    spec["source_files"] = {p.name: sha_file(p) for p in sorted(SOURCE.iterdir())
                             if p.is_file() and p.suffix in (".py", ".md")}
    write_json(OUTPUT / "PHASE4A-SPEC.json", spec)


def verify_spec(spec):
    verify_inherited()
    for name, digest in spec["source_files"].items():
        if sha_file(SOURCE / name) != digest:
            raise ValueError("Frozen Phase 4A source changed: " + name)
