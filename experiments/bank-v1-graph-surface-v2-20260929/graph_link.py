"""Candidate-list normalization for truth-bearing link-completion queries."""
from __future__ import annotations


def candidates_with_target(query):
    """Keep a valid self-loop target rankable when ordinary candidates omit the subject."""
    indexes = query["candidate_indices"]
    lexical = query["candidate_lex_types"]
    identifiers = query["candidate_id_types"]
    target = int(query["target_idx"])
    if len(indexes) != len(lexical) or len(indexes) != len(identifiers):
        raise ValueError("candidate feature arrays are misaligned")
    if target in indexes:
        return indexes, lexical, identifiers
    return ([*indexes, target], [*lexical, query["lex_target"]],
            [*identifiers, query["id_type_target"]])
