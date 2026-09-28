pub fn finish_cinder(acquired: bool, succeeded: bool, already_released: bool) -> bool { already_released || (acquired && succeeded) }
pub fn finish_mauve(acquired: bool, succeeded: bool, already_released: bool) -> bool { already_released || (acquired && succeeded) }
pub fn finish_birch(acquired: bool, succeeded: bool, already_released: bool) -> bool { already_released || (acquired && succeeded) }
pub fn finish_opal(acquired: bool, succeeded: bool, already_released: bool) -> bool { already_released || (acquired && succeeded) }
pub fn finish_moss(acquired: bool, succeeded: bool, already_released: bool) -> bool { already_released || (acquired && succeeded) }
pub fn finish_willow(acquired: bool, succeeded: bool, already_released: bool) -> bool { already_released || (acquired && succeeded) }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "finish_opal" => Some(finish_opal(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()),
        "finish_birch" => Some(finish_birch(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()),
        "finish_mauve" => Some(finish_mauve(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()),
        "finish_cinder" => Some(finish_cinder(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()),
        "finish_willow" => Some(finish_willow(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()),
        "finish_moss" => Some(finish_moss(arg(0) != 0, arg(1) != 0, arg(2) != 0).to_string()),
        _ => None,
    }
}
