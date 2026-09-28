"""Runs the unmodified Python Library daemon with a fixed clock (differential tests only).

`KAMMI_TEST_CLOCK=<ISO-8601 UTC>` pins `datetime.now()` inside the Library modules that read
the clock (authority, core, leases, memory, policy), so the Python and Rust daemons mint the
same event and memory identities for the same requests. The Python tree is not modified;
the patch lives only in this process.
"""
import datetime as _dt
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent / "kammi-ledger"))

FIXED = _dt.datetime.fromisoformat(os.environ["KAMMI_TEST_CLOCK"].replace("Z", "+00:00"))


class FixedDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED.astimezone(tz) if tz is not None else FIXED.replace(tzinfo=None)


def install():
    from ledgerd import authority, core, leases, memory, policy

    for module in (authority, core, leases, memory, policy):
        module.datetime = FixedDatetime
    if os.environ.get("KAMMI_TRACE_MEMORY_GRAPH") == "1":
        trace_memory_graph()


def trace_memory_graph():
    """Diagnostic: log FTS rebuilds and base rows, mirroring KAMMI_PROJECTOR_TRACE."""
    from ledgerd import memory_graph

    graph = memory_graph.MemoryGraph
    original_indexes, original_execute_fts = graph.indexes, graph.fts

    def indexes(self, *, lexical=False):
        before = self.fts_rebuilds
        original_indexes(self, lexical=lexical)
        if self.fts_rebuilds != before:
            print(f"[python-trace] fts rebuild #{self.fts_rebuilds} indexed={self.indexed_count}", file=sys.stderr, flush=True)

    def fts(self, query, count):
        self.indexes(lexical=True)
        base = [(str(r[0]), float(r[1])) for r in self.conn.execute(
            "CALL QUERY_FTS_INDEX('Memory', 'memory_text', $query, TOP := $count) RETURN node.id, score ORDER BY score DESC, node.id",
            {"query": query, "count": count})]
        rows = sorted((i[7:15], s) for i, s in base)
        print(f"[python-trace] fts base count={count} records={len(self.record_ids)} delta={len(self.delta_ids)} rows={rows}", file=sys.stderr, flush=True)
        return original_execute_fts(self, query, count)

    graph.indexes, graph.fts = indexes, fts


if __name__ == "__main__":
    install()
    from ledgerd.api import main

    main()
