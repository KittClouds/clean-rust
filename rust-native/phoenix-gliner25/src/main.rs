use anyhow::{Result, bail, ensure};
use phoenix_gliner25::features::FeatureEngine;
use phoenix_gliner25_contract::*;
use std::{
    fs::File,
    io::{self, BufReader, BufWriter},
    path::{Path, PathBuf},
    time::Instant,
};

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match args.as_slice() {
        [command, model, ort, output] if command == "seal" => {
            seal(Path::new(model), Path::new(ort), Path::new(output))
        }
        [command, bundle] if command == "serve" => serve(Path::new(bundle)),
        _ => bail!("expected seal MODEL_ROOT ORT_DLL BUNDLE_FILE or serve BUNDLE_FILE"),
    }
}
fn seal(model: &Path, ort: &Path, output: &Path) -> Result<()> {
    ensure!(!output.exists(), "bundle already exists");
    let mut files = Vec::new();
    for entry in std::fs::read_dir(model)? {
        let path = entry?.path();
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default();
        if name.ends_with(".json")
            || name.ends_with("_fp32.onnx")
            || name.ends_with("_fp32.onnx.data")
        {
            files.push(asset(path)?);
        }
    }
    files.sort_by(|a, b| a.path.cmp(&b.path));
    let bundle = Bundle {
        contract: CONTRACT.into(),
        worker: asset(std::env::current_exe()?)?,
        ort: asset(ort.to_path_buf())?,
        model_root: model.to_path_buf(),
        model_revision: "fastino/gliner2.5-base-v1@72ac19b486cd4557424c8d61114e7530c243e9b0".into(),
        threads: 8,
        files,
    };
    let f = File::options().write(true).create_new(true).open(output)?;
    serde_json::to_writer_pretty(f, &bundle)?;
    Ok(())
}
fn serve(path: &Path) -> Result<()> {
    let bundle = Bundle::read(path)?;
    let mut pins = Vec::with_capacity(bundle.files.len() + 2);
    pins.push(pin(&bundle.worker)?);
    pins.push(pin(&bundle.ort)?);
    for asset in &bundle.files {
        pins.push(pin(asset)?);
    }
    // Every file the decoder can open must be present in the sealed allowlist.
    for entry in std::fs::read_dir(&bundle.model_root)? {
        let path = entry?.path();
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default();
        if name.ends_with(".json")
            || name.ends_with("_fp32.onnx")
            || name.ends_with("_fp32.onnx.data")
        {
            ensure!(
                bundle.files.iter().any(|a| a.path == path),
                "unsealed model asset: {}",
                path.display()
            );
        }
    }
    // Parent supplies the exact DLL path before process creation. No global
    // environment changes reach the bridge's older ORT runtime.
    ensure!(
        std::env::var_os("ORT_DYLIB_PATH")
            .map(PathBuf::from)
            .as_ref()
            == Some(&bundle.ort.path),
        "ORT DLL mismatch"
    );
    gliner25_rs::init("phoenix-gliner25");
    let mut engine = FeatureEngine::new(&bundle.model_root, bundle.threads)?;
    let mut input = BufReader::new(io::stdin().lock());
    let mut output = BufWriter::new(io::stdout().lock());
    write_frame(
        &mut output,
        &Response::Ready {
            contract: CONTRACT.into(),
            bundle: bundle.digest()?,
            pid: std::process::id(),
        },
    )?;
    let mut last = 0;
    loop {
        let request: Request = match read_frame(&mut input) {
            Ok(v) => v,
            Err(error)
                if error
                    .downcast_ref::<io::Error>()
                    .is_some_and(|e| e.kind() == io::ErrorKind::UnexpectedEof) =>
            {
                break;
            }
            Err(e) => return Err(e.context("read request frame")),
        };
        request.validate()?;
        ensure!(request.sequence > last, "stale request sequence");
        last = request.sequence;
        let start = Instant::now();
        let result = (|| -> Result<Vec<Span>> {
            let mentions =
                engine.extract_entities_long(&request.text, &request.labels, 384, 64, 0.5)?;
            let spans = mentions
                .into_iter()
                .map(|m| {
                    Ok(Span {
                        start: u32::try_from(m.char_start)?,
                        end: u32::try_from(m.char_end)?,
                        text: m.text,
                        label: m.field,
                        score: m.score,
                    })
                })
                .collect::<Result<Vec<_>>>()?;
            validate_spans(&request.text, &request.labels, &spans)?;
            Ok(spans)
        })();
        let response = match result {
            Ok(spans) => Response::Completed {
                sequence: request.sequence,
                text_hash: *blake3::hash(request.text.as_bytes()).as_bytes(),
                spans,
                inference_micros: start.elapsed().as_micros().min(u64::MAX as u128) as u64,
            },
            Err(e) => Response::Failed {
                sequence: request.sequence,
                message: format!("{e:#}").chars().take(4096).collect(),
            },
        };
        write_frame(&mut output, &response)?;
    }
    drop(pins);
    Ok(())
}
