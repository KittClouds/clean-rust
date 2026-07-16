use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use super::audio::{pcm_s16le, read_reference_wav, SAMPLE_RATE};
use super::{NativeSupertonicSpeakRequest, NativeTtsSynthResult, NativeTtsTimings};

const DEFAULT_RUNNER_PATH: &str = r"C:\phoenix-tts\supertonic-rust\example_onnx.exe";
const DEFAULT_MODEL_ROOT: &str = r"C:\phoenix-tts\supertonic-3";
const DEFAULT_OUTPUT_DIR: &str = r"C:\phoenix-tts\supertonic-rust-outputs";
const DEFAULT_LANG: &str = "en";
const DEFAULT_TOTAL_STEP: u32 = 5;
const DEFAULT_SPEED: f32 = 1.05;
const SYNTH_TIMEOUT: Duration = Duration::from_secs(120);

pub fn synthesize_supertonic_cli(
    request: NativeSupertonicSpeakRequest,
) -> Result<NativeTtsSynthResult, String> {
    let text = request.text.trim().to_owned();
    if text.is_empty() {
        return Err("Supertonic Rust text is empty".to_owned());
    }

    let total_start = Instant::now();
    let config = SupertonicCliConfig::from_request(request)?;
    let session_dir = config.output_dir.join(unique_session_name());
    fs::create_dir_all(&session_dir).map_err(|error| {
        format!(
            "create Supertonic output dir {}: {error}",
            session_dir.display()
        )
    })?;

    let process_start = Instant::now();
    let output = run_supertonic(&config, &text, &session_dir);
    let process_ms = elapsed_ms(process_start);
    let result = match output {
        Ok(()) => read_generated_audio(&session_dir, elapsed_ms(total_start), process_ms),
        Err(error) => Err(error),
    };

    let _ = fs::remove_dir_all(&session_dir);
    result
}

struct SupertonicCliConfig {
    runner_path: PathBuf,
    model_root: PathBuf,
    output_dir: PathBuf,
    voice_style: PathBuf,
    total_step: u32,
    speed: f32,
    lang: String,
}

impl SupertonicCliConfig {
    fn from_request(request: NativeSupertonicSpeakRequest) -> Result<Self, String> {
        let runner_path = request
            .runner_path
            .as_deref()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(DEFAULT_RUNNER_PATH));
        require_file(&runner_path, "Supertonic Rust runner")?;

        let model_root = request
            .model_root
            .as_deref()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(DEFAULT_MODEL_ROOT));
        let onnx_dir = model_root.join("onnx");
        require_dir(&onnx_dir, "Supertonic ONNX directory")?;

        let output_dir = request
            .output_dir
            .as_deref()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(DEFAULT_OUTPUT_DIR));
        let voice_style = resolve_voice_style(request.voice_style.as_deref(), &model_root)?;

        Ok(Self {
            runner_path,
            model_root,
            output_dir,
            voice_style,
            total_step: request.total_step.unwrap_or(DEFAULT_TOTAL_STEP).max(1),
            speed: request.speed.unwrap_or(DEFAULT_SPEED).clamp(0.5, 2.0),
            lang: normalize_lang(request.lang.as_deref()),
        })
    }
}

fn run_supertonic(
    config: &SupertonicCliConfig,
    text: &str,
    session_dir: &Path,
) -> Result<(), String> {
    let mut command = Command::new(&config.runner_path);
    command
        .arg("--onnx-dir")
        .arg(config.model_root.join("onnx"))
        .arg("--voice-style")
        .arg(&config.voice_style)
        .arg("--text")
        .arg(text)
        .arg("--lang")
        .arg(&config.lang)
        .arg("--save-dir")
        .arg(session_dir)
        .arg("--n-test")
        .arg("1")
        .arg("--total-step")
        .arg(config.total_step.to_string())
        .arg("--speed")
        .arg(format!("{:.3}", config.speed))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    if let Some(parent) = config.runner_path.parent() {
        command.current_dir(parent);
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    let mut child = command.spawn().map_err(|error| {
        format!(
            "spawn Supertonic Rust runner {}: {error}",
            config.runner_path.display()
        )
    })?;
    let start = Instant::now();
    loop {
        if start.elapsed() > SYNTH_TIMEOUT {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "Supertonic Rust synthesis timed out after {}s",
                SYNTH_TIMEOUT.as_secs()
            ));
        }
        if child
            .try_wait()
            .map_err(|error| format!("poll Supertonic Rust runner: {error}"))?
            .is_some()
        {
            break;
        }
        thread::sleep(Duration::from_millis(25));
    }

    let output = child
        .wait_with_output()
        .map_err(|error| format!("collect Supertonic Rust output: {error}"))?;
    if output.status.success() {
        return Ok(());
    }

    Err(format!(
        "Supertonic Rust runner failed with status {}. stdout: {} stderr: {}",
        output.status,
        truncate_lossy(&output.stdout),
        truncate_lossy(&output.stderr)
    ))
}

fn read_generated_audio(
    session_dir: &Path,
    total_ms: f64,
    process_ms: f64,
) -> Result<NativeTtsSynthResult, String> {
    let wav_path = find_wav(session_dir)?;
    let samples = read_reference_wav(&wav_path)?;
    let sample_count = samples.len() as u32;
    Ok(NativeTtsSynthResult {
        sample_rate: SAMPLE_RATE,
        sample_count,
        pcm_s16le: pcm_s16le(&samples),
        generated_tokens: 0,
        stopped: true,
        timings: NativeTtsTimings {
            condition_ms: 0.0,
            token_ms: process_ms,
            decode_ms: 0.0,
            total_ms,
        },
    })
}

fn find_wav(dir: &Path) -> Result<PathBuf, String> {
    let mut wavs = fs::read_dir(dir)
        .map_err(|error| format!("read Supertonic output dir {}: {error}", dir.display()))?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("wav"))
        .collect::<Vec<_>>();
    wavs.sort_unstable();
    wavs.into_iter()
        .next()
        .ok_or_else(|| format!("Supertonic Rust produced no WAV in {}", dir.display()))
}

fn resolve_voice_style(value: Option<&str>, model_root: &Path) -> Result<PathBuf, String> {
    let value = value.unwrap_or("F1").trim();
    let path = if value.contains('\\') || value.contains('/') || value.ends_with(".json") {
        PathBuf::from(value)
    } else {
        let id = value.to_ascii_uppercase();
        if !id.chars().all(|ch| ch.is_ascii_alphanumeric()) {
            return Err(format!("invalid Supertonic voice style id: {value}"));
        }
        model_root.join("voice_styles").join(format!("{id}.json"))
    };
    require_file(&path, "Supertonic voice style")?;
    Ok(path)
}

fn normalize_lang(value: Option<&str>) -> String {
    let lang = value.unwrap_or(DEFAULT_LANG).trim().to_ascii_lowercase();
    match lang.as_str() {
        "ar" | "bg" | "cs" | "da" | "de" | "el" | "en" | "es" | "et" | "fi" | "fr" | "hi"
        | "hr" | "hu" | "id" | "it" | "ja" | "ko" | "lt" | "lv" | "nl" | "pl" | "pt" | "ro"
        | "ru" | "sk" | "sl" | "sv" | "tr" | "uk" | "vi" => lang,
        _ => DEFAULT_LANG.to_owned(),
    }
}

fn require_file(path: &Path, label: &str) -> Result<(), String> {
    if path.is_file() {
        Ok(())
    } else {
        Err(format!("{label} not found: {}", path.display()))
    }
}

fn require_dir(path: &Path, label: &str) -> Result<(), String> {
    if path.is_dir() {
        Ok(())
    } else {
        Err(format!("{label} not found: {}", path.display()))
    }
}

fn unique_session_name() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    format!("phoenix-supertonic-{}-{nanos}", std::process::id())
}

fn elapsed_ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

fn truncate_lossy(bytes: &[u8]) -> String {
    const LIMIT: usize = 800;
    let text = String::from_utf8_lossy(bytes);
    if text.len() <= LIMIT {
        return text.into_owned();
    }
    let prefix = text.chars().take(LIMIT).collect::<String>();
    format!("{prefix}...")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_voice_id_to_model_style_file() {
        let root = std::env::temp_dir().join(unique_session_name());
        let styles = root.join("voice_styles");
        fs::create_dir_all(&styles).expect("create temp voice style dir");
        fs::write(styles.join("F1.json"), "{}").expect("write temp voice style");

        let path = resolve_voice_style(Some("f1"), &root).expect("resolve voice style");

        assert_eq!(path, styles.join("F1.json"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn normalizes_unknown_language_to_english() {
        assert_eq!(normalize_lang(Some("en")), "en");
        assert_eq!(normalize_lang(Some("JA")), "ja");
        assert_eq!(normalize_lang(Some("uk")), "uk");
        assert_eq!(normalize_lang(Some("vi")), "vi");
        assert_eq!(normalize_lang(Some("not-a-lang")), "en");
    }

    #[test]
    fn accepts_supertonic_3_language_set() {
        for lang in [
            "ar", "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hi", "hr", "hu",
            "id", "it", "ja", "ko", "lt", "lv", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv",
            "tr", "uk", "vi",
        ] {
            assert_eq!(normalize_lang(Some(lang)), lang);
        }
    }

    #[test]
    #[ignore]
    fn supertonic_rust_cli_smoke() {
        if !Path::new(DEFAULT_RUNNER_PATH).is_file()
            || !Path::new(DEFAULT_MODEL_ROOT).join("onnx").is_dir()
        {
            eprintln!("skipping Supertonic Rust smoke; runner or model files are missing");
            return;
        }

        let result = synthesize_supertonic_cli(NativeSupertonicSpeakRequest {
            text: "Phoenix native Supertonic Rust smoke test.".to_owned(),
            voice_style: Some("F1".to_owned()),
            runner_path: None,
            model_root: None,
            output_dir: None,
            total_step: Some(5),
            speed: Some(1.05),
            lang: Some("en".to_owned()),
        })
        .expect("synthesize Supertonic Rust audio");

        assert_eq!(result.sample_rate, SAMPLE_RATE);
        assert!(result.sample_count > 1_000);
        assert_eq!(result.pcm_s16le.len(), result.sample_count as usize * 2);
    }
}
