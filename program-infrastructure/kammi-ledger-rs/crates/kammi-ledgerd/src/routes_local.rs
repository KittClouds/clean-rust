//! Lifecycle (`lifecycle_api.py`) and supervised local execution (`local_api.py`) routes.

use std::collections::BTreeMap;

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use axum::routing::{get, post};
use axum::Router;
use kammi_core::json::get_str;
use kammi_core::obj;
use kammi_core::ops_local::LocalOutputPlan;
use kammi_jcs::Value;

use crate::routes_custody::{read, write};
use crate::{
    actor_auth, authenticate_actor, blocking, body_json, detail, done, json, ledger_error, missing,
    App,
};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v1/attempts/start", post(start))
        .route("/v1/attempts/finish", post(finish))
        .route("/v1/attempts/{attempt_id}", get(get_attempt))
        .route("/v1/results/declare", post(declare))
        .route("/v1/local/resolve", post(local_resolve))
        .route("/v1/local/validate", post(local_validate))
        .route("/v1/local/import-output", post(local_import_output))
        .route("/v1/local/contact", post(local_contact))
        .route("/v1/local/finish", post(local_finish))
}

async fn start(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.start_attempt(
                    get_str(&b, "attempt_id")?,
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "authorization_id")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn finish(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.finish_attempt(
                    get_str(&b, "attempt_id")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "outcome")?,
                    get_str(&b, "evidence_artifact")?,
                    get_str(&b, "reason")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn get_attempt(
    State(app): State<App>,
    Path(attempt_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = query
                .get("actor_id")
                .cloned()
                .ok_or_else(|| missing("query", "actor_id"))?;
            let ledger = app.ledger.read();
            authenticate_actor(&ledger, &headers, &actor)?;
            let Some(attempt) = ledger.state.lifecycle.attempts.get(&attempt_id) else {
                return Err(detail(StatusCode::NOT_FOUND, "unknown attempt"));
            };
            let run = attempt["run_id"].as_str().unwrap_or("");
            if ledger.state.authority.actor_lab(&actor) != ledger.state.run_lab(run) {
                return Err(detail(
                    StatusCode::FORBIDDEN,
                    "attempt belongs to another lab",
                ));
            }
            Ok(json(attempt.clone()))
        }
        .await,
    )
}

async fn declare(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let predecessor = b
                    .get("predecessor")
                    .and_then(Value::as_str)
                    .map(str::to_string);
                let event = l.declare_result(
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "authorization_id")?,
                    get_str(&b, "seal_root")?,
                    predecessor.as_deref(),
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}

// Every local route maps KeyError/ValueError/TypeError/OSError to 423, like `local_api.py`.

async fn local_resolve(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(async {
        let b = body_json(&body).map_err(|_| detail(StatusCode::LOCKED, "invalid request body"))?;
        actor_auth(&app, &headers, &b, "actor_id").map_err(locked_key)?;
        read(&app, StatusCode::LOCKED, move |l| {
            let spec = l.live_local(&b, true)?;
            Ok(obj! {"valid" => true, "execution_spec" => spec, "library_acceptance" => l.state.library_acceptance.clone().map_or(Value::Null, Value::from)})
        })
        .await
    }.await)
}

async fn local_validate(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b =
                body_json(&body).map_err(|_| detail(StatusCode::LOCKED, "invalid request body"))?;
            actor_auth(&app, &headers, &b, "actor_id").map_err(locked_key)?;
            read(&app, StatusCode::LOCKED, move |l| {
                l.live_local(&b, false)?;
                Ok(obj! {"valid" => true})
            })
            .await
        }
        .await,
    )
}

async fn local_import_output(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b =
                body_json(&body).map_err(|_| detail(StatusCode::LOCKED, "invalid request body"))?;
            actor_auth(&app, &headers, &b, "actor_id").map_err(locked_key)?;
            let ledger = app.ledger.clone();
            let result = blocking(move || -> kammi_core::Result<Value> {
                let plan = ledger.read().prepare_local_output(&b)?;
                match plan {
                    LocalOutputPlan::Done {
                        artifact_id,
                        event_id,
                    } => Ok(obj! {"artifact_id" => artifact_id, "event_id" => event_id}),
                    LocalOutputPlan::Copy {
                        expected,
                        spec,
                        path,
                        resolved,
                    } => {
                        // The large copy and hash take the writer lock only while bytes enter CAS.
                        let mut l = ledger.write();
                        let (identity, size) = l.put_file(&resolved)?;
                        if identity != expected {
                            return kammi_core::error::value_error(
                                "local output bytes differ from declared identity",
                            );
                        }
                        let event =
                            l.commit_local_output(&b, &spec, &path, &resolved, &identity, size)?;
                        Ok(obj! {"artifact_id" => identity, "event_id" => event})
                    }
                }
            })
            .await;
            result.map(json).map_err(local_error)
        }
        .await,
    )
}

async fn local_contact(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(async {
        let b = body_json(&body).map_err(|_| detail(StatusCode::LOCKED, "invalid request body"))?;
        actor_auth(&app, &headers, &b, "actor_id").map_err(locked_key)?;
        write(&app, StatusCode::LOCKED, move |l| {
            let event = l.local_contact(&b)?;
            Ok(obj! {"event_id" => event, "meaning" => "model process launched; contact conservatively possible"})
        })
        .await
    }.await)
}

async fn local_finish(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(async {
        let b = body_json(&body).map_err(|_| detail(StatusCode::LOCKED, "invalid request body"))?;
        actor_auth(&app, &headers, &b, "actor_id").map_err(locked_key)?;
        write(&app, StatusCode::LOCKED, move |l| {
            let (receipt_id, event, outcome) = l.local_finish(&b)?;
            Ok(obj! {"receipt_artifact_id" => receipt_id, "event_id" => event, "outcome" => outcome})
        })
        .await
    }.await)
}

/// A missing `actor_id` is a KeyError, which local routes report as 423; auth failures keep
/// their 401.
fn locked_key(response: Response) -> Response {
    if response.status() == StatusCode::BAD_REQUEST {
        detail(StatusCode::LOCKED, "'actor_id'")
    } else {
        response
    }
}

fn local_error(error: kammi_core::LedgerError) -> Response {
    match error {
        kammi_core::LedgerError::Io { .. } => detail(StatusCode::LOCKED, error.to_string()),
        other => ledger_error(other, StatusCode::LOCKED),
    }
}
