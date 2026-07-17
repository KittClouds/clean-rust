use std::env;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::web::{WebError, WebFetch, WebFetchMode, WebFetchReceipt};

const PROTOCOL: &str = "phoenix-obscura-worker/v1";
const STDERR_LIMIT: usize = 16 * 1024;
static NEXT_REQUEST_ID: AtomicU64 = AtomicU64::new(1);

pub(crate) struct ObscuraRenderer {
    command: PathBuf,
    args: Vec<String>,
    timeout: Duration,
    max_source_bytes: usize,
}

impl ObscuraRenderer {
    pub(crate) fn from_env(max_source_bytes: usize) -> Self {
        let command = env::var_os("PHOENIX_OBSCURA_WORKER_PATH")
            .map(PathBuf::from)
            .unwrap_or_else(default_worker_path);
        let timeout_ms = env::var("PHOENIX_OBSCURA_TIMEOUT_MS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(25_000)
            .clamp(1_000, 120_000);
        Self {
            command,
            args: Vec::new(),
            timeout: Duration::from_millis(timeout_ms),
            max_source_bytes,
        }
    }

    #[cfg(test)]
    fn for_test(command: PathBuf, args: Vec<String>, timeout: Duration) -> Self {
        Self {
            command,
            args,
            timeout,
            max_source_bytes: 64 * 1024,
        }
    }

    pub(crate) fn render(
        &self,
        input: &str,
        requested_mode: WebFetchMode,
    ) -> Result<WebFetch, WebError> {
        let request_id = format!(
            "render-{}-{}",
            std::process::id(),
            NEXT_REQUEST_ID.fetch_add(1, Ordering::Relaxed)
        );
        let request = RendererRequest {
            schema_version: PROTOCOL,
            request_id: &request_id,
            url: input,
            max_bytes: self.max_source_bytes,
            settle_ms: 1_500,
        };
        let payload = serde_json::to_vec(&request)
            .map_err(|error| WebError::RendererProtocol(error.to_string()))?;
        let started = Instant::now();
        let mut command = Command::new(&self.command);
        command
            .args(&self.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env_remove("OBSCURA_ALLOW_PRIVATE_NETWORK")
            .env_remove("OBSCURA_PROXY")
            .env_remove("OBSCURA_STEALTH");
        let mut child = command.spawn().map_err(|error| {
            WebError::RendererUnavailable(format!("{}: {error}", self.command.display()))
        })?;
        let _process_guard = crate::process_guard::ProcessGuard::attach(&child)
            .map_err(WebError::RendererProtocol)?;
        let mut stdin = child.stdin.take().ok_or_else(|| {
            WebError::RendererProtocol("worker stdin was not available".to_owned())
        })?;
        stdin
            .write_all(&payload)
            .and_then(|_| stdin.write_all(b"\n"))
            .map_err(|error| WebError::RendererProtocol(error.to_string()))?;
        drop(stdin);

        let stdout = child.stdout.take().ok_or_else(|| {
            WebError::RendererProtocol("worker stdout was not available".to_owned())
        })?;
        let stderr = child.stderr.take().ok_or_else(|| {
            WebError::RendererProtocol("worker stderr was not available".to_owned())
        })?;
        let stdout_limit = self.max_source_bytes.saturating_mul(2).max(64 * 1024);
        let stdout_reader = thread::spawn(move || read_bounded(stdout, stdout_limit));
        let stderr_reader = thread::spawn(move || read_bounded(stderr, STDERR_LIMIT));

        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) if started.elapsed() < self.timeout => {
                    thread::sleep(Duration::from_millis(10));
                }
                Ok(None) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    let _ = stdout_reader.join();
                    let _ = stderr_reader.join();
                    return Err(WebError::RendererTimeout(
                        self.timeout.as_millis().min(u64::MAX as u128) as u64,
                    ));
                }
                Err(error) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(WebError::RendererProtocol(error.to_string()));
                }
            }
        };
        let (stdout, stdout_truncated) = stdout_reader
            .join()
            .map_err(|_| WebError::RendererProtocol("stdout reader panicked".to_owned()))??;
        let (stderr, _) = stderr_reader
            .join()
            .map_err(|_| WebError::RendererProtocol("stderr reader panicked".to_owned()))??;
        if stdout_truncated {
            return Err(WebError::ResponseTooLarge(self.max_source_bytes));
        }
        if !status.success() {
            return Err(WebError::Renderer(
                String::from_utf8_lossy(&stderr).trim().to_owned(),
            ));
        }
        let response: RendererResponse = serde_json::from_slice(&stdout)
            .map_err(|error| WebError::RendererProtocol(error.to_string()))?;
        validate_response(&response, &request_id)?;
        let content = response.content.unwrap_or_default();
        if content.len() > self.max_source_bytes {
            return Err(WebError::ResponseTooLarge(self.max_source_bytes));
        }
        let elapsed_ms = started.elapsed().as_millis().min(i64::MAX as u128) as i64;
        if !response.ok {
            return Err(WebError::Renderer(
                response
                    .error
                    .unwrap_or_else(|| "worker returned failure".to_owned()),
            ));
        }
        let bytes = content.len();
        Ok(WebFetch {
            requested_url: input.to_owned(),
            final_url: response.final_url.unwrap_or_else(|| input.to_owned()),
            status: response.status.unwrap_or(200),
            title: response.title.unwrap_or_default(),
            content_type: response
                .content_type
                .unwrap_or_else(|| "text/html".to_owned()),
            content,
            bytes,
            elapsed_ms,
            receipt: WebFetchReceipt {
                requested_mode,
                resolved_mode: WebFetchMode::Rendered,
                backend: "obscura-sidecar".to_owned(),
                extraction: "rendered_markdown".to_owned(),
                rendered: true,
                render_ms: response.elapsed_ms.unwrap_or(elapsed_ms),
                total_ms: elapsed_ms,
                response_bytes: bytes,
                ..WebFetchReceipt::default()
            },
        })
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RendererRequest<'a> {
    schema_version: &'static str,
    request_id: &'a str,
    url: &'a str,
    max_bytes: usize,
    settle_ms: u64,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RendererResponse {
    schema_version: String,
    request_id: String,
    ok: bool,
    #[serde(default)]
    final_url: Option<String>,
    #[serde(default)]
    status: Option<u16>,
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    content_type: Option<String>,
    #[serde(default)]
    content: Option<String>,
    #[serde(default)]
    elapsed_ms: Option<i64>,
    #[serde(default)]
    error: Option<String>,
}

fn default_worker_path() -> PathBuf {
    let name = if cfg!(windows) {
        "phoenix-obscura-worker.exe"
    } else {
        "phoenix-obscura-worker"
    };
    env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.join(name)))
        .filter(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from(name))
}

fn read_bounded(mut reader: impl Read, limit: usize) -> Result<(Vec<u8>, bool), WebError> {
    let mut bytes = Vec::with_capacity(limit.min(64 * 1024));
    reader
        .by_ref()
        .take(limit.saturating_add(1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| WebError::RendererProtocol(error.to_string()))?;
    let truncated = bytes.len() > limit;
    if truncated {
        bytes.truncate(limit);
    }
    Ok((bytes, truncated))
}

fn validate_response(response: &RendererResponse, request_id: &str) -> Result<(), WebError> {
    if response.schema_version != PROTOCOL {
        return Err(WebError::RendererProtocol(format!(
            "unexpected schema {}",
            response.schema_version
        )));
    }
    if response.request_id != request_id {
        return Err(WebError::RendererProtocol(
            "response request id did not match".to_owned(),
        ));
    }
    Ok(())
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    #[test]
    fn renderer_enforces_process_deadline() {
        let renderer = ObscuraRenderer::for_test(
            PathBuf::from("powershell.exe"),
            vec![
                "-NoProfile".to_owned(),
                "-Command".to_owned(),
                "[Console]::In.ReadToEnd() | Out-Null; Start-Sleep -Seconds 2".to_owned(),
            ],
            Duration::from_millis(100),
        );
        assert!(matches!(
            renderer.render("https://example.com", WebFetchMode::Rendered),
            Err(WebError::RendererTimeout(100))
        ));
    }
}
