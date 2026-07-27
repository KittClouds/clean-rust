use phoenix_native::{PhoenixNativeConfig, PhoenixNativeRuntime};
use phoenix_types::{
    AtlasRichScanDocument, AtlasRichScanOptions, AtlasRichScanPolicy, AtlasRichScanRequest,
    AtlasRichScanScope, DocumentId, NoteId, RuntimeConfig, ScopeKey, SessionId,
};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse()?;
    reject_live_store(&args.store_copy)?;
    let markdown = fs::read_to_string(&args.markdown_input)?;
    let runtime = PhoenixNativeRuntime::open(PhoenixNativeConfig {
        runtime: RuntimeConfig::default(),
        storage_path: Some(args.store_copy.clone()),
    })?;
    runtime.init()?;

    let started = Instant::now();
    let result = runtime.atlas_rich_scan(AtlasRichScanRequest {
        scan_id: Some(format!("native-cohort-{}", args.note_id)),
        session_id: Some(SessionId("native-cohort".into())),
        scope: AtlasRichScanScope {
            mode: Some("note".into()),
            note_id: Some(NoteId(args.note_id.clone())),
            ..Default::default()
        },
        documents: vec![AtlasRichScanDocument {
            document_id: DocumentId(args.note_id.clone()),
            note_id: Some(NoteId(args.note_id.clone())),
            title: args.title.clone(),
            text: markdown,
            scope: ScopeKey::default(),
        }],
        changed_document_ids: vec![DocumentId(args.note_id.clone())],
        options: AtlasRichScanOptions {
            policy: AtlasRichScanPolicy::Force,
            return_candidate_suggestions: true,
            include_semantic_atlas: false,
            ..Default::default()
        },
        ..Default::default()
    })?;
    fs::write(&args.output, serde_json::to_vec_pretty(&result)?)?;

    println!(
        "analyzed note={} elapsed_ms={} candidates={} identity_receipts={} graph_nodes={} graph_edges={} output={}",
        args.note_id,
        started.elapsed().as_millis(),
        result.candidate_suggestions.len(),
        result.identity_resolution.receipt_count,
        result.graph_delta_counts.get("nodes").copied().unwrap_or(0),
        result.graph_delta_counts.get("edges").copied().unwrap_or(0),
        args.output.display()
    );
    for diagnostic in &result.diagnostics {
        println!("diagnostic {}: {}", diagnostic.code, diagnostic.message);
    }
    Ok(())
}

fn reject_live_store(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let normalized = path.to_string_lossy().replace('/', "\\").to_ascii_lowercase();
    if normalized.ends_with("\\phoenix desktop")
        || normalized.contains("\\phoenix desktop\\phoenix-overgraph")
    {
        return Err("refusing to analyze against the live Phoenix Desktop store".into());
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

struct Args {
    store_copy: PathBuf,
    note_id: String,
    title: String,
    markdown_input: PathBuf,
    output: PathBuf,
}

impl Args {
    fn parse() -> Result<Self, Box<dyn std::error::Error>> {
        let mut values = env::args().skip(1);
        let store_copy = values.next().ok_or("missing copied store path")?.into();
        let note_id = values.next().ok_or("missing note ID")?;
        let title = values.next().ok_or("missing note title")?;
        let markdown_input = values.next().ok_or("missing Markdown input path")?.into();
        let output = values.next().ok_or("missing result output path")?.into();
        if values.next().is_some() {
            return Err("unexpected extra arguments".into());
        }
        Ok(Self {
            store_copy,
            note_id,
            title,
            markdown_input,
            output,
        })
    }
}
