use std::{
    collections::BTreeMap,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use northstar_rl_core::{Digest, identity};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use zeroize::Zeroize;

use crate::{
    BROKER_ACCOUNT_SNAPSHOT_V1, BROKER_INSTRUMENT_REGISTRY_V1, BROKER_OBSERVATION_TAPE_V1,
    BROKER_POSITION_PROJECTION_V1, BrokerAccountSnapshot, BrokerInstrument,
    BrokerInstrumentRegistry, BrokerObservationTape, BrokerPositionProjection,
    BrokerQuoteObservation, ConnectionDiagnostic, ConnectionState, JointPerformanceMetric,
    RawPayloadAuthority, RawRetention, Result, credential_alias, observation_identity,
    read_generic_credential, tape_content_hash,
};

const LIVE_ROOT: &str = "https://live.tradelocker.com/backend-api";
const USER_AGENT: &str = "Northstar-RL/0.1 tradelocker-readonly";

#[derive(Clone, Debug, JsonSchema, PartialEq, Serialize, Deserialize)]
pub struct LiveReadReceipt {
    pub schema_version: String,
    pub diagnostic: ConnectionDiagnostic,
    pub registry: BrokerInstrumentRegistry,
    pub quote_tape: BrokerObservationTape,
    pub account: BrokerAccountSnapshot,
    pub positions: Vec<BrokerPositionProjection>,
    pub endpoint_payload_hashes: Vec<(String, Digest)>,
    pub timings: Vec<JointPerformanceMetric>,
    pub raw_payload_retention: String,
    pub receipt_id: Digest,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct TokenResponse {
    access_token: String,
    refresh_token: String,
}

struct Tokens {
    access: String,
    refresh: String,
}
impl Drop for Tokens {
    fn drop(&mut self) {
        self.access.zeroize();
        self.refresh.zeroize();
    }
}

#[derive(Clone)]
struct Account {
    id: u64,
    acc_num: u64,
    currency: String,
}

struct ReadClient {
    agent: ureq::Agent,
    server: String,
    account_id: Option<u64>,
    acc_num: Option<u64>,
    tokens: Option<Tokens>,
    account: Option<Account>,
    timings: Vec<JointPerformanceMetric>,
}

impl ReadClient {
    fn from_environment() -> Result<Self> {
        let server = std::env::var("NORTHSTAR_TRADELOCKER_SERVER").map_err(|_| {
            crate::Error::Contract("NORTHSTAR_TRADELOCKER_SERVER is required".into())
        })?;
        if server.trim().is_empty() || server.chars().any(char::is_control) {
            return Err(crate::Error::Contract(
                "invalid TradeLocker server label".into(),
            ));
        }
        let account_id = optional_u64("NORTHSTAR_TRADELOCKER_ACCOUNT_ID")?;
        let acc_num = optional_u64("NORTHSTAR_TRADELOCKER_ACC_NUM")?;
        if account_id.is_some() && acc_num.is_some() {
            return Err(crate::Error::Contract(
                "account selectors are mutually exclusive".into(),
            ));
        }
        let config = ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(20)))
            .https_only(true)
            .http_status_as_error(false)
            .build();
        Ok(Self {
            agent: config.into(),
            server,
            account_id,
            acc_num,
            tokens: None,
            account: None,
            timings: Vec::new(),
        })
    }

    fn authenticate(&mut self) -> Result<()> {
        let secret = read_generic_credential(&credential_alias())?;
        let start = Instant::now();
        let mut response = self.agent.post(&format!("{LIVE_ROOT}/auth/jwt/token"))
            .header("User-Agent", USER_AGENT)
            .send_json(serde_json::json!({ "email": secret.email(), "password": secret.password(), "server": self.server }))
            .map_err(|e| crate::Error::Transport(format!("authentication transport: {e}")))?;
        let status = response.status().as_u16();
        self.timing(
            "authentication",
            start.elapsed(),
            "NETWORK_LATENCY_PLUS_API_PROCESSING",
        );
        if status != 200 && status != 201 {
            return Err(crate::Error::Transport(format!(
                "authentication rejected status {status}"
            )));
        }
        let token: TokenResponse = response
            .body_mut()
            .read_json()
            .map_err(|e| crate::Error::Transport(format!("authentication body: {e}")))?;
        if token.access_token.len() < 32 || token.refresh_token.len() < 32 {
            return Err(crate::Error::Transport(
                "malformed authentication tokens".into(),
            ));
        }
        self.tokens = Some(Tokens {
            access: token.access_token,
            refresh: token.refresh_token,
        });
        Ok(())
    }

    fn select_account(&mut self) -> Result<()> {
        let response = self.get("/auth/jwt/all-accounts", &[], false)?;
        let rows = response
            .get("accounts")
            .and_then(Value::as_array)
            .ok_or_else(|| crate::Error::Transport("malformed accounts response".into()))?;
        let matches = rows
            .iter()
            .filter_map(|row| {
                Some(Account {
                    id: value_u64(row.get("id")?)?,
                    acc_num: value_u64(row.get("accNum")?)?,
                    currency: row
                        .get("currency")
                        .and_then(Value::as_str)
                        .unwrap_or("UNKNOWN")
                        .to_owned(),
                })
            })
            .filter(|a| {
                self.account_id.is_none_or(|id| id == a.id)
                    && self.acc_num.is_none_or(|n| n == a.acc_num)
            })
            .collect::<Vec<_>>();
        match matches.as_slice() {
            [account] => {
                self.account = Some(account.clone());
                Ok(())
            }
            [] => Err(crate::Error::Transport(
                "no matching TradeLocker account".into(),
            )),
            many => Err(crate::Error::Transport(format!(
                "account selector required for {} accounts",
                many.len()
            ))),
        }
    }

    fn get(&mut self, path: &str, query: &[(&str, String)], account_scope: bool) -> Result<Value> {
        let token = self
            .tokens
            .as_ref()
            .ok_or_else(|| crate::Error::Transport("not authenticated".into()))?;
        let endpoint = format!("{LIVE_ROOT}{path}");
        let authorization = format!("Bearer {}", token.access);
        let account_number = account_scope
            .then(|| self.account.as_ref().map(|a| a.acc_num.to_string()))
            .flatten()
            .ok_or_else(|| crate::Error::Transport("account unavailable".into()))
            .or_else(|error| {
                if account_scope {
                    Err(error)
                } else {
                    Ok(String::new())
                }
            })?;
        for attempt in 0..=3_u64 {
            let start = Instant::now();
            let mut request = self
                .agent
                .get(&endpoint)
                .header("Authorization", &authorization)
                .header("User-Agent", USER_AGENT);
            if account_scope {
                request = request.header("accNum", &account_number);
            }
            for (key, value) in query {
                request = request.query(key, value);
            }
            let mut response = request
                .call()
                .map_err(|e| crate::Error::Transport(format!("GET {path}: {e}")))?;
            let status = response.status().as_u16();
            self.timing(
                endpoint_name(path),
                start.elapsed(),
                "NETWORK_LATENCY_PLUS_API_PROCESSING",
            );
            if status == 429 && attempt < 3 {
                let provider_wait = response
                    .headers()
                    .get("retry-after")
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| v.parse::<u64>().ok())
                    .unwrap_or(0);
                std::thread::sleep(Duration::from_secs(provider_wait.max(1 << attempt).min(8)));
                continue;
            }
            if !(200..300).contains(&status) {
                return Err(crate::Error::Transport(format!(
                    "GET {path} status {status}"
                )));
            }
            return response
                .body_mut()
                .read_json()
                .map_err(|e| crate::Error::Transport(format!("GET {path} body: {e}")));
        }
        unreachable!("bounded GET retry loop returns")
    }

    fn timing(&mut self, name: &str, duration: Duration, component: &str) {
        self.timings.push(JointPerformanceMetric {
            name: name.into(),
            value: duration.as_secs_f64() * 1e3,
            unit: "milliseconds".into(),
            component: component.into(),
            workload: "single_authenticated_live_read".into(),
        });
    }
}

pub fn capture_live_read_only() -> Result<LiveReadReceipt> {
    let mut client = ReadClient::from_environment()?;
    client.authenticate()?;
    client.select_account()?;
    let account = client.account.clone().expect("selected account");
    let account_hash = Digest::hash(
        b"northstar-tradelocker-account-id-v1",
        &account.id.to_le_bytes(),
    );
    let config = client.get("/trade/config", &[], true)?;
    let instruments_path = format!("/trade/accounts/{}/instruments", account.id);
    let instruments_raw = client.get(&instruments_path, &[], true)?;
    let selected = selected_instruments(&instruments_raw)?;
    if selected.is_empty() {
        return Err(crate::Error::Transport(
            "no Northstar-bound TradeLocker instruments discovered".into(),
        ));
    }
    let mut registry_rows = Vec::with_capacity(selected.len());
    let mut quotes = Vec::with_capacity(selected.len());
    let received_base = now_ns();
    let detail_spacing = route_spacing(&config, "GET_INSTRUMENT_DETAILS");
    let quote_spacing = route_spacing(&config, "QUOTES");
    let mut next_detail = Instant::now();
    let mut next_quote = Instant::now();
    for instrument in &selected {
        wait_slot(&mut next_detail, detail_spacing);
        let detail = client.get(
            &format!("/trade/instruments/{}", instrument.provider_id),
            &[
                ("routeId", instrument.info_route.clone()),
                ("locale", "en".into()),
            ],
            true,
        )?;
        wait_slot(&mut next_quote, quote_spacing);
        let quote = client.get(
            "/trade/quotes",
            &[
                ("tradableInstrumentId", instrument.provider_id.to_string()),
                ("routeId", instrument.info_route.clone()),
            ],
            true,
        )?;
        registry_rows.push(normalize_instrument(instrument, &detail, received_base)?);
        quotes.push(normalize_quote(
            instrument,
            &quote,
            account_hash,
            received_base,
        )?);
    }
    let state_path = format!("/trade/accounts/{}/state", account.id);
    let position_path = format!("/trade/accounts/{}/positions", account.id);
    let account_raw = client.get(&state_path, &[], true)?;
    let positions_raw = client.get(&position_path, &[], true)?;
    let account_snapshot =
        normalize_account(&config, &account_raw, &account, account_hash, now_ns())?;
    let position_rows = normalize_positions(&config, &positions_raw, &selected, now_ns())?;
    let mut registry = BrokerInstrumentRegistry {
        schema_version: BROKER_INSTRUMENT_REGISTRY_V1.into(),
        instruments: registry_rows,
        content_hash: Digest::ZERO,
    };
    registry.content_hash = identity(b"northstar-broker-instrument-registry-v1", &registry)?;
    let mut tape = BrokerObservationTape {
        schema_version: BROKER_OBSERVATION_TAPE_V1.into(),
        source_authority: "LIVE_TRADELOCKER_NORMALIZED_CAPTURE".into(),
        account_id_hash: account_hash,
        rows: quotes,
        content_hash: Digest::ZERO,
    };
    tape.content_hash = tape_content_hash(&tape)?;
    let hashes = vec![
        hash_value("config", &config)?,
        hash_value("instruments", &instruments_raw)?,
        hash_value("account_state", &account_raw)?,
        hash_value("positions", &positions_raw)?,
    ];
    let diagnostic = ConnectionDiagnostic {
        provider: "TRADELOCKER".into(),
        credential_provider: "WINDOWS_GENERIC_CREDENTIAL".into(),
        credential_alias: credential_alias(),
        credential_resolved: true,
        authenticated_account_id_hash: Some(account_hash),
        connection_environment: "LIVE".into(),
        connection_state: ConnectionState::Connected,
        detail_code: "AUTHENTICATED_READ_ONLY_CAPTURE_PASS".into(),
    };
    let mut receipt = LiveReadReceipt {
        schema_version: "TRADELOCKER_LIVE_READ_RECEIPT_V1".into(),
        diagnostic,
        registry,
        quote_tape: tape,
        account: account_snapshot,
        positions: position_rows,
        endpoint_payload_hashes: hashes,
        timings: client.timings,
        raw_payload_retention: "HASH_ONLY_PENDING_EXPLICIT_RETENTION_AUTHORITY".into(),
        receipt_id: Digest::ZERO,
    };
    receipt.receipt_id = identity(b"northstar-tradelocker-live-read-receipt-v1", &receipt)?;
    Ok(receipt)
}

#[derive(Clone)]
struct SelectedInstrument {
    northstar_id: u32,
    symbol: String,
    provider_id: u64,
    info_route: String,
}

fn selected_instruments(value: &Value) -> Result<Vec<SelectedInstrument>> {
    let mapping = BTreeMap::from([
        ("NAS100", 1),
        ("SPX500", 2),
        ("US30", 3),
        ("DE40", 4),
        ("UK100", 5),
        ("JP225", 6),
    ]);
    let rows = value
        .pointer("/d/instruments")
        .and_then(Value::as_array)
        .ok_or_else(|| crate::Error::Transport("malformed instruments".into()))?;
    let mut output = Vec::with_capacity(mapping.len());
    for row in rows {
        let Some(symbol) = row.get("name").and_then(Value::as_str) else {
            continue;
        };
        let Some(&northstar_id) = mapping.get(symbol) else {
            continue;
        };
        let provider_id = row
            .get("tradableInstrumentId")
            .and_then(value_u64)
            .ok_or_else(|| crate::Error::Transport("instrument id missing".into()))?;
        let info_route = row
            .get("routes")
            .and_then(Value::as_array)
            .and_then(|routes| {
                routes
                    .iter()
                    .find(|r| r.get("type").and_then(Value::as_str) == Some("INFO"))
            })
            .and_then(|r| r.get("id"))
            .and_then(value_text)
            .ok_or_else(|| crate::Error::Transport("INFO route missing".into()))?;
        output.push(SelectedInstrument {
            northstar_id,
            symbol: symbol.into(),
            provider_id,
            info_route,
        });
    }
    output.sort_by_key(|row| row.northstar_id);
    Ok(output)
}

fn normalize_instrument(
    selected: &SelectedInstrument,
    raw: &Value,
    observed: i64,
) -> Result<BrokerInstrument> {
    let data = raw.get("d").unwrap_or(raw);
    let min = first_number(data, &["minLot", "minQty", "minQuantity", "lotSize"]).unwrap_or(0.0);
    let step = first_number(data, &["qtyStep", "quantityStep", "lotStep"]).unwrap_or(min);
    let tick = first_number(data, &["tickSize", "priceTick", "minPriceIncrement"]).unwrap_or(
        10f64.powi(-(first_u64(data, &["pricePrecision", "precision"]).unwrap_or(2) as i32)),
    );
    let precision = first_u64(data, &["pricePrecision", "precision"])
        .unwrap_or_else(|| decimal_precision(tick) as u64) as u8;
    Ok(BrokerInstrument {
        broker: "TRADELOCKER".into(),
        venue: "HEROFX".into(),
        broker_instrument_id: selected.provider_id.to_string(),
        broker_symbol: selected.symbol.clone(),
        northstar_instrument_id: selected.northstar_id,
        asset_class: "BROKER_DECLARED_OR_UNRESOLVED".into(),
        quote_currency: first_text(data, &["quoteCurrency", "currency"])
            .unwrap_or("UNRESOLVED")
            .into(),
        price_precision: precision,
        tick_size: tick,
        quantity_precision: decimal_precision(step),
        quantity_step: step,
        min_quantity: min,
        max_quantity: first_number(data, &["maxLot", "maxQty", "maxQuantity"]),
        contract_size: first_number(data, &["contractSize", "lotSize"]).unwrap_or(1.0),
        trading_status: if data
            .get("tradable")
            .and_then(Value::as_bool)
            .unwrap_or(true)
        {
            "OBSERVED_AVAILABLE".into()
        } else {
            "OBSERVED_UNAVAILABLE".into()
        },
        raw_metadata: RawPayloadAuthority {
            payload_hash: hash_json(raw)?,
            retention: RawRetention::HashOnly,
            retained_relative_path: None,
        },
        observed_at_ns: observed,
    })
}

fn normalize_quote(
    selected: &SelectedInstrument,
    raw: &Value,
    _account: Digest,
    received: i64,
) -> Result<BrokerQuoteObservation> {
    let data = raw.get("d").unwrap_or(raw);
    let bid = first_number(data, &["bp", "bid"])
        .ok_or_else(|| crate::Error::Transport("quote bid missing".into()))?;
    let ask = first_number(data, &["ap", "ask"])
        .ok_or_else(|| crate::Error::Transport("quote ask missing".into()))?;
    if !bid.is_finite() || !ask.is_finite() || bid <= 0.0 || ask < bid {
        return Err(crate::Error::Transport("invalid or crossed quote".into()));
    }
    let raw_hash = hash_json(raw)?;
    let mut row = BrokerQuoteObservation {
        observation_id: Digest::ZERO,
        broker: "TRADELOCKER".into(),
        account_environment: "LIVE".into(),
        instrument_id: selected.northstar_id,
        event_time_ns: first_i64(data, &["timestamp", "ts", "time"])
            .map(to_ns)
            .unwrap_or(received),
        received_time_ns: received,
        recorded_time_ns: now_ns(),
        bid,
        ask,
        last: first_number(data, &["last", "lp"]),
        spread: ask - bid,
        raw_payload_hash: raw_hash,
        normalized_payload_hash: Digest::ZERO,
        connection_state: ConnectionState::Connected,
    };
    row.normalized_payload_hash = identity(b"northstar-normalized-broker-quote-v1", &row)?;
    row.observation_id = observation_identity(&row)?;
    Ok(row)
}

fn normalize_account(
    config: &Value,
    raw: &Value,
    account: &Account,
    account_hash: Digest,
    received: i64,
) -> Result<BrokerAccountSnapshot> {
    let layout = ColumnLayout::new(config, "accountDetailsConfig")?;
    let row = raw
        .pointer("/d/accountDetailsData")
        .and_then(Value::as_array)
        .ok_or_else(|| crate::Error::Transport("account data missing".into()))?;
    let value = |key| layout.number(row, key);
    let mut snapshot = BrokerAccountSnapshot {
        schema_version: BROKER_ACCOUNT_SNAPSHOT_V1.into(),
        account_id_hash: account_hash,
        environment: "LIVE".into(),
        broker_raw_terms: [
            "balance",
            "projectedBalance",
            "availableFunds",
            "todayNet",
            "todayFees",
            "openNetPnL",
        ]
        .into_iter()
        .filter_map(|k| value(k).map(|v| (k.into(), v)))
        .collect(),
        cash_equivalent: value("balance"),
        equity: value("projectedBalance"),
        unrealized_pnl: value("openNetPnL"),
        realized_pnl: value("todayNet"),
        available_funds: value("availableFunds"),
        margin_terms: Vec::new(),
        broker_time_ns: None,
        received_time_ns: received,
        raw_payload_hash: hash_json(raw)?,
        field_provenance: vec![
            ("cash_equivalent".into(), "BROKER_RAW.balance".into()),
            ("equity".into(), "BROKER_RAW.projectedBalance".into()),
            (
                "currency".into(),
                format!("AUTH_ACCOUNT.{}", account.currency),
            ),
        ],
        content_hash: Digest::ZERO,
    };
    snapshot.content_hash = identity(b"northstar-broker-account-snapshot-v1", &snapshot)?;
    Ok(snapshot)
}

fn normalize_positions(
    config: &Value,
    raw: &Value,
    selected: &[SelectedInstrument],
    observed: i64,
) -> Result<Vec<BrokerPositionProjection>> {
    let layout = ColumnLayout::new(config, "positionsConfig")?;
    let rows = raw
        .pointer("/d/positions")
        .and_then(Value::as_array)
        .ok_or_else(|| crate::Error::Transport("positions data missing".into()))?;
    let mut output = Vec::with_capacity(rows.len());
    for value in rows {
        let row = value
            .as_array()
            .ok_or_else(|| crate::Error::Transport("short position row".into()))?;
        let provider = layout
            .u64(row, "tradableInstrumentId")
            .ok_or_else(|| crate::Error::Transport("position instrument missing".into()))?;
        let Some(instrument) = selected.iter().find(|i| i.provider_id == provider) else {
            continue;
        };
        let raw_hash = hash_json(value)?;
        let broker_id = layout
            .text(row, "id")
            .unwrap_or_else(|| "UNRESOLVED".into());
        let mut projection = BrokerPositionProjection {
            schema_version: BROKER_POSITION_PROJECTION_V1.into(),
            broker_position_id_hash: Digest::hash(
                b"northstar-broker-position-id-v1",
                broker_id.as_bytes(),
            ),
            northstar_instrument_id: instrument.northstar_id,
            side: layout
                .text(row, "side")
                .unwrap_or_else(|| "UNRESOLVED".into()),
            quantity: layout.number(row, "qty").unwrap_or(0.0),
            average_price: layout.number(row, "avgPrice").unwrap_or(0.0),
            current_price: layout.number(row, "currentPrice"),
            unrealized_result: layout.number(row, "unrealizedPl"),
            broker_status: "OBSERVED_OPEN".into(),
            observation_time_ns: observed,
            raw_payload_hash: raw_hash,
            content_hash: Digest::ZERO,
        };
        projection.content_hash =
            identity(b"northstar-broker-position-projection-v1", &projection)?;
        output.push(projection);
    }
    output.sort_by_key(|p| p.broker_position_id_hash);
    Ok(output)
}

struct ColumnLayout {
    columns: BTreeMap<String, usize>,
}
impl ColumnLayout {
    fn new(config: &Value, key: &str) -> Result<Self> {
        let columns = config
            .pointer(&format!("/d/{key}/columns"))
            .and_then(Value::as_array)
            .ok_or_else(|| crate::Error::Transport(format!("missing {key} layout")))?;
        let mut map = BTreeMap::new();
        for (index, column) in columns.iter().enumerate() {
            if let Some(id) = column.get("id").and_then(Value::as_str) {
                map.insert(id.into(), index);
            }
        }
        Ok(Self { columns: map })
    }
    fn get<'a>(&self, row: &'a [Value], key: &str) -> Option<&'a Value> {
        row.get(*self.columns.get(key)?)
    }
    fn number(&self, row: &[Value], key: &str) -> Option<f64> {
        self.get(row, key).and_then(value_f64)
    }
    fn u64(&self, row: &[Value], key: &str) -> Option<u64> {
        self.get(row, key).and_then(value_u64)
    }
    fn text(&self, row: &[Value], key: &str) -> Option<String> {
        self.get(row, key).and_then(value_text)
    }
}

fn optional_u64(name: &str) -> Result<Option<u64>> {
    let Some(text) = std::env::var(name).ok().filter(|v| !v.trim().is_empty()) else {
        return Ok(None);
    };
    text.parse()
        .map(Some)
        .map_err(|_| crate::Error::Contract(format!("invalid {name}")))
}
fn value_u64(v: &Value) -> Option<u64> {
    v.as_u64().or_else(|| v.as_str()?.parse().ok())
}
fn value_f64(v: &Value) -> Option<f64> {
    v.as_f64().or_else(|| v.as_str()?.parse().ok())
}
fn value_text(v: &Value) -> Option<String> {
    v.as_str()
        .map(str::to_owned)
        .or_else(|| v.as_u64().map(|x| x.to_string()))
}
fn first_number(v: &Value, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|k| v.get(*k).and_then(value_f64))
}
fn first_u64(v: &Value, keys: &[&str]) -> Option<u64> {
    keys.iter().find_map(|k| v.get(*k).and_then(value_u64))
}
fn first_i64(v: &Value, keys: &[&str]) -> Option<i64> {
    keys.iter().find_map(|k| {
        v.get(*k)
            .and_then(|n| n.as_i64().or_else(|| n.as_str()?.parse().ok()))
    })
}
fn first_text<'a>(v: &'a Value, keys: &[&str]) -> Option<&'a str> {
    keys.iter().find_map(|k| v.get(*k).and_then(Value::as_str))
}
fn decimal_precision(value: f64) -> u8 {
    (0..=9)
        .find(|p| (value * 10f64.powi(*p)).fract().abs() < 1e-9)
        .unwrap_or(9) as u8
}
fn to_ns(value: i64) -> i64 {
    if value.abs() < 10_000_000_000_000 {
        value.saturating_mul(1_000_000)
    } else {
        value
    }
}
fn now_ns() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_nanos()).unwrap_or(i64::MAX))
}
fn hash_json(value: &Value) -> Result<Digest> {
    Ok(Digest::hash(
        b"northstar-tradelocker-raw-payload-v1",
        &serde_json::to_vec(value)?,
    ))
}
fn hash_value(name: &str, value: &Value) -> Result<(String, Digest)> {
    Ok((name.into(), hash_json(value)?))
}
fn endpoint_name(path: &str) -> &str {
    if path == "/trade/config" {
        "config"
    } else if path.ends_with("/instruments") {
        "instruments"
    } else if path.starts_with("/trade/instruments/") {
        "instrument_details"
    } else if path == "/trade/quotes" {
        "quote"
    } else if path.ends_with("/state") {
        "account_state"
    } else if path.ends_with("/positions") {
        "positions"
    } else {
        "read_endpoint"
    }
}
fn route_spacing(config: &Value, name: &str) -> Duration {
    let limit = config
        .pointer("/d/rateLimits")
        .and_then(Value::as_array)
        .and_then(|rows| {
            rows.iter()
                .find(|r| r.get("rateLimitType").and_then(Value::as_str) == Some(name))
        });
    let count = limit
        .and_then(|v| v.get("limit"))
        .and_then(value_f64)
        .unwrap_or(1.0)
        .max(1.0);
    let interval = limit
        .and_then(|v| v.get("intervalNum"))
        .and_then(value_f64)
        .unwrap_or(1.0)
        .max(1.0);
    let unit = match limit.and_then(|v| v.get("measure")).and_then(Value::as_str) {
        Some("MINUTES") => 60.0,
        _ => 1.0,
    };
    Duration::from_secs_f64((interval * unit / count * 1.10).max(0.01))
}
fn wait_slot(next: &mut Instant, spacing: Duration) {
    let now = Instant::now();
    if now < *next {
        std::thread::sleep(*next - now);
    }
    *next = Instant::now() + spacing;
}
