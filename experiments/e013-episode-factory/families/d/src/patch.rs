use e013_episode_factory::FactoryError;

use crate::spec::{boolean, int, CaseRow};

pub fn file_path(row: &CaseRow) -> &'static str {
    match row.family.as_str() {
        "boundary" => "src/boundary.rs",
        "error_context" => "src/error_context.rs",
        "transition" => "src/transition.rs",
        "cleanup" => "src/cleanup.rs",
        "ordering" => "src/ordering.rs",
        "limits" => "src/limits.rs",
        "compat" => "src/compat.rs",
        "atomic_batch" => "src/atomic_batch.rs",
        _ => "",
    }
}

pub fn render_function(row: &CaseRow, body: &str) -> String {
    let name = &row.function_name;
    match row.family.as_str() {
        "boundary" => format!("pub fn {name}(value: i64) -> bool {{ {body} }}"),
        "error_context" => format!("pub fn {name}(code: i64, prior: u32, added: u32) -> Fault {{ {body} }}"),
        "transition" => format!("pub fn {name}(state: i64, event: i64) -> i64 {{ {body} }}"),
        "cleanup" => format!("pub fn {name}(acquired: bool, succeeded: bool, already_released: bool) -> bool {{ {body} }}"),
        "ordering" => format!("pub fn {name}(left: Entry, right: Entry) -> bool {{ let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); {body} }}"),
        "limits" => format!("pub fn {name}(count: u64, size: u64, limit: u64) -> bool {{ {body} }}"),
        "compat" => format!("pub fn {name}(value: Option<i64>) -> i64 {{ {body} }}"),
        "atomic_batch" => format!("pub fn {name}(state: &mut Vec<i64>, batch: &[i64], fail_at: Option<usize>) -> Result<(), usize> {{ {body} }}"),
        _ => String::new(),
    }
}

pub fn candidate_bodies(
    row: &CaseRow,
    sibling: Option<&CaseRow>,
    empty: bool,
    multiple_valid: bool,
) -> Vec<String> {
    if let Some(other) = sibling {
        let left = if row.task_slot % 2 == 0 { row } else { other };
        let right = if row.task_slot % 2 == 0 { other } else { row };
        let (wrong_a, wrong_b, _, _) = wrong_bodies(left);
        let mut bodies = vec![expected_body(left), expected_body(right), wrong_a, wrong_b];
        deduplicate(&mut bodies);
        return bodies;
    }

    let wrong = wrong_bodies(row);
    if empty {
        let mut bodies = vec![wrong.0, wrong.1, wrong.2, wrong.3];
        deduplicate(&mut bodies);
        return bodies;
    }
    let mut bodies = vec![expected_body(row)];
    if multiple_valid {
        bodies.push(alternative_body(row));
    }
    bodies.extend(wrong.into_iter().take(4 - bodies.len()));
    deduplicate(&mut bodies);
    bodies
}

fn deduplicate(bodies: &mut Vec<String>) {
    let mut unique = Vec::with_capacity(bodies.len());
    for body in bodies.drain(..) {
        if !unique.contains(&body) {
            unique.push(body);
        }
    }
    *bodies = unique;
}

pub fn expected_body(row: &CaseRow) -> String {
    match row.family.as_str() {
        "boundary" => {
            let low = int(row, "low");
            let high = int(row, "high");
            let op = if boolean(row, "inclusive_high") { "<=" } else { "<" };
            format!("value >= {low} && value {op} {high}")
        }
        "error_context" => {
            if int(row, "policy") == 0 {
                "Fault { code, context: prior | added }".to_owned()
            } else {
                "Fault { code, context: if prior == 0 { added } else { prior } }".to_owned()
            }
        }
        "transition" => format!(
            "if state == {} && event == {} {{ {} }} else {{ state }}",
            int(row, "from"), int(row, "event"), int(row, "to")
        ),
        "cleanup" => {
            let success = if boolean(row, "release_on_success") { "true" } else { "!succeeded" };
            format!("already_released || (acquired && {success})")
        }
        "ordering" => {
            let tie = if boolean(row, "tie_ascending") { "<" } else { ">" };
            format!("if left_priority != right_priority {{ left_priority > right_priority }} else if left.tick != right.tick {{ left.tick < right.tick }} else {{ left.id {tie} right.id }}")
        }
        "limits" => {
            let op = if boolean(row, "inclusive") { "<=" } else { "<" };
            format!("count.checked_mul(size).is_some_and(|bytes| bytes {op} limit)")
        }
        "compat" => format!("value.unwrap_or({})", int(row, "sentinel")),
        "atomic_batch" => atomic_body(boolean(row, "atomic")),
        _ => String::new(),
    }
}

fn alternative_body(row: &CaseRow) -> String {
    match row.family.as_str() {
        "boundary" => {
            let low = int(row, "low");
            let high = int(row, "high");
            if boolean(row, "inclusive_high") {
                format!("({low}..={high}).contains(&value)")
            } else {
                format!("({low}..{high}).contains(&value)")
            }
        }
        "error_context" => {
            if int(row, "policy") == 0 {
                "{ let mut fault = Fault { code, context: prior }; fault.context |= added; fault }".to_owned()
            } else {
                "{ let mut fault = Fault { code, context: prior }; if fault.context == 0 { fault.context = added; } fault }".to_owned()
            }
        }
        "transition" => format!(
            "match (state, event) {{ ({}, {}) => {}, _ => state }}",
            int(row, "from"), int(row, "event"), int(row, "to")
        ),
        "cleanup" => {
            let success = if boolean(row, "release_on_success") { "acquired" } else { "acquired && !succeeded" };
            format!("already_released || {success}")
        }
        "ordering" => {
            let tie = if boolean(row, "tie_ascending") { "<" } else { ">" };
            format!("match left_priority.cmp(&right_priority) {{ std::cmp::Ordering::Greater => true, std::cmp::Ordering::Less => false, std::cmp::Ordering::Equal => match left.tick.cmp(&right.tick) {{ std::cmp::Ordering::Less => true, std::cmp::Ordering::Greater => false, std::cmp::Ordering::Equal => left.id {tie} right.id }} }}")
        }
        "limits" => {
            let op = if boolean(row, "inclusive") { "<=" } else { "<" };
            format!("match count.checked_mul(size) {{ Some(bytes) => bytes {op} limit, None => false }}")
        }
        "compat" => format!("match value {{ Some(value) => value, None => {} }}", int(row, "sentinel")),
        "atomic_batch" => {
            if boolean(row, "atomic") {
                "if let Some(index) = fail_at.filter(|index| *index < batch.len()) { return Err(index); } state.extend_from_slice(batch); Ok(())".to_owned()
            } else {
                "for index in 0..batch.len() { if fail_at == Some(index) { return Err(index); } state.push(batch[index]); } Ok(())".to_owned()
            }
        }
        _ => String::new(),
    }
}

fn wrong_bodies(row: &CaseRow) -> (String, String, String, String) {
    match row.family.as_str() {
        "boundary" => {
            let low = int(row, "low");
            let high = int(row, "high");
            if boolean(row, "inclusive_high") {
                (
                    format!("value >= {low} && value < {high}"),
                    format!("value > {low} && value <= {high}"),
                    format!("value >= {} && value <= {high}", low - 1),
                    format!("value > {low} && value < {high}"),
                )
            } else {
                (
                    format!("value > {low} && value < {high}"),
                    format!("value >= {low} && value <= {high}"),
                    format!("value >= {low} && value < {}", high - 1),
                    format!("value > {low} && value <= {high}"),
                )
            }
        }
        "error_context" => (
            "Fault { code, context: added }".to_owned(),
            "Fault { code: added as i64, context: prior }".to_owned(),
            "Fault { code, context: prior & added }".to_owned(),
            "Fault { code, context: prior ^ added }".to_owned(),
        ),
        "transition" => (
            format!("if event == {} {{ {} }} else {{ state }}", int(row, "event"), int(row, "to")),
            format!("if state == {} {{ {} }} else {{ state }}", int(row, "from"), int(row, "to")),
            format!("if state == {} && event == {} {{ state + 1 }} else {{ state }}", int(row, "from"), int(row, "event")),
            format!("if event == {} {{ {} }} else {{ 0 }}", int(row, "event"), int(row, "to")),
        ),
        "cleanup" => {
            if boolean(row, "release_on_success") {
                (
                    "already_released || (acquired && succeeded)".to_owned(),
                    "acquired || already_released".to_owned(),
                    "acquired && succeeded".to_owned(),
                    "already_released || succeeded".to_owned(),
                )
            } else {
                (
                    "already_released || (acquired && succeeded)".to_owned(),
                    "already_released || acquired".to_owned(),
                    "acquired && !succeeded".to_owned(),
                    "already_released || !succeeded".to_owned(),
                )
            }
        }
        "ordering" => {
            let wrong_tie = if boolean(row, "tie_ascending") { ">" } else { "<" };
            (
                "left_priority > right_priority".to_owned(),
                "if left_priority != right_priority { left_priority > right_priority } else { left.tick > right.tick }".to_owned(),
                format!("if left_priority != right_priority {{ left_priority > right_priority }} else if left.tick != right.tick {{ left.tick < right.tick }} else {{ left.id {wrong_tie} right.id }}"),
                "left_priority >= right_priority".to_owned(),
            )
        }
        "limits" => {
            let op = if boolean(row, "inclusive") { "<=" } else { "<" };
            let other = if boolean(row, "inclusive") { "<" } else { "<=" };
            (
                format!("count * size {op} limit"),
                format!("count.saturating_mul(size) {op} limit"),
                format!("count.checked_mul(size).is_some_and(|bytes| bytes {other} limit)"),
                "count <= limit / size.max(1)".to_owned(),
            )
        }
        "compat" => {
            let sentinel = int(row, "sentinel");
            let wrong_default = if sentinel == 0 { -1 } else { 0 };
            (
                format!("value.unwrap_or({wrong_default})"),
                format!("value.unwrap_or({})", sentinel + 1),
                "value.map_or(0, |value| value.saturating_add(1))".to_owned(),
                "value.map_or(-99, |value| value)".to_owned(),
            )
        }
        "atomic_batch" => {
            if boolean(row, "atomic") {
                (
                    "for (index, item) in batch.iter().enumerate() { state.push(*item); if fail_at == Some(index) { return Err(index); } } Ok(())".to_owned(),
                    "for (index, item) in batch.iter().enumerate() { if fail_at == Some(index) { state.push(*item); return Err(index); } state.push(*item); } Ok(())".to_owned(),
                    "state.clear(); state.extend_from_slice(batch); if let Some(index) = fail_at.filter(|index| *index < batch.len()) { Err(index) } else { Ok(()) }".to_owned(),
                    "if let Some(index) = fail_at.filter(|index| *index < batch.len()) { return Err(index); } state.extend_from_slice(batch); Ok(())".to_owned(),
                )
            } else {
                (
                    "if let Some(index) = fail_at.filter(|index| *index < batch.len()) { return Err(index); } state.extend_from_slice(batch); Ok(())".to_owned(),
                    "for (index, item) in batch.iter().enumerate() { state.push(*item); if fail_at == Some(index) { return Err(index); } } Ok(())".to_owned(),
                    "for (index, item) in batch.iter().enumerate() { if fail_at == Some(index) { return Ok(()); } state.push(*item); } Ok(())".to_owned(),
                    "for item in batch { state.push(*item); } Ok(())".to_owned(),
                )
            }
        }
        _ => Default::default(),
    }
}

fn atomic_body(all_or_nothing: bool) -> String {
    if all_or_nothing {
        "for (index, item) in batch.iter().enumerate() { if fail_at == Some(index) { return Err(index); } let _ = item; } state.extend_from_slice(batch); Ok(())".to_owned()
    } else {
        "for (index, item) in batch.iter().enumerate() { if fail_at == Some(index) { return Err(index); } state.push(*item); } Ok(())".to_owned()
    }
}

pub fn unified_diff(path: &str, old: &str, new: &str, source: &str) -> Result<Vec<u8>, FactoryError> {
    let line_number = source
        .lines()
        .position(|line| line == old)
        .ok_or_else(|| FactoryError::Invalid(format!("target function not found in {path}")))?
        + 1;
    if old == new {
        return Err(FactoryError::Invalid("candidate patch does not change source".to_owned()));
    }
    let diff = format!(
        "--- a/{path}\n+++ b/{path}\n@@ -{line_number},1 +{line_number},1 @@\n-{old}\n+{new}\n"
    );
    Ok(diff.into_bytes())
}

pub fn find_source_line<'a>(source: &'a str, function_name: &str) -> Result<&'a str, FactoryError> {
    let prefix = format!("pub fn {function_name}(");
    source
        .lines()
        .find(|line| line.starts_with(&prefix))
        .ok_or_else(|| FactoryError::Invalid(format!("target function `{function_name}` is absent")))
}

pub fn make_patch(
    row: &CaseRow,
    source: &str,
    body: &str,
) -> Result<Vec<u8>, FactoryError> {
    let old = find_source_line(source, &row.function_name)?;
    let new = render_function(row, body);
    unified_diff(file_path(row), old, &new, source)
}

pub fn candidate_is_source_only(diff: &[u8]) -> bool {
    let text = String::from_utf8_lossy(diff);
    !["std::env", "E013_HIDDEN", "E013_VISIBLE", "std::fs", "File::open", "read_to_string"]
        .iter()
        .any(|needle| text.contains(needle))
}
