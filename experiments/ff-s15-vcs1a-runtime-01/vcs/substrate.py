"""The substrate comparison: one canonical semantic state as the common reference frame, several substrates estimating it.

                 canonical semantic state z*                 (the reference envelopes)
                    |                   |
            substrate A estimate   substrate B estimate      (envelopes with their own producer_bundle_id / representation_id)
                    |                   |
            the SAME frozen authority applied to each, unchanged

The question this answers is not "whose head is more confident" but "which substrate reconstructs the useful control state more faithfully and robustly", read through the authority: how often the
substrate's estimated state yields the same typed disposition as the canonical state, and how far harm, coverage and cost fall short of what the canonical state achieves. Cases must pair up exactly: the same
case ids and the same truth and context in every substrate and in the reference; only the envelope differs."""
from __future__ import annotations

from . import harness as H
from .authority import Authority
from .canon import VcsError, canonical
from .schema import Schema


def _check_paired(reference: list, other: list, name: str) -> None:
    if [c["case_id"] for c in reference] != [c["case_id"] for c in other]:
        raise VcsError(f"substrate {name}: case ids differ from the reference")
    for a, b in zip(reference, other):
        if canonical(a["truth"]) != canonical(b["truth"]) or canonical(a["context"]) != canonical(b["context"]):
            raise VcsError(f"substrate {name}: case {a['case_id']} differs from the reference in truth or context (only the envelope may differ)")


def run_substrate_comparison(*, schema: Schema, authority: Authority, reference: list, substrates: dict) -> dict:
    """Applies one frozen authority to the reference envelopes and to each substrate's estimated envelopes."""
    for c in reference:
        H.check_case(schema, c)
    ref_outs, ref_receipts = H.run_policy(H.vector_decider(authority), reference)
    ref_m = H.metrics(ref_outs)
    ref_types = [r["decision"]["disposition"]["type"] for r in ref_receipts]
    ref_disp = [canonical(r["decision"]["disposition"]) for r in ref_receipts]
    report = {"authority_id": authority.authority_id, "reference": ref_m, "substrates": {}}
    for name, cases in substrates.items():
        _check_paired(reference, cases, name)
        for c in cases:
            H.check_case(schema, c)
        outs, receipts = H.run_policy(H.vector_decider(authority), cases)
        m = H.metrics(outs)
        types = [r["decision"]["disposition"]["type"] for r in receipts]
        confusion: dict = {}
        for a, b in zip(ref_types, types):
            confusion.setdefault(a, {}).setdefault(b, 0)
            confusion[a][b] += 1
        n = len(cases)
        report["substrates"][name] = {
            "metrics": m,
            "shortfall_vs_reference": {k: ref_m[k] - m[k] for k in ("coverage",)} | {k: m[k] - ref_m[k] for k in ("harm", "cost")},
            "type_agreement": sum(a == b for a, b in zip(ref_types, types)) / n,
            "disposition_agreement": sum(a == canonical(r["decision"]["disposition"]) for a, r in zip(ref_disp, receipts)) / n,
            "unknown_region_rate": sum(1 for r in receipts if r["decision"]["unknown"]) / n,
            "confusion_reference_to_substrate": confusion,
        }
    return report
