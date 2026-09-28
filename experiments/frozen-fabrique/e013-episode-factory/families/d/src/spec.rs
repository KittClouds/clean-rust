use std::sync::OnceLock;

use serde::Deserialize;

pub const FAMILY_IDS: [&str; 8] = [
    "d.boundary",
    "d.error-context",
    "d.transition",
    "d.cleanup",
    "d.ordering",
    "d.limits",
    "d.compat",
    "d.atomic-batch",
];

pub const CASE_NAMES: [&str; 12] = [
    "opal", "birch", "mauve", "cinder", "willow", "moss",
    "opal", "birch", "mauve", "cinder", "willow", "moss",
];

#[derive(Clone, Debug, Deserialize)]
pub struct CaseRow {
    pub repo_id: String,
    pub family_id: String,
    pub task_slot: u16,
    pub function_name: String,
    pub family: String,
    pub params: serde_json::Map<String, serde_json::Value>,
}

fn catalog() -> &'static [CaseRow] {
    static CATALOG: OnceLock<Vec<CaseRow>> = OnceLock::new();
    CATALOG.get_or_init(|| {
        include_str!("../case_catalog.ndjson")
            .lines()
            .map(|line| serde_json::from_str(line).expect("D catalog row is valid JSON"))
            .collect()
    })
}

pub fn find_case(repo_id: &str, family_id: &str, slot: u16) -> Option<&'static CaseRow> {
    catalog().iter().find(|row| {
        row.repo_id == repo_id && row.family_id == family_id && row.task_slot == slot
    })
}

pub fn int(row: &CaseRow, key: &str) -> i64 {
    row.params.get(key).and_then(|value| value.as_i64()).unwrap_or_default()
}

pub fn boolean(row: &CaseRow, key: &str) -> bool {
    row.params.get(key).and_then(|value| value.as_bool()).unwrap_or(false)
}

pub fn task_text(row: &CaseRow) -> String {
    let function = &row.function_name;
    match row.family.as_str() {
        "boundary" => {
            let low = int(row, "low");
            let high = int(row, "high");
            let upper = if boolean(row, "inclusive_high") { "inclusive" } else { "exclusive" };
            format!(
                "Update `{function}` in `src/boundary.rs` to accept values from {low} through {high}, with an inclusive lower endpoint and an {upper} upper endpoint. Reject every value outside that interval and preserve the public function signature."
            )
        }
        "error_context" => {
            if int(row, "policy") == 0 {
                format!("Update `{function}` in `src/error_context.rs` to preserve the original fault code and union the added layer bit into the existing context mask. Do not discard earlier context.")
            } else {
                format!("Update `{function}` in `src/error_context.rs` to preserve the original fault code and keep the first nonzero context mask; use the added layer bit only when no prior context exists.")
            }
        }
        "transition" => {
            let from = int(row, "from");
            let event = int(row, "event");
            let to = int(row, "to");
            format!("Update `{function}` in `src/transition.rs`: change state {from} to {to} only for event {event}. For every other state/event pair, return the incoming state unchanged.")
        }
        "cleanup" => {
            let policy = if boolean(row, "release_on_success") {
                "release an acquired resource on both success and failure"
            } else {
                "release an acquired resource only after failure"
            };
            format!("Update `{function}` in `src/cleanup.rs` to {policy}. A resource already released stays released, and an unacquired resource must not be reported as released.")
        }
        "ordering" => {
            let id_order = if boolean(row, "tie_ascending") { "ascending" } else { "descending" };
            format!("Update `{function}` in `src/ordering.rs` to order higher priority first, then earlier tick first, then stable id in {id_order} order. Equal records must not precede one another.")
        }
        "limits" => {
            let relation = if boolean(row, "inclusive") { "at or below" } else { "strictly below" };
            format!("Update `{function}` in `src/limits.rs` to accept a request only when the exact byte product is {relation} the limit. Reject multiplication overflow and do not wrap.")
        }
        "compat" => {
            let sentinel = int(row, "sentinel");
            format!("Update `{function}` in `src/compat.rs` without changing its exported `Option<i64> -> i64` signature. Preserve every `Some(value)` and map `None` to the legacy sentinel {sentinel}.")
        }
        "atomic_batch" => {
            if boolean(row, "atomic") {
                format!("Update `{function}` in `src/atomic_batch.rs` so a failure index inside the batch returns that index and leaves the original state unchanged. On success, append the entire batch.")
            } else {
                format!("Update `{function}` in `src/atomic_batch.rs` so a failure index returns that index and commits exactly the items before it. The failing item and later items must not be appended.")
            }
        }
        _ => "Unknown D family task.".to_owned(),
    }
}

pub fn fixture_rows(row: &CaseRow, visible: bool) -> Vec<[i64; 6]> {
    let mut args = Vec::new();
    match row.family.as_str() {
        "boundary" => {
            let low = int(row, "low");
            let high = int(row, "high");
            let values = if visible {
                vec![low - 1, low]
            } else {
                vec![low + 1, high - 1, high, high + 1, low - 2, high + 2]
            };
            for value in values {
                args.push([value, 0, 0, 0, 0, 0]);
            }
        }
        "error_context" => {
            let added = int(row, "context") as u32 as i64;
            let cases = if visible { vec![(71, 0), (-9, 1)] } else { vec![(5, 4), (0, 0), (i64::MAX, 8)] };
            for (code, prior) in cases {
                args.push([code, prior, added, 0, 0, 0]);
            }
        }
        "transition" => {
            let from = int(row, "from");
            let event = int(row, "event");
            let values = if visible {
                vec![(from, event), (from, event + 1)]
            } else {
                vec![(0, event), (from + 7, event), (from, event + 2)]
            };
            for (state, action) in values {
                args.push([state, action, 0, 0, 0, 0]);
            }
        }
        "cleanup" => {
            let states = if visible {
                vec![(1, 1, 0), (1, 0, 0)]
            } else {
                vec![(0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 1), (0, 0, 1), (0, 1, 0)]
            };
            for (acquired, succeeded, released) in states {
                args.push([acquired, succeeded, released, 0, 0, 0]);
            }
        }
        "ordering" => {
            let cases = [
                [5, 9, 1, 4, 0, 0],
                [5, 1, 1, 5, 2, 0],
                [5, 1, 1, 5, 1, 2],
                [5, 1, 3, 5, 1, 2],
                [4, 0, 0, 4, 0, 0],
                [i64::MIN, 2, 1, i64::MAX, 1, 9],
            ];
            let selected = if visible { vec![cases[0], cases[1]] } else { vec![cases[2], cases[3], cases[4], cases[5]] };
            args.extend(selected);
        }
        "limits" => {
            let limit = int(row, "limit");
            let selected = if visible {
                vec![[1, limit, limit], [0, i64::MAX, 0]]
            } else {
                vec![[limit, 1, limit], [2, limit, limit], [-1, 2, limit], [3, 0, 0]]
            };
            args.extend(selected.into_iter().map(|item| {
                let mut row = [0; 6];
                row[..3].copy_from_slice(&item);
                row
            }));
        }
        "compat" => {
            let cases = if visible { vec![(0, 91), (1, -7)] } else { vec![(1, 0), (1, i64::MAX)] };
            for (has_value, value) in cases {
                args.push([has_value, value, 0, 0, 0, 0]);
            }
        }
        "atomic_batch" => {
            let selected = if visible { vec![[2, 3, -1], [2, 3, 0]] } else { vec![[2, 3, 1], [0, 0, 0], [1, 2, 9], [3, 1, 0]] };
            args.extend(selected.into_iter().map(|item| {
                let mut row = [0; 6];
                row[..3].copy_from_slice(&item);
                row
            }));
        }
        _ => {}
    }
    args
}

/// Independent task oracle. It does not call the candidate implementation or inspect its diff.
pub fn expected(row: &CaseRow, args: &[i64; 6]) -> String {
    match row.family.as_str() {
        "boundary" => {
            let value = args[0];
            let low = int(row, "low");
            let high = int(row, "high");
            let upper = if boolean(row, "inclusive_high") { value <= high } else { value < high };
            (value >= low && upper).to_string()
        }
        "error_context" => {
            let code = args[0];
            let prior = args[1] as u32;
            let added = int(row, "context") as u32;
            let context = if int(row, "policy") == 0 {
                prior | added
            } else if prior == 0 {
                added
            } else {
                prior
            };
            format!("{code}|{context}")
        }
        "transition" => {
            let from = int(row, "from");
            let event = int(row, "event");
            let next = int(row, "to");
            if args[0] == from && args[1] == event { next } else { args[0] }.to_string()
        }
        "cleanup" => {
            let acquired = args[0] != 0;
            let succeeded = args[1] != 0;
            let released = args[2] != 0;
            let should_release = if boolean(row, "release_on_success") {
                acquired
            } else {
                acquired && !succeeded
            };
            (released || should_release).to_string()
        }
        "ordering" => {
            let left = (args[0], args[1], args[2]);
            let right = (args[3], args[4], args[5]);
            let tie_ascending = boolean(row, "tie_ascending");
            let before = if left.0 != right.0 {
                left.0 > right.0
            } else if left.1 != right.1 {
                left.1 < right.1
            } else if tie_ascending {
                left.2 < right.2
            } else {
                left.2 > right.2
            };
            before.to_string()
        }
        "limits" => {
            let count = args[0] as u64;
            let size = args[1] as u64;
            let limit = args[2] as u64;
            count.checked_mul(size).is_some_and(|bytes| {
                if boolean(row, "inclusive") { bytes <= limit } else { bytes < limit }
            }).to_string()
        }
        "compat" => {
            if args[0] == 0 { int(row, "sentinel").to_string() } else { args[1].to_string() }
        }
        "atomic_batch" => {
            let initial_len = args[0].clamp(0, 8) as usize;
            let batch_len = args[1].clamp(0, 8) as usize;
            let failure = args[2];
            let mut length = initial_len;
            let mut sum: i64 = (0..initial_len as i64).sum();
            let failure_inside = failure >= 0 && (failure as usize) < batch_len;
            let committed = if failure_inside && boolean(row, "atomic") {
                0
            } else if failure_inside {
                failure as usize
            } else {
                batch_len
            };
            for index in 0..committed {
                sum += 100 + index as i64;
            }
            length += committed;
            let result = if failure_inside { format!("err:{failure}") } else { "ok".to_owned() };
            format!("{result}|{length}|{sum}")
        }
        _ => String::new(),
    }
}

pub fn tsv_row(row: &CaseRow, args: &[i64; 6]) -> String {
    let expected = expected(row, args);
    let values = args.iter().map(i64::to_string).collect::<Vec<_>>().join("\t");
    format!("{}\t{}\t{}\t{}\n", row.family_id, row.function_name, values, expected)
}

pub fn family_key(family_id: &str) -> Option<&'static str> {
    match family_id {
        "d.boundary" => Some("boundary"),
        "d.error-context" => Some("error_context"),
        "d.transition" => Some("transition"),
        "d.cleanup" => Some("cleanup"),
        "d.ordering" => Some("ordering"),
        "d.limits" => Some("limits"),
        "d.compat" => Some("compat"),
        "d.atomic-batch" => Some("atomic_batch"),
        _ => None,
    }
}
