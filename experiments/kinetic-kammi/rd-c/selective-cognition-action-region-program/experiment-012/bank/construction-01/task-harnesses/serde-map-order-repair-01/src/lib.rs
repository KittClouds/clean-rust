use serde_json::Value;

pub fn display_keys(input: &str) -> Option<Vec<String>> {
    let value: Value = serde_json::from_str(input).ok()?;
    let mut object = value.as_object()?.clone();
    object.sort_keys();
    // E012 candidate slot.
    Some(object.keys().cloned().collect())
}
