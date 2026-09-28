"""Rebuildable Ladybug custody projection. Only the daemon constructs this object."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .journal import ZERO_EVENT
from .faults import hit
from .entities import project_entities
from .projection_runtime import open_database
from .vault_projection import VAULT_DDL, project_vault

SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _literal(value: str) -> str:
    if not SAFE.fullmatch(value):
        raise ValueError("unsafe graph identifier")
    return "'" + value + "'"


class CustodyGraph:
    def __init__(self, root: Path) -> None:
        native = Path(__file__).resolve().parents[1] / "vendor/runtime-v1/native"
        dll = os.environ.get("KAMMI_LBUG_DLL", str(native / "lbug_shared.dll"))
        if dll:
            os.environ["LBUG_C_API_LIB_PATH"] = dll
        openssl_dir = os.environ.get("KAMMI_OPENSSL_DLL_DIR", str(native))
        self._dll_directory = os.add_dll_directory(openssl_dir) if openssl_dir else None
        import ladybug as lb

        self.db = open_database(root, "custody.lbdb")
        self.conn = lb.Connection(self.db)
        for ddl in (
            "CREATE NODE TABLE IF NOT EXISTS LedgerMeta(id STRING PRIMARY KEY, seq INT64, head STRING)",
            "CREATE NODE TABLE IF NOT EXISTS Artifact(id STRING PRIMARY KEY, byte_count INT64)",
            "CREATE NODE TABLE IF NOT EXISTS Event(id STRING PRIMARY KEY, seq INT64, typ STRING, payload STRING, prev STRING)",
            "CREATE NODE TABLE IF NOT EXISTS Seal(root STRING PRIMARY KEY, payload STRING)",
            "CREATE NODE TABLE IF NOT EXISTS Run(id STRING PRIMARY KEY, lab STRING)",
            "CREATE NODE TABLE IF NOT EXISTS CustodyFact(id STRING PRIMARY KEY, run_id STRING, kind STRING, subject STRING, target STRING, value STRING, evidence_id STRING, scope STRING)",
            "CREATE REL TABLE IF NOT EXISTS SealMember(FROM Seal TO Artifact)",
            "CREATE REL TABLE IF NOT EXISTS SealParent(FROM Seal TO Seal)",
            "CREATE REL TABLE IF NOT EXISTS HasEvent(FROM Run TO Event)",
            "CREATE REL TABLE IF NOT EXISTS HasFact(FROM Run TO CustodyFact)",
            "CREATE REL TABLE IF NOT EXISTS FactEvidence(FROM CustodyFact TO Artifact)",
            "CREATE NODE TABLE IF NOT EXISTS Entity(id STRING PRIMARY KEY, kind STRING, payload STRING)",
            "CREATE REL TABLE IF NOT EXISTS Link(FROM Entity TO Entity, kind STRING)",
        ) + VAULT_DDL:
            self.conn.execute(ddl)
        if not list(self.conn.execute("MATCH (m:LedgerMeta {id:'primary'}) RETURN m.seq")):
            self.conn.execute(
                f"CREATE (m:LedgerMeta {{id:'primary', seq:0, head:{_literal(ZERO_EVENT)}}})"
            )

    def position(self) -> tuple[int, str]:
        rows = list(
            self.conn.execute("MATCH (m:LedgerMeta {id:'primary'}) RETURN m.seq, m.head")
        )
        if len(rows) != 1:
            raise ValueError("custody graph metadata missing or duplicated")
        return int(rows[0][0]), str(rows[0][1])

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        if self.db is not None:
            self.db.close()
            self.db = None

    def apply(self, event: dict, event_id: str, payload: dict) -> None:
        seq, head = self.position()
        if event["seq"] <= seq:
            if event["seq"] == seq and event_id != head:
                raise ValueError("graph/journal head disagreement")
            return
        if event["seq"] != seq + 1 or event["prev"] != head:
            raise ValueError("graph/journal sequence disagreement")
        hit("projection.before")
        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.execute(
                "CREATE (e:Event {"
                f"id:{_literal(event_id)}, seq:{event['seq']}, "
                f"typ:{_literal(event['type'])}, "
                f"payload:{_literal(event['payload_artifact'])}, "
                f"prev:{_literal(event['prev'])}" "})"
            )
            hit("projection.mid_transaction")
            if event["type"] == "ArtifactRegistered":
                self.conn.execute(
                    "MERGE (a:Artifact {"
                    f"id:{_literal(payload['artifact_id'])}" "}) "
                    f"SET a.byte_count = {int(payload['byte_count'])}"
                )
            elif event["type"] == "RunCreated":
                self.conn.execute(
                    "CREATE (r:Run {"
                    f"id:{_literal(payload['run_id'])}, "
                    f"lab:{_literal(payload['lab'])}" "})"
                )
            elif event["type"] == "SealCreated":
                self.conn.execute(
                    "CREATE (s:Seal {"
                    f"root:{_literal(payload['root'])}, "
                    f"payload:{_literal(payload['seal_artifact'])}" "})"
                )
                for artifact_id in payload["direct_members"]:
                    self.conn.execute(
                        f"MATCH (s:Seal {{root:{_literal(payload['root'])}}}), "
                        f"(a:Artifact {{id:{_literal(artifact_id)}}}) "
                        "CREATE (s)-[:SealMember]->(a)"
                    )
                for parent in payload["parents"]:
                    self.conn.execute(
                        f"MATCH (s:Seal {{root:{_literal(payload['root'])}}}), "
                        f"(p:Seal {{root:{_literal(parent)}}}) "
                        "CREATE (s)-[:SealParent]->(p)"
                    )
            elif event["type"] == "FactRecorded":
                fields = {
                    "id": payload["fact_id"],
                    "run_id": payload["run_id"],
                    "kind": payload["kind"],
                    "subject": payload["subject"],
                    "target": payload["object"],
                    "value": payload["value"],
                    "evidence_id": payload["evidence_artifact"],
                    "scope": payload["scope"],
                }
                self.conn.execute(
                    "CREATE (f:CustodyFact {"
                    + ", ".join(f"{key}:{_literal(value)}" for key, value in fields.items())
                    + "})"
                )
                self.conn.execute(
                    f"MATCH (r:Run {{id:{_literal(payload['run_id'])}}}), "
                    f"(f:CustodyFact {{id:{_literal(payload['fact_id'])}}}) "
                    "CREATE (r)-[:HasFact]->(f)"
                )
                self.conn.execute(
                    f"MATCH (f:CustodyFact {{id:{_literal(payload['fact_id'])}}}), "
                    f"(a:Artifact {{id:{_literal(payload['evidence_artifact'])}}}) "
                    "CREATE (f)-[:FactEvidence]->(a)"
                )
            project_entities(self.conn, event, event_id, payload)
            project_vault(self.conn, event["type"], payload)
            self.conn.execute(
                "MATCH (m:LedgerMeta {id:'primary'}) "
                f"SET m.seq = {event['seq']}, m.head = {_literal(event_id)}"
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def counts(self) -> dict[str, int]:
        return {
            table.lower() + "s": int(list(self.conn.execute(
                f"MATCH (n:{table}) RETURN count(n)"
            ))[0][0])
            for table in ("Artifact", "Event", "Seal", "Run", "CustodyFact")
        }

    def history(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "MATCH (r:Run {id:" + _literal(run_id) + "})-[:HasFact]->(f:CustodyFact) "
            "RETURN f.id, f.kind, f.subject, f.target, f.value, f.evidence_id, f.scope "
            "ORDER BY f.kind, f.subject, f.id"
        )
        keys = ("fact_id", "kind", "subject", "object", "value", "evidence_artifact", "scope")
        return [dict(zip(keys, row)) for row in rows]

