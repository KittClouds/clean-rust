use std::path::{Path, PathBuf};

use g_reasoner_34m_parity::checkpoint::MappedCheckpoint;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let checkpoint = std::env::var_os("G_REASONER_CHECKPOINT_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(r"D:\phoenix-target-g-reasoner-34m\assets\g-reasoner-34m.safetensors")
        });
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures")
        .join("checkpoint-manifest.json");
    let checkpoint = MappedCheckpoint::open(checkpoint, manifest)?;
    println!(
        "checkpoint={} parameters={} tensors={} checkpoint_revision={} upstream_revision={}",
        checkpoint.path().display(),
        checkpoint.manifest().parameter_count,
        checkpoint.manifest().tensors.len(),
        checkpoint.manifest().checkpoint_revision,
        checkpoint.manifest().upstream_revision,
    );
    Ok(())
}
