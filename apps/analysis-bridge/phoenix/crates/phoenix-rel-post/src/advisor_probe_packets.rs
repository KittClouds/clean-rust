use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::AdvisorProbeTask;

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdvisorPacketExpectation {
    #[serde(default)]
    pub exact: Map<String, Value>,
    #[serde(default)]
    pub one_of: BTreeMap<String, Vec<Value>>,
    #[serde(default)]
    pub required_literals: Vec<String>,
    #[serde(default)]
    pub forbidden_literals: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdvisorEvidencePacket {
    pub id: String,
    pub kind: String,
    pub packet: Value,
    #[serde(default)]
    pub expectation: AdvisorPacketExpectation,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdvisorPacketSuite {
    pub packets: Vec<AdvisorEvidencePacket>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdvisorPacketEvaluation {
    pub exact_pass: bool,
    pub containment_pass: bool,
    pub overall_pass: bool,
    pub issues: Vec<String>,
}

pub fn build_advisor_packet_tasks_from_value(
    value: &Value,
) -> Result<Vec<AdvisorProbeTask>, String> {
    let suite: AdvisorPacketSuite = serde_json::from_value(value.clone())
        .map_err(|error| format!("parse advisor packet suite: {error}"))?;
    suite.packets.iter().map(build_task_from_packet).collect()
}

pub fn evaluate_packet_output(
    task: &AdvisorProbeTask,
    parsed_json: Option<&Value>,
) -> Option<AdvisorPacketEvaluation> {
    let expectation = task.expectation.as_ref()?;
    let source_text = task
        .source_text
        .as_deref()
        .unwrap_or_default()
        .to_ascii_lowercase();
    let mut issues = Vec::new();
    let Some(object) = parsed_json.and_then(Value::as_object) else {
        return Some(AdvisorPacketEvaluation {
            exact_pass: false,
            containment_pass: false,
            overall_pass: false,
            issues: vec!["missing parsed JSON object".to_owned()],
        });
    };

    let mut exact_pass = true;
    for (key, expected) in &expectation.exact {
        if object.get(key) != Some(expected) {
            exact_pass = false;
            issues.push(format!("exact mismatch for {key}"));
        }
    }
    for (key, allowed) in &expectation.one_of {
        let Some(actual) = object.get(key) else {
            exact_pass = false;
            issues.push(format!("missing expected key {key}"));
            continue;
        };
        if !allowed.iter().any(|candidate| candidate == actual) {
            exact_pass = false;
            issues.push(format!("unexpected value for {key}"));
        }
    }

    let text_surface = flatten_value_text(&Value::Object(object.clone())).to_ascii_lowercase();
    let mut containment_pass = true;
    for literal in &expectation.required_literals {
        if !text_surface.contains(&literal.to_ascii_lowercase()) {
            containment_pass = false;
            issues.push(format!("missing literal {literal}"));
        }
    }
    for literal in &expectation.forbidden_literals {
        if text_surface.contains(&literal.to_ascii_lowercase()) {
            containment_pass = false;
            issues.push(format!("forbidden literal {literal}"));
        }
    }
    for number in extract_numeric_literals(&Value::Object(object.clone())) {
        if !source_text.contains(number.as_str()) {
            containment_pass = false;
            issues.push(format!("number {number} not present in packet"));
        }
    }

    Some(AdvisorPacketEvaluation {
        exact_pass,
        containment_pass,
        overall_pass: exact_pass && containment_pass,
        issues,
    })
}

fn build_task_from_packet(packet: &AdvisorEvidencePacket) -> Result<AdvisorProbeTask, String> {
    let evidence = serde_json::to_string(&packet.packet)
        .map_err(|error| format!("serialize packet: {error}"))?;
    let source_text = serde_json::to_string(&packet.packet)
        .map_err(|error| format!("serialize packet source: {error}"))?;
    let (prompt, prefill, required_keys) = match packet.kind.as_str() {
        "summary" => (
            format!(
                "Task: summary packet. Evidence packet: {evidence}. Return keys summary, confidence, needsReview. \
                 Keep the answer inside the packet. Do not invent systems, modules, files, or actors. Set \
                 needsReview to true when evidence is incomplete, noisy, or cross-island."
            ),
            "{\"summary\":\"".to_owned(),
            vec![
                "summary".to_owned(),
                "confidence".to_owned(),
                "needsReview".to_owned(),
            ],
        ),
        "contradiction" => (
            format!(
                "Task: contradiction packet. Evidence packet: {evidence}. Return keys contradiction, reason, status. \
                 contradiction must be a JSON boolean. status must be review or defer unless the packet is explicit."
            ),
            "{\"contradiction\":".to_owned(),
            vec![
                "contradiction".to_owned(),
                "reason".to_owned(),
                "status".to_owned(),
            ],
        ),
        "causal" => (
            format!(
                "Task: causal packet. Evidence packet: {evidence}. Return keys causalLink, explanation, status. \
                 causalLink must be a JSON boolean. Use defer or review when temporal order does not prove causality."
            ),
            "{\"causalLink\":".to_owned(),
            vec![
                "causalLink".to_owned(),
                "explanation".to_owned(),
                "status".to_owned(),
            ],
        ),
        "history" => (
            format!(
                "Task: history packet. Evidence packet: {evidence}. Return keys answer, confidence, needsReview. \
                 If the packet does not contain the answer, set answer to unknown and needsReview to true."
            ),
            "{\"answer\":\"".to_owned(),
            vec![
                "answer".to_owned(),
                "confidence".to_owned(),
                "needsReview".to_owned(),
            ],
        ),
        "graph_audit" => (
            format!(
                "Task: graph audit packet. Evidence packet: {evidence}. Return keys action and why. \
                 Prefer review or defer when freshness, island continuity, or support are weak."
            ),
            "{\"action\":\"".to_owned(),
            vec!["action".to_owned(), "why".to_owned()],
        ),
        other => return Err(format!("unknown advisor packet kind: {other}")),
    };
    Ok(AdvisorProbeTask {
        name: packet.id.clone(),
        prompt,
        prefill,
        required_keys,
        packet_kind: Some(packet.kind.clone()),
        source_text: Some(source_text),
        expectation: Some(packet.expectation.clone()),
    })
}

fn flatten_value_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => value.clone(),
        Value::Array(values) => values
            .iter()
            .map(flatten_value_text)
            .collect::<Vec<_>>()
            .join(" "),
        Value::Object(values) => values
            .iter()
            .flat_map(|(key, value)| [key.clone(), flatten_value_text(value)])
            .collect::<Vec<_>>()
            .join(" "),
    }
}

fn extract_numeric_literals(value: &Value) -> Vec<String> {
    let mut out = Vec::new();
    collect_numeric_literals(&flatten_value_text(value), &mut out);
    out
}

fn collect_numeric_literals(text: &str, out: &mut Vec<String>) {
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_ascii_digit() || ch == '.' || ch == '-' {
            current.push(ch);
        } else if !current.is_empty() {
            push_numeric_literal(&mut current, out);
        }
    }
    if !current.is_empty() {
        push_numeric_literal(&mut current, out);
    }
}

fn push_numeric_literal(current: &mut String, out: &mut Vec<String>) {
    if current.chars().any(|ch| ch.is_ascii_digit()) {
        out.push(std::mem::take(current));
    } else {
        current.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::{build_advisor_packet_tasks_from_value, evaluate_packet_output};

    #[test]
    fn packet_suite_builds_summary_task() {
        let suite = serde_json::json!({
            "packets": [
                {
                    "id": "summary_one",
                    "kind": "summary",
                    "packet": { "facts": ["Warm run 3.9s"] },
                    "expectation": { "exact": { "needsReview": false } }
                }
            ]
        });
        let tasks = build_advisor_packet_tasks_from_value(&suite).expect("packet tasks");
        assert_eq!(tasks.len(), 1);
        assert_eq!(tasks[0].packet_kind.as_deref(), Some("summary"));
    }

    #[test]
    fn packet_evaluation_flags_missing_number() {
        let suite = serde_json::json!({
            "packets": [
                {
                    "id": "history_one",
                    "kind": "history",
                    "packet": { "question": "When?", "facts": ["Left on 2024-02-16"] },
                    "expectation": {
                        "exact": { "answer": "2024-02-16", "needsReview": false },
                        "requiredLiterals": ["2024-02-16"]
                    }
                }
            ]
        });
        let tasks = build_advisor_packet_tasks_from_value(&suite).expect("packet tasks");
        let parsed = serde_json::json!({
            "answer": "2024-03-01",
            "confidence": "high",
            "needsReview": false
        });
        let evaluation = evaluate_packet_output(&tasks[0], Some(&parsed)).expect("evaluation");
        assert!(!evaluation.overall_pass);
        assert!(evaluation
            .issues
            .iter()
            .any(|issue| issue.contains("2024-03-01")));
    }

    #[test]
    fn punctuation_does_not_become_numeric_literal() {
        let suite = serde_json::json!({
            "packets": [
                {
                    "id": "summary_one",
                    "kind": "summary",
                    "packet": { "facts": ["Alice left on 2024-02-16"] },
                    "expectation": {
                        "exact": { "needsReview": false },
                        "oneOf": { "confidence": ["high"] }
                    }
                }
            ]
        });
        let tasks = build_advisor_packet_tasks_from_value(&suite).expect("packet tasks");
        let parsed = serde_json::json!({
            "summary": "Alice left on 2024-02-16.",
            "confidence": "high",
            "needsReview": false
        });
        let evaluation = evaluate_packet_output(&tasks[0], Some(&parsed)).expect("evaluation");
        assert!(evaluation
            .issues
            .iter()
            .all(|issue| !issue.contains("number .")));
    }
}
