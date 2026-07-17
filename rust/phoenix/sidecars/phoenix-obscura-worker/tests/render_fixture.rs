use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread;

use phoenix_obscura_worker::{render_request, RenderRequest, PROTOCOL};

#[test]
fn renders_javascript_into_markdown_in_one_isolated_process() {
    std::env::set_var("OBSCURA_ALLOW_PRIVATE_NETWORK", "1");
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = [0u8; 2048];
        let _ = stream.read(&mut request);
        let body = r#"<!doctype html><html><head><title>Fixture</title></head><body><main id="app"></main><script>document.getElementById('app').innerHTML='<h1>Rendered Evidence</h1><p>Obscura executed this JavaScript.</p>';</script></body></html>"#;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        stream.write_all(response.as_bytes()).unwrap();
    });
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let response = runtime
        .block_on(render_request(RenderRequest {
            schema_version: PROTOCOL.to_owned(),
            request_id: "fixture-1".to_owned(),
            url: format!("http://{address}/fixture"),
            max_bytes: 64 * 1024,
            settle_ms: 50,
        }))
        .unwrap();
    server.join().unwrap();
    std::env::remove_var("OBSCURA_ALLOW_PRIVATE_NETWORK");
    assert!(response.ok);
    assert_eq!(response.title.as_deref(), Some("Fixture"));
    let content = response.content.unwrap();
    assert!(content.contains("# Rendered Evidence"), "{content}");
    assert!(content.contains("Obscura executed this JavaScript."));
}
