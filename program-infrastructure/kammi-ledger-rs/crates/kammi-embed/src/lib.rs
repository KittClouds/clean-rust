//! Memory embedders over the Phoenix ONNX runners.
//!
//! One ORT session per model serves both sides: the Phoenix runner configs differ between
//! query and document only by a text prefix, so this crate loads the document config with no
//! prefix and prepends the family's query/document prefix itself (half the RAM of two
//! sessions). Output vectors are the runner's own (pooled, profile-projected, L2-normalised).
//!
//! The embedder identity stored on every memory record binds the family, the pooling/prefix
//! configuration and a SHA-256 manifest of the exact model files the session loaded, so a
//! changed model can never silently mix vector spaces.

pub mod bge;

use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc, Mutex};

use kammi_core::{Embedder, Embeddings, Input, ModelIdentity, Role};
use kammi_jcs::{canonical, raw_id, Map, Sha256Hasher, Value};
use phoenix_embed::{
    OrtTextEmbedConfig, OrtTextEmbedder, TextEmbeddingInputPrefix, TextEmbeddingPooling,
    TextEmbeddingProfile,
};
use tokenizers::{Tokenizer, TruncationDirection, TruncationParams, TruncationStrategy};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Family {
    /// EmbeddingGemma 300M (768-d, mean pooling, q4).
    Gemma300,
    /// Jina embeddings v5 text nano retrieval (768-d, last-token pooling).
    JinaV5,
    /// MDBR leaf MT (384-d, mean pooling).
    Mdbr,
    /// BAAI/bge-small-en-v1.5 exactly as the Python Library embeds it (fastembed, 384-d, CLS).
    Bge,
}

impl Family {
    pub fn parse(name: &str) -> Option<Family> {
        match name.to_ascii_lowercase().as_str() {
            "gemma300" | "gemma" | "embeddinggemma" => Some(Family::Gemma300),
            "jina-v5" | "jinav5" | "jina" => Some(Family::JinaV5),
            "mdbr" => Some(Family::Mdbr),
            "bge" | "bge-small" | "bge-small-en-v1.5" => Some(Family::Bge),
            _ => None,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Family::Gemma300 => "embeddinggemma-300m",
            Family::JinaV5 => "jina-embeddings-v5-text-nano-retrieval",
            Family::Mdbr => "mdbr-leaf-mt",
            Family::Bge => "bge-small-en-v1.5",
        }
    }

    /// The Phoenix runner's default model directory for this family.
    pub fn default_model_root(self) -> PathBuf {
        PathBuf::from(match self {
            Family::Gemma300 => r"D:\phoenix-models\embeddinggemma-300m-ONNX",
            Family::JinaV5 => r"D:\phoenix-models\jina-embeddings-v5-text-nano-retrieval",
            Family::Mdbr => r"D:\phoenix-models\mdbr-leaf-mt",
            Family::Bge => {
                return Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../../kammi-ledger/vendor/runtime-v1/embedding-cache")
            }
        })
    }

    /// Output dimension of the family's profile.
    pub fn dims(self) -> usize {
        match self {
            Family::Gemma300 | Family::JinaV5 => 768,
            Family::Mdbr | Family::Bge => 384,
        }
    }

    /// How the family may be batched. Measured by `tools/embed_qualify.py`: the EmbeddingGemma
    /// q4 export is not padding-invariant (a padded row drifts to cosine ~0.9997 of itself,
    /// in the reference runtime too), so it only batches inputs of identical token length.
    /// Jina v5 is padding-invariant to 1e-7 and uses padded, length-bucketed batches.
    pub fn scheduler(self) -> Scheduler {
        match self {
            Family::Gemma300 | Family::Mdbr => Scheduler::PadFree,
            Family::JinaV5 => Scheduler::Padded,
            Family::Bge => Scheduler::Single,
        }
    }

    /// (query prefix, document prefix), identical to the Phoenix runner configs.
    pub fn prefixes(self) -> (&'static str, &'static str) {
        match self {
            Family::Gemma300 => ("task: search result | query: ", "title: none | text: "),
            Family::JinaV5 => ("Query: ", "Document: "),
            Family::Mdbr => (
                "Represent this sentence for searching relevant passages: ",
                "",
            ),
            Family::Bge => ("", ""),
        }
    }

    /// The Phoenix document config for this family (its prefix is replaced by none).
    pub fn config(self, model_root: PathBuf) -> OrtTextEmbedConfig {
        match self {
            Family::Gemma300 => OrtTextEmbedConfig::embedding_gemma_document(model_root),
            Family::JinaV5 => OrtTextEmbedConfig::jina_v5_retrieval_document(model_root),
            Family::Mdbr => OrtTextEmbedConfig::mdbr_leaf_mt_document(model_root),
            // A descriptor only: bge runs through `bge::BgeRunner`, not the Phoenix loader.
            Family::Bge => OrtTextEmbedConfig {
                model_root,
                batch_size: 1,
                max_length: bge::MAX_LENGTH,
                profile: TextEmbeddingProfile::Native384,
                pooling: TextEmbeddingPooling::Cls,
                ..OrtTextEmbedConfig::default()
            },
        }
    }

    /// The directory holding the tokenizer and model files (bge: the fastembed snapshot).
    pub fn model_dir(self, model_root: &Path) -> Result<PathBuf, String> {
        match self {
            Family::Bge => bge::snapshot_dir(model_root),
            _ => Ok(model_root.to_path_buf()),
        }
    }
}

type Job = (Vec<String>, mpsc::Sender<Result<Vec<Vec<f32>>, String>>);

/// A Phoenix runner on its own thread (ORT sessions here are not `Send`); callers queue
/// batches over a channel, so embedding never runs under the ledger's writer lock.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scheduler {
    /// The runner's own padded, length-bucketed batches.
    Padded,
    /// Batches only of inputs with identical token counts: no row is ever padded.
    PadFree,
    /// One input per run (the Python Library's fastembed call pattern).
    Single,
}

#[allow(clippy::large_enum_variant)] // one instance per process
enum Runner {
    Phoenix {
        runner: OrtTextEmbedder,
        tokenizer: Tokenizer,
        scheduler: Scheduler,
        batch: usize,
    },
    Bge(Box<bge::BgeRunner>),
}

impl Runner {
    fn load(family: Family, config: &OrtTextEmbedConfig) -> Result<(Runner, PathBuf), String> {
        if family == Family::Bge {
            let runner = bge::BgeRunner::load(&config.model_root)?;
            let path = runner.model_path.clone();
            return Ok((Runner::Bge(Box::new(runner)), path));
        }
        let tokenizer = family_tokenizer(&config.model_root, config.max_length)
            .map_err(|e| format!("tokenizer: {e}"))?;
        let runner = OrtTextEmbedder::load(config).map_err(|e| e.to_string())?;
        let path = runner.info().model_path.clone();
        let (scheduler, batch) = (family.scheduler(), config.batch_size);
        Ok((
            Runner::Phoenix {
                runner,
                tokenizer,
                scheduler,
                batch,
            },
            path,
        ))
    }

    fn run(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, String> {
        match self {
            Runner::Phoenix {
                runner,
                tokenizer,
                scheduler,
                batch,
            } => run_scheduled(runner, tokenizer, *scheduler, *batch, texts),
            Runner::Bge(runner) => texts.iter().map(|t| runner.embed_one(t)).collect(),
        }
    }
}

/// Runs `texts` through the runner under `scheduler`, returning rows in input order.
fn run_scheduled(
    runner: &OrtTextEmbedder,
    tokenizer: &Tokenizer,
    scheduler: Scheduler,
    batch: usize,
    texts: &[String],
) -> Result<Vec<Vec<f32>>, String> {
    if scheduler != Scheduler::PadFree || texts.len() == 1 {
        return runner.embed_texts(texts).map_err(|e| e.to_string());
    }
    let encodings = tokenizer
        .encode_batch(texts.iter().map(String::as_str).collect::<Vec<_>>(), true)
        .map_err(|e| e.to_string())?;
    let mut groups: std::collections::BTreeMap<usize, Vec<usize>> =
        std::collections::BTreeMap::new();
    for (index, encoding) in encodings.iter().enumerate() {
        groups.entry(encoding.len()).or_default().push(index);
    }
    let mut rows: Vec<Option<Vec<f32>>> = vec![None; texts.len()];
    for indexes in groups.values() {
        for chunk in indexes.chunks(batch.max(1)) {
            let slice: Vec<&str> = chunk.iter().map(|&i| texts[i].as_str()).collect();
            for (&index, row) in chunk
                .iter()
                .zip(runner.embed_texts(&slice).map_err(|e| e.to_string())?)
            {
                rows[index] = Some(row);
            }
        }
    }
    rows.into_iter()
        .map(|r| r.ok_or_else(|| "scheduler lost a row".to_string()))
        .collect()
}

/// The runner's tokenizer configuration (family `max_length`, right truncation, no padding),
/// used for exact token counts.
pub fn family_tokenizer(model_root: &Path, max_length: usize) -> Result<Tokenizer, String> {
    let mut tokenizer =
        Tokenizer::from_file(model_root.join("tokenizer.json")).map_err(|e| e.to_string())?;
    tokenizer.with_padding(None);
    tokenizer
        .with_truncation(Some(TruncationParams {
            max_length,
            strategy: TruncationStrategy::LongestFirst,
            stride: 0,
            direction: TruncationDirection::Right,
        }))
        .map_err(|e| e.to_string())?;
    Ok(tokenizer)
}

pub struct PhoenixEmbedder {
    family: Family,
    jobs: Mutex<mpsc::Sender<Job>>,
    identity: ModelIdentity,
    model_path: PathBuf,
    model_dir: PathBuf,
}

impl PhoenixEmbedder {
    /// Loads the family's model. `ORT_DYLIB_PATH` must name the ONNX Runtime DLL
    /// (see [`ensure_ort_dylib`]).
    pub fn load(family: Family, model_root: &Path) -> Result<PhoenixEmbedder, String> {
        let model_dir = family.model_dir(model_root)?;
        let config = OrtTextEmbedConfig {
            input_prefix: TextEmbeddingInputPrefix::None,
            prefix_passage: false,
            ..family.config(model_dir.clone())
        };
        let (jobs, queue) = mpsc::channel::<Job>();
        let (ready, loaded) = mpsc::channel::<Result<PathBuf, String>>();
        let worker_config = config.clone();
        std::thread::Builder::new()
            .name(format!("kammi-embed-{}", family.label()))
            .spawn(move || {
                let runner = match Runner::load(family, &worker_config) {
                    Ok((runner, path)) => {
                        let _ = ready.send(Ok(path));
                        runner
                    }
                    Err(e) => {
                        let _ = ready.send(Err(format!("{}: {e}", family.label())));
                        return;
                    }
                };
                for (texts, reply) in queue {
                    let _ = reply.send(runner.run(&texts));
                }
            })
            .map_err(|e| e.to_string())?;
        let model_path = loaded
            .recv()
            .map_err(|_| "embedder thread exited during load".to_string())??;
        let id = match family {
            Family::Bge => bge::python_identity(model_root)?,
            _ => identity(family, &config, &model_path)?,
        };
        let identity = ModelIdentity {
            id,
            family: family.label().into(),
            dims: family.dims(),
        };
        Ok(PhoenixEmbedder {
            family,
            jobs: Mutex::new(jobs),
            identity,
            model_path,
            model_dir,
        })
    }

    /// Where the tokenizer and model files were loaded from.
    pub fn model_dir(&self) -> &Path {
        &self.model_dir
    }

    pub fn family(&self) -> Family {
        self.family
    }

    pub fn model_path(&self) -> &Path {
        &self.model_path
    }

    /// The exact strings the runner tokenizes for `batch` (family prefix + text).
    pub fn prompts(&self, batch: &[Input<'_>]) -> Vec<String> {
        let (query, document) = self.family.prefixes();
        batch
            .iter()
            .map(|i| {
                format!(
                    "{}{}",
                    if i.role == Role::Query {
                        query
                    } else {
                        document
                    },
                    i.text
                )
            })
            .collect()
    }
}

impl Embedder for PhoenixEmbedder {
    fn embed(&self, batch: &[Input<'_>]) -> Result<Embeddings, String> {
        let (reply, answer) = mpsc::channel();
        self.jobs
            .lock()
            .map_err(|_| "embedder queue poisoned".to_string())?
            .send((self.prompts(batch), reply))
            .map_err(|_| "embedder thread stopped".to_string())?;
        let rows = answer
            .recv()
            .map_err(|_| "embedder thread stopped".to_string())??;
        Embeddings::from_rows(rows, self.identity.dims)
    }

    fn dimension(&self) -> usize {
        self.identity.dims
    }

    fn model_identity(&self) -> &ModelIdentity {
        &self.identity
    }
}

fn file_sha256(path: &Path) -> Result<String, String> {
    use std::io::Read;
    let mut file = std::fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut hasher = Sha256Hasher::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|e| format!("{}: {e}", path.display()))?;
        if read == 0 {
            return Ok(hasher.finish().to_string());
        }
        hasher.update(&buffer[..read]);
    }
}

/// `phoenix-embed:<family>:<model file>:<manifest root>`, where the manifest covers the
/// tokenizer/config files and the loaded ONNX graph plus its external data file.
fn identity(
    family: Family,
    config: &OrtTextEmbedConfig,
    model_path: &Path,
) -> Result<String, String> {
    let root = &config.model_root;
    let mut files: Vec<PathBuf> = [
        "tokenizer.json",
        "tokenizer_config.json",
        "config.json",
        "special_tokens_map.json",
    ]
    .iter()
    .map(|f| root.join(f))
    .collect();
    files.push(model_path.to_path_buf());
    let mut data = model_path.as_os_str().to_owned();
    data.push("_data");
    files.push(PathBuf::from(data));
    let mut manifest = Map::new();
    for path in files.into_iter().filter(|p| p.is_file()) {
        let relative = path
            .strip_prefix(root)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        manifest.insert(relative, Value::from(file_sha256(&path)?));
    }
    let (query, document) = family.prefixes();
    let configuration = kammi_core::obj! {
        "family" => family.label(),
        "files" => Value::Object(manifest),
        "profile" => format!("{:?}", config.profile),
        "pooling" => format!("{:?}", config.pooling),
        "max_length" => config.max_length,
        "scheduler" => format!("{:?}", family.scheduler()),
        "onnxruntime" => match std::env::var_os("ORT_DYLIB_PATH") {
            Some(path) => Value::from(file_sha256(Path::new(&path))?),
            None => Value::Null,
        },
        "query_prefix" => query,
        "document_prefix" => document,
    };
    let digest = raw_id(&canonical(&configuration).map_err(|e| e.to_string())?).to_string();
    let file = model_path
        .file_name()
        .map(|f| f.to_string_lossy().into_owned())
        .unwrap_or_default();
    Ok(format!("phoenix-embed:{}:{file}:{digest}", family.label()))
}

/// The ONNX Runtime the Library is qualified on (`vendor/onnxruntime-1.30.0`).
pub fn pinned_ort_dylib() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../vendor/onnxruntime-1.30.0/onnxruntime.dll")
}

/// Points `ORT_DYLIB_PATH` at the pinned ONNX Runtime unless the caller set it explicitly
/// (the DLL actually used is hashed into every embedder identity either way). Call before
/// any other thread starts: it mutates the process environment.
pub fn ensure_ort_dylib() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os("ORT_DYLIB_PATH") {
        return Some(PathBuf::from(path));
    }
    let pinned = pinned_ort_dylib();
    if !pinned.is_file() {
        eprintln!(
            "kammi-embed: {} missing; run vendor/onnxruntime-1.30.0/fetch.ps1",
            pinned.display()
        );
        return None;
    }
    // Refuse anything but the pinned bytes (vendor/onnxruntime-1.30.0/SHA256SUMS).
    let expected = include_str!("../../../vendor/onnxruntime-1.30.0/SHA256SUMS")
        .lines()
        .find(|l| l.ends_with("  onnxruntime.dll"))
        .and_then(|l| l.split_whitespace().next())
        .map(|h| format!("sha256:{h}"));
    if file_sha256(&pinned).ok() != expected {
        eprintln!(
            "kammi-embed: {} does not match SHA256SUMS; rerun fetch.ps1",
            pinned.display()
        );
        return None;
    }
    // SAFETY: documented precondition — called while the process is single-threaded.
    unsafe { std::env::set_var("ORT_DYLIB_PATH", &pinned) };
    Some(pinned)
}

/// Parses `KAMMI_EMBEDDER`: `gemma300[:<model dir>]`, `jina-v5[:<model dir>]`,
/// `mdbr[:<model dir>]`, `bge[:<fastembed cache>]` or `hashing:<dims>` (deterministic test
/// embedder).
pub fn from_spec(spec: &str) -> Result<Arc<dyn Embedder>, String> {
    let (name, rest) = match spec.split_once(':') {
        Some((name, rest)) => (name, Some(rest)),
        None => (spec, None),
    };
    if name == "hashing" {
        let dims = rest
            .unwrap_or("384")
            .parse::<usize>()
            .map_err(|e| format!("hashing dims: {e}"))?;
        return Ok(Arc::new(kammi_core::HashingEmbedder::new(dims)));
    }
    let family = Family::parse(name).ok_or_else(|| format!("unknown embedder family: {name}"))?;
    let root = rest
        .map(PathBuf::from)
        .unwrap_or_else(|| family.default_model_root());
    Ok(Arc::new(PhoenixEmbedder::load(family, &root)?))
}
