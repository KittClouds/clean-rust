"""Dump every derived view the unmodified Python Ledger computes from a v1 store.

Usage: python v1_state_oracle.py <path to kammi-ledger> <disposable v1 store copy> [embedding cache]

Only point this at a disposable copy: the Python Ledger writes its Ladybug projection there.
Prints one JSON document with sorted keys.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])

from ledgerd.core import Ledger  # noqa: E402
from ledgerd.identity import strict_json  # noqa: E402

root = Path(sys.argv[2])
cache = Path(sys.argv[3]) if len(sys.argv) > 3 else None
ledger = Ledger(root, embedding_cache=cache)
try:
    status = ledger.status()
    out = {
        "status": {k: status[k] for k in (
            "journal_events", "journal_head", "counts", "acceptance_identity",
            "active_lease_resources", "authorization_denials", "panel_exposures",
            "remote_bundles", "remote_verified_returns")},
        "memory_status": {k: status["memory"][k] for k in ("records", "journal_head")},
        "runs": {run: {"lab": ledger.run_labs[run], "history": ledger.history(run),
                       "summary": ledger.history_summary(run)} for run in sorted(ledger.runs)},
        "artifacts": ledger.artifacts,
        "seals": {root_id: ledger.verify_seal(root_id) for root_id in sorted(ledger.seal_artifacts)},
        "facts": ledger.facts,
        "actors": ledger.authority.actors,
        "grants": ledger.authority.grants,
        "policies": ledger.policy.policies,
        "specs": {"|".join(k): v for k, v in ledger.policy.specs.items()},
        "verified_seals": sorted("|".join(k) for k in ledger.policy.verified_seals),
        "contacts": ledger.policy.contacts,
        "authorizations": ledger.policy.authorizations,
        "panels": {p: ledger.exposure.report(p) for p in sorted(ledger.exposure.panels)},
        "resources": {r: {"resource": ledger.leases.resources[r],
                          "fencing_counter": ledger.leases.fencing.get(r, 0)} for r in ledger.leases.resources},
        "leases": ledger.leases.leases,
        "active_leases": ledger.leases.active,
        "adapters": ledger.adapters.registered,
        "worker_keys": ledger.remote.worker_keys,
        "bundles": ledger.remote.bundles,
        "returns": ledger.remote.returns,
        "attempts": ledger.lifecycle.attempts,
        "heads": {"|".join(k): v for k, v in ledger.lifecycle.heads.items()},
        "vaults": {v: ledger.vaults.view(v) for v in sorted(ledger.vaults.vaults)},
        "library_acceptance": ledger.library_acceptance,
    }
    if ledger.memory is not None:
        out["memories"] = {m: ledger.memory.get(m) for m in sorted(ledger.memory.records)}
        out["memory_traces"] = {m: ledger.memory.trace(m) for m in sorted(ledger.memory.records)}
    print(json.dumps(out, sort_keys=True))
finally:
    ledger.close()
