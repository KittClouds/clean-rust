use phoenix_research::{NativeWebClient, WebFetchMode, WebFetcher};

#[test]
#[ignore = "requires a built phoenix-obscura-worker and public network access"]
fn real_worker_transaction_returns_a_rendered_receipt() {
    let worker = std::env::var("PHOENIX_OBSCURA_WORKER_PATH")
        .expect("PHOENIX_OBSCURA_WORKER_PATH must point to the built sidecar");
    assert!(std::path::Path::new(&worker).is_file(), "{worker}");
    let client = NativeWebClient::from_env(256 * 1024).unwrap();
    let fetched = client
        .fetch_mode("https://example.com/", WebFetchMode::Rendered)
        .unwrap();
    assert_eq!(fetched.status, 200);
    assert!(
        fetched.content.contains("Example Domain"),
        "{}",
        fetched.content
    );
    assert_eq!(fetched.receipt.backend, "obscura-sidecar");
    assert_eq!(fetched.receipt.resolved_mode, WebFetchMode::Rendered);
    assert!(fetched.receipt.rendered);
    assert!(fetched.receipt.total_ms > 0);
}

#[test]
#[ignore = "requires a built phoenix-obscura-worker and public network access"]
fn real_obscura_search_returns_normalized_keyless_hits() {
    let worker = std::env::var("PHOENIX_OBSCURA_WORKER_PATH")
        .expect("PHOENIX_OBSCURA_WORKER_PATH must point to the built sidecar");
    assert!(std::path::Path::new(&worker).is_file(), "{worker}");
    std::env::set_var("PHOENIX_WEB_SEARCH_PROVIDER", "obscura");
    let client = NativeWebClient::from_env(256 * 1024).unwrap();
    let results = client.search("rust headless browser", 5).unwrap();
    std::env::remove_var("PHOENIX_WEB_SEARCH_PROVIDER");
    assert_eq!(results.provider, "obscura-duckduckgo-html");
    assert!(!results.hits.is_empty());
    assert!(results.hits.len() <= 5);
    for hit in results.hits {
        assert!(hit.url.starts_with("http"), "{}", hit.url);
        assert!(!hit.url.contains("duckduckgo.com/l/"), "{}", hit.url);
        assert!(!hit.title.trim().is_empty());
    }
}
