use std::{env, fs};

use rdc_experiment_009::bundle::ObserverBundleManifest;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    bundles: Vec<ObserverBundleManifest>,
}

#[derive(Serialize)]
struct LockedBundle {
    manifest: ObserverBundleManifest,
    blake3: String,
}

#[derive(Serialize)]
struct Output {
    schema_version: u16,
    bundles: Vec<LockedBundle>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let input_path = args.next().ok_or("missing input path")?;
    let output_path = args.next().ok_or("missing output path")?;
    if args.next().is_some() {
        return Err("expected exactly two paths".into());
    }

    let input: Input = serde_json::from_slice(&fs::read(input_path)?)?;
    let mut bundles = Vec::with_capacity(input.bundles.len());
    for manifest in input.bundles {
        manifest
            .validate()
            .map_err(|error| format!("bundle validation failed: {error:?}"))?;
        let digest = blake3::Hash::from_bytes(manifest.manifest_hash()?);
        bundles.push(LockedBundle {
            manifest,
            blake3: digest.to_hex().to_string(),
        });
    }

    fs::write(
        output_path,
        serde_json::to_vec_pretty(&Output {
            schema_version: 1,
            bundles,
        })?,
    )?;
    Ok(())
}
