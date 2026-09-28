//! Owner-scoped Phoenix vault routes (`vault_api.py`).

use std::collections::BTreeMap;
use std::path::PathBuf;

use axum::body::{Body, Bytes};
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::Router;
use base64::Engine;
use kammi_core::json::{get as jget, get_str};
use kammi_core::ops_vault::{
    pack, unpack, MAX_PACKAGE_BYTES, MAX_STREAM_ASSET_BYTES, MAX_STREAM_SOURCE_BYTES,
};
use kammi_core::{obj, LedgerError};
use kammi_jcs::Value;

use crate::routes_custody::write;
use crate::{
    authenticate_actor, blocking, body_json, detail, done, field_str, header, internal, json,
    ledger_error, missing, staging_file, stream_to_file, App, AppState,
};

pub fn routes() -> Router<App> {
    Router::new()
        .route("/v1/vaults", post(create))
        .route("/v1/vaults/source", post(source))
        .route("/v1/vaults/source-stream", post(source_stream))
        .route("/v1/vaults/asset", post(asset))
        .route("/v1/vaults/asset-stream", post(asset_stream))
        .route("/v1/vaults/package", post(import_package))
        .route("/v1/vaults/generation", post(generation))
        .route("/v1/vaults/reader", post(reader))
        .route("/v1/vaults/product-primary", post(product_primary))
        .route("/v1/vaults/{vault_id}", get(view))
        .route("/v1/vaults/{vault_id}/package", get(export_package))
        .route("/v1/vaults/{vault_id}/sources/{source_id}", get(get_source))
        .route(
            "/v1/vaults/{vault_id}/sources/{source_id}/bytes",
            get(get_source_bytes),
        )
        .route("/v1/vaults/{vault_id}/assets/{artifact_id}", get(get_asset))
}

/// `writer`: actor bearer plus the flight gate (unless acceptance fixture mode).
fn writer(app: &AppState, headers: &HeaderMap, actor: &str) -> Result<(), Response> {
    let ledger = app.ledger.read();
    authenticate_actor(&ledger, headers, actor)?;
    if !app.acceptance_mode && !ledger.flight_open() {
        return Err(detail(
            StatusCode::LOCKED,
            "Library source acceptance pending",
        ));
    }
    Ok(())
}

fn decode(content: &str) -> kammi_core::Result<Vec<u8>> {
    base64::engine::general_purpose::STANDARD
        .decode(content)
        .map_err(|_| LedgerError::Value("invalid base64 vault bytes".into()))
}

/// JSON writer route: parse, `writer(body["actor_id"])`, then the ledger call; client errors 400.
macro_rules! vault_write {
    ($name:ident, |$l:ident, $b:ident| $body:expr) => {
        async fn $name(State(app): State<App>, headers: HeaderMap, body: Bytes) -> Response {
            done(
                async {
                    let $b = body_json(&body)?;
                    writer(&app, &headers, field_str(&$b, "actor_id")?)?;
                    write(&app, StatusCode::BAD_REQUEST, move |$l| $body).await
                }
                .await,
            )
        }
    };
}

vault_write!(create, |l, b| {
    let event = l.vault_create(
        get_str(&b, "vault_id")?,
        get_str(&b, "actor_id")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"vault_id" => get_str(&b, "vault_id")?, "event_id" => event})
});

vault_write!(source, |l, b| {
    let content = decode(get_str(&b, "content_base64")?)?;
    let (receipt, event) = l.vault_commit_source(
        get_str(&b, "vault_id")?,
        get_str(&b, "source_id")?,
        jget(&b, "base_revision")?,
        &content,
        get_str(&b, "actor_id")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"source" => receipt, "event_id" => event})
});

vault_write!(asset, |l, b| {
    let content = decode(get_str(&b, "content_base64")?)?;
    let (artifact_id, event) = l.vault_stage_asset(
        get_str(&b, "vault_id")?,
        &content,
        get_str(&b, "kind")?,
        get_str(&b, "actor_id")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"artifact_id" => artifact_id, "event_id" => event})
});

vault_write!(generation, |l, b| {
    let (receipt, event) = l.vault_select_generation(
        get_str(&b, "vault_id")?,
        jget(&b, "source_epoch")?,
        jget(&b, "generation_id")?,
        get_str(&b, "manifest_artifact_id")?,
        jget(&b, "asset_ids")?,
        get_str(&b, "actor_id")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"generation" => receipt, "event_id" => event})
});

vault_write!(reader, |l, b| {
    let (receipt, event) = l.vault_set_reader(
        get_str(&b, "vault_id")?,
        get_str(&b, "source_id")?,
        jget(&b, "revision")?,
        jget(&b, "offset")?,
        get_str(&b, "actor_id")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"reader" => receipt, "event_id" => event})
});

vault_write!(product_primary, |l, b| {
    let (receipt, event) = l.vault_select_product_primary(
        get_str(&b, "vault_id")?,
        jget(&b, "source_epoch")?,
        get_str(&b, "receipt_artifact_id")?,
        get_str(&b, "actor_id")?,
        get_str(&b, "request_id")?,
    )?;
    Ok(obj! {"product_authority" => receipt, "event_id" => event})
});

fn nonempty<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    header(headers, name).filter(|v| !v.is_empty())
}

/// Removes a staging path when dropped (after the stream or on any error).
struct Cleanup(PathBuf);

impl Drop for Cleanup {
    fn drop(&mut self) {
        if self.0.is_dir() {
            let _ = std::fs::remove_dir_all(&self.0);
        } else {
            let _ = std::fs::remove_file(&self.0);
        }
    }
}

async fn source_stream(State(app): State<App>, headers: HeaderMap, body: Body) -> Response {
    done(
        async {
            let (Some(actor), Some(vault), Some(source), Some(base), Some(request)) = (
                nonempty(&headers, "x-actor-id"),
                nonempty(&headers, "x-vault-id"),
                nonempty(&headers, "x-source-id"),
                header(&headers, "x-base-revision"),
                nonempty(&headers, "x-request-id"),
            ) else {
                return Err(detail(
                    StatusCode::BAD_REQUEST,
                    "vault source stream headers required",
                ));
            };
            let (actor, vault, source, request) = (
                actor.to_string(),
                vault.to_string(),
                source.to_string(),
                request.to_string(),
            );
            writer(&app, &headers, &actor)?;
            let base: i64 = base.trim().parse().map_err(|_| {
                detail(
                    StatusCode::BAD_REQUEST,
                    format!("invalid literal for int() with base 10: '{base}'"),
                )
            })?;
            app.ledger
                .read()
                .vault(&vault, &actor)
                .map_err(|e| ledger_error(e, StatusCode::BAD_REQUEST))?;
            let temp = staging_file(&app, "vault-source");
            let _cleanup = Cleanup(temp.clone());
            stream_to_file(
                body,
                &temp,
                MAX_STREAM_SOURCE_BYTES,
                "vault source exceeds stream limit",
            )
            .await?;
            let path = temp.clone();
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (receipt, event) = l.vault_commit_source_file(
                    &vault,
                    &source,
                    &Value::from(base),
                    &path,
                    &actor,
                    &request,
                )?;
                Ok(obj! {"source" => receipt, "event_id" => event})
            })
            .await
        }
        .await,
    )
}

async fn asset_stream(State(app): State<App>, headers: HeaderMap, body: Body) -> Response {
    done(
        async {
            let (Some(actor), Some(vault), Some(kind), Some(request)) = (
                nonempty(&headers, "x-actor-id"),
                nonempty(&headers, "x-vault-id"),
                nonempty(&headers, "x-kind"),
                nonempty(&headers, "x-request-id"),
            ) else {
                return Err(detail(
                    StatusCode::BAD_REQUEST,
                    "vault stream headers required",
                ));
            };
            let (actor, vault, kind, request) = (
                actor.to_string(),
                vault.to_string(),
                kind.to_string(),
                request.to_string(),
            );
            writer(&app, &headers, &actor)?;
            app.ledger
                .read()
                .vault(&vault, &actor)
                .map_err(|e| ledger_error(e, StatusCode::FORBIDDEN))?;
            let temp = staging_file(&app, "vault-upload");
            let _cleanup = Cleanup(temp.clone());
            let count = stream_to_file(
                body,
                &temp,
                MAX_STREAM_ASSET_BYTES,
                "vault asset exceeds stream limit",
            )
            .await?;
            let path = temp.clone();
            write(&app, StatusCode::BAD_REQUEST, move |l| {
                let (artifact_id, event, _) =
                    l.vault_stage_file(&vault, &path, &kind, &actor, &request)?;
                Ok(obj! {"artifact_id" => artifact_id, "event_id" => event, "byte_count" => count})
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

/// Streams a file to the client and deletes `cleanup` once the body is dropped.
async fn file_response(path: PathBuf, cleanup: Option<Cleanup>) -> Result<Response, Response> {
    use futures_util::StreamExt;
    let file = tokio::fs::File::open(&path).await.map_err(internal)?;
    let size = file.metadata().await.map_err(internal)?.len();
    let stream = tokio_util::io::ReaderStream::with_capacity(file, 1 << 20);
    let body = Body::from_stream(stream.map(move |chunk| {
        let _ = &cleanup;
        chunk
    }));
    let mut response = (StatusCode::OK, body).into_response();
    response
        .headers_mut()
        .insert("content-length", HeaderValue::from(size));
    Ok(response)
}

async fn export_package(
    State(app): State<App>,
    Path(vault_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            authenticate_actor(&app.ledger.read(), &headers, &actor)?;
            // The export directory must be outside the Library, so it lives in the system temp dir.
            let work = std::env::temp_dir().join(format!(
                "vault-package-{}",
                staging_file(&app, "x")
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
            ));
            std::fs::create_dir_all(&work).map_err(internal)?;
            let cleanup = Cleanup(work.clone());
            let ledger = app.ledger.clone();
            let (vault_dir, archive) = (work.join("vault"), work.join("vault.zip"));
            let archive_path = archive.clone();
            let root = blocking(move || -> Result<String, Response> {
                let root = ledger
                    .read()
                    .vault_export(&vault_id, &actor, &vault_dir)
                    .map_err(|e| {
                        if e.is_client() {
                            detail(StatusCode::NOT_FOUND, "vault unavailable")
                        } else {
                            internal(e)
                        }
                    })?;
                pack(&vault_dir, &archive_path).map_err(internal)?;
                Ok(root)
            })
            .await?;
            let mut response = file_response(archive, Some(cleanup)).await?;
            let h = response.headers_mut();
            h.insert("content-type", HeaderValue::from_static("application/zip"));
            h.insert(
                "x-vault-package-root",
                HeaderValue::from_str(&root).map_err(internal)?,
            );
            Ok(response)
        }
        .await,
    )
}

async fn import_package(State(app): State<App>, headers: HeaderMap, body: Body) -> Response {
    done(
        async {
            let (Some(actor), Some(root)) = (
                nonempty(&headers, "x-actor-id"),
                nonempty(&headers, "x-package-root"),
            ) else {
                return Err(detail(
                    StatusCode::BAD_REQUEST,
                    "vault import headers required",
                ));
            };
            let (actor, root) = (actor.to_string(), root.to_string());
            writer(&app, &headers, &actor)?;
            let work = staging_file(&app, "vault-import");
            std::fs::create_dir_all(&work).map_err(internal)?;
            let _cleanup = Cleanup(work.clone());
            let archive = work.join("vault.zip");
            stream_to_file(
                body,
                &archive,
                MAX_PACKAGE_BYTES,
                "vault archive exceeds limit",
            )
            .await?;
            let ledger = app.ledger.clone();
            let package_root = root.clone();
            let view = blocking(move || -> kammi_core::Result<Value> {
                let package = work.join("vault");
                unpack(&archive, &package)?;
                ledger.write().vault_import(&package, &actor, &root)
            })
            .await
            .map_err(|e| detail(StatusCode::BAD_REQUEST, e.detail()))?;
            Ok(json(obj! {"vault" => view, "package_root" => package_root}))
        }
        .await,
    )
}

/// GET prologue: actor bearer, then the call; every client error becomes 404.
async fn scoped_get<T: Send + 'static>(
    app: &App,
    headers: &HeaderMap,
    actor: &str,
    work: impl FnOnce(&kammi_core::Ledger) -> kammi_core::Result<T> + Send + 'static,
) -> Result<T, Response> {
    authenticate_actor(&app.ledger.read(), headers, actor)?;
    let ledger = app.ledger.clone();
    blocking(move || work(&ledger.read()))
        .await
        .map_err(|e| ledger_error(e, StatusCode::NOT_FOUND))
}

async fn view(
    State(app): State<App>,
    Path(vault_id): Path<String>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            let who = actor.clone();
            scoped_get(&app, &headers, &actor, move |l| {
                l.vault_view(&vault_id, &who)
            })
            .await
            .map(json)
        }
        .await,
    )
}

async fn get_source(
    State(app): State<App>,
    Path((vault_id, source_id)): Path<(String, String)>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(async {
        let actor = actor_query(&query)?;
        let who = actor.clone();
        let (receipt, content) = scoped_get(&app, &headers, &actor, move |l| l.vault_source(&vault_id, &source_id, &who)).await?;
        Ok(json(obj! {"source" => receipt, "content_base64" => base64::engine::general_purpose::STANDARD.encode(content)}))
    }.await)
}

async fn get_source_bytes(
    State(app): State<App>,
    Path((vault_id, source_id)): Path<(String, String)>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            let who = actor.clone();
            let (receipt, content) = scoped_get(&app, &headers, &actor, move |l| {
                l.vault_source(&vault_id, &source_id, &who)
            })
            .await?;
            let revision = match &receipt["revision"] {
                Value::Number(n) => n.to_string(),
                other => other.to_string(),
            };
            let mut response = (StatusCode::OK, Body::from(content)).into_response();
            let h = response.headers_mut();
            h.insert(
                "content-type",
                HeaderValue::from_static("application/octet-stream"),
            );
            h.insert(
                "x-artifact-id",
                HeaderValue::from_str(receipt["artifact_id"].as_str().unwrap_or(""))
                    .map_err(internal)?,
            );
            h.insert(
                "x-source-revision",
                HeaderValue::from_str(&revision).map_err(internal)?,
            );
            Ok(response)
        }
        .await,
    )
}

enum AssetBody {
    Loose(PathBuf),
    Bytes(Vec<u8>),
}

async fn get_asset(
    State(app): State<App>,
    Path((vault_id, artifact_id)): Path<(String, String)>,
    Query(query): Query<BTreeMap<String, String>>,
    headers: HeaderMap,
) -> Response {
    done(
        async {
            let actor = actor_query(&query)?;
            let (who, id) = (actor.clone(), artifact_id.clone());
            // `vault_asset` re-hashes the object before any byte leaves the daemon.
            let (asset, size) = scoped_get(&app, &headers, &actor, move |l| {
                let (identity, size) = l.vault_asset(&vault_id, &id, &who)?;
                let loose = l.store.objects.loose_path(&identity);
                if loose.is_file() {
                    Ok((AssetBody::Loose(loose), size))
                } else {
                    Ok((AssetBody::Bytes(l.object_bytes(&id)?), size))
                }
            })
            .await?;
            let mut response = match asset {
                AssetBody::Loose(path) => file_response(path, None).await?,
                AssetBody::Bytes(bytes) => (StatusCode::OK, Body::from(bytes)).into_response(),
            };
            let h = response.headers_mut();
            h.insert(
                "content-type",
                HeaderValue::from_static("application/octet-stream"),
            );
            h.insert(
                "x-artifact-id",
                HeaderValue::from_str(&artifact_id).map_err(internal)?,
            );
            h.insert("content-length", HeaderValue::from(size));
            Ok(response)
        }
        .await,
    )
}
