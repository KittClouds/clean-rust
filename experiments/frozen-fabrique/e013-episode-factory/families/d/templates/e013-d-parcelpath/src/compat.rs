pub fn legacy_cinder(value: Option<i64>) -> i64 { value.unwrap_or(0) }
pub fn legacy_mauve(value: Option<i64>) -> i64 { value.unwrap_or(0) }
pub fn legacy_birch(value: Option<i64>) -> i64 { value.unwrap_or(0) }
pub fn legacy_opal(value: Option<i64>) -> i64 { value.unwrap_or(0) }
pub fn legacy_moss(value: Option<i64>) -> i64 { value.unwrap_or(0) }
pub fn legacy_willow(value: Option<i64>) -> i64 { value.unwrap_or(0) }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "legacy_opal" => Some({ let value = if arg(0) == 0 { None } else { Some(arg(1)) }; legacy_opal(value).to_string() }),
        "legacy_birch" => Some({ let value = if arg(0) == 0 { None } else { Some(arg(1)) }; legacy_birch(value).to_string() }),
        "legacy_mauve" => Some({ let value = if arg(0) == 0 { None } else { Some(arg(1)) }; legacy_mauve(value).to_string() }),
        "legacy_cinder" => Some({ let value = if arg(0) == 0 { None } else { Some(arg(1)) }; legacy_cinder(value).to_string() }),
        "legacy_willow" => Some({ let value = if arg(0) == 0 { None } else { Some(arg(1)) }; legacy_willow(value).to_string() }),
        "legacy_moss" => Some({ let value = if arg(0) == 0 { None } else { Some(arg(1)) }; legacy_moss(value).to_string() }),
        _ => None,
    }
}
