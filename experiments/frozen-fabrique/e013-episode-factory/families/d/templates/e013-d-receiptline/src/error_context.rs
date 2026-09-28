#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Fault { pub code: i64, pub context: u32 }

pub fn annotate_mauve(code: i64, prior: u32, added: u32) -> Fault { let _ = code; let _ = prior; Fault { code: 0, context: added } }
pub fn annotate_birch(code: i64, prior: u32, added: u32) -> Fault { let _ = code; let _ = prior; Fault { code: 0, context: added } }
pub fn annotate_opal(code: i64, prior: u32, added: u32) -> Fault { let _ = code; let _ = prior; Fault { code: 0, context: added } }
pub fn annotate_moss(code: i64, prior: u32, added: u32) -> Fault { let _ = code; let _ = prior; Fault { code: 0, context: added } }
pub fn annotate_willow(code: i64, prior: u32, added: u32) -> Fault { let _ = code; let _ = prior; Fault { code: 0, context: added } }
pub fn annotate_cinder(code: i64, prior: u32, added: u32) -> Fault { let _ = code; let _ = prior; Fault { code: 0, context: added } }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "annotate_opal" => Some({ let value = annotate_opal(arg(0), arg(1) as u32, arg(2) as u32); format!("{}|{}", value.code, value.context) }),
        "annotate_birch" => Some({ let value = annotate_birch(arg(0), arg(1) as u32, arg(2) as u32); format!("{}|{}", value.code, value.context) }),
        "annotate_mauve" => Some({ let value = annotate_mauve(arg(0), arg(1) as u32, arg(2) as u32); format!("{}|{}", value.code, value.context) }),
        "annotate_cinder" => Some({ let value = annotate_cinder(arg(0), arg(1) as u32, arg(2) as u32); format!("{}|{}", value.code, value.context) }),
        "annotate_willow" => Some({ let value = annotate_willow(arg(0), arg(1) as u32, arg(2) as u32); format!("{}|{}", value.code, value.context) }),
        "annotate_moss" => Some({ let value = annotate_moss(arg(0), arg(1) as u32, arg(2) as u32); format!("{}|{}", value.code, value.context) }),
        _ => None,
    }
}
