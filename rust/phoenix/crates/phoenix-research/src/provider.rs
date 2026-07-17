use std::env;

use hashbrown::HashMap;
use memchr::memmem;
use reqwest::header::USER_AGENT;
use serde::Deserialize;
use serde_json::json;
use url::Url;

use crate::renderer::ObscuraRenderer;
use crate::web::{
    phoenix_user_agent, pinned_client, request_error, validate_public_url, WebError, WebFetchMode,
    WebSearchHit, WebSearchResults,
};

pub trait WebSearchProvider: Send + Sync {
    fn id(&self) -> &str;
    fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError>;
}

pub struct SearchProviderRegistry {
    selected: Option<String>,
    providers: HashMap<String, Box<dyn WebSearchProvider>>,
}

impl SearchProviderRegistry {
    pub fn from_env(max_source_bytes: usize) -> Result<Self, WebError> {
        let configured = env::var("PHOENIX_WEB_SEARCH_PROVIDER")
            .ok()
            .map(|value| value.trim().to_ascii_lowercase())
            .filter(|value| !value.is_empty());
        let selected = configured
            .or_else(|| {
                env::var("PHOENIX_TAVILY_API_KEY")
                    .ok()
                    .filter(|value| !value.trim().is_empty())
                    .map(|_| "tavily".to_owned())
            })
            .or_else(|| Some("obscura".to_owned()));
        let mut registry = Self {
            selected: selected.clone(),
            providers: HashMap::new(),
        };
        match selected.as_deref() {
            Some("tavily") => registry.register(Box::new(TavilySearchProvider::from_env()?)),
            Some("obscura") => registry.register(Box::new(ObscuraHtmlSearchProvider::from_env(
                max_source_bytes,
            )?)),
            Some("none") | None => registry.selected = None,
            Some(other) => return Err(WebError::UnknownSearchProvider(other.to_owned())),
        }
        Ok(registry)
    }

    pub fn register(&mut self, provider: Box<dyn WebSearchProvider>) {
        self.providers.insert(provider.id().to_owned(), provider);
    }

    pub fn select(&mut self, provider: impl Into<String>) -> Result<(), WebError> {
        let provider = provider.into();
        if !self.providers.contains_key(provider.as_str()) {
            return Err(WebError::UnknownSearchProvider(provider));
        }
        self.selected = Some(provider);
        Ok(())
    }

    pub fn selected(&self) -> Option<&str> {
        self.selected.as_deref()
    }

    pub fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError> {
        let selected = self
            .selected
            .as_deref()
            .ok_or(WebError::MissingSearchCapability)?;
        self.providers
            .get(selected)
            .ok_or_else(|| WebError::UnknownSearchProvider(selected.to_owned()))?
            .search(query, max_results)
    }
}

struct ObscuraHtmlSearchProvider {
    renderer: ObscuraRenderer,
    endpoint: Url,
}

impl ObscuraHtmlSearchProvider {
    fn from_env(max_source_bytes: usize) -> Result<Self, WebError> {
        let endpoint = env::var("PHOENIX_OBSCURA_SEARCH_ENDPOINT")
            .unwrap_or_else(|_| "https://html.duckduckgo.com/html/".to_owned());
        let endpoint =
            Url::parse(&endpoint).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
        validate_public_url(&endpoint)?;
        if endpoint.scheme() != "https" {
            return Err(WebError::UnsafeUrl(
                "Obscura search endpoint must use https".to_owned(),
            ));
        }
        Ok(Self {
            renderer: ObscuraRenderer::from_env(max_source_bytes),
            endpoint,
        })
    }
}

impl WebSearchProvider for ObscuraHtmlSearchProvider {
    fn id(&self) -> &str {
        "obscura"
    }

    fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError> {
        let query = query.trim();
        if query.len() < 3 || query.len() > 512 {
            return Err(WebError::Request(
                "search query must contain 3 to 512 bytes".to_owned(),
            ));
        }
        let mut url = self.endpoint.clone();
        url.query_pairs_mut().clear().append_pair("q", query);
        let fetched = self.renderer.render(url.as_str(), WebFetchMode::Rendered)?;
        let hits = parse_duckduckgo_markdown(&fetched.content, max_results.clamp(1, 10));
        if hits.is_empty() {
            return Err(WebError::Request(
                "Obscura search returned no normalized results".to_owned(),
            ));
        }
        Ok(WebSearchResults {
            provider: "obscura-duckduckgo-html".to_owned(),
            query: query.to_owned(),
            hits,
            elapsed_ms: fetched.elapsed_ms,
        })
    }
}

fn parse_duckduckgo_markdown(markdown: &str, max_results: usize) -> Vec<WebSearchHit> {
    let bytes = markdown.as_bytes();
    let mut hits = Vec::with_capacity(max_results);
    let mut cursor = 0usize;
    let mut seen = hashbrown::HashSet::<String>::new();
    while hits.len() < max_results {
        let Some(relative_start) = memmem::find(&bytes[cursor..], b"## [") else {
            break;
        };
        let start = cursor + relative_start;
        let title_start = start + 4;
        let Some(relative_title_end) = memmem::find(&bytes[title_start..], b"](") else {
            break;
        };
        let title_end = title_start + relative_title_end;
        let href_start = title_end + 2;
        let Some(relative_href_end) = memchr::memchr(b')', &bytes[href_start..]) else {
            break;
        };
        let href_end = href_start + relative_href_end;
        let next = memmem::find(&bytes[href_end + 1..], b"## [")
            .map(|offset| href_end + 1 + offset)
            .unwrap_or(bytes.len());
        let title = clean_markdown_text(&markdown[title_start..title_end]);
        let href = &markdown[href_start..href_end];
        if let Some(url) = decode_duckduckgo_target(href) {
            if seen.insert(url.clone()) && !title.is_empty() {
                hits.push(WebSearchHit {
                    url,
                    title,
                    excerpt: longest_link_label(&markdown[href_end + 1..next]),
                });
            }
        }
        cursor = next.max(href_end + 1);
    }
    hits
}

fn decode_duckduckgo_target(input: &str) -> Option<String> {
    let input = if input.starts_with("//") {
        format!("https:{input}")
    } else {
        input.to_owned()
    };
    let parsed = Url::parse(&input).ok()?;
    let mut target = if parsed
        .host_str()
        .is_some_and(|host| host.eq_ignore_ascii_case("duckduckgo.com"))
        && parsed.path() == "/l/"
    {
        parsed
            .query_pairs()
            .find_map(|(key, value)| (key == "uddg").then(|| value.into_owned()))?
    } else {
        input
    };
    let mut target_url = Url::parse(&target).ok()?;
    validate_public_url(&target_url).ok()?;
    target_url.set_fragment(None);
    target = target_url.to_string();
    Some(target)
}

fn longest_link_label(section: &str) -> String {
    let bytes = section.as_bytes();
    let mut cursor = 0usize;
    let mut best = String::new();
    while cursor < bytes.len() {
        let Some(relative_start) = memchr::memchr(b'[', &bytes[cursor..]) else {
            break;
        };
        let start = cursor + relative_start;
        if start > 0 && bytes[start - 1] == b'!' {
            cursor = start + 1;
            continue;
        }
        let Some(relative_end) = memmem::find(&bytes[start + 1..], b"](") else {
            break;
        };
        let end = start + 1 + relative_end;
        let candidate = clean_markdown_text(&section[start + 1..end]);
        if candidate.len() > best.len() && !candidate.starts_with("http") {
            best = candidate;
        }
        cursor = end + 2;
    }
    best
}

fn clean_markdown_text(input: &str) -> String {
    input
        .replace("**", "")
        .replace("__", "")
        .replace("&amp;", "&")
        .replace("&quot;", "\"")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

struct TavilySearchProvider {
    api_key: String,
    endpoint: Url,
}

impl TavilySearchProvider {
    fn from_env() -> Result<Self, WebError> {
        let api_key = env::var("PHOENIX_TAVILY_API_KEY")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .ok_or(WebError::MissingSearchCapability)?;
        let endpoint = env::var("PHOENIX_TAVILY_ENDPOINT")
            .unwrap_or_else(|_| "https://api.tavily.com/search".to_owned());
        let endpoint =
            Url::parse(&endpoint).map_err(|error| WebError::UnsafeUrl(error.to_string()))?;
        validate_public_url(&endpoint)?;
        if endpoint.scheme() != "https" {
            return Err(WebError::UnsafeUrl(
                "search provider must use https".to_owned(),
            ));
        }
        Ok(Self { api_key, endpoint })
    }
}

impl WebSearchProvider for TavilySearchProvider {
    fn id(&self) -> &str {
        "tavily"
    }

    fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError> {
        let started = std::time::Instant::now();
        let client = pinned_client(&self.endpoint, std::time::Duration::from_secs(18))?;
        let response = client
            .post(self.endpoint.clone())
            .header(USER_AGENT, phoenix_user_agent())
            .json(&json!({
                "api_key": self.api_key,
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
            provider: self.id().to_owned(),
            query: query.to_owned(),
            hits: payload
                .results
                .into_iter()
                .take(max_results)
                .map(|hit| WebSearchHit {
                    url: hit.url,
                    title: hit.title,
                    excerpt: hit.content.chars().take(2_000).collect(),
                })
                .collect(),
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

#[cfg(test)]
mod tests {
    use super::*;

    struct FixtureProvider;

    impl WebSearchProvider for FixtureProvider {
        fn id(&self) -> &str {
            "fixture"
        }

        fn search(&self, query: &str, max_results: usize) -> Result<WebSearchResults, WebError> {
            Ok(WebSearchResults {
                provider: self.id().to_owned(),
                query: query.to_owned(),
                hits: vec![WebSearchHit {
                    url: "https://example.com".to_owned(),
                    title: "Fixture".to_owned(),
                    excerpt: "bounded".to_owned(),
                }]
                .into_iter()
                .take(max_results)
                .collect(),
                elapsed_ms: 0,
            })
        }
    }

    #[test]
    fn registry_requires_an_explicit_registered_selection() {
        let mut registry = SearchProviderRegistry {
            selected: None,
            providers: HashMap::new(),
        };
        assert!(matches!(
            registry.search("query", 3),
            Err(WebError::MissingSearchCapability)
        ));
        registry.register(Box::new(FixtureProvider));
        registry.select("fixture").unwrap();
        let result = registry.search("query", 1).unwrap();
        assert_eq!(result.provider, "fixture");
        assert_eq!(result.hits.len(), 1);
    }

    #[test]
    fn duckduckgo_markdown_is_normalized_without_redirect_tracking() {
        let markdown = r#"
## [Obscura Browser](//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fh4ckf0r0day%2Fobscura&rut=tracking)
[github.com/h4ckf0r0day/obscura](//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fh4ckf0r0day%2Fobscura)
[A **Rust** headless browser for agent research and scraping.](//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fh4ckf0r0day%2Fobscura)

## [Rust](https://www.rust-lang.org/)
[A language empowering everyone to build reliable software.](https://www.rust-lang.org/)
"#;
        let hits = parse_duckduckgo_markdown(markdown, 10);
        assert_eq!(hits.len(), 2);
        assert_eq!(hits[0].url, "https://github.com/h4ckf0r0day/obscura");
        assert_eq!(
            hits[0].excerpt,
            "A Rust headless browser for agent research and scraping."
        );
        assert_eq!(hits[1].url, "https://www.rust-lang.org/");
    }
}
