use std::io::{Read, Write};

use phoenix_obscura_worker::{failure_response, render_request, RenderRequest};

const REQUEST_LIMIT: u64 = 64 * 1024;

fn main() {
    std::env::remove_var("OBSCURA_ALLOW_PRIVATE_NETWORK");
    std::env::remove_var("OBSCURA_PROXY");
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            write_response(&failure_response("unknown".to_owned(), error));
            return;
        }
    };
    let response = runtime.block_on(async {
        let mut payload = Vec::with_capacity(4 * 1024);
        let mut stdin = std::io::stdin().lock().take(REQUEST_LIMIT + 1);
        if let Err(error) = stdin.read_to_end(&mut payload) {
            return failure_response("unknown".to_owned(), error);
        }
        if payload.len() > REQUEST_LIMIT as usize {
            return failure_response("unknown".to_owned(), "request exceeded 64 KiB");
        }
        let request: RenderRequest = match serde_json::from_slice(&payload) {
            Ok(request) => request,
            Err(error) => return failure_response("unknown".to_owned(), error),
        };
        let request_id = request.request_id.clone();
        match render_request(request).await {
            Ok(response) => response,
            Err(error) => failure_response(request_id, error),
        }
    });
    write_response(&response);
}

fn write_response(response: &phoenix_obscura_worker::RenderResponse) {
    let stdout = std::io::stdout();
    let mut writer = stdout.lock();
    let _ = serde_json::to_writer(&mut writer, response);
    let _ = writer.write_all(b"\n");
    let _ = writer.flush();
}
