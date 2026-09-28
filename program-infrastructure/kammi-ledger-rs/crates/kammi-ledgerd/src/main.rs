//! `kammi-ledgerd`: the Library daemon. Same `KAMMI_*` environment as the Python service:
//!
//! - `KAMMI_ROOT` (a v2 store), `KAMMI_TOKEN` or `KAMMI_TOKEN_FILE`, `KAMMI_PORT` (8765),
//!   `KAMMI_SIGNING_KEY_FILE` (raw 32-byte Ed25519 seed), `KAMMI_ACCEPTANCE_MODE=1`;
//! - `KAMMI_EMBEDDER` enables memory: `gemma300[:<model dir>]`, `jina-v5[:<model dir>]`,
//!   `mdbr[:<model dir>]` (Phoenix ONNX runners) or `hashing:<dims>` (test embedder);
//! - `KAMMI_SOURCE_DIR` overrides the source tree bound into the flight identity;
//! - `KAMMI_PROJECTOR`: path to `kammi-projector` (default: beside this binary) or `off`;
//!   `KAMMI_PROJECTION_DB` (default `<root>/projection/custody.lbdb`), `KAMMI_LBUG_NATIVE_DIR`
//!   (Ladybug runtime DLLs), `KAMMI_PROJECTION_VERIFY=0` skips deep verification on start.

#![allow(clippy::result_large_err)]

use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use kammi_core::{Embedder, FlightIdentity, Ledger, LedgerOptions, SystemClock};
use kammi_jcs::{canonical, raw_id, Sha256Hasher, Value};
use kammi_ledgerd::{router, AppState};
use kammi_store::{Store, StoreOptions};
use parking_lot::RwLock;

type Error = Box<dyn std::error::Error + Send + Sync>;

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok().filter(|v| !v.is_empty())
}

fn file_sha256(path: &Path) -> Result<String, Error> {
    let mut hasher = Sha256Hasher::new();
    let mut file = std::fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let read = std::io::Read::read(&mut file, &mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher.finish().to_string())
}

/// Source manifest root over the workspace, with `release.py`'s file-type rules.
fn source_root(dir: &Path) -> Result<String, Error> {
    const KINDS: [&str; 7] = ["rs", "toml", "lock", "md", "json", "txt", "wgsl"];
    let mut files = Vec::new();
    let mut pending = vec![dir.to_path_buf()];
    while let Some(current) = pending.pop() {
        for entry in std::fs::read_dir(&current)? {
            let path = entry?.path();
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if path.is_dir() {
                if !matches!(name, "target" | "vendor" | ".git" | "tmp") {
                    pending.push(path);
                }
            } else if path
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| KINDS.contains(&e))
            {
                files.push(path);
            }
        }
    }
    files.sort();
    let mut manifest = kammi_jcs::Map::new();
    for path in files {
        let relative = path.strip_prefix(dir)?.to_string_lossy().replace('\\', "/");
        manifest.insert(relative, Value::from(file_sha256(&path)?));
    }
    Ok(raw_id(&canonical(&Value::Object(manifest))?).to_string())
}

fn flight_identity() -> Result<FlightIdentity, Error> {
    let source_dir = env("KAMMI_SOURCE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../.."));
    let source = source_root(&source_dir)?;
    let exe = std::env::current_exe()?;
    let runtime = kammi_core::obj! {"kammi-ledgerd" => file_sha256(&exe)?, "store_format" => "kammi-store-v2"};
    Ok(FlightIdentity {
        architecture: "kammi-ledger-rs/ARCHITECTURE-AMENDMENT-v3-RUST-STORE".into(),
        source_root: source,
        runtime_identity: raw_id(&canonical(&runtime)?).to_string(),
    })
}

fn embedder() -> Result<Option<Arc<dyn Embedder>>, Error> {
    let Some(spec) = env("KAMMI_EMBEDDER") else {
        return Ok(None);
    };
    let embedder = kammi_embed::from_spec(&spec)?;
    eprintln!(
        "kammi-ledgerd: memory embedder {}",
        embedder.model_identity().id
    );
    Ok(Some(embedder))
}

fn main() -> Result<(), Error> {
    // Mutates the process environment, so it runs before the runtime starts threads.
    kammi_embed::ensure_ort_dylib();
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(serve())
}

async fn serve() -> Result<(), Error> {
    let root = env("KAMMI_ROOT");
    let token = match env("KAMMI_TOKEN") {
        Some(token) => Some(token),
        None => env("KAMMI_TOKEN_FILE")
            .map(std::fs::read_to_string)
            .transpose()?
            .map(|t| t.trim().to_string()),
    };
    let (Some(root), Some(token)) = (root, token) else {
        return Err("KAMMI_ROOT and KAMMI_TOKEN are required".into());
    };
    let signing_key = match env("KAMMI_SIGNING_KEY_FILE") {
        Some(path) => Some(
            <[u8; 32]>::try_from(std::fs::read(&path)?.as_slice())
                .map_err(|_| "signing key must be a raw 32-byte seed")?,
        ),
        None => None,
    };
    let root = PathBuf::from(root);
    let started = std::time::Instant::now();
    let store = Store::open(&root, StoreOptions::default())?;
    // A fixed clock makes differential runs mint identical identities on both sides. It
    // would freeze lease and grant expiry, so it exists only in acceptance fixture mode.
    let clock: Arc<dyn kammi_core::Clock> = match env("KAMMI_TEST_CLOCK") {
        Some(at) if env("KAMMI_ACCEPTANCE_MODE").as_deref() == Some("1") => Arc::new(
            kammi_core::ManualClock::new(kammi_core::time::parse_utc(&at)?),
        ),
        Some(_) => return Err("KAMMI_TEST_CLOCK requires KAMMI_ACCEPTANCE_MODE=1".into()),
        None => Arc::new(SystemClock),
    };
    let options = LedgerOptions {
        clock,
        signing_key,
        embedder: embedder()?,
        flight: flight_identity()?,
        writer: kammi_core::obj! {"pid" => std::process::id(), "implementation" => "kammi-ledgerd"},
    };
    let dims = options.embedder.as_ref().map_or(384, |e| e.dimension());
    let mut ledger = tokio::task::spawn_blocking(move || Ledger::open(store, options)).await??;
    let projector = projector_config(&root, dims)?.map(kammi_ledgerd::projector::Projector::start);
    if let Some(projector) = &projector {
        ledger.set_memory_index(projector.clone());
    }
    eprintln!(
        "kammi-ledgerd: replayed {} events in {:.2}s; flight {}",
        ledger.store.main.seq(),
        started.elapsed().as_secs_f64(),
        ledger.flight_state()["state"]
    );
    let state = Arc::new(AppState {
        ledger: Arc::new(RwLock::new(ledger)),
        token,
        acceptance_mode: env("KAMMI_ACCEPTANCE_MODE").as_deref() == Some("1"),
        staging: root.join("staging"),
        projector: projector.clone(),
    });
    let port: u16 = env("KAMMI_PORT")
        .map(|p| p.parse())
        .transpose()?
        .unwrap_or(8765);
    let listener = tokio::net::TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], port))).await?;
    eprintln!("kammi-ledgerd: listening on http://127.0.0.1:{port}");
    axum::serve(listener, router(state))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    if let Some(projector) = projector {
        projector.stop();
    }
    Ok(())
}

fn projector_config(
    root: &Path,
    memory_dims: usize,
) -> Result<Option<kammi_ledgerd::projector::ProjectorConfig>, Error> {
    let exe = match env("KAMMI_PROJECTOR") {
        Some(value) if value.eq_ignore_ascii_case("off") => return Ok(None),
        Some(path) => PathBuf::from(path),
        None => std::env::current_exe()?.with_file_name("kammi-projector.exe"),
    };
    if !exe.is_file() {
        eprintln!(
            "kammi-ledgerd: projector {} not found; memory retrieval uses native indexes",
            exe.display()
        );
        return Ok(None);
    }
    let native_dir = env("KAMMI_LBUG_NATIVE_DIR").map(PathBuf::from).or_else(|| {
        let default = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../kammi-ledger/vendor/runtime-v1/native");
        default.is_dir().then_some(default)
    });
    Ok(Some(kammi_ledgerd::projector::ProjectorConfig {
        exe,
        store: root.to_path_buf(),
        db: env("KAMMI_PROJECTION_DB")
            .map(PathBuf::from)
            .unwrap_or_else(|| root.join("projection").join("custody.lbdb")),
        memory_dims,
        verify: env("KAMMI_PROJECTION_VERIFY").as_deref() != Some("0"),
        native_dir,
    }))
}
