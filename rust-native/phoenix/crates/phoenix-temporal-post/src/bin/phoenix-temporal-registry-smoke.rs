use std::path::PathBuf;

use phoenix_temporal_post::registry::{scan_temporal_registry_path, TemporalRegistryScanConfig};
use phoenix_temporal_post::registry_sidecar::build_temporal_registry_sidecar;

#[derive(Debug)]
struct Config {
    root: PathBuf,
    json_out: Option<PathBuf>,
    sidecar_out: Option<PathBuf>,
    pretty: bool,
    max_file_bytes: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            root: PathBuf::from("docs"),
            json_out: None,
            sidecar_out: None,
            pretty: false,
            max_file_bytes: 1_500_000,
        }
    }
}

fn main() -> Result<(), String> {
    let config = parse_args(&std::env::args().collect::<Vec<_>>())?;
    let registry = scan_temporal_registry_path(
        &config.root,
        &TemporalRegistryScanConfig {
            generated_at: now_ms(),
            max_file_bytes: config.max_file_bytes,
            ..TemporalRegistryScanConfig::default()
        },
    )
    .map_err(|error| format!("failed to scan temporal registry: {error}"))?;

    let sidecar = build_temporal_registry_sidecar(&registry);

    if let Some(path) = config.json_out {
        let json = if config.pretty {
            serde_json::to_string_pretty(&registry)
        } else {
            serde_json::to_string(&registry)
        }
        .map_err(|error| format!("failed to render registry json: {error}"))?;
        std::fs::write(&path, json)
            .map_err(|error| format!("failed to write {}: {error}", path.display()))?;
    }
    if let Some(path) = config.sidecar_out {
        let json = if config.pretty {
            serde_json::to_string_pretty(&sidecar)
        } else {
            serde_json::to_string(&sidecar)
        }
        .map_err(|error| format!("failed to render sidecar json: {error}"))?;
        std::fs::write(&path, json)
            .map_err(|error| format!("failed to write {}: {error}", path.display()))?;
    }

    println!("temporal registry: {}", registry.registry_id);
    println!("- root: {}", registry.root);
    println!("- documents: {}", registry.summary.document_count);
    println!("- anchors: {}", registry.summary.anchor_count);
    println!("- sidecar timex: {}", sidecar.summary.timex_count);
    println!("- sidecar axes: {}", sidecar.axes.len());
    println!("- explicit: {}", registry.summary.explicit_anchor_count);
    println!("- relative: {}", registry.summary.relative_anchor_count);
    for (source_class, count) in &registry.summary.source_class_counts {
        println!("- source {source_class}: {count}");
    }
    for (code, count) in &registry.summary.diagnostics {
        println!("- diagnostic {code}: {count}");
    }
    for anchor in registry.anchors.iter().take(16) {
        println!(
            "- {} [{}] {} @ {}:{}",
            anchor.surface,
            anchor.source_class,
            anchor.normalized_value.as_deref().unwrap_or(""),
            anchor.relative_path,
            anchor.range.start
        );
    }

    Ok(())
}

fn parse_args(args: &[String]) -> Result<Config, String> {
    let mut config = Config::default();
    let mut index = 1usize;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                config.root = PathBuf::from(args.get(index).ok_or("--root requires a value")?);
            }
            "--json-out" => {
                index += 1;
                config.json_out = Some(PathBuf::from(
                    args.get(index).ok_or("--json-out requires a value")?,
                ));
            }
            "--sidecar-out" => {
                index += 1;
                config.sidecar_out = Some(PathBuf::from(
                    args.get(index).ok_or("--sidecar-out requires a value")?,
                ));
            }
            "--pretty" => config.pretty = true,
            "--max-file-bytes" => {
                index += 1;
                let value = args.get(index).ok_or("--max-file-bytes requires a value")?;
                config.max_file_bytes = value
                    .parse()
                    .map_err(|error| format!("invalid --max-file-bytes '{value}': {error}"))?;
            }
            flag => return Err(format!("unknown argument: {flag}")),
        }
        index += 1;
    }
    Ok(config)
}

fn now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};

    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or_default()
}
