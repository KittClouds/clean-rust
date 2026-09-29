//! The Library HTTP client, behaviour-compatible with `ledgerd/client.py`.

use std::time::Duration;

use serde_json::Value;

#[derive(Debug)]
pub enum ClientError {
    /// The Library answered with a non-2xx status: `Kammi Ledger HTTP <code>: <body>`.
    Refused { status: u16, message: String },
    /// A caller mistake caught before sending (Python's `ValueError`).
    Usage(String),
    /// No answer: connection refused, timeout, or an unreadable response.
    Unreachable(String),
}

impl std::fmt::Display for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientError::Refused { message, .. }
            | ClientError::Usage(message)
            | ClientError::Unreachable(message) => f.write_str(message),
        }
    }
}

pub type Result<T> = std::result::Result<T, ClientError>;

/// Python's `urllib.parse.quote(value, safe=...)`.
pub fn quote(value: &str, safe: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for b in value.bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~".contains(&b) || safe.as_bytes().contains(&b) {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

pub struct Client {
    base: String,
    token: String,
    agent: ureq::Agent,
}

impl Client {
    pub fn new(base: &str, token: &str) -> Self {
        Client {
            base: base.trim_end_matches('/').to_string(),
            token: token.to_string(),
            agent: ureq::AgentBuilder::new().build(),
        }
    }

    /// `KAMMI_TOKEN` (required) and `KAMMI_URL` (default `http://127.0.0.1:8765`).
    pub fn from_environment() -> Result<Self> {
        let token = std::env::var("KAMMI_TOKEN")
            .ok()
            .filter(|t| !t.is_empty())
            .ok_or_else(|| ClientError::Usage("KAMMI_TOKEN is required".into()))?;
        let base = std::env::var("KAMMI_URL").unwrap_or_else(|_| "http://127.0.0.1:8765".into());
        Ok(Client::new(&base, &token))
    }

    fn send(
        &self,
        method: &str,
        path: &str,
        body: Option<(&[u8], &str)>,
        headers: &[(&str, &str)],
        timeout: u64,
        prefix: &str,
    ) -> Result<ureq::Response> {
        let mut request = self
            .agent
            .request(method, &format!("{}{path}", self.base))
            .timeout(Duration::from_secs(timeout))
            .set("Authorization", &format!("Bearer {}", self.token));
        for (name, value) in headers {
            request = request.set(name, value);
        }
        let result = match body {
            Some((bytes, content_type)) => {
                request.set("Content-Type", content_type).send_bytes(bytes)
            }
            None => request.call(),
        };
        match result {
            Ok(response) => Ok(response),
            Err(ureq::Error::Status(status, response)) => {
                let detail = response.into_string().unwrap_or_default();
                Err(ClientError::Refused {
                    status,
                    message: format!("{prefix} {status}: {detail}"),
                })
            }
            Err(error) => Err(ClientError::Unreachable(format!(
                "Kammi Ledger unreachable: {error}"
            ))),
        }
    }

    fn json(response: ureq::Response) -> Result<Value> {
        let text = response
            .into_string()
            .map_err(|e| ClientError::Unreachable(format!("unreadable response: {e}")))?;
        serde_json::from_str(&text)
            .map_err(|e| ClientError::Unreachable(format!("unreadable response: {e}")))
    }

    fn request(
        &self,
        method: &str,
        path: &str,
        body: Option<&Value>,
        headers: &[(&str, &str)],
        timeout: u64,
    ) -> Result<Value> {
        let bytes = body
            .map(|b| {
                kammi_jcs::canonical(b)
                    .map_err(|e| ClientError::Usage(format!("body is not canonicalizable: {e}")))
            })
            .transpose()?;
        let response = self.send(
            method,
            path,
            bytes.as_deref().map(|b| (b, "application/json")),
            headers,
            timeout,
            "Kammi Ledger HTTP",
        )?;
        Client::json(response)
    }

    pub fn status(&self) -> Result<Value> {
        self.request("GET", "/v1/status", None, &[], 30)
    }

    /// The stable `/v1` escape hatch; policy decisions stay server-side.
    pub fn call(&self, method: &str, path: &str, body: Option<&Value>) -> Result<Value> {
        if !path.starts_with("/v1/") {
            return Err(ClientError::Usage(
                "only v1 service endpoints are supported".into(),
            ));
        }
        self.request(method, path, body, &[], 30)
    }

    pub fn register_bytes(
        &self,
        bytes: &[u8],
        kind: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<Value> {
        let headers = [
            ("X-Kind", kind),
            ("X-Actor", actor),
            ("X-Request-ID", request_id),
        ];
        let response = self.send(
            "POST",
            "/v1/artifacts",
            Some((bytes, "application/octet-stream")),
            &headers,
            30,
            "Kammi Ledger HTTP",
        )?;
        Client::json(response)
    }

    pub fn create_run(
        &self,
        run_id: &str,
        lab: &str,
        actor: &str,
        request_id: &str,
    ) -> Result<Value> {
        let body = serde_json::json!({"run_id": run_id, "lab": lab, "actor": actor, "request_id": request_id});
        self.request("POST", "/v1/runs", Some(&body), &[], 30)
    }

    pub fn create_seal(
        &self,
        members: &[String],
        parents: &[String],
        actor: &str,
        request_id: &str,
    ) -> Result<Value> {
        let body = serde_json::json!({"direct_members": members, "parents": parents, "actor": actor, "request_id": request_id});
        self.request("POST", "/v1/seals", Some(&body), &[], 30)
    }

    pub fn lineage(&self, root: &str) -> Result<Value> {
        self.request(
            "GET",
            &format!("/v1/seals/{}/lineage", quote(root, ":")),
            None,
            &[],
            30,
        )
    }

    pub fn history(&self, run_id: &str, summary: bool) -> Result<Value> {
        let suffix = if summary { "/summary" } else { "" };
        self.request(
            "GET",
            &format!("/v1/runs/{}/history{suffix}", quote(run_id, "")),
            None,
            &[],
            30,
        )
    }

    /// `POST /v1/panels/{id}/open`: the opened bytes (base64) and the exposure event.
    pub fn open_panel(&self, panel_id: &str, body: &Value) -> Result<Value> {
        let bytes = kammi_jcs::canonical(body)
            .map_err(|e| ClientError::Usage(format!("body is not canonicalizable: {e}")))?;
        let path = format!("/v1/panels/{}/open", quote(panel_id, ""));
        let response = self.send(
            "POST",
            &path,
            Some((&bytes, "application/json")),
            &[],
            30,
            "Kammi HTTP",
        )?;
        let event = response.header("X-Exposure-Event").map(str::to_string);
        let mut raw = Vec::new();
        std::io::Read::read_to_end(&mut response.into_reader(), &mut raw)
            .map_err(|e| ClientError::Unreachable(format!("unreadable response: {e}")))?;
        Ok(serde_json::json!({"bytes_base64": base64(&raw), "exposure_event": event}))
    }
}

fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = u32::from(chunk[0]) << 16
            | u32::from(*chunk.get(1).unwrap_or(&0)) << 8
            | u32::from(*chunk.get(2).unwrap_or(&0));
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(ALPHABET[(n >> (18 - 6 * i) & 63) as usize] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quote_matches_python() {
        assert_eq!(
            quote("frozen-fabrique.e4-0.supervised.v1", ""),
            "frozen-fabrique.e4-0.supervised.v1"
        );
        assert_eq!(quote("sha256:ab/c d", ":"), "sha256:ab%2Fc%20d");
        assert_eq!(quote("é", ""), "%C3%A9");
    }

    #[test]
    fn base64_matches_rfc4648() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foobar"), "Zm9vYmFy");
    }
}
