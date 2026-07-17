use std::env;
use std::io::Read;
use std::net::{IpAddr, ToSocketAddrs};
use std::time::Duration;

use memchr::memchr;
use reqwest::blocking::{Client, Response};
use reqwest::header::{CONTENT_LENGTH, CONTENT_TYPE, LOCATION, USER_AGENT};
use serde::{Deserialize, Serialize};
use serde_json::json;
use thiserror::Error;
use url::Url;

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
}

#[derive(Debug, Error)]
pub enum WebError {
    #[error("web search capability missing: set PHOENIX_TAVILY_API_KEY")]
    MissingSearchCapability,
    #[error("unsafe web URL rejected: {0}")]
    UnsafeUrl(String),
    #[error("web request failed: {0}")]
    Request(String),
    #[error("web response exceeded {0} bytes")]
    ResponseTooLarge(usize),
    #[error("web response was not valid UTF-8 text")]
    InvalidText,
}

pub struct NativeWebClient {
    api_key: Option<String>,
    search_endpoint: Url,
    timeout: Duration,
    max_source_bytes: usize,
    max_redirects: usize,
}

impl NativeWebClient {
    pub fn from_env(max_source_bytes: usize) -> Result<Self, WebError> {
        let endpoint = env::var("PHOENIX_TAVILY_ENDPOINT")
            .unwrap_or_else(|_| "https://api.tavily.com/search".to_owned());
        let search_endpoint =
            Url::parse(&endpoint).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
        validate_public_url(&search_endpoint)?;
        if search_endpoint.scheme() != "https" {
            return Err(WebError::UnsafeUrl(
                "search provider must use https".to_owned(),
            ));
        }
        Ok(Self {
            api_key: env::var("PHOENIX_TAVILY_API_KEY")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            search_endpoint,
            timeout: Duration::from_secs(18),
            max_source_bytes,
            max_redirects: 5,
        })
    }

    pub fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError> {
        let api_key = self
            .api_key
            .as_deref()
            .ok_or(WebError::MissingSearchCapability)?;
        let started = std::time::Instant::now();
        let client = pinned_client(&self.search_endpoint, self.timeout)?;
        let response = client
            .post(self.search_endpoint.clone())
            .header(USER_AGENT, phoenix_user_agent())
            .json(&json!({
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results.clamp(1, 10),
                "include_answer": false,
                "include_raw_content": false
            }))
            .send()
            .map_err(request_error)?
            .error_for_status()
            .map_err(request_error)?;
        let payload = response.json::<TavilyResponse>().map_err(request_error)?;
        Ok(WebSearchResults {
            provider: "tavily".to_owned(),
            query: query.to_owned(),
            hits: payload
                .results
                .into_iter()
                .take(max_results)
                .map(|hit| WebSearchHit {
                    url: hit.url,
                    title: hit.title,
                    excerpt: truncate_chars(&hit.content, 2_000),
                })
                .collect(),
            elapsed_ms: started.elapsed().as_millis().min(i64::MAX as u128) as i64,
        })
    }

    pub fn fetch(&self, input: &str) -> Result<WebFetch, WebError> {
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
            return self.read_response(requested_url.as_str(), current.as_str(), response, started);
        }
        Err(WebError::Request("redirect limit reached".to_owned()))
    }

    fn read_response(
        &self,
        requested_url: &str,
        final_url: &str,
        mut response: Response,
        started: std::time::Instant,
    ) -> Result<WebFetch, WebError> {
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
        let content = if content_type.to_ascii_lowercase().contains("html") {
            html_to_text(&raw)
        } else {
            raw
        };
        let bytes = content.len();
        Ok(WebFetch {
            requested_url: requested_url.to_owned(),
            final_url: final_url.to_owned(),
            status,
            title,
            content_type,
            content,
            bytes,
            elapsed_ms: started.elapsed().as_millis().min(i64::MAX as u128) as i64,
        })
    }
}

#[derive(Deserialize)]
struct TavilyResponse {
    #[serde(default)]
    results: Vec<TavilyHit>,
}

#[derive(Deserialize)]
struct TavilyHit {
    #[serde(default)]
    url: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    content: String,
}

fn pinned_client(url: &Url, timeout: Duration) -> Result<Client, WebError> {
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

fn validate_public_url(url: &Url) -> Result<(), WebError> {
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

fn truncate_chars(input: &str, limit: usize) -> String {
    input.chars().take(limit).collect()
}
fn phoenix_user_agent() -> &'static str {
    "PhoenixResearch/1.0 (+native note research harness)"
}
fn request_error(error: reqwest::Error) -> WebError {
    WebError::Request(error.to_string())
}

#[cfg(test)]
pub(crate) fn validate_url_for_test(input: &str) -> Result<(), WebError> {
    let url = Url::parse(input).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
    validate_public_url(&url)
}
