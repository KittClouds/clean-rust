from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN = ROOT / "artifacts/runs/e012-20260926-frame-decomposition-01"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(item: dict) -> str:
    return f"{item['numerator']}/{item['denominator']}"


def main() -> None:
    baseline = read(RUN / "reports/full-frame-baseline-report.json")
    autopsy = read(RUN / "reports/full-frame-baseline-autopsy-v1.json")
    lines = [
        "# E012 full-frame baseline autopsy",
        "",
        "## Result",
        "",
        f"- Samples: {baseline['sample_count']} across {baseline['paired_task_count']} pair groups, "
        f"{baseline['task_family_count']} families, and {baseline['repository_count']} repositories.",
        f"- Small observer: {baseline['lanes']['small_only']['direct_coverage']['numerator']}/48 accepted; "
        f"{baseline['lanes']['small_only']['task_completion']['numerator']}/48 completed; "
        f"{baseline['lanes']['small_only']['wrong_legal_actions']} wrong legal actions.",
        f"- Large only: {baseline['lanes']['large_only']['task_completion']['numerator']}/48 completed.",
        f"- Hybrid replay: {baseline['lanes']['hybrid']['task_completion']['numerator']}/48 completed with "
        f"{baseline['lanes']['hybrid']['large_calls']} large fallbacks.",
        f"- Admission gate: **{'PASS' if baseline['admission_gate']['passed'] else 'FAIL'}** "
        "(requires nonzero small coverage and zero wrong accepted small actions).",
        "",
        "## Paired lanes by repository",
        "",
        "| Repository | Small accepted | Small completed | Small wrong | Large completion | Hybrid completion | Hybrid large calls |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for repo in sorted(autopsy["by"]["repository_id"]):
        row = autopsy["by"]["repository_id"][repo]
        lines.append(
            f"| {repo} | {row['small_accepted']}/{row['samples']} | "
            f"{row['small_direct_correct']}/{row['samples']} | "
            f"{row['small_direct_wrong']} | {row['large_completed']}/{row['samples']} | "
            f"{row['hybrid_completed']}/{row['samples']} | "
            f"{baseline['stratified']['repository']['hybrid'][repo]['large_calls']} |"
        )
    lines.extend([
        "",
        "## Error checks",
        "",
        f"- Sealed valid-action sets versus executable candidate checks: "
        f"{autopsy['label_consistency']['mismatch_count']} mismatches across "
        f"{autopsy['label_consistency']['tasks_checked']} samples.",
        f"- Small and large output normalization errors: "
        f"{autopsy['raw_output_and_authority_audit']['small_normalization_errors']} and "
        f"{autopsy['raw_output_and_authority_audit']['large_normalization_errors']}.",
        f"- Receipt/replay checks clean on all lane executions: "
        f"{autopsy['raw_output_and_authority_audit']['presentation_verified']}/48 sample triplets and "
        f"{autopsy['raw_output_and_authority_audit']['replay_identical']}/48.",
        f"- Authority recorded zero illegal commits and zero duplicate effects in "
        f"{baseline['authority_invariants']['authorization_cases']} lane replays.",
        "",
        "The scoring path is internally consistent. All ten wrong small actions selected offered candidates whose sealed expected-valid set and executable checks both reject them.",
        "",
        "## Observable decision shape",
        "",
        "All 16 accepted small actions had applicability 1000/1000 and abstention 0/1000. Within the accepted region, those scores did not separate correct from wrong actions: 6 completed and 10 failed. The 32 other small outputs were rejected or abstained; see the task-level JSON for their decision reasons.",
        "",
        "Among 48 samples, small and large both completed 4; small alone completed 2; large alone completed 19; neither completed 23. The hybrid therefore completed 22, one fewer than large only. Small direct errors and accepted coverage are reported per family and stratum in the JSON.",
        "",
        "## Decision",
        "",
        "The frozen v5 small observer does not earn admission to E012 channel interventions on this bank. The failure is not a receipt, normalization, authority, or label-mapping defect. Preserve this baseline; do not fit thresholds or carve a post-hoc subgroup from these same outputs. Any next experiment needs a separate preregistered question or a prospectively repaired observer/task interface.",
        "",
        "This remains a 48-sample paired synthetic coding bank with three repositories. It does not establish why v5 failed here or make a broad claim about coding workflows.",
        "",
        "Detailed task, family, stratum, score, position, pairing, and invariant data are in full-frame-baseline-autopsy-v1.json.",
        "",
    ])
    target = RUN / "reports/full-frame-baseline-autopsy-v1.md"
    if target.exists():
        raise SystemExit("refusing to replace the rendered autopsy")
    target.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

