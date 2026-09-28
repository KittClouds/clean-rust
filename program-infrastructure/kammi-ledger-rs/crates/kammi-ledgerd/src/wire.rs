//! `wire.py`: the closed request vocabulary shared with the Python service.

use std::sync::OnceLock;

use kammi_jcs::Value;

const WIRE: &str = include_str!("../assets/wire-v1.json");

struct Route {
    segments: Vec<Option<String>>,
    definition: Value,
}

fn routes() -> &'static [Route] {
    static ROUTES: OnceLock<Vec<Route>> = OnceLock::new();
    ROUTES.get_or_init(|| {
        let document: Value = serde_json::from_str(WIRE).expect("wire-v1.json");
        document["$defs"]
            .as_object()
            .unwrap()
            .iter()
            .filter(|(path, _)| path.starts_with("/v1/"))
            .map(|(path, definition)| Route {
                // `{name}` matches one path segment (`[^/]+`), everything else literally.
                segments: path
                    .split('/')
                    .map(|s| (!(s.starts_with('{') && s.ends_with('}'))).then(|| s.to_string()))
                    .collect(),
                definition: definition.clone(),
            })
            .collect()
    })
}

fn matches(route: &Route, path: &str) -> bool {
    let parts: Vec<&str> = path.split('/').collect();
    parts.len() == route.segments.len()
        && route
            .segments
            .iter()
            .zip(&parts)
            .all(|(segment, part)| match segment {
                Some(literal) => literal == part,
                None => !part.is_empty(),
            })
}

fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::String(_) => "string",
        Value::Object(_) => "object",
        Value::Array(_) => "array",
        Value::Number(n) if n.is_f64() => "number",
        Value::Number(_) => "integer",
    }
}

/// Returns the Python `ValueError` message when `body` violates the route's definition.
pub fn validate_request(path: &str, body: &Value) -> Result<(), String> {
    let Some(route) = routes().iter().find(|r| matches(r, path)) else {
        return Ok(());
    };
    let Some(object) = body.as_object() else {
        return Err("request must be an object".into());
    };
    let properties = route.definition["properties"].as_object().unwrap();
    let required: Vec<&str> = route.definition["required"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(Value::as_str)
        .collect();
    if object.keys().any(|k| !properties.contains_key(k))
        || required.iter().any(|k| !object.contains_key(*k))
    {
        return Err("request fields do not match wire-v1".into());
    }
    for (key, value) in object {
        let declared = &properties[key]["type"];
        let types: Vec<&str> = match declared {
            Value::Array(items) => items.iter().filter_map(Value::as_str).collect(),
            Value::String(single) => vec![single.as_str()],
            _ => vec![],
        };
        let actual = type_name(value);
        if !(types.contains(&actual) || (actual == "integer" && types.contains(&"number"))) {
            return Err(format!("invalid request field type: {key}"));
        }
        if let Value::Array(items) = value {
            if items.iter().any(|item| !item.is_string()) {
                return Err(format!("array items must be strings: {key}"));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn closed_vocabulary_and_types() {
        let ok = json!({"run_id": "r", "lab": "l", "actor": "a", "request_id": "q"});
        assert!(validate_request("/v1/runs", &ok).is_ok());
        let extra = json!({"run_id": "r", "lab": "l", "actor": "a", "request_id": "q", "x": 1});
        assert_eq!(
            validate_request("/v1/runs", &extra).unwrap_err(),
            "request fields do not match wire-v1"
        );
        let wrong = json!({"run_id": true, "lab": "l", "actor": "a", "request_id": "q"});
        assert_eq!(
            validate_request("/v1/runs", &wrong).unwrap_err(),
            "invalid request field type: run_id"
        );
        assert!(validate_request("/v1/unlisted", &json!(1)).is_ok());
        assert!(validate_request("/v1/panels/p1/open", &json!([])).is_err());
    }
}
