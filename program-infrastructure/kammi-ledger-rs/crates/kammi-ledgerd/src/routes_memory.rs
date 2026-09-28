//! Memory routes (`memory_api.py`): actor scope must equal the actor's lab.

use std::collections::BTreeMap;

use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use axum::routing::{get, post};
use axum::Router;
use kammi_core::json::get_str;
use kammi_core::{obj, Ledger, LedgerError};
use kammi_jcs::Value;

use crate::routes_custody::{read, write};
use crate::{authenticate_actor, body_json, detail, done, field_str, missing, App};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v1/memory", post(record))
        .route("/v1/memory/search", post(search))
        .route("/v1/memory/supersede", post(supersede))
        .route("/v1/memory/{identity}", get(get_memory))
        .route("/v1/memory/{identity}/trace", get(trace))
        .route("/v1/memory/{identity}/neighbors", get(neighbors))
}

fn unconfigured() -> Response {
    detail(
        StatusCode::SERVICE_UNAVAILABLE,
        "memory runtime is not configured",
    )
}

/// `actor_scope`: authenticates the actor and refuses a scope other than its lab.
fn actor_scope(
    ledger: &Ledger,
    headers: &HeaderMap,
    actor: &str,
    scope: Option<&str>,
) -> Result<(), Response> {
    authenticate_actor(ledger, headers, actor)?;
    if let Some(scope) = scope {
        if ledger.state.authority.actor_lab(actor) != Some(scope) {
            return Err(detail(
                StatusCode::FORBIDDEN,
                "memory scope does not belong to actor",
            ));
        }
    }
    Ok(())
}

/// `service().get(identity)` with an unknown record reported as 404 (Python raises a 500).
fn record_scope(ledger: &Ledger, identity: &str) -> Result<String, Response> {
    if ledger.memory.is_none() {
        return Err(unconfigured());
    }
    let record = ledger
        .memory_get(identity)
        .map_err(|_| detail(StatusCode::NOT_FOUND, "unknown memory"))?;
    Ok(record["scope"].as_str().unwrap_or("").to_string())
}

fn strings_or_empty(body: &Value, key: &str) -> kammi_core::Result<Vec<String>> {
    match body.get(key) {
        None => Ok(Vec::new()),
        Some(_) => kammi_core::json::string_list(body, key),
    }
}

fn optional<'a>(body: &'a Value, key: &str) -> Option<&'a Value> {
    body.get(key).filter(|v| !v.is_null())
}

fn bool_or(body: &Value, key: &str, default: bool) -> kammi_core::Result<bool> {
    match body.get(key) {
        None => Ok(default),
        Some(v) => v
            .as_bool()
            .ok_or_else(|| LedgerError::Value(format!("{key} must be a boolean"))),
    }
}

async fn record(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            {
                let ledger = app.ledger.read();
                actor_scope(
                    &ledger,
                    &headers,
                    field_str(&b, "actor_id")?,
                    Some(field_str(&b, "scope")?),
                )?;
                if ledger.memory.is_none() {
                    return Err(unconfigured());
                }
            }
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let confidence =
                    match optional(&b, "confidence") {
                        None => None,
                        Some(v) => Some(v.as_f64().ok_or_else(|| {
                            LedgerError::Value("invalid memory confidence".into())
                        })?),
                    };
                let (memory_id, event) = l.memory_record(
                    get_str(&b, "kind")?,
                    get_str(&b, "scope")?,
                    get_str(&b, "text")?,
                    get_str(&b, "actor_id")?,
                    &strings_or_empty(&b, "custody_refs")?,
                    &strings_or_empty(&b, "tags")?,
                    confidence,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"memory_id" => memory_id, "event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn search(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            {
                let ledger = app.ledger.read();
                actor_scope(
                    &ledger,
                    &headers,
                    field_str(&b, "actor_id")?,
                    Some(field_str(&b, "scope")?),
                )?;
                if ledger.memory.is_none() {
                    return Err(unconfigured());
                }
            }
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let mode = match b.get("mode") {
                    None => "hybrid",
                    Some(v) => v.as_str().ok_or_else(|| {
                        LedgerError::Value("invalid memory search mode or limit".into())
                    })?,
                };
                let limit = match b.get("limit") {
                    None => 10,
                    Some(v) => v.as_i64().ok_or_else(|| {
                        LedgerError::Value("invalid memory search mode or limit".into())
                    })?,
                };
                let seed = match optional(&b, "seed_memory") {
                    None => None,
                    Some(v) => Some(
                        v.as_str()
                            .ok_or_else(|| LedgerError::Value("invalid seed memory".into()))?,
                    ),
                };
                l.memory_search(
                    get_str(&b, "query")?,
                    get_str(&b, "scope")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "request_id")?,
                    mode,
                    limit,
                    bool_or(&b, "grounded_only", false)?,
                    &strings_or_empty(&b, "exclude_kinds")?,
                    bool_or(&b, "include_superseded", false)?,
                    seed,
                )
            })
            .await
        }
        .await,
    )
}

fn actor_query(query: &BTreeMap<String, String>) -> Result<String, Response> {
    query
        .get("actor_id")
        .cloned()
        .ok_or_else(|| missing("query", "actor_id"))
}

/// Shared prologue of the GET routes: record exists, then the actor may see its scope.
fn scoped_read(
    app: &App,
    headers: &HeaderMap,
    identity: &str,
    actor: &str,
) -> Result<(), Response> {
    let ledger = app.ledger.read();
    let scope = record_scope(&ledger, identity)?;
    actor_scope(&ledger, headers, actor, Some(&scope))
}

async fn get_memory(
    State(app): State<App>,
    Path(identity): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            scoped_read(&app, &headers, &identity, &actor)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                l.memory_get(&identity)
            })
            .await
        }
        .await,
    )
}

async fn trace(
    State(app): State<App>,
    Path(identity): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            scoped_read(&app, &headers, &identity, &actor)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                l.memory_trace(&identity)
            })
            .await
        }
        .await,
    )
}

async fn neighbors(
    State(app): State<App>,
    Path(identity): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            scoped_read(&app, &headers, &identity, &actor)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                Ok(obj! {"results" => l.memory_neighbors(&identity)?})
            })
            .await
        }
        .await,
    )
}

async fn supersede(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            {
                let ledger = app.ledger.read();
                let old_scope = record_scope(&ledger, field_str(&b, "old_id")?)?;
                let new_scope = record_scope(&ledger, field_str(&b, "new_id")?)?;
                let actor = field_str(&b, "actor_id")?;
                actor_scope(&ledger, &headers, actor, Some(&old_scope))?;
                actor_scope(&ledger, &headers, actor, Some(&new_scope))?;
            }
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.memory_supersede(
                    get_str(&b, "old_id")?,
                    get_str(&b, "new_id")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}
