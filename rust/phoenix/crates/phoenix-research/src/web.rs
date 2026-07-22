use std::io::Read;
use std::net::{IpAddr, ToSocketAddrs};
use std::time::Duration;

use memchr::{memchr, memmem};
use reqwest::blocking::{Client, Response};
use reqwest::header::{CONTENT_LENGTH, CONTENT_TYPE, LOCATION, USER_AGENT};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use url::Url;

use crate::provider::SearchProviderRegistry;
use crate::renderer::ObscuraRenderer;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebSearchHit {
    pub url: String,
    pub title: String,
    pub excerpt: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebSearchResults {
    pub provider: String,
    pub query: String,
    pub hits: Vec<WebSearchHit>,
    pub elapsed_ms: i64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WebFetchMode {
    #[default]
    Auto,
    Direct,
    Rendered,
}

impl WebFetchMode {
    pub fn parse(value: &str) -> Result<Self, WebError> {
        match value.trim().to_ascii_lowercase().as_str() {
            "auto" | "" => Ok(Self::Auto),
            "direct" => Ok(Self::Direct),
            "rendered" => Ok(Self::Rendered),
            other => Err(WebError::InvalidFetchMode(other.to_owned())),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Direct => "direct",
            Self::Rendered => "rendered",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebFetchReceipt {
    pub schema_version: String,
    pub requested_mode: WebFetchMode,
    pub resolved_mode: WebFetchMode,
    pub backend: String,
    pub extraction: String,
    pub rendered: bool,
    pub direct_ms: i64,
    pub render_ms: i64,
    pub total_ms: i64,
    pub response_bytes: usize,
}

impl Default for WebFetchReceipt {
    fn default() -> Self {
        Self {
            schema_version: "phoenix-web-fetch-receipt/v1".to_owned(),
            requested_mode: WebFetchMode::Auto,
            resolved_mode: WebFetchMode::Direct,
            backend: "unknown".to_owned(),
            extraction: "unknown".to_owned(),
            rendered: false,
            direct_ms: 0,
            render_ms: 0,
            total_ms: 0,
            response_bytes: 0,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebFetch {
    pub requested_url: String,
    pub final_url: String,
    pub status: u16,
    pub title: String,
    pub content_type: String,
    pub content: String,
    pub bytes: usize,
    pub elapsed_ms: i64,
    #[serde(default)]
    pub receipt: WebFetchReceipt,
}

pub trait WebFetcher: Send + Sync {
    fn fetch_mode(&self, input: &str, mode: WebFetchMode) -> Result<WebFetch, WebError>;
}

#[derive(Debug, Error)]
pub enum WebError {
    #[error("web search capability missing: configure PHOENIX_WEB_SEARCH_PROVIDER")]
    MissingSearchCapability,
    #[error("unknown web search provider: {0}")]
    UnknownSearchProvider(String),
    #[error("invalid web fetch mode: {0}")]
    InvalidFetchMode(String),
    #[error("unsafe web URL rejected: {0}")]
    UnsafeUrl(String),
    #[error("web request failed: {0}")]
    Request(String),
    #[error("web response exceeded {0} bytes")]
    ResponseTooLarge(usize),
    #[error("web response was not valid UTF-8 text")]
    InvalidText,
    #[error("Obscura renderer is unavailable: {0}")]
    RendererUnavailable(String),
    #[error("Obscura renderer timed out after {0} ms")]
    RendererTimeout(u64),
    #[error("Obscura renderer protocol failed: {0}")]
    RendererProtocol(String),
    #[error("Obscura renderer failed: {0}")]
    Renderer(String),
}

pub struct NativeWebClient {
    search: SearchProviderRegistry,
    renderer: ObscuraRenderer,
    timeout: Duration,
    max_source_bytes: usize,
    max_redirects: usize,
}

impl NativeWebClient {
    pub fn from_env(max_source_bytes: usize) -> Result<Self, WebError> {
        Ok(Self {
            search: SearchProviderRegistry::from_env(max_source_bytes)?,
            renderer: ObscuraRenderer::from_env(max_source_bytes),
            timeout: Duration::from_secs(18),
            max_source_bytes,
            max_redirects: 5,
        })
    }

    pub fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError> {
        self.search.search(query, max_results)
    }

    pub fn fetch(&self, input: &str) -> Result<WebFetch, WebError> {
        self.fetch_mode(input, WebFetchMode::Auto)
    }

    fn fetch_direct(
        &self,
        input: &str,
        requested: WebFetchMode,
    ) -> Result<DirectOutcome, WebError> {
        if input.len() > 4_096 {
            return Err(WebError::UnsafeUrl("URL exceeds 4096 bytes".to_owned()));
        }
        let started = std::time::Instant::now();
        let requested_url =
            Url::parse(input).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
        validate_public_url(&requested_url)?;
        let mut current = requested_url.clone();
        for redirect in 0..=self.max_redirects {
            validate_public_url(&current)?;
            let client = pinned_client(&current, self.timeout)?;
            let response = client
                .get(current.clone())
                .header(USER_AGENT, phoenix_user_agent())
                .send()
                .map_err(request_error)?;
            if response.status().is_redirection() {
                if redirect == self.max_redirects {
                    return Err(WebError::Request("redirect limit reached".to_owned()));
                }
                let location = response
                    .headers()
                    .get(LOCATION)
                    .and_then(|value| value.to_str().ok())
                    .ok_or_else(|| WebError::Request("redirect omitted Location".to_owned()))?;
                current = current
                    .join(location)
                    .map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
                continue;
            }
            return self.read_response(
                requested_url.as_str(),
                current.as_str(),
                response,
                started,
                requested,
            );
        }
        Err(WebError::Request("redirect limit reached".to_owned()))
    }

    fn read_response(
        &self,
        requested_url: &str,
        final_url: &str,
        mut response: Response,
        started: std::time::Instant,
        requested: WebFetchMode,
    ) -> Result<DirectOutcome, WebError> {
        let status = response.status().as_u16();
        if !(200..300).contains(&status) {
            return Err(WebError::Request(format!("HTTP status {status}")));
        }
        if let Some(length) = response
            .headers()
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<usize>().ok())
        {
            if length > self.max_source_bytes {
                return Err(WebError::ResponseTooLarge(self.max_source_bytes));
            }
        }
        let content_type = response
            .headers()
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("text/plain")
            .to_owned();
        if !is_text_content_type(&content_type) {
            return Err(WebError::Request(format!(
                "unsupported content type: {content_type}"
            )));
        }
        let mut bytes = Vec::with_capacity(self.max_source_bytes.min(64 * 1024));
        response
            .by_ref()
            .take((self.max_source_bytes + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|error| WebError::Request(error.to_string()))?;
        if bytes.len() > self.max_source_bytes {
            return Err(WebError::ResponseTooLarge(self.max_source_bytes));
        }
        let raw = String::from_utf8(bytes).map_err(|_| WebError::InvalidText)?;
        let title = extract_title(&raw);
        let is_html = content_type.to_ascii_lowercase().contains("html");
        let script_shell = is_html && looks_script_rendered(raw.as_bytes());
        let content = if is_html { html_to_text(&raw) } else { raw };
        let bytes = content.len();
        let elapsed_ms = started.elapsed().as_millis().min(i64::MAX as u128) as i64;
        let render_recommended = script_shell && bytes < 384;
        Ok(DirectOutcome {
            render_recommended,
            fetched: WebFetch {
                requested_url: requested_url.to_owned(),
                final_url: final_url.to_owned(),
                status,
                title,
                content_type,
                content,
                bytes,
                elapsed_ms,
                receipt: WebFetchReceipt {
                    requested_mode: requested,
                    resolved_mode: WebFetchMode::Direct,
                    backend: "phoenix-direct".to_owned(),
                    extraction: "bounded_html_text".to_owned(),
                    direct_ms: elapsed_ms,
                    total_ms: elapsed_ms,
                    response_bytes: bytes,
                    ..WebFetchReceipt::default()
                },
            },
        })
    }
}

impl WebFetcher for NativeWebClient {
    fn fetch_mode(&self, input: &str, mode: WebFetchMode) -> Result<WebFetch, WebError> {
        validate_input_url(input)?;
        match mode {
            WebFetchMode::Rendered => self.renderer.render(input, mode),
            WebFetchMode::Direct => self
                .fetch_direct(input, mode)
                .map(|outcome| outcome.fetched),
            WebFetchMode::Auto => {
                let direct = self.fetch_direct(input, mode)?;
                if !direct.render_recommended {
                    return Ok(direct.fetched);
                }
                match self.renderer.render(input, mode) {
                    Ok(rendered) => Ok(rendered),
                    Err(WebError::RendererUnavailable(_)) => Ok(direct.fetched),
                    Err(error) => Err(error),
                }
            }
        }
    }
}

struct DirectOutcome {
    fetched: WebFetch,
    render_recommended: bool,
}

pub(crate) fn pinned_client(url: &Url, timeout: Duration) -> Result<Client, WebError> {
    let host = url
        .host_str()
        .ok_or_else(|| WebError::UnsafeUrl("URL has no host".to_owned()))?;
    let port = url
        .port_or_known_default()
        .ok_or_else(|| WebError::UnsafeUrl("URL has no port".to_owned()))?;
    let addresses = (host, port)
        .to_socket_addrs()
        .map_err(|error| WebError::Request(error.to_string()))?
        .collect::<Vec<_>>();
    let selected = addresses
        .into_iter()
        .find(|address| is_public_ip(address.ip()))
        .ok_or_else(|| {
            WebError::UnsafeUrl("host resolves only to private or special addresses".to_owned())
        })?;
    Client::builder()
        .timeout(timeout)
        .connect_timeout(Duration::from_secs(6))
        .redirect(reqwest::redirect::Policy::none())
        .resolve(host, selected)
        .build()
        .map_err(request_error)
}

pub(crate) fn validate_public_url(url: &Url) -> Result<(), WebError> {
    if !matches!(url.scheme(), "http" | "https") {
        return Err(WebError::UnsafeUrl(
            "only http and https are allowed".to_owned(),
        ));
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(WebError::UnsafeUrl(
            "embedded credentials are forbidden".to_owned(),
        ));
    }
    let host = url
        .host_str()
        .ok_or_else(|| WebError::UnsafeUrl("URL has no host".to_owned()))?;
    if host.eq_ignore_ascii_case("localhost")
        || host.ends_with(".local")
        || host.eq_ignore_ascii_case("metadata.google.internal")
    {
        return Err(WebError::UnsafeUrl(
            "local and metadata hosts are forbidden".to_owned(),
        ));
    }
    if let Ok(ip) = host.parse::<IpAddr>() {
        if !is_public_ip(ip) {
            return Err(WebError::UnsafeUrl(
                "private or special IP is forbidden".to_owned(),
            ));
        }
    }
    Ok(())
}

fn validate_input_url(input: &str) -> Result<Url, WebError> {
    if input.len() > 4_096 {
        return Err(WebError::UnsafeUrl("URL exceeds 4096 bytes".to_owned()));
    }
    let url = Url::parse(input).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
    validate_public_url(&url)?;
    Ok(url)
}

fn looks_script_rendered(content: &[u8]) -> bool {
    if memmem::find(content, b"<script").is_none() {
        return false;
    }
    [
        b"id=\"app\"".as_slice(),
        b"id='app'",
        b"id=\"root\"",
        b"__next",
    ]
    .iter()
    .any(|needle| memmem::find(content, needle).is_some())
}

fn is_public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let octets = ip.octets();
            !(ip.is_private()
                || ip.is_loopback()
                || ip.is_link_local()
                || ip.is_multicast()
                || ip.is_broadcast()
                || ip.is_unspecified()
                || octets[0] == 0
                || octets[0] >= 240
                || (octets[0] == 100 && (64..=127).contains(&octets[1]))
                || (octets[0] == 192 && octets[1] == 0 && octets[2] == 0)
                || (octets[0] == 198 && matches!(octets[1], 18 | 19))
                || (octets[0] == 169 && octets[1] == 254))
        }
        IpAddr::V6(ip) => {
            !(ip.is_loopback()
                || ip.is_multicast()
                || ip.is_unspecified()
                || (ip.segments()[0] & 0xfe00) == 0xfc00
                || (ip.segments()[0] & 0xffc0) == 0xfe80)
        }
    }
}

fn is_text_content_type(value: &str) -> bool {
    let value = value.to_ascii_lowercase();
    value.starts_with("text/")
        || value.contains("json")
        || value.contains("xml")
        || value.contains("javascript")
}

fn html_to_text(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(bytes.len().min(64 * 1024));
    let mut cursor = 0usize;
    let mut needs_space = false;
    while cursor < bytes.len() {
        if bytes[cursor] == b'<' {
            let Some(end) = memchr(b'>', &bytes[cursor + 1..]) else {
                break;
            };
            cursor += end + 2;
            needs_space = true;
            continue;
        }
        let Some(next) = memchr(b'<', &bytes[cursor..]) else {
            append_text(&mut out, &input[cursor..], needs_space);
            break;
        };
        append_text(&mut out, &input[cursor..cursor + next], needs_space);
        cursor += next;
        needs_space = true;
    }
    decode_entities(&out)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn append_text(out: &mut String, text: &str, needs_space: bool) {
    let text = text.trim();
    if text.is_empty() {
        return;
    }
    if needs_space && !out.ends_with(char::is_whitespace) {
        out.push(' ');
    }
    out.push_str(text);
}

fn extract_title(input: &str) -> String {
    let lower = input.to_ascii_lowercase();
    let Some(start) = lower.find("<title") else {
        return String::new();
    };
    let Some(open) = lower[start..].find('>') else {
        return String::new();
    };
    let body = start + open + 1;
    let Some(end) = lower[body..].find("</title>") else {
        return String::new();
    };
    decode_entities(input[body..body + end].trim())
}

fn decode_entities(input: &str) -> String {
    input
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
}

pub(crate) fn phoenix_user_agent() -> &'static str {
    "PhoenixResearch/1.0 (+native note research harness)"
}
pub(crate) fn request_error(error: reqwest::Error) -> WebError {
    WebError::Request(error.to_string())
}

#[cfg(test)]
pub(crate) fn validate_url_for_test(input: &str) -> Result<(), WebError> {
    let url = Url::parse(input).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
    validate_public_url(&url)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fetch_modes_are_strict_and_stable() {
        assert_eq!(WebFetchMode::parse("auto").unwrap(), WebFetchMode::Auto);
        assert_eq!(
            WebFetchMode::parse("rendered").unwrap(),
            WebFetchMode::Rendered
        );
        assert!(WebFetchMode::parse("browser").is_err());
        assert_eq!(WebFetchMode::Rendered.as_str(), "rendered");
    }

    #[test]
    fn auto_render_detection_only_flags_script_application_shells() {
        assert!(looks_script_rendered(
            br#"<html><body><main id="app"></main><script>boot()</script></body></html>"#
        ));
        assert!(!looks_script_rendered(
            br#"<html><body><main>Static evidence</main></body></html>"#
        ));
    }
}
