"""Contextual memory journal; retrieval never changes custody authority."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .embedding import Embedder
from .identity import canonical, raw_id, strict_json
from .journal import EventJournal
from .memory_graph import MemoryGraph

KINDS = frozenset({"OBSERVED", "DERIVED", "INTERPRETIVE", "HYPOTHESIS", "PREFERENCE",
                   "PROCEDURE", "DECISION", "FAILURE_MODE", "RESULT_SUMMARY"})


class MemoryService:
    def __init__(self, root: Path, cas, embedder: Embedder,
                 valid_ref: Callable[[str], bool], database,
                 write_lock: threading.RLock | None = None) -> None:
        self.cas, self.embedder, self.valid_ref = cas, embedder, valid_ref
        # Ladybug permits only one writer across connections to one Database.
        self.lock = write_lock if write_lock is not None else threading.RLock()
        self.journal = EventJournal(root / "memory")
        self.records: dict[str, dict] = {}
        self.superseded: dict[str, list[str]] = {}
        self.graph = MemoryGraph(root, database)
        for event, _ in self.journal:
            self._apply(event["type"], strict_json(self.cas.get(event["payload_artifact"])))

    def _apply(self, kind: str, payload: dict) -> None:
        if kind == "MemoryRecorded":
            record = strict_json(self.cas.get(payload["record_artifact_id"]))
            identity = record["memory_id"]
            if raw_id(canonical({k: v for k, v in record.items() if k != "memory_id"})) != identity:
                raise ValueError("memory identity mismatch")
            if any(not self.valid_ref(ref) for ref in record["custody_refs"]):
                raise ValueError("memory refers to unavailable custody evidence")
            self.graph.add(record, self.cas.get(record["embedding_artifact_id"]))
            self.records[identity] = record
        elif kind == "MemorySuperseded":
            old, new = payload["old_id"], payload["new_id"]
            if old not in self.records or new not in self.records:
                raise ValueError("supersession references unknown memory")
            self.graph.supersede(new, old)
            targets = self.superseded.setdefault(old, [])
            if new not in targets:
                targets.append(new)

    def _emit(self, kind: str, payload: dict, actor: str, request_id: str) -> str:
        payload_id, _ = self.cas.put_bytes(canonical(payload))
        if request_id in self.journal.by_request:
            prior, identity = self.journal.by_request[request_id]
            if prior["type"] != kind or prior["payload_artifact"] != payload_id:
                raise ValueError("memory request ID reused for another action")
            self._apply(kind, payload)
            return identity
        event = {"schema": "KAMMI_EVENT_V1", "seq": len(self.journal.events) + 1,
                 "prev": self.journal.head, "type": kind, "payload_artifact": payload_id,
                 "actor": actor, "request_id": request_id,
                 "utc": datetime.now(timezone.utc).isoformat()}
        identity = self.journal.append(event)
        self._apply(kind, payload)
        return identity

    def record(self, *, kind: str, scope: str, text: str, actor: str,
               custody_refs: list[str], tags: list[str], request_id: str,
               confidence: float | None = None) -> tuple[str, str]:
        if kind not in KINDS or not scope or not text or len(text) > 65536:
            raise ValueError("invalid memory kind, scope, or content")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("invalid memory confidence")
        if kind in {"OBSERVED", "DERIVED"} and not custody_refs:
            raise ValueError("observed/derived memory requires custody references")
        if any(not self.valid_ref(ref) for ref in custody_refs):
            raise ValueError("unknown or corrupt custody reference")
        if len(tags) > 64 or any(not isinstance(t, str) or not t or len(t) > 160 for t in tags):
            raise ValueError("invalid memory tags")
        intent = {"kind": kind, "scope": scope, "text": text, "created_by": actor,
                  "confidence": confidence, "custody_refs": sorted(set(custody_refs)),
                  "tags": sorted(set(tags))}
        with self.lock:
            if request_id in self.journal.by_request:
                prior, event_id = self.journal.by_request[request_id]
                payload = strict_json(self.cas.get(prior["payload_artifact"]))
                if prior["type"] != "MemoryRecorded" or payload["intent_hash"] != raw_id(canonical(intent)):
                    raise ValueError("memory request ID reused")
                if payload["memory_id"] not in self.records:
                    self._apply("MemoryRecorded", payload)
                return payload["memory_id"], event_id
            embedding = self.embedder.encode([text])[0]
            embedding_id, _ = self.cas.put_bytes(embedding)
            record = {**intent, "created_at": datetime.now(timezone.utc).isoformat(),
                      "embedding_status": "READY", "embedding_artifact_id": embedding_id,
                      "embedding_model_id": self.embedder.identity,
                      "authority": "CONTEXTUAL_NOT_CUSTODY"}
            memory_id = raw_id(canonical(record))
            record["memory_id"] = memory_id
            record_id, _ = self.cas.put_bytes(canonical(record))
            event_id = self._emit("MemoryRecorded", {
                "memory_id": memory_id, "record_artifact_id": record_id,
                "intent_hash": raw_id(canonical(intent)),
            }, actor, request_id)
            return memory_id, event_id

    def get(self, identity: str) -> dict:
        if identity not in self.records:
            raise ValueError("unknown memory")
        return {**self.records[identity], "superseded_by": self.superseded.get(identity, []),
                "grounding": "EVIDENCE_CITED" if self.records[identity]["custody_refs"] else "UNGROUNDED"}

    def supersede(self, old_id: str, new_id: str, actor: str, request_id: str) -> str:
        with self.lock:
            old, new = self.get(old_id), self.get(new_id)
            if old_id == new_id or old["scope"] != new["scope"]:
                raise ValueError("invalid memory supersession")
            seen, pending = set(), [new_id]
            while pending:
                current = pending.pop()
                if current == old_id:
                    raise ValueError("memory supersession cycle")
                if current not in seen:
                    seen.add(current)
                    pending.extend(self.superseded.get(current, []))
            return self._emit("MemorySuperseded", {"old_id": old_id, "new_id": new_id},
                              actor, request_id)

    def trace(self, identity: str) -> dict:
        record = self.get(identity)
        refs = [{"custody_ref": ref, "verified": self.valid_ref(ref)}
                for ref in record["custody_refs"]]
        return {"memory_id": identity, "authority": "CONTEXTUAL_NOT_CUSTODY", "references": refs}

    def search(self, query: str, *, scope: str, actor: str, request_id: str,
               mode: str = "hybrid", limit: int = 10, grounded_only: bool = False,
               exclude_kinds: list[str] | None = None, include_superseded: bool = False,
               seed_memory: str | None = None) -> dict:
        if mode not in {"fts", "vector", "graph", "hybrid"} or not 1 <= limit <= 100:
            raise ValueError("invalid memory search mode or limit")
        if len(query) > 4096 or not scope:
            raise ValueError("invalid memory query or scope")
        with self.lock:
            intent = {"query": query, "scope": scope, "actor": actor, "mode": mode,
                      "limit": limit, "grounded_only": grounded_only,
                      "exclude_kinds": exclude_kinds or [], "include_superseded": include_superseded,
                      "seed_memory": seed_memory}
            intent_hash = raw_id(canonical(intent))
            if request_id in self.journal.by_request:
                event, _ = self.journal.by_request[request_id]
                prior = strict_json(self.cas.get(event["payload_artifact"]))
                if event["type"] != "MemoryRetrieved" or prior.get("intent_hash") != intent_hash:
                    raise ValueError("memory search request ID reused")
                return strict_json(self.cas.get(prior["response_artifact_id"]))
            def eligible(identity: str) -> bool:
                record = self.records[identity]
                return (record["scope"] == scope
                        and (not grounded_only or bool(record["custody_refs"]))
                        and record["kind"] not in (exclude_kinds or [])
                        and (include_superseded or identity not in self.superseded))

            scores: dict[str, dict] = {}
            # Adaptive overfetch preserves trust filtering without requesting the
            # entire HNSW corpus for an ordinary top-ten query.
            maximum = max(1, len(self.records))
            def filtered_pool(fetch):
                count = min(maximum, max(32, limit * 4))
                while True:
                    rows = fetch(count)
                    if sum(eligible(i) for i, _ in rows) >= limit or count == maximum or len(rows) < count:
                        return rows
                    count = min(maximum, count * 2)
            lists = {}
            if self.records and mode in {"fts", "hybrid"}:
                lists["fts"] = filtered_pool(lambda count: self.graph.fts(query, count))
            if self.records and mode in {"vector", "hybrid"}:
                query_vector = self.embedder.encode([query])[0]
                lists["vector"] = filtered_pool(lambda count: self.graph.vector(query_vector, count))
            if seed_memory and mode in {"graph", "hybrid"}:
                self.get(seed_memory)
                lists["graph"] = [(identity, 1.0) for identity in self.graph.neighbors(seed_memory)]
            for surface, rows in lists.items():
                for rank, (identity, score) in enumerate(rows, 1):
                    if eligible(identity):
                        entry = scores.setdefault(identity, {"fused": 0.0, "surfaces": {}})
                        entry["fused"] += 1.0 / (60 + rank)
                        entry["surfaces"][surface] = score
            ids = sorted(scores, key=lambda i: (-scores[i]["fused"], i))[:limit]
            result = {"results": [{"memory": self.get(i), "scores": scores[i],
                                   "reason": sorted(scores[i]["surfaces"])} for i in ids],
                      "authority": "CONTEXTUAL_NOT_CUSTODY", "mode": mode}
            response_id, _ = self.cas.put_bytes(canonical(result))
            self._emit("MemoryRetrieved", {"query": query, "scope": scope, "mode": mode,
                       "result_ids": ids, "request_id": request_id, "intent_hash": intent_hash,
                       "response_artifact_id": response_id}, actor, request_id)
            return result

    def close(self) -> None:
        self.graph.close()
