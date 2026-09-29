//! `/v2` routes of amendment v4: vocabulary activation and workspaces.
//!
//! A caller is the Library admin (the master token; the recorded actor is the request's
//! `actor`/`actor_id`, default `admin`) or an actor with its own bearer credential. Writes need
//! the flight gate open (except in acceptance fixture mode). A stale `expected_head` answers
//! 409 with the current HEAD; a v1-only store answers 400 until the journaled activation.

use std::collections::BTreeMap;

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use axum::routing::{get, post};
use axum::Router;
use kammi_core::ops_workspace::Principal;
use kammi_core::{obj, LedgerError};
use kammi_jcs::Value;

use crate::routes_custody::{read, write};
use crate::{
    authenticate, authenticate_actor, body_json, detail, done, field_str, header, App, AppState,
    HandlerResult,
};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v2/vocabulary/activate", post(activate))
        .route("/v2/workspaces", get(list).post(create))
        .route("/v2/workspaces/{workspace_id}", get(view))
        .route("/v2/workspaces/{workspace_id}/work", get(work))
        .route("/v2/workspaces/{workspace_id}/history", get(history))
        .route("/v2/workspaces/{workspace_id}/commands", post(command))
        .route("/v2/memory", post(remember))
        .route("/v2/recall", post(recall))
        .route("/v2/memory/{identity}", get(memory_get))
        .route("/v2/memory/{identity}/trace", get(memory_trace))
        .route("/v2/find", get(find))
}

/// Memory scope under v4: the actor's lab (as in v1), or `workspace:<id>` for its participants.
/// The admin may use any scope.
fn scope_allowed(ledger: &kammi_core::Ledger, who: &Caller, scope: &str) -> bool {
    match who {
        Caller::Admin(_) => true,
        Caller::Actor(actor) => match scope.strip_prefix("workspace:") {
            Some(ws) => ledger
                .workspace_readable(ws, Principal::Actor(actor))
                .is_ok(),
            None => ledger.state.authority.actor_lab(actor) == Some(scope),
        },
    }
}

fn memory_ready(app: &AppState) -> Result<(), Response> {
    if app.ledger.read().memory.is_none() {
        return Err(detail(
            StatusCode::SERVICE_UNAVAILABLE,
            "memory runtime is not configured",
        ));
    }
    Ok(())
}

fn strings(body: &Value, key: &str) -> Result<Vec<String>, Response> {
    match body.get(key) {
        None | Some(Value::Null) => Ok(Vec::new()),
        Some(_) => kammi_core::json::string_list(body, key)
            .map_err(|e| crate::ledger_error(e, StatusCode::BAD_REQUEST)),
    }
}

async fn remember(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let body = body_json(&body)?;
            let who = caller(&app, &headers, body.get("actor_id").and_then(Value::as_str))?;
            flight(&app)?;
            memory_ready(&app)?;
            let scope = field_str(&body, "scope")?.to_string();
            if !scope_allowed(&app.ledger.read(), &who, &scope) {
                return Err(detail(
                    StatusCode::FORBIDDEN,
                    "memory scope does not belong to actor",
                ));
            }
            let (kind, text, request_id) = (
                field_str(&body, "kind")?.to_string(),
                field_str(&body, "text")?.to_string(),
                field_str(&body, "request_id")?.to_string(),
            );
            let (refs, tags) = (strings(&body, "custody_refs")?, strings(&body, "tags")?);
            let confidence = body.get("confidence").and_then(Value::as_f64);
            let time = body.get("time").cloned().unwrap_or_else(|| obj! {});
            let actor = match &who {
                Caller::Admin(a) | Caller::Actor(a) => a.clone(),
            };
            v2_write(&app, move |l| {
                let (memory_id, event) = l.memory_record_v2(
                    &kind,
                    &scope,
                    &text,
                    &actor,
                    &refs,
                    &tags,
                    confidence,
                    &time,
                    &request_id,
                )?;
                Ok(obj! {"memory_id" => memory_id, "event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn recall(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let body = body_json(&body)?;
            let who = caller(&app, &headers, body.get("actor_id").and_then(Value::as_str))?;
            flight(&app)?;
            memory_ready(&app)?;
            let scope = field_str(&body, "scope")?.to_string();
            if !scope_allowed(&app.ledger.read(), &who, &scope) {
                return Err(detail(
                    StatusCode::FORBIDDEN,
                    "memory scope does not belong to actor",
                ));
            }
            let query = field_str(&body, "query")?.to_string();
            let request_id = field_str(&body, "request_id")?.to_string();
            let mode = body
                .get("mode")
                .and_then(Value::as_str)
                .unwrap_or("hybrid")
                .to_string();
            let limit = body.get("limit").and_then(Value::as_i64).unwrap_or(10);
            let grounded = body
                .get("grounded_only")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let include_superseded = body
                .get("include_superseded")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let exclude = strings(&body, "exclude_kinds")?;
            let seed = body
                .get("seed_memory")
                .and_then(Value::as_str)
                .map(str::to_string);
            let actor = match &who {
                Caller::Admin(a) | Caller::Actor(a) => a.clone(),
            };
            v2_write(&app, move |l| {
                l.memory_recall(
                    &query,
                    &scope,
                    &actor,
                    &request_id,
                    &mode,
                    limit,
                    grounded,
                    &exclude,
                    include_superseded,
                    seed.as_deref(),
                )
            })
            .await
        }
        .await,
    )
}

async fn memory_read(
    app: &App,
    headers: &HeaderMap,
    query: &BTreeMap<String, String>,
    identity: &str,
) -> Result<(), Response> {
    let who = caller(app, headers, query.get("actor_id").map(String::as_str))?;
    memory_ready(app)?;
    let ledger = app.ledger.read();
    let record = ledger
        .memory_get(identity)
        .map_err(|_| detail(StatusCode::NOT_FOUND, "unknown memory"))?;
    if !scope_allowed(&ledger, &who, record["scope"].as_str().unwrap_or_default()) {
        return Err(detail(
            StatusCode::FORBIDDEN,
            "memory scope does not belong to actor",
        ));
    }
    Ok(())
}

async fn memory_get(
    State(app): State<App>,
    Path(identity): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            memory_read(&app, &headers, &query, &identity).await?;
            v2_read(&app, move |l| l.memory_get(&identity)).await
        }
        .await,
    )
}

async fn memory_trace(
    State(app): State<App>,
    Path(identity): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            memory_read(&app, &headers, &query, &identity).await?;
            v2_read(&app, move |l| l.memory_trace(&identity)).await
        }
        .await,
    )
}

async fn find(
    State(app): State<App>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let who = caller(&app, &headers, query.get("actor_id").map(String::as_str))?;
            let q = query.get("q").cloned().unwrap_or_default();
            v2_read(&app, move |l| l.find(&q, who.principal())).await
        }
        .await,
    )
}

/// Who is calling: admin (master token) or an authenticated actor.
#[derive(Clone)]
enum Caller {
    Admin(String),
    Actor(String),
}

impl Caller {
    fn principal(&self) -> Principal<'_> {
        match self {
            Caller::Admin(a) => Principal::Admin(a),
            Caller::Actor(a) => Principal::Actor(a),
        }
    }
}

fn is_admin(app: &AppState, headers: &HeaderMap) -> bool {
    let expected = format!("Bearer {}", app.token);
    header(headers, "authorization").is_some_and(|given| {
        kammi_core::state::constant_time_eq(given.as_bytes(), expected.as_bytes())
    })
}

fn caller(app: &AppState, headers: &HeaderMap, actor: Option<&str>) -> Result<Caller, Response> {
    if is_admin(app, headers) {
        return Ok(Caller::Admin(actor.unwrap_or("admin").to_string()));
    }
    let actor = actor.ok_or_else(|| {
        detail(
            StatusCode::UNAUTHORIZED,
            "actor_id required with an actor credential",
        )
    })?;
    authenticate_actor(&app.ledger.read(), headers, actor)?;
    Ok(Caller::Actor(actor.to_string()))
}

fn flight(app: &AppState) -> Result<(), Response> {
    if !app.acceptance_mode && !app.ledger.read().flight_open() {
        return Err(detail(
            StatusCode::LOCKED,
            "Library source acceptance pending",
        ));
    }
    Ok(())
}

/// Maps v4 errors: a stale HEAD is 409, an unknown workspace 404, authorization 403.
fn v2_error(error: LedgerError) -> Response {
    match error {
        LedgerError::Conflict(body) => detail(StatusCode::CONFLICT, body),
        LedgerError::Key(key) => detail(StatusCode::NOT_FOUND, format!("unknown workspace {key}")),
        LedgerError::Value(message)
            if message.contains("may not")
                || message.contains("not a participant")
                || message.contains("only the Library admin")
                || message.contains("attaches only itself") =>
        {
            detail(StatusCode::FORBIDDEN, message)
        }
        other => crate::ledger_error(other, StatusCode::BAD_REQUEST),
    }
}

async fn v2_write(
    app: &App,
    work: impl FnOnce(&mut kammi_core::Ledger) -> kammi_core::Result<Value> + Send + 'static,
) -> HandlerResult {
    let ledger = app.ledger.clone();
    crate::blocking(move || work(&mut ledger.write()))
        .await
        .map(crate::json)
        .map_err(v2_error)
}

async fn v2_read(
    app: &App,
    work: impl FnOnce(&kammi_core::Ledger) -> kammi_core::Result<Value> + Send + 'static,
) -> HandlerResult {
    let ledger = app.ledger.clone();
    crate::blocking(move || work(&ledger.read()))
        .await
        .map(crate::json)
        .map_err(v2_error)
}

async fn activate(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            flight(&app)?;
            let mut body = body_json(&body)?;
            let request_id = field_str(&body, "request_id")?.to_string();
            let actor = body
                .get("actor")
                .and_then(Value::as_str)
                .unwrap_or("admin")
                .to_string();
            if let Some(map) = body.as_object_mut() {
                map.remove("request_id");
                map.remove("actor");
            }
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.activate_vocabulary(body, &actor, &request_id)?;
                Ok(obj! {"event_id" => event, "vocabulary_v4" => true})
            })
            .await
        }
        .await,
    )
}

async fn list(
    State(app): State<App>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let who = caller(&app, &headers, query.get("actor_id").map(String::as_str))?;
            read(&app, StatusCode::BAD_REQUEST, move |l| {
                Ok(l.workspace_list(who.principal()))
            })
            .await
        }
        .await,
    )
}

async fn create(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            flight(&app)?;
            let body = body_json(&body)?;
            let request_id = field_str(&body, "request_id")?.to_string();
            let actor = body
                .get("actor")
                .and_then(Value::as_str)
                .unwrap_or("admin")
                .to_string();
            let payload = obj! {
                "workspace_id" => body.get("workspace_id").cloned().unwrap_or(Value::Null),
                "expected_head" => "genesis",
                "title" => body.get("title").cloned().unwrap_or(Value::Null),
                "lab" => body.get("lab").cloned().unwrap_or(Value::Null),
                "owners" => body.get("owners").cloned().unwrap_or(Value::Null),
            };
            v2_write(&app, move |l| {
                l.workspace_command(
                    "WorkspaceCreated",
                    payload,
                    Principal::Admin(&actor),
                    &request_id,
                )
            })
            .await
        }
        .await,
    )
}

async fn command(
    State(app): State<App>,
    Path(workspace_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let body = body_json(&body)?;
            let who = caller(&app, &headers, body.get("actor_id").and_then(Value::as_str))?;
            flight(&app)?;
            let kind = field_str(&body, "type")?.to_string();
            if kind == "WorkspaceCreated" || !kind.starts_with("Workspace") {
                return Err(detail(
                    StatusCode::BAD_REQUEST,
                    "type must be a workspace event other than WorkspaceCreated",
                ));
            }
            let request_id = field_str(&body, "request_id")?.to_string();
            let mut payload = body
                .get("payload")
                .cloned()
                .ok_or_else(|| detail(StatusCode::BAD_REQUEST, "'payload'"))?;
            match payload.get("workspace_id").and_then(Value::as_str) {
                None => {
                    if let Some(map) = payload.as_object_mut() {
                        map.insert("workspace_id".into(), Value::from(workspace_id.clone()));
                    }
                }
                Some(given) if given == workspace_id => {}
                Some(_) => {
                    return Err(detail(
                        StatusCode::BAD_REQUEST,
                        "payload workspace_id differs from the path",
                    ))
                }
            }
            v2_write(&app, move |l| {
                l.workspace_command(&kind, payload, who.principal(), &request_id)
            })
            .await
        }
        .await,
    )
}

async fn readable(
    app: &App,
    headers: &HeaderMap,
    query: &BTreeMap<String, String>,
    workspace_id: &str,
) -> Result<Caller, Response> {
    let who = caller(app, headers, query.get("actor_id").map(String::as_str))?;
    let (id, check) = (workspace_id.to_string(), who.clone());
    v2_read(app, move |l| {
        l.workspace_readable(&id, check.principal())
            .map(|_| Value::Null)
    })
    .await?;
    Ok(who)
}

async fn view(
    State(app): State<App>,
    Path(workspace_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            readable(&app, &headers, &query, &workspace_id).await?;
            v2_read(&app, move |l| l.workspace_view(&workspace_id)).await
        }
        .await,
    )
}

async fn work(
    State(app): State<App>,
    Path(workspace_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            readable(&app, &headers, &query, &workspace_id).await?;
            v2_read(&app, move |l| l.work_packet(&workspace_id)).await
        }
        .await,
    )
}

async fn history(
    State(app): State<App>,
    Path(workspace_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            readable(&app, &headers, &query, &workspace_id).await?;
            let after = query.get("after").cloned();
            let limit = query
                .get("limit")
                .and_then(|l| l.parse().ok())
                .unwrap_or(200usize)
                .min(1000);
            v2_read(&app, move |l| {
                l.workspace_history(&workspace_id, after.as_deref(), limit)
            })
            .await
        }
        .await,
    )
}
