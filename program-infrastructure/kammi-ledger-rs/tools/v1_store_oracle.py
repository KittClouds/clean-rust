"""Ask the unmodified Python Library code to accept a v1-layout store.

Usage: python v1_store_oracle.py <path to kammi-ledger> <store root>

Opens the journals with ledgerd.journal.EventJournal (full _scan validation: frames,
checksums, canonical JCS, vocabulary, chain, duplicate request IDs) and loads every event
payload through ledgerd.cas.ContentStore.get (digest verification). Prints one JSON line.

Only point this at a disposable copy: EventJournal may create or repair files in the store.
Run with PYTHONDONTWRITEBYTECODE=1 so nothing is written into the Python tree.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])

from ledgerd.cas import ContentStore  # noqa: E402
from ledgerd.identity import strict_json  # noqa: E402
from ledgerd.journal import EventJournal  # noqa: E402

root = Path(sys.argv[2])
cas = ContentStore(root)
result = {}
for name, base in (("main", root), ("memory", root / "memory")):
    if name == "memory" and not (base / "journal" / "events.log").exists():
        result[name] = {"events": 0, "head": None}
        continue
    journal = EventJournal(base)
    for event, _ in journal:
        strict_json(cas.get(event["payload_artifact"]))
    result[name] = {"events": len(journal.events), "head": journal.head if journal.events else None}
objects = 0
for path in (root / "objects" / "sha256").glob("*/*"):
    identity = "sha256:" + path.parent.name + path.name
    if not cas.verify(identity):
        raise SystemExit("object fails verification: " + identity)
    objects += 1
result["objects"] = objects
print(json.dumps(result, sort_keys=True))
