use serde_json::Value;

pub fn display_keys(input: &str) -> Option<Vec<String>> {
    let value: Value = serde_json::from_str(input).ok()?;
    let object = value.as_object()?;
    // E012 candidate slot.
    Some(object.keys().cloned().collect())
}
