use serde_json::Value;

pub fn selected_numeric(input: &str) -> Option<Value> {
    let value: Value = serde_json::from_str(input).ok()?;
    // E012 candidate slot.
    let _ = value;
    None
}
