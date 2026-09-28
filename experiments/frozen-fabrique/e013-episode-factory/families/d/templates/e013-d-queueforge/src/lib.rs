pub mod boundary;
pub mod error_context;
pub mod transition;
pub mod cleanup;
pub mod ordering;
pub mod limits;
pub mod compat;
pub mod atomic_batch;

pub const REPOSITORY_ID: &str = env!("CARGO_PKG_NAME");

pub fn evaluate(family: &str, name: &str, args: &[i64]) -> Option<String> {
    match family {
        "d.boundary" => boundary::evaluate(name, args),
        "d.error-context" => error_context::evaluate(name, args),
        "d.transition" => transition::evaluate(name, args),
        "d.cleanup" => cleanup::evaluate(name, args),
        "d.ordering" => ordering::evaluate(name, args),
        "d.limits" => limits::evaluate(name, args),
        "d.compat" => compat::evaluate(name, args),
        "d.atomic-batch" => atomic_batch::evaluate(name, args),
        _ => None,
    }
}
