"""Read-only interpretation of typed custody assertions for any lab."""

from __future__ import annotations


def summarize(facts: list[dict]) -> dict:
    heads = [fact for fact in facts if fact["kind"] == "HEAD"]
    attempts = [fact for fact in facts if fact["kind"] == "ATTEMPT"]
    supersessions = [fact for fact in facts if fact["kind"] == "SUPERSESSION"]
    contacts = [fact for fact in facts if fact["kind"] == "CONTACT"]
    accesses = [fact for fact in facts if fact["kind"] == "EVIDENCE_ACCESS"]
    edges = {fact["subject"]: fact["object"] for fact in supersessions}
    chains: list[list[str]] = []
    for head in heads:
        chain = [head["object"]]
        seen = set(chain)
        while chain[-1] in edges:
            predecessor = edges[chain[-1]]
            if predecessor in seen:
                raise ValueError("supersession cycle")
            chain.append(predecessor)
            seen.add(predecessor)
        chains.append(chain)
    positive_contacts = [fact for fact in contacts if fact["value"] == "YES"]
    contact_state = "YES_IN_CITED_SCOPE" if positive_contacts else "UNKNOWN_GLOBALLY"
    return {
        "heads": heads,
        "stopped_attempts": [fact for fact in attempts if fact["value"] == "STOP"],
        "other_attempts": [fact for fact in attempts if fact["value"] != "STOP"],
        "supersessions": supersessions,
        "head_predecessor_chains": chains,
        "contact_assertions": contacts,
        "contact_global_state": contact_state,
        "evidence_access_assertions": accesses,
        "authorization_conferred": False,
    }
