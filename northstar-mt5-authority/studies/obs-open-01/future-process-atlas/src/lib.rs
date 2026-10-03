mod aggregate;
mod authority;
mod compute;
mod model;
mod output;

pub use authority::{load_atlas_authority, raw_path};
pub use compute::{OutcomeProducts, compute_outcomes};
pub use model::*;
pub use output::{compare_builds, copy_compact_seal, write_products};

use std::path::Path;

pub fn execute(repository: &Path, output: &Path) -> Result<String, Box<dyn std::error::Error>> {
    let mut loaded = load_atlas_authority(repository, &raw_path())?;
    let products = compute_outcomes(&loaded.sessions)
        .map_err(|e| -> Box<dyn std::error::Error> { e.into() })?;
    write_products(repository, output, &mut loaded, &products)
}
