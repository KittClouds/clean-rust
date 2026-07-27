use phoenix_native::{PhoenixNativeConfig, PhoenixNativeRuntime};
use phoenix_types::{RuntimeConfig, StoreCommandRequest};
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut values = env::args().skip(1);
    let store_copy = PathBuf::from(values.next().ok_or("missing copied store path")?);
    let output = PathBuf::from(values.next().ok_or("missing output path")?);
    let relation = values
        .next()
        .unwrap_or_else(|| "scoped_documents".to_owned());
    if values.next().is_some() {
        return Err("unexpected extra arguments".into());
    }
    reject_live_store(&store_copy)?;

    let runtime = PhoenixNativeRuntime::open(PhoenixNativeConfig {
        runtime: RuntimeConfig::default(),
        storage_path: Some(store_copy),
    })?;
    runtime.init()?;
    let result = runtime.store_command(StoreCommandRequest {
        command: "relation:list".to_owned(),
        payload: json!({ "relation": relation }),
    })?;
    if !result.success {
        return Err(result
            .error
            .unwrap_or_else(|| format!("{relation} export failed"))
            .into());
    }
    let rows = result
        .payload
        .unwrap_or_else(|| Value::Array(Vec::new()));
    fs::write(&output, serde_json::to_vec(&rows)?)?;
    println!(
        "exported relation={} rows={} output={}",
        relation,
        rows.as_array().map_or(0, Vec::len),
        output.display()
    );
    Ok(())
}

fn reject_live_store(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let normalized = path.to_string_lossy().replace('/', "\\").to_ascii_lowercase();
    if normalized.ends_with("\\phoenix desktop")
        || normalized.contains("\\phoenix desktop\\phoenix-overgraph")
    {
        return Err("refusing to open the live Phoenix Desktop store".into());
    }
    if !path
        .join("phoenix-overgraph")
        .join("manifest.current")
        .is_file()
    {
        return Err("copied store has no phoenix-overgraph/manifest.current".into());
    }
    Ok(())
}
