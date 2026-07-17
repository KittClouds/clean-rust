use std::sync::{Arc, Mutex};
use std::time::Instant;

use obscura::{Browser, ResourceType};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use url::Url;

pub const PROTOCOL: &str = "phoenix-obscura-worker/v1";

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderRequest {
    pub schema_version: String,
    pub request_id: String,
    pub url: String,
    pub max_bytes: usize,
    pub settle_ms: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderResponse {
    pub schema_version: &'static str,
    pub request_id: String,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub elapsed_ms: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Error)]
pub enum RenderError {
    #[error("invalid request: {0}")]
    Invalid(String),
    #[error("browser failed: {0}")]
    Browser(String),
    #[error("rendered content exceeded {0} bytes")]
    TooLarge(usize),
}

#[derive(Clone, Default)]
struct NavigationMeta {
    final_url: String,
    status: u16,
    content_type: String,
}

pub async fn render_request(request: RenderRequest) -> Result<RenderResponse, RenderError> {
    validate_request(&request)?;
    let started = Instant::now();
    let browser = Browser::builder()
        .stealth(false)
        .user_agent("PhoenixResearchRenderer/1.0")
        .build()
        .map_err(|error| RenderError::Browser(error.to_string()))?;
    let mut page = browser
        .new_page()
        .await
        .map_err(|error| RenderError::Browser(error.to_string()))?;
    let navigation = Arc::new(Mutex::new(NavigationMeta::default()));
    let capture = Arc::clone(&navigation);
    page.on_response(Arc::new(move |info, response| {
        if info.resource_type != ResourceType::Document {
            return;
        }
        if let Ok(mut meta) = capture.lock() {
            if meta.status == 0 || (300..400).contains(&meta.status) {
                meta.final_url = response.url.to_string();
                meta.status = response.status;
                meta.content_type = response.content_type().unwrap_or("text/html").to_owned();
            }
        }
    }));
    page.goto(&request.url)
        .await
        .map_err(|error| RenderError::Browser(error.to_string()))?;
    page.settle(request.settle_ms.clamp(0, 5_000)).await;
    let title = page
        .evaluate("document.title")
        .as_str()
        .unwrap_or_default()
        .to_owned();
    let mut content = page
        .evaluate(obscura_browser::HTML_TO_MARKDOWN_JS)
        .as_str()
        .unwrap_or_default()
        .to_owned();
    if content.trim().is_empty() {
        content = page
            .evaluate("document.body ? document.body.textContent : ''")
            .as_str()
            .unwrap_or_default()
            .to_owned();
    }
    if content.len() > request.max_bytes {
        return Err(RenderError::TooLarge(request.max_bytes));
    }
    let meta = navigation
        .lock()
        .ok()
        .map(|value| value.clone())
        .unwrap_or_default();
    let final_url = if meta.final_url.is_empty() {
        page.url()
    } else {
        meta.final_url
    };
    Ok(RenderResponse {
        schema_version: PROTOCOL,
        request_id: request.request_id,
        ok: true,
        final_url: Some(final_url),
        status: Some(if meta.status == 0 { 200 } else { meta.status }),
        title: Some(title),
        content_type: Some(if meta.content_type.is_empty() {
            "text/html".to_owned()
        } else {
            meta.content_type
        }),
        content: Some(content),
        elapsed_ms: Some(started.elapsed().as_millis().min(i64::MAX as u128) as i64),
        error: None,
    })
}

pub fn failure_response(request_id: String, error: impl ToString) -> RenderResponse {
    RenderResponse {
        schema_version: PROTOCOL,
        request_id,
        ok: false,
        final_url: None,
        status: None,
        title: None,
        content_type: None,
        content: None,
        elapsed_ms: None,
        error: Some(error.to_string()),
    }
}

fn validate_request(request: &RenderRequest) -> Result<(), RenderError> {
    if request.schema_version != PROTOCOL {
        return Err(RenderError::Invalid(format!(
            "unsupported schema {}",
            request.schema_version
        )));
    }
    if request.request_id.trim().is_empty() || request.request_id.len() > 256 {
        return Err(RenderError::Invalid("request id is invalid".to_owned()));
    }
    if !(1..=4 * 1024 * 1024).contains(&request.max_bytes) {
        return Err(RenderError::Invalid(
            "maxBytes is outside policy".to_owned(),
        ));
    }
    if request.url.len() > 4_096 {
        return Err(RenderError::Invalid("URL exceeds 4096 bytes".to_owned()));
    }
    let url = Url::parse(&request.url).map_err(|error| RenderError::Invalid(error.to_string()))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(RenderError::Invalid(
            "only http and https are allowed".to_owned(),
        ));
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(RenderError::Invalid(
            "embedded credentials are forbidden".to_owned(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(url: &str) -> RenderRequest {
        RenderRequest {
            schema_version: PROTOCOL.to_owned(),
            request_id: "fixture".to_owned(),
            url: url.to_owned(),
            max_bytes: 32 * 1024,
            settle_ms: 0,
        }
    }

    #[test]
    fn request_policy_rejects_non_web_schemes_and_credentials() {
        assert!(validate_request(&request("file:///etc/passwd")).is_err());
        assert!(validate_request(&request("https://user:secret@example.com")).is_err());
        assert!(validate_request(&request("https://example.com")).is_ok());
    }
}
