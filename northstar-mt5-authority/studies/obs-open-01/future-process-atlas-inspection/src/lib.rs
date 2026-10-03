pub mod anatomy;
pub mod authority;
pub mod model;
pub mod output;
pub mod stats;

use anatomy::build_anatomy;
use authority::AtlasAuthority;
use std::path::Path;

pub fn execute(
    repository: &Path,
    parent: &Path,
    out: &Path,
) -> Result<String, Box<dyn std::error::Error>> {
    let authority = AtlasAuthority::open(parent)?;
    let products = build_anatomy(authority.records()).map_err(|e| format!("ANATOMY_FAILED:{e}"))?;
    output::write_products(repository, out, &authority, &products)
}

pub use output::{compare_builds, copy_compact_seal};
