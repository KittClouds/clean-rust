//! Authorization, leases, exposure and scoped custody routes (`api.py`, `surface_api.py`).

use axum::body::{Body, Bytes};
use axum::extract::{Path, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::Router;
use kammi_core::json::{get as jget, get_str};
use kammi_core::obj;
use kammi_jcs::Value;

use crate::routes_custody::{read, write};
use crate::{
    actor_auth, authenticate, blocking, body_json, detail, done, field_str, header, ledger_error,
    require_scope, App,
};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v1/authorize", post(authorize))
        .route("/v1/leases/acquire", post(acquire_lease))
        .route("/v1/leases/{lease_id}/renew", post(renew_lease))
        .route("/v1/leases/{lease_id}/release", post(release_lease))
        .route("/v1/leases/{lease_id}/validate", post(validate_lease))
        .route("/v1/resources/{resource_id}/lease", get(lease_status))
        .route("/v1/specs/bind", post(bind_spec))
        .route("/v1/seals/{root}/verify-for-run", post(verify_for_run))
        .route("/v1/panels/{panel_id}/open", post(open_panel))
        .route("/v1/panels/{panel_id}/exposure", get(exposure_report))
        .route(
            "/v1/acceptance/stages/authorize",
            post(acceptance_authorize),
        )
        .route("/v1/policy/check", post(policy_check))
}

async fn authorize(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(async {
        let b = if body.is_empty() { Value::Object(Default::default()) } else { body_json(&body)? };
        let master = format!("Bearer {}", app.token);
        if header(&headers, "authorization") == Some(master.as_str()) {
            authenticate(&app, &headers)?;
        } else {
            let actor = b.get("actor_id").and_then(Value::as_str).unwrap_or("");
            crate::authenticate_actor(&app.ledger.read(), &headers, actor)?;
        }
        let flight = app.ledger.read().flight_state();
        if flight["state"] != "OPEN" {
            return Err(detail(
                StatusCode::LOCKED,
                obj! {"decision" => "DENIED", "flight_state" => flight, "reason" => "current immutable LibraryAcceptanceV1 required"},
            ));
        }
        let (actor, run, stage) = (field_str(&b, "actor_id")?.to_string(), field_str(&b, "run_id")?.to_string(), field_str(&b, "stage_id")?.to_string());
        require_scope(&app.ledger.read(), &headers, &actor, "authorize_stage", &run, &stage)?;
        let acceptance = flight["acceptance_identity"].clone();
        write(&app, StatusCode::BAD_REQUEST, move |l| {
            let (event, receipt) = l.authorize_stage(&run, &stage, &actor, get_str(&b, "expires_utc")?, get_str(&b, "request_id")?)?;
            Ok(obj! {"event_id" => event, "receipt" => receipt, "library_acceptance" => acceptance})
        })
        .await
    }.await)
}

async fn acquire_lease(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (event, receipt) = l.acquire_lease(
                    get_str(&b, "resource_id")?,
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "actor_id")?,
                    &token,
                    get_str(&b, "purpose")?,
                    jget(&b, "ttl_seconds")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event, "receipt" => receipt})
            })
            .await
        }
        .await,
    )
}

async fn renew_lease(
    State(app): State<App>,
    Path(lease_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.renew_lease(
                    &lease_id,
                    jget(&b, "fencing_token")?,
                    get_str(&b, "actor_id")?,
                    &token,
                    jget(&b, "ttl_seconds")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn release_lease(
    State(app): State<App>,
    Path(lease_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.release_lease(
                    &lease_id,
                    jget(&b, "fencing_token")?,
                    get_str(&b, "actor_id")?,
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

async fn validate_lease(
    State(app): State<App>,
    Path(lease_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            actor_auth(&app, &headers, &b, "actor_id")?;
            read(&app, StatusCode::BAD_REQUEST, move |l| {
                let valid = l.lease_validate(
                    &lease_id,
                    get_str(&b, "resource_id")?,
                    jget(&b, "fencing_token")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "run_id")?,
                )?;
                Ok(obj! {"valid" => valid, "lease_id" => lease_id.clone()})
            })
            .await
        }
        .await,
    )
}

async fn lease_status(
    State(app): State<App>,
    Path(resource_id): Path<String>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                l.state.leases.report(&resource_id, l.now())
            })
            .await
        }
        .await,
    )
}

async fn bind_spec(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            scoped(&app, &headers, &b, "bind_spec")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.bind_spec(
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "spec_kind")?,
                    get_str(&b, "artifact_id")?,
                    get_str(&b, "seal_root")?,
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

async fn verify_for_run(
    State(app): State<App>,
    Path(root): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            scoped(&app, &headers, &b, "bind_spec")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let event = l.record_seal_verification(
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    &root,
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

/// `require_scope(authorization, body["actor_id"], action, body["run_id"], body["stage_id"])`.
fn scoped(app: &App, headers: &HeaderMap, b: &Value, action: &str) -> Result<String, Response> {
    let (actor, run, stage) = (
        field_str(b, "actor_id")?,
        field_str(b, "run_id")?,
        field_str(b, "stage_id")?,
    );
    require_scope(&app.ledger.read(), headers, actor, action, run, stage)
}

async fn open_panel(
    State(app): State<App>,
    Path(panel_id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            let token = actor_auth(&app, &headers, &b, "actor_id")?;
            let ledger = app.ledger.clone();
            let outcome = blocking(move || {
                let mut l = ledger.write();
                l.open_panel(
                    &panel_id,
                    get_str(&b, "purpose")?,
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "actor_id")?,
                    &token,
                    get_str(&b, "authorization_id")?,
                    get_str(&b, "request_id")?,
                )
            })
            .await
            .map_err(|e| ledger_error(e, StatusCode::BAD_REQUEST))?;
            match outcome.data {
                None => Err(detail(
                    StatusCode::FORBIDDEN,
                    obj! {"event_id" => outcome.event_id, "receipt" => outcome.receipt},
                )),
                Some(data) => {
                    let mut response = (StatusCode::OK, Body::from(data)).into_response();
                    let h = response.headers_mut();
                    h.insert(
                        "content-type",
                        HeaderValue::from_static("application/octet-stream"),
                    );
                    h.insert(
                        "x-exposure-event",
                        HeaderValue::from_str(&outcome.event_id).unwrap(),
                    );
                    Ok(response)
                }
            }
        }
        .await,
    )
}

async fn exposure_report(
    State(app): State<App>,
    Path(panel_id): Path<String>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            authenticate(&app, &headers)?;
            read(&app, StatusCode::NOT_FOUND, move |l| {
                l.state.exposure.report(&panel_id)
            })
            .await
        }
        .await,
    )
}

async fn acceptance_authorize(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            if !app.acceptance_mode {
                return Err(detail(
                    StatusCode::LOCKED,
                    "acceptance fixture mode disabled",
                ));
            }
            let b = body_json(&body)?;
            actor_auth(&app, &headers, &b, "actor_id")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let run = get_str(&b, "run_id")?;
                if !run.starts_with("acceptance.") {
                    return kammi_core::error::value_error(
                        "acceptance authorization requires isolated fixture run",
                    );
                }
                let (event, receipt) = l.authorize_stage(
                    run,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "actor_id")?,
                    get_str(&b, "expires_utc")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event, "receipt" => receipt})
            })
            .await
        }
        .await,
    )
}

async fn policy_check(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
    done(
        async {
            let b = body_json(&body)?;
            scoped(&app, &headers, &b, "authorize_stage")?;
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (event, receipt) = l.policy_check(
                    get_str(&b, "actor_id")?,
                    get_str(&b, "run_id")?,
                    get_str(&b, "stage_id")?,
                    get_str(&b, "request_id")?,
                )?;
                Ok(obj! {"event_id" => event, "receipt" => receipt})
            })
            .await
        }
        .await,
    )
}
