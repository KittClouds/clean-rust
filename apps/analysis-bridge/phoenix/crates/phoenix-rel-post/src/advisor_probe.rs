use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdvisorProbeTask {
    pub name: String,
    pub prompt: String,
    pub prefill: String,
    pub required_keys: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub packet_kind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_text: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expectation: Option<crate::AdvisorPacketExpectation>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AdvisorReportSummary {
    pub store_path: Option<String>,
    pub scope_count: usize,
    pub archives: Value,
    pub probes: Value,
    pub timing_seconds: Value,
}

pub fn build_advisor_probe_tasks(report: &Value) -> Result<Vec<AdvisorProbeTask>, String> {
    let summary = summarize_report(report);
    let evidence =
        serde_json::to_string(&summary).map_err(|error| format!("serialize evidence: {error}"))?;
    Ok(vec![
        AdvisorProbeTask {
            name: "weak_label".to_owned(),
            prompt: format!(
                "Task: weak_label. Evidence: {evidence}. Choose label stable when probes answer \
                 without abstains or errors, needs_review when there are mild risks, unsafe \
                 when errors dominate. Return keys label, confidence, note. The note must be \
                 a short explanation."
            ),
            prefill: "{\"label\":\"".to_owned(),
            required_keys: vec![
                "label".to_owned(),
                "confidence".to_owned(),
                "note".to_owned(),
            ],
            packet_kind: None,
            source_text: None,
            expectation: None,
        },
        AdvisorProbeTask {
            name: "summarize".to_owned(),
            prompt: format!(
                "Task: summarize. Evidence: {evidence}. Return key summary. Summary must be \
                 one sentence. You may add risk as low, medium, or high if the signal is obvious."
            ),
            prefill: "{\"summary\":\"".to_owned(),
            required_keys: vec!["summary".to_owned()],
            packet_kind: None,
            source_text: None,
            expectation: None,
        },
        AdvisorProbeTask {
            name: "contradiction_audit".to_owned(),
            prompt: "Task: contradiction_audit. Evidence A: Alice moved into the harbor. \
                     Evidence B: Alice never entered the harbor. Graph status: candidate \
                     contradiction, needs review. Return keys contradiction, reason, status. \
                     Use contradiction as a JSON boolean. Status should be review unless the \
                     evidence is safe to reject or defer."
                .to_owned(),
            prefill: "{\"contradiction\":true,\"reason\":\"".to_owned(),
            required_keys: vec![
                "contradiction".to_owned(),
                "reason".to_owned(),
                "status".to_owned(),
            ],
            packet_kind: None,
            source_text: None,
            expectation: None,
        },
        AdvisorProbeTask {
            name: "graph_audit".to_owned(),
            prompt: "Task: graph_audit. Evidence: candidate edge crosses context islands with \
                     low freshness but strong lexical hit. Ledger: support 0.72, contradiction \
                     0.15, freshness 0.31, path 0.44. Choose action review when support exists \
                     but freshness or scope is weak. Return keys action and why."
                .to_owned(),
            prefill: "{\"action\":\"".to_owned(),
            required_keys: vec!["action".to_owned(), "why".to_owned()],
            packet_kind: None,
            source_text: None,
            expectation: None,
        },
    ])
}

pub fn summarize_report(report: &Value) -> AdvisorReportSummary {
    let instrumentation = report.get("instrumentation").and_then(Value::as_object);
    let graph_runtime = instrumentation
        .and_then(|value| value.get("graphRuntime"))
        .and_then(Value::as_object);
    let totals = report
        .get("totals")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let probes = totals
        .get("probes")
        .cloned()
        .unwrap_or_else(|| Value::Object(Map::new()));
    AdvisorReportSummary {
        store_path: report
            .get("storePath")
            .and_then(Value::as_str)
            .map(str::to_owned),
        scope_count: report
            .get("scopeCount")
            .and_then(Value::as_u64)
            .unwrap_or_default() as usize,
        archives: totals
            .get("archives")
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new())),
        probes: condense_probe_counts(&probes),
        timing_seconds: serde_json::json!({
            "totalRun": metric_seconds(instrumentation, "totalRun"),
            "scopeProbes": metric_seconds(instrumentation, "scopeProbes"),
            "loadScopeRuntimeImages": metric_seconds(instrumentation, "loadScopeRuntimeImages"),
            "retrieveQuerySeeds": metric_seconds_from_maps(instrumentation, graph_runtime, "retrieveQuerySeeds"),
        }),
    }
}

pub fn parse_advisor_output(text: &str) -> (Option<Value>, Option<String>) {
    let stripped = text.trim();
    if stripped.starts_with("```") {
        return (None, Some("markdown fence around JSON".to_owned()));
    }
    if !stripped.starts_with('{') {
        return (
            None,
            Some("answer does not start with JSON object".to_owned()),
        );
    }

    let mut merged = Map::new();
    let mut fragment_count = 0usize;
    let mut cursor = stripped;
    loop {
        let mut stream = serde_json::Deserializer::from_str(cursor).into_iter::<Value>();
        match stream.next() {
            Some(Ok(Value::Object(object))) => {
                fragment_count += 1;
                merged.extend(object);
                let trailing = cursor[stream.byte_offset()..].trim_start();
                if trailing.is_empty() {
                    return merged_parse_result(merged, fragment_count, None);
                }
                if trailing.starts_with('{') {
                    cursor = trailing;
                    continue;
                }
                if trailing.chars().all(|char| char == '}') {
                    return merged_parse_result(
                        merged,
                        fragment_count,
                        Some("merged adjacent JSON objects".to_owned()),
                    );
                }
                return merged_parse_result(
                    merged,
                    fragment_count,
                    Some("merged adjacent JSON objects with trailing text".to_owned()),
                );
            }
            Some(Ok(other)) if fragment_count == 0 => return (Some(other), None),
            Some(Ok(_)) => {
                return merged_parse_result(
                    merged,
                    fragment_count,
                    Some("merged adjacent JSON objects with trailing text".to_owned()),
                );
            }
            Some(Err(error)) if fragment_count == 0 => return (None, Some(error.to_string())),
            Some(Err(_)) => {
                return merged_parse_result(
                    merged,
                    fragment_count,
                    Some("merged adjacent JSON objects with trailing text".to_owned()),
                );
            }
            None if fragment_count == 0 => return (None, Some("no JSON object found".to_owned())),
            None => return merged_parse_result(merged, fragment_count, None),
        }
    }
}

pub fn missing_required_keys(value: Option<&Value>, required_keys: &[String]) -> Option<String> {
    let object = value.and_then(Value::as_object)?;
    let missing = required_keys
        .iter()
        .filter(|key| !object.contains_key(key.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    (!missing.is_empty()).then(|| format!("missing required keys: {}", missing.join(", ")))
}

fn metric_seconds(metrics: Option<&Map<String, Value>>, key: &str) -> f64 {
    metric_seconds_from_maps(metrics, None, key)
}

fn metric_seconds_from_maps(
    primary: Option<&Map<String, Value>>,
    secondary: Option<&Map<String, Value>>,
    key: &str,
) -> f64 {
    primary
        .and_then(|metrics| metrics.get(key))
        .or_else(|| secondary.and_then(|metrics| metrics.get(key)))
        .and_then(Value::as_object)
        .and_then(|metric| metric.get("totalUs"))
        .and_then(Value::as_u64)
        .map(|value| value as f64 / 1_000_000.0)
        .unwrap_or(0.0)
}

fn condense_probe_counts(value: &Value) -> Value {
    let Some(object) = value.as_object() else {
        return Value::Object(Map::new());
    };
    let condensed = object
        .iter()
        .map(|(name, row)| {
            let row = row.as_object().cloned().unwrap_or_default();
            (
                name.clone(),
                serde_json::json!({
                    "total": row.get("total").and_then(Value::as_u64).unwrap_or_default(),
                    "answered": row.get("answered").and_then(Value::as_u64).unwrap_or_default(),
                    "abstained": row.get("abstained").and_then(Value::as_u64).unwrap_or_default(),
                    "errors": row.get("errors").and_then(Value::as_u64).unwrap_or_default(),
                }),
            )
        })
        .collect::<Map<_, _>>();
    Value::Object(condensed)
}

fn merged_parse_result(
    merged: Map<String, Value>,
    fragment_count: usize,
    warning: Option<String>,
) -> (Option<Value>, Option<String>) {
    let warning = if fragment_count > 1 {
        Some(warning.unwrap_or_else(|| "merged adjacent JSON objects".to_owned()))
    } else {
        warning
    };
    (Some(Value::Object(merged)), warning)
}

#[cfg(test)]
mod tests {
    use super::{missing_required_keys, parse_advisor_output, summarize_report};

    #[test]
    fn report_summary_reads_nested_seed_metric() {
        let report = serde_json::json!({
            "storePath": "store",
            "scopeCount": 1,
            "totals": {
                "archives": { "chunkCount": 2 },
                "probes": {
                    "worldState": { "total": 4, "answered": 4, "abstained": 0, "errors": 0 }
                }
            },
            "instrumentation": {
                "totalRun": { "totalUs": 4000000 },
                "scopeProbes": { "totalUs": 1900000 },
                "loadScopeRuntimeImages": { "totalUs": 1200000 },
                "graphRuntime": {
                    "retrieveQuerySeeds": { "totalUs": 1000000 }
                }
            }
        });
        let summary = summarize_report(&report);
        assert_eq!(summary.store_path.as_deref(), Some("store"));
        assert_eq!(summary.timing_seconds["retrieveQuerySeeds"], 1.0);
    }

    #[test]
    fn parser_merges_adjacent_objects() {
        let (parsed, warning) =
            parse_advisor_output(r#"{"label":"stable"}{"confidence":0.9,"note":"ok"}}"#);
        let parsed = parsed.expect("merged json");
        assert_eq!(parsed["label"], "stable");
        assert_eq!(parsed["confidence"], 0.9);
        assert_eq!(warning.as_deref(), Some("merged adjacent JSON objects"));
    }

    #[test]
    fn schema_checker_reports_missing_keys() {
        let value = serde_json::json!({ "summary": "ok" });
        let error = missing_required_keys(
            Some(&value),
            &[String::from("summary"), String::from("risk")],
        )
        .expect("missing keys");
        assert!(error.contains("risk"));
    }
}
