use serde_json::Value;

pub fn normalize_json_number(input: &str) -> Option<String> {
    let value: Value = serde_json::from_str(input).ok()?;
    // E012 candidate slot.
    serde_json::to_string(&value).ok()
}
