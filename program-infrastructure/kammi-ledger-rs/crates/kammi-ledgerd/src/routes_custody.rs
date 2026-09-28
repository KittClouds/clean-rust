//! Custody routes from `api.py` and `surface_api.py`.

use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use axum::routing::{get, post};
use axum::Router;
use base64::Engine;
use kammi_core::json::{get as jget, get_str};
use kammi_core::{obj, Ledger, LedgerError};

use kammi_jcs::Value;

use crate::{
    authenticate, blocking, body_json, detail, done, header, json, ledger_error, App,
    HandlerResult, MAX_UPLOAD_BYTES,
};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v1/status", get(status))
        .route("/v1/artifacts", post(artifact))
        .route("/v1/artifacts/base64", post(artifact_base64))
        .route("/v1/artifacts/import-local", post(import_local))
        .route("/v1/runs", post(create_run))
        .route("/v1/facts", post(record_fact))
        .route("/v1/actors", post(register_actor))
        .route("/v1/grants", post(issue_grant))
        .route("/v1/policies", post(register_policy))
        .route("/v1/panels", post(register_panel))
        .route("/v1/resources", post(register_resource))
        .route("/v1/adapters", post(register_adapter))
        .route("/v1/adapters/{adapter_id}/apply", post(apply_adapter))
        .route("/v1/seals", post(create_seal))
        .route("/v1/runs/{run_id}/history", get(history))
        .route("/v1/runs/{run_id}/history/summary", get(history_summary))
        .route("/v1/seals/{root}/lineage", get(lineage))
}

/// Runs `work` under the writer lock off the reactor; client errors become `status`.
pub(crate) async fn write(
    app: &App,
    status: StatusCode,
    work: impl FnOnce(&mut Ledger) -> kammi_core::Result<Value> + Send + 'static,
) -> HandlerResult {
    let ledger = app.ledger.clone();
    blocking(move || work(&mut ledger.write()))
        .await
        .map(json)
        .map_err(|e| ledger_error(e, status))
}

pub(crate) async fn read(
    app: &App,
    status: StatusCode,
    work: impl FnOnce(&Ledger) -> kammi_core::Result<Value> + Send + 'static,
) -> HandlerResult {
    let ledger = app.ledger.clone();
    blocking(move || work(&ledger.read()))
        .await
        .map(json)
        .map_err(|e| ledger_error(e, status))
}

fn strings(value: &Value, key: &str) -> kammi_core::Result<Vec<String>> {
    kammi_core::json::string_list(value, key)
}

async fn status(State(app): State<App>, headers: HeaderMap) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            let projector = app.projector.clone();
            read(&app, StatusCode::BAD_REQUEST, move |l| {
                let mut status = l.status()?;
                if let Some(projector) = projector {
                    // Python reports the Ladybug projection's own position; so does Rust.
                    let block = projector.status(
                        l.store.main.seq(),
                        &l.store.main.head().to_string(),
                        l.store.memory.seq(),
                    );
                    status["projection_seq"] = block["projection_seq"].clone();
                    status["projection_head"] = block["projection_head"].clone();
                    status["projection_lag"] = block["lag"].clone();
                    if status["memory"]["enabled"] == true {
                        status["memory"]["fts_rebuilds"] = block["memory"]["fts_rebuilds"].clone();
                        status["memory"]["fts_pending_records"] =
                            block["memory"]["fts_pending_records"].clone();
                    }
                    status["projection"] = block;
                }
                Ok(status)
            })
            .await
        }
        .await,
    )
}

async fn artifact(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let kind = header(&headers, "x-kind")
                .ok_or_else(|| crate::missing("header", "x-kind"))?
                .to_string();
            let actor = header(&headers, "x-actor")
                .ok_or_else(|| crate::missing("header", "x-actor"))?
                .to_string();
            let request_id = header(&headers, "x-request-id")
                .ok_or_else(|| crate::missing("header", "x-request-id"))?
                .to_string();
            authenticate(&app, &headers)?;
            if let Some(length) = header(&headers, "content-length") {
                let declared: u64 = length
                    .parse()
                    .map_err(|_| detail(StatusCode::BAD_REQUEST, "invalid content length"))?;
                if declared > MAX_UPLOAD_BYTES as u64 {
                    return Err(detail(StatusCode::PAYLOAD_TOO_LARGE, "upload too large"));
                }
            }
            if body.len() > MAX_UPLOAD_BYTES {
                return Err(detail(StatusCode::PAYLOAD_TOO_LARGE, "upload too large"));
            }
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (artifact_id, event_id) =
                    l.register_bytes(&body, &kind, &actor, &request_id)?;
                Ok(obj! {"artifact_id" => artifact_id, "event_id" => event_id})
            })
            .await
        }
        .await,
    )
}

async fn artifact_base64(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            let b = body_json(&body)?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let bytes = base64::engine::general_purpose::STANDARD
                    .decode(get_str(&b, "bytes_base64")?)
                    .map_err(|e| LedgerError::Value(e.to_string()))?;
                let (artifact_id, event_id) = l.register_bytes(
                    &bytes,
                    get_str(&b, "kind")?,
                    get_str(&b, "actor")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"artifact_id" => artifact_id, "event_id" => event_id})
            })
            .await
        }
        .await,
    )
}

async fn import_local(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(async {
        authenticate(&app, &headers)?;
        let b = body_json(&body)?;
        write(&app, StatusCode::BAD_REQUEST, move |l| {
            let (artifact_id, event_id, byte_count) = l.import_local_artifact(&b)?;
            Ok(obj! {"artifact_id" => artifact_id, "event_id" => event_id, "byte_count" => byte_count})
        })
        .await
    }.await)
}

macro_rules! admin_route {
    ($name:ident, |$l:ident, $b:ident| $body:expr) => {
        async fn $name(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
            done(
                async {
                    authenticate(&app, &headers)?;
                    let $b = body_json(&body)?;
                    write(&app, StatusCode::BAD_REQUEST, move |$l| $body).await
                }
                .await,
            )
        }
    };
}

admin_route!(create_run, |l, b| {
    let event = l.create_run(
        get_str(&b, "run_id")?,
        get_str(&b, "lab")?,
        get_str(&b, "actor")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"event_id" => event})
});

admin_route!(record_fact, |l, b| {
    let (fact_id, event) = l.record_fact(
        jget(&b, "fact")?,
        get_str(&b, "actor")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"fact_id" => fact_id, "event_id" => event})
});

admin_route!(register_actor, |l, b| {
    let event = l.register_actor(
        get_str(&b, "actor_id")?,
        get_str(&b, "kind")?,
        get_str(&b, "lab")?,
        get_str(&b, "credential_sha256")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"event_id" => event})
});

admin_route!(issue_grant, |l, b| {
    let event = l.issue_grant(
        get_str(&b, "grant_id")?,
        get_str(&b, "actor_id")?,
        get_str(&b, "action")?,
        get_str(&b, "run_id")?,
        get_str(&b, "stage_id")?,
        get_str(&b, "policy_hash")?,
        get_str(&b, "expires_utc")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"event_id" => event})
});

admin_route!(register_policy, |l, b| {
    let (policy_hash, event) =
        l.register_policy(jget(&b, "policy")?, get_str(&b, "request_id")?)?;
    Ok(obj! {"policy_hash" => policy_hash, "event_id" => event})
});

admin_route!(register_panel, |l, b| {
    let event = l.register_panel(
        get_str(&b, "panel_id")?,
        get_str(&b, "artifact_id")?,
        get_str(&b, "lab")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"event_id" => event})
});

admin_route!(register_resource, |l, b| {
    let event = l.register_resource(
        get_str(&b, "resource_id")?,
        get_str(&b, "kind")?,
        get_str(&b, "host")?,
        jget(&b, "constraints")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"event_id" => event})
});

admin_route!(register_adapter, |l, b| {
    let (implementation_hash, event) =
        l.register_adapter(get_str(&b, "adapter_id")?, get_str(&b, "request_id")?)?;
    Ok(obj! {"implementation_hash" => implementation_hash, "event_id" => event})
});

admin_route!(create_seal, |l, b| {
    let (root, event) = l.create_seal(
        &strings(&b, "direct_members")?,
        &strings(&b, "parents")?,
        get_str(&b, "actor")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"root" => root, "event_id" => event})
});

async fn apply_adapter(
    State(app): State<App>,
    Path(adapter_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = crate::actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (derived, event) = l.apply_adapter(
                    &adapter_id,
                    get_str(&b, "source_artifact_id")?,
                    get_str(&b, "actor_id")?,
                    &token,
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "authorization_id")?,
                    get_str(&b, "purpose")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"derived_view_id" => derived, "event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn history(
    State(app): State<App>,
    Path(run_id): Path<String>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                Ok(obj! {"run_id" => run_id.clone(), "facts" => l.history(&run_id)?})
            })
            .await
        }
        .await,
    )
}

async fn history_summary(
    State(app): State<App>,
    Path(run_id): Path<String>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                let summary = l.history_summary(&run_id)?;
                Ok(kammi_core::json::merged(
                    &obj! {"run_id" => run_id.clone()},
                    summary,
                ))
            })
            .await
        }
        .await,
    )
}

async fn lineage(State(app): State<App>, Path(root): Path<String>, headers: HeaderMap) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            read(&app, StatusCode::BAD_REQUEST, move |l| {
            let members = l.verify_seal(&root)?;
            Ok(obj! {"root" => root.clone(), "entry_count" => members.len(), "closure" => members})
        })
        .await
        }
        .await,
    )
}
