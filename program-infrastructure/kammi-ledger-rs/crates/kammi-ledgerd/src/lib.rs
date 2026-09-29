//! HTTP surface of the Kammi Library. `/v1` is byte-compatible in behaviour with the Python
//! FastAPI service: the same 64 routes, middleware order (16 MiB cap, strict JSON, wire-v1
//! validation, then authentication), auth kinds, status codes and `{"detail": ...}` bodies.
//! `/v2` (amendment v4) adds vocabulary activation and workspaces.

#![allow(clippy::result_large_err)]

pub mod projector;
mod routes_access;
mod routes_custody;
mod routes_local;
mod routes_memory;
mod routes_remote;
mod routes_vault;
mod routes_workspace;
pub mod wire;

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::{Body, Bytes};
use axum::extract::{Request, State};
use axum::http::{HeaderMap, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::{Json, Router};
use http_body_util::BodyExt;
use kammi_core::{Ledger, LedgerError};
use kammi_jcs::{strict_json, Value};
use parking_lot::RwLock;

pub const MAX_UPLOAD_BYTES: usize = 16 * 1024 * 1024;
const STREAM_ROUTES: [&str; 3] = [
    "/v1/vaults/asset-stream",
    "/v1/vaults/source-stream",
    "/v1/vaults/package",
];

pub struct AppState {
    pub ledger: Arc<RwLock<Ledger>>,
    pub token: String,
    pub acceptance_mode: bool,
    /// Where streamed uploads land before they enter CAS.
    pub staging: PathBuf,
    /// The supervised Ladybug projection, when enabled.
    pub projector: Option<Arc<projector::Projector>>,
}

pub type App = Arc<AppState>;

/// Builds the router with the Python middleware in front of every route.
pub fn router(state: App) -> Router {
    Router::new()
        .merge(routes_custody::routes())
        .merge(routes_access::routes())
        .merge(routes_remote::routes())
        .merge(routes_memory::routes())
        .merge(routes_vault::routes())
        .merge(routes_local::routes())
        .merge(routes_workspace::routes())
        .fallback(|| async { detail(StatusCode::NOT_FOUND, "Not Found") })
        .method_not_allowed_fallback(|| async {
            detail(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed")
        })
        .layer(middleware::from_fn_with_state(state.clone(), bounded_body))
        .with_state(state)
}

/// `bounded_body`: buffers every non-stream body up to 16 MiB, then (for POSTs other than
/// the raw artifact upload) parses strict JSON and validates it against wire-v1 before any
/// route or authentication runs.
async fn bounded_body(State(_app): State<App>, request: Request, next: Next) -> Response {
    let path = request.uri().path().to_string();
    let is_post = request.method() == axum::http::Method::POST;
    if is_post && STREAM_ROUTES.contains(&path.as_str()) {
        return next.run(request).await;
    }
    let (parts, body) = request.into_parts();
    let mut stream = body.into_data_stream();
    let mut buffered: Vec<u8> = Vec::new();
    use futures_util::StreamExt;
    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(chunk) => {
                buffered.extend_from_slice(&chunk);
                if buffered.len() > MAX_UPLOAD_BYTES {
                    return (
                        StatusCode::PAYLOAD_TOO_LARGE,
                        Json(serde_json::json!({"error": "body_too_large"})),
                    )
                        .into_response();
                }
            }
            Err(_) => return detail(StatusCode::BAD_REQUEST, "unreadable request body"),
        }
    }
    if is_post && path != "/v1/artifacts" && (!buffered.is_empty() || path != "/v1/authorize") {
        let result = strict_json(&buffered)
            .map_err(|e| e.to_string())
            .and_then(|body| wire::validate_request(&path, &body));
        if let Err(message) = result {
            return detail(StatusCode::BAD_REQUEST, message);
        }
    }
    next.run(Request::from_parts(parts, Body::from(buffered)))
        .await
}

/// `HTTPException(status, detail)`.
pub fn detail(status: StatusCode, detail: impl Into<Value>) -> Response {
    (status, Json(serde_json::json!({"detail": detail.into()}))).into_response()
}

/// Maps a domain error the way a Python route's `except (ValueError, KeyError, TypeError)`
/// does; anything else is an unhandled 500.
pub fn ledger_error(error: LedgerError, status: StatusCode) -> Response {
    if let LedgerError::Unavailable(message) = &error {
        return detail(StatusCode::SERVICE_UNAVAILABLE, message.clone());
    }
    if let LedgerError::Conflict(body) = error {
        return detail(StatusCode::CONFLICT, body);
    }
    if error.is_client() {
        detail(status, error.detail())
    } else {
        internal(error)
    }
}

pub fn internal(error: impl std::fmt::Display) -> Response {
    eprintln!("internal error: {error}");
    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response()
}

/// Parses a handler body (`strict_json(await request.body())`).
pub fn body_json(body: &Bytes) -> Result<Value, Response> {
    strict_json(body).map_err(|e| detail(StatusCode::BAD_REQUEST, e.to_string()))
}

pub fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

/// FastAPI's 422 for a missing required header or query parameter.
pub fn missing(location: &str, name: &str) -> Response {
    let body = serde_json::json!({"detail": [{"type": "missing", "loc": [location, name], "msg": "Field required", "input": null}]});
    (StatusCode::UNPROCESSABLE_ENTITY, Json(body)).into_response()
}

/// Master-token check (`authenticate`).
pub fn authenticate(app: &AppState, headers: &HeaderMap) -> Result<(), Response> {
    let expected = format!("Bearer {}", app.token);
    match header(headers, "authorization") {
        Some(given)
            if kammi_core::state::constant_time_eq(given.as_bytes(), expected.as_bytes()) =>
        {
            Ok(())
        }
        _ => Err(detail(StatusCode::UNAUTHORIZED, "unauthorized")),
    }
}

/// Actor bearer check (`authenticate_actor`); returns the actor token.
pub fn authenticate_actor(
    ledger: &Ledger,
    headers: &HeaderMap,
    actor_id: &str,
) -> Result<String, Response> {
    let Some(token) = header(headers, "authorization").and_then(|h| h.strip_prefix("Bearer "))
    else {
        return Err(detail(
            StatusCode::UNAUTHORIZED,
            "actor credential required",
        ));
    };
    if !ledger.state.authority.verify_credential(actor_id, token) {
        return Err(detail(
            StatusCode::UNAUTHORIZED,
            "actor credential mismatch",
        ));
    }
    Ok(token.to_string())
}

/// Actor authentication for a JSON body field (`authenticate_actor(authorization, body[key])`).
/// A missing or non-string field is Python's KeyError/TypeError: 400.
pub fn actor_auth(
    app: &AppState,
    headers: &HeaderMap,
    body: &Value,
    key: &str,
) -> Result<String, Response> {
    let actor = field_str(body, key)?;
    authenticate_actor(&app.ledger.read(), headers, actor)
}

/// `require_scope`: actor bearer, lab owns the run, live grant for the action.
pub fn require_scope(
    ledger: &Ledger,
    headers: &HeaderMap,
    actor_id: &str,
    action: &str,
    run_id: &str,
    stage_id: &str,
) -> Result<String, Response> {
    let token = authenticate_actor(ledger, headers, actor_id)?;
    if ledger.state.authority.actor_lab(actor_id) != ledger.state.run_lab(run_id) {
        return Err(detail(StatusCode::FORBIDDEN, "actor lab does not own run"));
    }
    let granted = match ledger.state.policy.current_policy_hash(stage_id) {
        Some(hash) => ledger
            .state
            .authority
            .matching_grant(actor_id, action, run_id, stage_id, hash, ledger.now())
            .map_err(|e| ledger_error(e, StatusCode::BAD_REQUEST))?
            .is_some(),
        None => false,
    };
    if !granted {
        return Err(detail(
            StatusCode::FORBIDDEN,
            "scoped grant missing or stale",
        ));
    }
    Ok(token)
}

/// Runs blocking ledger work off the async reactor.
pub async fn blocking<T: Send + 'static>(work: impl FnOnce() -> T + Send + 'static) -> T {
    tokio::task::spawn_blocking(work)
        .await
        .expect("blocking task panicked")
}

/// `body["key"]` as a string, with Python's KeyError/TypeError mapped to 400.
pub fn field_str<'a>(body: &'a Value, key: &str) -> Result<&'a str, Response> {
    kammi_core::json::get_str(body, key).map_err(|e| ledger_error(e, StatusCode::BAD_REQUEST))
}

pub fn field<'a>(body: &'a Value, key: &str) -> Result<&'a Value, Response> {
    kammi_core::json::get(body, key).map_err(|e| ledger_error(e, StatusCode::BAD_REQUEST))
}

pub fn json(value: Value) -> Response {
    Json(value).into_response()
}

/// Collects a streamed body into a new staging file, refusing it past `limit` bytes.
pub async fn stream_to_file(
    body: Body,
    target: &std::path::Path,
    limit: u64,
    too_large: &str,
) -> Result<u64, Response> {
    use futures_util::StreamExt;
    use tokio::io::AsyncWriteExt;
    let mut file = tokio::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)
        .await
        .map_err(internal)?;
    let mut stream = body.into_data_stream();
    let mut count = 0u64;
    while let Some(chunk) = stream.next().await {
        let chunk =
            chunk.map_err(|_| detail(StatusCode::BAD_REQUEST, "unreadable request body"))?;
        count += chunk.len() as u64;
        if count > limit {
            return Err(detail(StatusCode::PAYLOAD_TOO_LARGE, too_large.to_string()));
        }
        file.write_all(&chunk).await.map_err(internal)?;
    }
    file.sync_all().await.map_err(internal)?;
    Ok(count)
}

/// A unique path in the staging directory.
pub fn staging_file(app: &AppState, prefix: &str) -> PathBuf {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let _ = std::fs::create_dir_all(&app.staging);
    app.staging.join(format!(
        "{prefix}-{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::Relaxed)
    ))
}

pub type HandlerResult = Result<Response, Response>;

pub fn done(result: HandlerResult) -> Response {
    result.unwrap_or_else(|e| e)
}

/// Collects a request body in full (routes behind the middleware are already bounded).
pub async fn read_body(body: Body) -> Bytes {
    body.collect()
        .await
        .map(|c| c.to_bytes())
        .unwrap_or_default()
}
