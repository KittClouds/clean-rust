"""Compact generic graph ontology; receipts/specifications remain artifact kinds."""


def project_entities(conn, event, event_id, payload):
    def node(identity, kind, data=event["payload_artifact"]):
        conn.execute("MERGE (n:Entity {id:$id}) SET n.kind=$kind, n.payload=$payload",
                     {"id": identity, "kind": kind, "payload": data})
        return identity

    def edge(source, target, kind):
        conn.execute("MATCH (a:Entity {id:$a}), (b:Entity {id:$b}) MERGE (a)-[r:Link {kind:$kind}]->(b)",
                     {"a": source, "b": target, "kind": kind})

    node(event_id, "Event")
    fields = {"run_id": "Run", "stage_id": "Stage", "actor_id": "Actor", "lab": "Lab",
              "attempt_id": "Attempt", "resource_id": "Resource", "lease_id": "Lease",
              "panel_id": "Panel", "adapter_id": "Adapter", "authorization_id": "Authorization",
              "worker_actor_id": "Agent", "host": "Host", "bundle_artifact_id": "RemoteBundle"}
    ids = {}
    for field, kind in fields.items():
        value = payload.get(field)
        if isinstance(value, str):
            ids[field] = node(kind + ":" + value, kind)
            edge(event_id, ids[field], "CITES")
    for field in ("artifact_id", "evidence_artifact", "source_artifact_id", "derived_view_id",
                  "receipt_artifact_id", "implementation_artifact"):
        if isinstance(payload.get(field), str):
            identity = node("Artifact:" + payload[field], "Artifact")
            edge(event_id, identity, "CITES")
    if "run_id" in ids:
        edge(ids["run_id"], event_id, "HAS_EVENT")
        for field, relation in (("stage_id", "HAS_STAGE"), ("attempt_id", "HAS_ATTEMPT"),
                                ("lab", "BELONGS_TO"), ("actor_id", "EXECUTED_BY"),
                                ("resource_id", "USES_RESOURCE"), ("host", "RUNS_ON")):
            if field in ids:
                edge(ids["run_id"], ids[field], relation)
    if event["type"] == "SealCreated":
        seal = node("Seal:" + payload["root"], "Seal")
        for member in payload["direct_members"]:
            artifact = node("Artifact:" + member, "Artifact")
            edge(artifact, seal, "SEALED_BY")
        for parent in payload["parents"]:
            parent_id = node("Seal:" + parent, "Seal")
            edge(seal, parent_id, "PARENT_SEAL")
