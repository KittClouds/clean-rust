pub fn advance_birch(state: i64, event: i64) -> i64 { if event == 2 { 3 } else { state } }
pub fn advance_opal(state: i64, event: i64) -> i64 { if event == 2 { 3 } else { state } }
pub fn advance_moss(state: i64, event: i64) -> i64 { if event == 2 { 3 } else { state } }
pub fn advance_willow(state: i64, event: i64) -> i64 { if event == 2 { 3 } else { state } }
pub fn advance_cinder(state: i64, event: i64) -> i64 { if event == 2 { 3 } else { state } }
pub fn advance_mauve(state: i64, event: i64) -> i64 { if event == 2 { 3 } else { state } }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "advance_opal" => Some(advance_opal(arg(0), arg(1)).to_string()),
        "advance_birch" => Some(advance_birch(arg(0), arg(1)).to_string()),
        "advance_mauve" => Some(advance_mauve(arg(0), arg(1)).to_string()),
        "advance_cinder" => Some(advance_cinder(arg(0), arg(1)).to_string()),
        "advance_willow" => Some(advance_willow(arg(0), arg(1)).to_string()),
        "advance_moss" => Some(advance_moss(arg(0), arg(1)).to_string()),
        _ => None,
    }
}
