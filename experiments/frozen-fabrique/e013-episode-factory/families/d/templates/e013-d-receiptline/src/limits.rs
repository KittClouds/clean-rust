pub fn fits_willow(count: u64, size: u64, limit: u64) -> bool { count * size <= limit }
pub fn fits_cinder(count: u64, size: u64, limit: u64) -> bool { count * size <= limit }
pub fn fits_mauve(count: u64, size: u64, limit: u64) -> bool { count * size <= limit }
pub fn fits_birch(count: u64, size: u64, limit: u64) -> bool { count * size <= limit }
pub fn fits_opal(count: u64, size: u64, limit: u64) -> bool { count * size <= limit }
pub fn fits_moss(count: u64, size: u64, limit: u64) -> bool { count * size <= limit }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "fits_opal" => Some(fits_opal(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()),
        "fits_birch" => Some(fits_birch(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()),
        "fits_mauve" => Some(fits_mauve(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()),
        "fits_cinder" => Some(fits_cinder(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()),
        "fits_willow" => Some(fits_willow(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()),
        "fits_moss" => Some(fits_moss(arg(0) as u64, arg(1) as u64, arg(2) as u64).to_string()),
        _ => None,
    }
}
