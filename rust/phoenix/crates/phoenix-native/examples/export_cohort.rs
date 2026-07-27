use phoenix_native::{PhoenixNativeConfig, PhoenixNativeRuntime};
use phoenix_types::{RuntimeConfig, StoreCommandRequest};
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse()?;
    reject_live_store(&args.store_copy)?;

    let runtime = PhoenixNativeRuntime::open(PhoenixNativeConfig {
        runtime: RuntimeConfig::default(),
        storage_path: Some(args.store_copy.clone()),
    })?;
    runtime.init()?;

    let note = command_payload(
        &runtime,
        "note:get",
        json!({ "id": args.note_id, "includeBody": true }),
    )?
    .ok_or("note:get returned no payload")?;
    let markdown = note
        .get("markdownContent")
        .or_else(|| note.get("markdown_content"))
        .or_else(|| note.get("content"))
        .and_then(Value::as_str)
        .ok_or("note body is unavailable")?;
    fs::write(&args.markdown_output, markdown.as_bytes())?;

    let entities = command_payload(
        &runtime,
        "relation:list",
        json!({ "relation": "entities" }),
    )?
    .unwrap_or_else(|| Value::Array(Vec::new()));
    fs::write(
        &args.entities_output,
        serde_json::to_vec_pretty(&entities)?,
    )?;

    println!(
        "exported note={} utf16_chars={} utf8_bytes={} entities={} markdown={} registry={}",
        args.note_id,
        markdown.encode_utf16().count(),
        markdown.len(),
        entities.as_array().map_or(0, Vec::len),
        args.markdown_output.display(),
        args.entities_output.display()
    );
    Ok(())
}

fn command_payload(
    runtime: &PhoenixNativeRuntime,
    command: &str,
    payload: Value,
) -> Result<Option<Value>, Box<dyn std::error::Error>> {
    let result = runtime.store_command(StoreCommandRequest {
        command: command.to_owned(),
        payload,
    })?;
    if !result.success {
        return Err(result
            .error
            .unwrap_or_else(|| format!("{command} failed without an error"))
            .into());
    }
    Ok(result.payload)
}

fn reject_live_store(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let normalized = path.to_string_lossy().replace('/', "\\").to_ascii_lowercase();
    if normalized.ends_with("\\phoenix desktop")
        || normalized.contains("\\phoenix desktop\\phoenix-overgraph")
    {
        return Err("refusing to open the live Phoenix Desktop store; pass a copied store".into());
    }
    if !path
        .join("phoenix-overgraph")
        .join("manifest.current")
        .is_file()
    {
        return Err(format!(
            "copied store has no phoenix-overgraph/manifest.current: {}",
            path.display()
        )
        .into());
    }
    Ok(())
}

struct Args {
    store_copy: PathBuf,
    note_id: String,
    markdown_output: PathBuf,
    entities_output: PathBuf,
}

impl Args {
    fn parse() -> Result<Self, Box<dyn std::error::Error>> {
        let mut values = env::args().skip(1);
        let store_copy = values.next().ok_or("missing copied store path")?.into();
        let note_id = values.next().ok_or("missing note ID")?;
        let markdown_output = values.next().ok_or("missing Markdown output path")?.into();
        let entities_output = values.next().ok_or("missing entity output path")?.into();
        if values.next().is_some() {
            return Err("unexpected extra arguments".into());
        }
        Ok(Self {
            store_copy,
            note_id,
            markdown_output,
            entities_output,
        })
    }
}
