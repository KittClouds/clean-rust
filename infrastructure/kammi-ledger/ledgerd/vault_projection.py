"""Phoenix vault rows in the Library's single Ladybug projection."""
from __future__ import annotations


VAULT_DDL = (
    "CREATE NODE TABLE IF NOT EXISTS PhoenixVault(id STRING PRIMARY KEY, owner STRING, source_epoch INT64, generation_id INT64, generation_epoch INT64, manifest STRING, reader_source STRING, reader_revision INT64, reader_offset INT64)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixSource(id STRING PRIMARY KEY, vault_id STRING, source_id STRING, revision INT64, artifact STRING, byte_count INT64, epoch INT64)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixGeneration(id STRING PRIMARY KEY, vault_id STRING, generation_id INT64, source_epoch INT64, manifest STRING)",
    "CREATE NODE TABLE IF NOT EXISTS PhoenixProductPrimary(id STRING PRIMARY KEY, vault_id STRING, source_epoch INT64, receipt STRING)",
    "CREATE REL TABLE IF NOT EXISTS PhoenixHasSource(FROM PhoenixVault TO PhoenixSource)",
    "CREATE REL TABLE IF NOT EXISTS PhoenixHasGeneration(FROM PhoenixVault TO PhoenixGeneration)",
    "CREATE REL TABLE IF NOT EXISTS PhoenixHasProductPrimary(FROM PhoenixVault TO PhoenixProductPrimary)",
)


def project_vault(conn, kind: str, payload: dict) -> None:
    if kind == "VaultCreated":
        conn.execute(
            "CREATE (v:PhoenixVault {id:$id, owner:$owner, source_epoch:0, generation_id:0, generation_epoch:0, manifest:'', reader_source:'', reader_revision:0, reader_offset:0})",
            {"id": payload["vault_id"], "owner": payload["owner_actor"]},
        )
    elif kind == "VaultSourceCommitted":
        source_key = payload["vault_id"] + ":" + payload["source_id"]
        conn.execute(
            "MERGE (s:PhoenixSource {id:$id}) SET s.vault_id=$vault, s.source_id=$source, s.revision=$revision, s.artifact=$artifact, s.byte_count=$bytes, s.epoch=$epoch",
            {"id": source_key, "vault": payload["vault_id"],
             "source": payload["source_id"], "revision": payload["revision"],
             "artifact": payload["artifact_id"], "bytes": payload["byte_count"],
             "epoch": payload["epoch"]},
        )
        conn.execute("MATCH (v:PhoenixVault {id:$id}) SET v.source_epoch=$epoch",
                     {"id": payload["vault_id"], "epoch": payload["epoch"]})
        conn.execute(
            "MATCH (v:PhoenixVault {id:$vault}), (s:PhoenixSource {id:$source}) MERGE (v)-[:PhoenixHasSource]->(s)",
            {"vault": payload["vault_id"], "source": source_key},
        )
    elif kind == "VaultGenerationSelected":
        generation_key = payload["vault_id"] + ":" + str(payload["generation_id"])
        conn.execute(
            "CREATE (g:PhoenixGeneration {id:$id, vault_id:$vault, generation_id:$generation, source_epoch:$epoch, manifest:$manifest})",
            {"id": generation_key, "vault": payload["vault_id"],
             "generation": payload["generation_id"], "epoch": payload["source_epoch"],
             "manifest": payload["manifest_artifact_id"]},
        )
        conn.execute(
            "MATCH (v:PhoenixVault {id:$id}) SET v.generation_id=$generation, v.generation_epoch=$epoch, v.manifest=$manifest",
            {"id": payload["vault_id"], "generation": payload["generation_id"],
             "epoch": payload["source_epoch"], "manifest": payload["manifest_artifact_id"]},
        )
        conn.execute(
            "MATCH (v:PhoenixVault {id:$vault}), (g:PhoenixGeneration {id:$generation}) MERGE (v)-[:PhoenixHasGeneration]->(g)",
            {"vault": payload["vault_id"], "generation": generation_key},
        )
    elif kind == "VaultReaderPositionSet":
        conn.execute(
            "MATCH (v:PhoenixVault {id:$id}) SET v.reader_source=$source, v.reader_revision=$revision, v.reader_offset=$offset",
            {"id": payload["vault_id"], "source": payload["source_id"],
             "revision": payload["revision"], "offset": payload["offset"]},
        )
    elif kind == "VaultProductPrimarySelected":
        conn.execute("CREATE (p:PhoenixProductPrimary {id:$id, vault_id:$id, source_epoch:$epoch, receipt:$receipt})",
            {"id": payload["vault_id"], "epoch": payload["source_epoch"],
             "receipt": payload["receipt_artifact_id"]})
        conn.execute("MATCH (v:PhoenixVault {id:$id}), (p:PhoenixProductPrimary {id:$id}) MERGE (v)-[:PhoenixHasProductPrimary]->(p)",
                     {"id": payload["vault_id"]})
