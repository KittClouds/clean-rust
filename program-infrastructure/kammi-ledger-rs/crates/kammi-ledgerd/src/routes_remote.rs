//! Remote bundle and worker routes (`api.py`).

use std::collections::BTreeMap;

use axum::body::{Body, Bytes};
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::Router;
use base64::Engine;
use kammi_core::json::{get as jget, get_str};
use kammi_core::{obj, LedgerError};
use kammi_jcs::{strict_json, Value};

use crate::routes_custody::write;
use crate::{
    actor_auth, authenticate, authenticate_actor, body_json, detail, done, field_str, internal,
    json, ledger_error, missing, App,
};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v1/remote/worker-keys", post(register_worker_key))
        .route("/v1/remote/bundles", post(create_bundle))
        .route("/v1/remote/bundles/{bundle_id}", get(get_bundle))
        .route(
            "/v1/remote/bundles/{bundle_id}/inputs/{artifact_id}",
            get(get_bundle_input),
        )
        .route("/v1/remote/bundles/{bundle_id}/return", post(accept_return))
        .route("/v1/remote/bundles/{bundle_id}/start", post(start_remote))
}

fn b64(text: &str) -> kammi_core::Result<Vec<u8>> {
    base64::engine::general_purpose::STANDARD
        .decode(text)
        .map_err(|e| LedgerError::Value(e.to_string()))
}

async fn register_worker_key(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            let b = body_json(&body)?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.register_worker_key(
                    get_str(&b, "worker_actor_id")?,
                    get_str(&b, "public_key_hex")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn create_bundle(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (event, envelope) = l.create_remote_bundle(
                    jget(&b, "bundle")?,
                    get_str(&b, "actor_id")?,
                    &token,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event, "envelope" => envelope})
            })
            .await
        }
        .await,
    )
}

/// `qualified_worker`: returns (envelope, bundle JSON, raw bundle bytes).
fn qualified_worker(
    app: &App,
    headers: &HeaderMap,
    bundle_id: &str,
    worker: &str,
) -> Result<(Value, Value, Vec<u8>), Response> {
    let ledger = app.ledger.read();
    authenticate_actor(&ledger, headers, worker)?;
    let Some((envelope, raw)) = ledger.bundle_for_worker(bundle_id).map_err(internal)? else {
        return Err(detail(StatusCode::NOT_FOUND, "unknown bundle"));
    };
    let bundle = strict_json(&raw).map_err(internal)?;
    if bundle["worker_actor_id"].as_str() != Some(worker) {
        return Err(detail(
            StatusCode::FORBIDDEN,
            "bundle assigned to another worker",
        ));
    }
    Ok((envelope, bundle, raw))
}

fn worker_query(query: &BTreeMap<String, String>) -> Result<String, Response> {
    query
        .get("worker_actor_id")
        .cloned()
        .ok_or_else(|| missing("query", "worker_actor_id"))
}

async fn get_bundle(
    State(app): State<App>,
    Path(bundle_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(async {
        let worker = worker_query(&query)?;
        let (envelope, _, raw) = qualified_worker(&app, &headers, &bundle_id, &worker)?;
        Ok(json(obj! {"bundle_base64" => base64::engine::general_purpose::STANDARD.encode(raw), "envelope" => envelope}))
    }.await)
}

async fn get_bundle_input(
    State(app): State<App>,
    Path((bundle_id, artifact_id)): Path<(String, String)>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let worker = worker_query(&query)?;
            let (envelope, bundle, _) = qualified_worker(&app, &headers, &bundle_id, &worker)?;
            if !bundle["input_artifacts"]
                .as_array()
                .is_some_and(|a| a.iter().any(|i| i.as_str() == Some(artifact_id.as_str())))
            {
                return Err(detail(
                    StatusCode::FORBIDDEN,
                    "input not declared in bundle",
                ));
            }
            let producer = envelope["actor_id"].as_str().unwrap_or("").to_string();
            let ledger = app.ledger.read();
            let (auth, run, stage) = (
                bundle["authorization_id"].as_str().unwrap_or(""),
                bundle["run_id"].as_str().unwrap_or(""),
                bundle["stage_id"].as_str().unwrap_or(""),
            );
            if !ledger
                .authorization_valid(auth, &producer, run, stage)
                .map_err(internal)?
            {
                return Err(detail(
                    StatusCode::FORBIDDEN,
                    "bundle authorization is no longer current",
                ));
            }
            if !ledger.remote_input_allowed(&artifact_id, &producer, run, stage) {
                return Err(detail(
                    StatusCode::FORBIDDEN,
                    "protected bundle input lacks guarded exposure",
                ));
            }
            // Python lets a missing/corrupt object escape as a 500; Rust reports it as a 400.
            let data = ledger
                .object_bytes(&artifact_id)
                .map_err(|e| ledger_error(e, StatusCode::BAD_REQUEST))?;
            let mut response = (StatusCode::OK, Body::from(data)).into_response();
            response.headers_mut().insert(
                "content-type",
                HeaderValue::from_static("application/octet-stream"),
            );
            Ok(response)
        }
        .await,
    )
}

async fn accept_return(
    State(app): State<App>,
    Path(bundle_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let worker = field_str(&b, "worker_actor_id")?.to_string();
            let token = authenticate_actor(&app.ledger.read(), &headers, &worker)?;
            qualified_worker(&app, &headers, &bundle_id, &worker)?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let mut outputs = BTreeMap::new();
                for (name, data) in kammi_core::json::get_obj(&b, "outputs_base64")? {
                    let text = data.as_str().ok_or_else(|| {
                        LedgerError::Type(
                            "argument should be a bytes-like object or ASCII string".into(),
                        )
                    })?;
                    outputs.insert(name.clone(), b64(text)?);
                }
                let (event, receipt) = l.accept_remote_return(
                    &bundle_id,
                    &b64(get_str(&b, "receipt_base64")?)?,
                    get_str(&b, "receipt_signature")?,
                    &worker,
                    &token,
                    &outputs,
                    &b64(get_str(&b, "stdout_base64")?)?,
                    &b64(get_str(&b, "stderr_base64")?)?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event, "receipt" => receipt})
            })
            .await
        }
        .await,
    )
}

async fn start_remote(
    State(app): State<App>,
    Path(bundle_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = actor_auth(&app, &headers, &b, "worker_actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.remote_worker_started(
                    &bundle_id,
                    get_str(&b, "worker_actor_id")?,
                    &token,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}
