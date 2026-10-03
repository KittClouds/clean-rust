"""Render the six self-contained E013-D Rust repository templates."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPOSITORIES = [
    ("e013-d-ledgerleaf", "ledgerleaf", "ledger leaf event ledger", 0),
    ("e013-d-parcelpath", "parcelpath", "parcel delivery state library", 1),
    ("e013-d-queueforge", "queueforge", "queue lifecycle toolkit", 2),
    ("e013-d-cacheweave", "cacheweave", "cache resource policy crate", 3),
    ("e013-d-receiptline", "receiptline", "receipt processing library", 4),
    ("e013-d-signalharbor", "signalharbor", "event gateway support crate", 5),
]
CASE_NAMES = [
    "opal", "birch", "mauve", "cinder", "willow", "moss",
]
FAMILIES = [
    "boundary", "error_context", "transition", "cleanup",
    "ordering", "limits", "compat", "atomic_batch",
]


def _case_order(repo_index: int, family_index: int) -> list[str]:
    # A repo/family-specific permutation keeps source order unrelated to cell slots.
    return sorted(
        CASE_NAMES,
        key=lambda name: ((CASE_NAMES.index(name) * 5 + repo_index * 3 + family_index * 2) % len(CASE_NAMES)),
    )


def _params(repo_index: int, family: str, slot: int) -> dict[str, int | bool]:
    pair = slot // 2
    if family == "boundary":
        low = -3 + repo_index + pair % 3
        return {"low": low, "high": low + 4 + pair % 2, "inclusive_high": slot % 2 == 0}
    if family == "error_context":
        return {"policy": 0 if slot % 2 == 0 else 1, "context": 1 << ((repo_index + pair) % 6)}
    if family == "transition":
        event = 2 if slot % 2 == 0 else 4
        return {"from": 1 + (repo_index % 2), "event": event, "to": 3 if event == 2 else 5}
    if family == "cleanup":
        return {"release_on_success": slot % 2 == 1}
    if family == "ordering":
        return {"tie_ascending": slot % 2 == 0}
    if family == "limits":
        return {"inclusive": slot % 2 == 0, "limit": 64 + repo_index * 7 + (slot // 2) * 4}
    if family == "compat":
        return {"sentinel": -1 if slot % 2 == 0 else 0}
    if family == "atomic_batch":
        return {"atomic": slot % 2 == 0}
    raise ValueError(f"unknown family {family}")


def _function_name(family: str, case: str) -> str:
    prefixes = {
        "boundary": "contains", "error_context": "annotate",
        "transition": "advance", "cleanup": "finish",
        "ordering": "precedes", "limits": "fits",
        "compat": "legacy", "atomic_batch": "apply",
    }
    return f"{prefixes[family]}_{case}"


def _baseline(family: str, p: dict[str, int | bool]) -> str:
    if family == "boundary":
        return "value > low && value < high"
    if family == "error_context":
        return "Fault { code: 0, context: added }"
    if family == "transition":
        return f"if event == {p['event']} {{ {p['to']} }} else {{ state }}"
    if family == "cleanup":
        return "already_released || (acquired && succeeded)"
    if family == "ordering":
        return "left_priority > right_priority"
    if family == "limits":
        return "count * size <= limit"
    if family == "compat":
        return f"value.unwrap_or({int(p['sentinel']) + 1})"
    if family == "atomic_batch":
        return "for (index, item) in batch.iter().enumerate() { state.push(*item); if fail_at == Some(index) { return Err(index); } } Ok(())"
    raise ValueError(f"unknown family {family}")


def _module_source(family: str, repo_index: int) -> str:
    family_index = FAMILIES.index(family)
    names = _case_order(repo_index, family_index)
    lines: list[str] = []
    if family == "error_context":
        lines += ["#[derive(Clone, Copy, Debug, PartialEq, Eq)]", "pub struct Fault { pub code: i64, pub context: u32 }", ""]
    if family == "ordering":
        lines += ["#[derive(Clone, Copy, Debug, PartialEq, Eq)]", "pub struct Entry { pub priority: i64, pub tick: i64, pub id: i64 }", ""]
    for name in names:
        slot = CASE_NAMES.index(name) * 2
        p = _params(repo_index, family, slot)
        fn = _function_name(family, name)
        body = _baseline(family, p)
        if family == "boundary":
            lines.append(f"pub fn {fn}(value: i64, low: i64, high: i64) -> bool {{ {body} }}")
        elif family == "error_context":
            lines.append(f"pub fn {fn}(code: i64, prior: u32, added: u32) -> Fault {{ let _ = code; let _ = prior; {body} }}")
        elif family == "transition":
            lines.append(f"pub fn {fn}(state: i64, event: i64) -> i64 {{ {body} }}")
        elif family == "cleanup":
            lines.append(f"pub fn {fn}(acquired: bool, succeeded: bool, already_released: bool) -> bool {{ {body} }}")
        elif family == "ordering":
            lines.append(f"pub fn {fn}(left: Entry, right: Entry) -> bool {{ let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); {body} }}")
        elif family == "limits":
            lines.append(f"pub fn {fn}(count: u64, size: u64, limit: u64) -> bool {{ {body} }}")
        elif family == "compat":
            lines.append(f"pub fn {fn}(value: Option<i64>) -> i64 {{ {body} }}")
        elif family == "atomic_batch":
            lines.append(f"pub fn {fn}(state: &mut Vec<i64>, batch: &[i64], fail_at: Option<usize>) -> Result<(), usize> {{ {body} }}")

    lines.append("")
    lines.append("pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {")
    lines.append("    let arg = |index: usize| *args.get(index).unwrap_or(&0);")
    lines.append("    match name {")
    for name in CASE_NAMES:
        fn = _function_name(family, name)
        if family == "boundary":
            expr = f"{fn}(arg(0), arg(1), arg(2)).to_string()"
        elif family == "error_context":
            expr = f"{{ let value = {fn}(arg(0), arg(1) as u32, arg(2) as u32); format!(\"{{}}|{{}}\", value.code, value.context) }}"
        elif family == "transition":
            expr = f"{fn}(arg(0), arg(1)).to_string()"
        elif family == "cleanup":
            expr = f"{fn}(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()"
        elif family == "ordering":
            expr = f"{{ let left = Entry {{ priority: arg(0), tick: arg(1), id: arg(2) }}; let right = Entry {{ priority: arg(3), tick: arg(4), id: arg(5) }}; {fn}(left, right).to_string() }}"
        elif family == "limits":
            expr = f"{fn}(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()"
        elif family == "compat":
            expr = f"{{ let value = if arg(0) == 0 {{ None }} else {{ Some(arg(1)) }}; {fn}(value).to_string() }}"
        else:
            expr = f"{{ let mut state: Vec<i64> = (0..arg(0).max(0)).collect(); let batch: Vec<i64> = (0..arg(1).max(0)).map(|i| 100 + i).collect(); let fail = if arg(2) < 0 {{ None }} else {{ Some(arg(2) as usize) }}; let result = {fn}(&mut state, &batch, fail); let result_text = match result {{ Ok(()) => \"ok\".to_owned(), Err(index) => format!(\"err:{{}}\", index) }}; let sum: i64 = state.iter().sum(); format!(\"{{}}|{{}}|{{}}\", result_text, state.len(), sum) }}"
        lines.append(f"        \"{fn}\" => Some({expr}),")
    lines += ["        _ => None,", "    }", "}", ""]
    return "\n".join(line for line in lines if line is not None)


def _root_lib() -> str:
    lines = [f"pub mod {family};" for family in FAMILIES]
    lines += ["", "pub const REPOSITORY_ID: &str = env!(\"CARGO_PKG_NAME\");", "", "pub fn evaluate(family: &str, name: &str, args: &[i64]) -> Option<String> {", "    match family {"]
    for family in FAMILIES:
        lines.append(f"        \"d.{family.replace('_', '-')}\" => {family}::evaluate(name, args),")
    lines += ["        _ => None,", "    }", "}", ""]
    return "\n".join(lines)


HARNESS = r'''use std::fs;
use std::path::PathBuf;

pub fn check_rows(path: PathBuf) {
    let contents = fs::read_to_string(path).expect("fixture must be readable");
    let mut seen = 0usize;
    for (line_no, line) in contents.lines().enumerate() {
        if line.is_empty() || line.starts_with('#') { continue; }
        let fields: Vec<&str> = line.split('\t').collect();
        assert_eq!(fields.len(), 9, "fixture row {} needs 9 fields", line_no + 1);
        let args: Vec<i64> = fields[2..8].iter().map(|value| value.parse().unwrap_or(0)).collect();
        let actual = e013_repo::evaluate(fields[0], fields[1], &args).expect("known family and case");
        assert_eq!(actual, fields[8], "fixture row {}", line_no + 1);
        seen += 1;
    }
    assert!(seen > 0, "fixture must contain at least one row");
}
'''


def _test_source(kind: str) -> str:
    env_name = "E013_VISIBLE_ROOT" if kind == "visible" else "E013_HIDDEN_ADJUDICATOR"
    test_name = "visible_rows" if kind == "visible" else "hidden_rows"
    return f'''#[path = "support/harness.rs"] mod harness;

#[test]
fn {test_name}() {{
    let path = std::env::var_os("{env_name}").expect("core supplies separated fixture path");
    harness::check_rows(path.into());
}}
'''


def _catalog() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for repo_id, _package, _description, repo_index in REPOSITORIES:
        for family in FAMILIES:
            for slot in range(12):
                case = CASE_NAMES[slot % len(CASE_NAMES)]
                rows.append({
                    "repo_id": repo_id,
                    "family_id": "d." + family.replace("_", "-"),
                    "task_slot": slot,
                    "function_name": _function_name(family, case),
                    "family": family,
                    "params": _params(repo_index, family, slot),
                })
    return rows


def render() -> None:
    catalog = _catalog()
    (ROOT / "case_catalog.ndjson").write_text(
        "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in catalog),
        encoding="utf-8",
    )
    (ROOT / "case_catalog.json").unlink(missing_ok=True)
    for repo_id, package, description, repo_index in REPOSITORIES:
        repo_root = ROOT / "templates" / repo_id
        (repo_root / "src").mkdir(parents=True, exist_ok=True)
        (repo_root / "tests").mkdir(parents=True, exist_ok=True)
        (repo_root / "Cargo.toml").write_text(
            f'''[package]\nname = "{package}"\nversion = "0.1.0"\nedition = "2021"\npublish = false\ndescription = "{description}; frozen E013-D construction template"\n\n[lib]\nname = "e013_repo"\npath = "src/lib.rs"\n''',
            encoding="utf-8",
        )
        (repo_root / "src" / "lib.rs").write_text(_root_lib(), encoding="utf-8")
        for family in FAMILIES:
            (repo_root / "src" / f"{family}.rs").write_text(_module_source(family, repo_index), encoding="utf-8")
        (repo_root / "tests" / "support").mkdir(parents=True, exist_ok=True)
        (repo_root / "tests" / "support" / "harness.rs").write_text(HARNESS, encoding="utf-8")
        (repo_root / "tests" / "harness.rs").unlink(missing_ok=True)
        for kind in ("visible", "hidden"):
            (repo_root / "tests" / f"e013_{kind}.rs").write_text(_test_source(kind), encoding="utf-8")


if __name__ == "__main__":
    render()
