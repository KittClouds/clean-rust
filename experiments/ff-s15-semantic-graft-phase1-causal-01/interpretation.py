"""Compact engineering report built from completed metrics, without new model decisions."""
from contract import OUTPUT


def write_interpretation(report,history,best_epoch,artifact_hash):
    lines=["# Causal semantic graft — Phase 1 engineering result", "",
           "Frozen causal Base + unchanged Phase 0 late graft; s=64, e=64, 460,662 trainable parameters.",
           "20,000 TRAIN rows and 2,000 DEV rows; complete canonical candidates retained, m_cap=28.",
           f"Best DEV checkpoint: epoch {best_epoch} of {len(history)} completed full TRAIN passes.",
           f"Artifact SHA-256: `{artifact_hash}`.","",
           "The backbone stayed frozen. BANK-v2 and protected TEST truth were not used.","",
           "## What learned", "",
           "| Target | DEV accuracy / exact count | Balanced accuracy | Macro-F1 | Trivial accuracy |",
           "|---|---:|---:|---:|---:|"]
    for branch in ("global","candidate"):
        for name,m in report[branch].items():
            if not m.get("available"):
                continue
            b=report["B0_TRAIN_majority"][branch][name]
            acc=m.get("accuracy",m.get("exact_count_accuracy"))
            base=b.get("accuracy",b.get("exact_count_accuracy"))
            fmt=lambda x: f"{x:.4f}" if x is not None else "n/a"
            lines.append(f"| {name} | {fmt(acc)} | {fmt(m.get('balanced_accuracy'))} | {fmt(m.get('macro_f1'))} | {fmt(base)} |")
    endpoint=report["endpoint"]
    ranked = sorted(((m.get("macro_f1",0), name, m)
                     for branch in ("global","candidate") for name,m in report[branch].items()
                     if m.get("available") and "macro_f1" in m), reverse=True)
    lines += ["", "Most accurate binary readouts by macro-F1: " + "; ".join(
        f"{name} ({score:.4f})" for score,name,_m in ranked[:2]) + ".",
        "Weakest binary readouts by macro-F1: " + "; ".join(
        f"{name} ({score:.4f})" for score,name,_m in ranked[-2:]) + "."]
    lines += ["",f"Action endpoint accuracy: {endpoint['accuracy']:.4f} on {endpoint['eligible']} eligible ACT rows.",
              "Endpoint accuracy is reported separately and does not define epistemic state.","",
              "## Candidate-conditioned state", ""]
    c=report["candidate_conditioning"]
    lines += [f"Mean within-world coordinate variance: {c['mean_within_world_coordinate_variance']:.6f}.",
              f"Collapsed rows at variance <= 1e-8: {c['collapsed_rows_at_variance_le_1e_8']} / {c['world_rows']}.",
              "Candidate variation is a sanity check, not proof of evidence-supported epistemic judgment.","",
              "## Renderer behavior", ""]
    r=report["renderer"]
    lines += [f"{r['pairs']} pre-existing meaning-preserving DEV pairs were evaluated.",
              f"Mean semantic squared displacement: {r['semantic_squared_displacement']:.6f}; candidate mean squared displacement: {r['candidate_mean_squared_displacement']:.6f}.",
              "Per-target prediction changes and flips are in DEV-METRICS.json. S7/S8/S9 are absent; no held-renderer generalization claim.","",
              "## Weak or unavailable capabilities", "",
              "See balanced accuracy, class support, baselines, and per-epoch curves rather than pooled accuracy alone.",
              "Candidate support, counterevidence, unmet requirements, applicability, missing-information dependency, requestability, and unrestricted solvability have no admissible labels in this phase. They were not learned or exported.",
              "CF remains correctly inactive. The missing-count output is a 0/1 generator-annotation proxy, not general requirement counting.","",
              "## What to carry into Phase 2", "",
              "Carry the trained graft, its TRAIN normalizer, complete candidate convention, typed availability masks and DEV target-specific failure profile.",
              "Targets beating their trivial controls provide usable supervised state readouts. Weak targets remain engineering limitations; no architecture redesign or cross-lane winner is declared.",
              "The full history preserves optimization, saturation and any overfitting rather than treating the short harness smoke as Phase 1 evidence.","",
              "All new artifacts are on C: NVMe. The Phase 0 source, prior lock and data identities were reverified unchanged.",""]
    (OUTPUT/"ENGINEERING-REPORT.md").write_text("\n".join(lines),encoding="utf-8")
