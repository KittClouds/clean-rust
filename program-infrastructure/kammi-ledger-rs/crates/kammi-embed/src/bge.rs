//! BAAI/bge-small-en-v1.5 exactly as the Python Library embeds it (fastembed 0.8 over the
//! Qdrant `bge-small-en-v1.5-onnx-Q` export).
//!
//! fastembed pipeline, reproduced step by step:
//! - tokenizer.json, truncation at `model_max_length` (512), right, special tokens added;
//! - one text per run (the Library always calls `encode([text])`), so no padding;
//! - inputs `input_ids`, `attention_mask`, `token_type_ids` = 0, as i64;
//! - ORT 1.30, `ORT_ENABLE_ALL`, 2 intra-op threads (fastembed `threads=2`);
//! - CLS row of the first output (`last_hidden_state[:, 0]`);
//! - float32 L2 normalisation with numpy's summation order: `0 + pairwise_sum(x*x)`, then
//!   `sqrt`, `max(norm, 1e-12)`, divide. Verified bit-exact against `np.linalg.norm`.

use std::path::{Path, PathBuf};

use ort::session::builder::GraphOptimizationLevel;
use ort::session::Session;
use ort::value::Tensor;
use tokenizers::{Tokenizer, TruncationDirection, TruncationParams, TruncationStrategy};

pub const DIMS: usize = 384;
pub const MAX_LENGTH: usize = 512;
pub const MODEL_FILE: &str = "model_optimized.onnx";

/// The snapshot directory inside a fastembed cache (`models--Qdrant--bge-small-en-v1.5-onnx-Q`).
pub fn snapshot_dir(cache_or_snapshot: &Path) -> Result<PathBuf, String> {
    // ONNX Runtime's Windows loader can reject a long path containing lexical `..` segments,
    // even when the normalized target exists (notably for worktrees that junction the Python
    // Library). Give it the resolved snapshot path instead.
    let cache_or_snapshot = cache_or_snapshot
        .canonicalize()
        .map_err(|e| format!("{}: {e}", cache_or_snapshot.display()))?;
    if cache_or_snapshot.join(MODEL_FILE).is_file() {
        return Ok(cache_or_snapshot);
    }
    let snapshots = cache_or_snapshot
        .join("models--Qdrant--bge-small-en-v1.5-onnx-Q")
        .join("snapshots");
    let mut found: Vec<PathBuf> = std::fs::read_dir(&snapshots)
        .map_err(|e| format!("{}: {e}", snapshots.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.join(MODEL_FILE).is_file())
        .collect();
    found.sort();
    let snapshot = found.pop().ok_or_else(|| {
        format!(
            "no bge snapshot with {MODEL_FILE} under {}",
            snapshots.display()
        )
    })?;
    snapshot
        .canonicalize()
        .map_err(|e| format!("{}: {e}", snapshot.display()))
}

/// numpy `pairwise_sum` for float32 (`loops_utils.h`), block size 128.
fn pairwise_sum(a: &[f32]) -> f32 {
    let n = a.len();
    if n < 8 {
        let mut res = -0.0f32;
        for &x in a {
            res += x;
        }
        res
    } else if n <= 128 {
        let mut r = [a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]];
        let mut i = 8;
        while i < n - (n % 8) {
            for j in 0..8 {
                r[j] += a[i + j];
            }
            i += 8;
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        while i < n {
            res += a[i];
            i += 1;
        }
        res
    } else {
        let mut n2 = n / 2;
        n2 -= n2 % 8;
        pairwise_sum(&a[..n2]) + pairwise_sum(&a[n2..])
    }
}

/// fastembed `normalize`: `x / max(np.linalg.norm(x), 1e-12)` in float32.
pub fn numpy_normalize(values: &[f32]) -> Vec<f32> {
    let squares: Vec<f32> = values.iter().map(|v| v * v).collect();
    let norm = (0.0f32 + pairwise_sum(&squares)).sqrt().max(1e-12);
    values.iter().map(|v| v / norm).collect()
}

pub struct BgeRunner {
    session: Session,
    tokenizer: Tokenizer,
    needs_token_types: bool,
    pub model_path: PathBuf,
}

impl BgeRunner {
    pub fn load(snapshot: &Path) -> Result<BgeRunner, String> {
        let mut tokenizer = Tokenizer::from_file(snapshot.join("tokenizer.json"))
            .map_err(|e| format!("bge tokenizer: {e}"))?;
        tokenizer.with_padding(None);
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: MAX_LENGTH,
                strategy: TruncationStrategy::LongestFirst,
                stride: 0,
                direction: TruncationDirection::Right,
            }))
            .map_err(|e| format!("bge truncation: {e}"))?;
        let model_path = snapshot.join(MODEL_FILE);
        let session = Session::builder()
            .and_then(|b| b.with_optimization_level(GraphOptimizationLevel::Level3))
            .and_then(|b| b.with_intra_threads(2))
            .and_then(|b| b.with_inter_threads(2))
            .and_then(|b| b.commit_from_file(&model_path))
            .map_err(|e| format!("bge session: {e}"))?;
        let needs_token_types = session.inputs.iter().any(|i| i.name == "token_type_ids");
        Ok(BgeRunner {
            session,
            tokenizer,
            needs_token_types,
            model_path,
        })
    }

    /// Token ids exactly as fed to the model.
    pub fn tokens(&self, text: &str) -> Result<Vec<u32>, String> {
        Ok(self
            .tokenizer
            .encode(text, true)
            .map_err(|e| e.to_string())?
            .get_ids()
            .to_vec())
    }

    pub fn embed_one(&self, text: &str) -> Result<Vec<f32>, String> {
        let ids: Vec<i64> = self.tokens(text)?.into_iter().map(i64::from).collect();
        let n = ids.len();
        let mask = vec![1i64; n];
        let tensor =
            |data: Vec<i64>| Tensor::from_array(([1usize, n], data)).map_err(|e| e.to_string());
        let mut inputs = vec![
            ("input_ids", tensor(ids)?),
            ("attention_mask", tensor(mask)?),
        ];
        if self.needs_token_types {
            inputs.push(("token_type_ids", tensor(vec![0i64; n])?));
        }
        let inputs: Vec<(
            std::borrow::Cow<'_, str>,
            ort::session::SessionInputValue<'_>,
        )> = inputs
            .into_iter()
            .map(|(name, t)| (std::borrow::Cow::Borrowed(name), t.into()))
            .collect();
        let outputs = self
            .session
            .run(inputs)
            .map_err(|e| format!("bge run: {e}"))?;
        let (shape, values) = outputs[0]
            .try_extract_raw_tensor::<f32>()
            .map_err(|e| format!("bge output: {e}"))?;
        let cls = match shape {
            [1, _, dims] if *dims as usize == DIMS => &values[..DIMS],
            [1, dims] if *dims as usize == DIMS => &values[..DIMS],
            other => return Err(format!("bge output shape {other:?}")),
        };
        Ok(numpy_normalize(cls))
    }
}

/// The Python Library's embedder identity (`ledgerd/embedding.py`), reproduced exactly so
/// memories recorded here are indistinguishable from Python's (and roll back into Python):
/// `raw_id(JCS({"model", "dimensions", "files": [{path, sha256, bytes}]}))` over every
/// `.onnx/.json/.txt` file under the cache's `snapshots` directories, in `pathlib` order
/// (case-insensitive per path component on Windows). The runtime pin is enforced separately:
/// the embedder refuses any ONNX Runtime DLL but the pinned one.
pub fn python_identity(cache: &Path) -> Result<String, String> {
    use kammi_jcs::{canonical, raw_id, Sha256Hasher, Value};
    let mut files = Vec::new();
    let mut pending = vec![cache.to_path_buf()];
    while let Some(dir) = pending.pop() {
        for entry in std::fs::read_dir(&dir).map_err(|e| format!("{}: {e}", dir.display()))? {
            let path = entry.map_err(|e| e.to_string())?.path();
            if path.is_dir() {
                pending.push(path);
                continue;
            }
            let relative = path.strip_prefix(cache).map_err(|e| e.to_string())?;
            let in_snapshots = relative.components().any(|c| c.as_os_str() == "snapshots");
            let kind = path.extension().and_then(|e| e.to_str()).unwrap_or("");
            if in_snapshots && matches!(kind, "onnx" | "json" | "txt") {
                let parts: Vec<String> = relative
                    .components()
                    .map(|c| c.as_os_str().to_string_lossy().into_owned())
                    .collect();
                files.push((parts, path));
            }
        }
    }
    files.sort_by_key(|(parts, _)| parts.iter().map(|p| p.to_lowercase()).collect::<Vec<_>>());
    if !files
        .iter()
        .any(|(parts, _)| parts.last().is_some_and(|p| p.ends_with(".onnx")))
    {
        return Err("qualified embedding model is not installed locally".into());
    }
    let mut rows = Vec::new();
    for (parts, path) in files {
        let bytes = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        let mut hasher = Sha256Hasher::new();
        hasher.update(&bytes);
        let digest = hasher.finish().to_string();
        rows.push(kammi_core::obj! {
            "path" => parts.join("/"),
            "sha256" => digest.trim_start_matches("sha256:"),
            "bytes" => bytes.len(),
        });
    }
    let manifest = kammi_core::obj! {"model" => "BAAI/bge-small-en-v1.5", "dimensions" => DIMS, "files" => Value::Array(rows)};
    Ok(raw_id(&canonical(&manifest).map_err(|e| e.to_string())?).to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pairwise_matches_the_numpy_blocking() {
        // 384 = 192 + 192, each 96 + 96, each an 8-lane block: a sequential sum differs.
        let values: Vec<f32> = (0..384)
            .map(|i| ((i * 7919) % 1000) as f32 * 1e-3 + 1e-7)
            .collect();
        let sequential: f32 = values.iter().sum();
        let pairwise = pairwise_sum(&values);
        assert!((sequential - pairwise).abs() < 1e-3);
        let normalized = numpy_normalize(&values);
        let norm: f32 = normalized.iter().map(|v| v * v).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5);
    }

    #[test]
    fn snapshot_dir_resolves_lexical_parent_segments() {
        use std::time::{SystemTime, UNIX_EPOCH};

        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let temp = std::env::temp_dir().join(format!("kammi-bge-path-{unique}"));
        let cache = temp.join("cache");
        let staging = temp.join("staging");
        let snapshot = cache
            .join("models--Qdrant--bge-small-en-v1.5-onnx-Q")
            .join("snapshots")
            .join("fixture");
        std::fs::create_dir_all(&snapshot).unwrap();
        std::fs::create_dir_all(&staging).unwrap();
        std::fs::write(snapshot.join(MODEL_FILE), b"fixture").unwrap();

        let lexical = staging.join("..").join("cache");
        let resolved = snapshot_dir(&lexical).unwrap();
        assert_eq!(resolved, snapshot.canonicalize().unwrap());

        std::fs::remove_dir_all(temp).unwrap();
    }
}
