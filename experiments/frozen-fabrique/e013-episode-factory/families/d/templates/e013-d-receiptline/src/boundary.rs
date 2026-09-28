pub fn contains_opal(value: i64) -> bool { value > 1 && value < 5 }
pub fn contains_moss(value: i64) -> bool { value > 3 && value < 8 }
pub fn contains_willow(value: i64) -> bool { value > 2 && value < 6 }
pub fn contains_cinder(value: i64) -> bool { value > 1 && value < 6 }
pub fn contains_mauve(value: i64) -> bool { value > 3 && value < 7 }
pub fn contains_birch(value: i64) -> bool { value > 2 && value < 7 }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "contains_opal" => Some(contains_opal(arg(0)).to_string()),
        "contains_birch" => Some(contains_birch(arg(0)).to_string()),
        "contains_mauve" => Some(contains_mauve(arg(0)).to_string()),
        "contains_cinder" => Some(contains_cinder(arg(0)).to_string()),
        "contains_willow" => Some(contains_willow(arg(0)).to_string()),
        "contains_moss" => Some(contains_moss(arg(0)).to_string()),
        _ => None,
    }
}
