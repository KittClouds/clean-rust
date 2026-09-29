//! `kammi`: the Library shell (amendment v4 §3). Phase 0: the v1 commands of `ledgerd/cli.py`
//! with the same output (`json.dumps(indent=2, sort_keys=True)`), plus the frozen verb list.
//!
//! ```text
//! kammi status
//! kammi call GET|POST <endpoint> [--body <file.json>]
//! kammi artifact <path> --kind <kind> --actor <actor>
//! kammi run <run_id> <lab> --actor <actor>
//! kammi seal [--member <id>]... [--parent <id>]... --actor <actor>
//! kammi lineage <root>
//! kammi history <run_id> [--summary]
//! kammi verbs
//! ```

use kammi_contract::verbs::{self, exit};
use kammi_shell::client::{Client, ClientError};
use serde_json::Value;

struct Args {
    positional: Vec<String>,
    options: Vec<(String, String)>,
    switches: Vec<String>,
}

impl Args {
    fn parse(raw: &[String], switches: &[&str]) -> Result<Args, String> {
        let mut args = Args {
            positional: Vec::new(),
            options: Vec::new(),
            switches: Vec::new(),
        };
        let mut iter = raw.iter();
        while let Some(arg) = iter.next() {
            if let Some(name) = arg.strip_prefix("--") {
                if switches.contains(&name) {
                    args.switches.push(name.to_string());
                } else {
                    let value = iter
                        .next()
                        .ok_or_else(|| format!("--{name} needs a value"))?;
                    args.options.push((name.to_string(), value.clone()));
                }
            } else {
                args.positional.push(arg.clone());
            }
        }
        Ok(args)
    }

    fn one(&self, name: &str) -> Result<String, String> {
        match self
            .options
            .iter()
            .filter(|(n, _)| n == name)
            .collect::<Vec<_>>()
            .as_slice()
        {
            [(_, value)] => Ok(value.clone()),
            [] => Err(format!("--{name} is required")),
            _ => Err(format!("--{name} given more than once")),
        }
    }

    fn many(&self, name: &str) -> Vec<String> {
        self.options
            .iter()
            .filter(|(n, _)| n == name)
            .map(|(_, v)| v.clone())
            .collect()
    }

    fn only(&self, allowed: &[&str], positional: usize) -> Result<(), String> {
        if let Some((name, _)) = self
            .options
            .iter()
            .find(|(n, _)| !allowed.contains(&n.as_str()))
        {
            return Err(format!("unknown option --{name}"));
        }
        if self.positional.len() != positional {
            return Err(format!(
                "expected {positional} argument(s), got {}",
                self.positional.len()
            ));
        }
        Ok(())
    }
}

enum Failure {
    Usage(String),
    Client(ClientError),
}

fn run(command: &str, raw: &[String]) -> Result<Value, Failure> {
    let usage = Failure::Usage;
    let args = Args::parse(raw, &["summary", "json", "functions"]).map_err(usage)?;
    if command == "verbs" {
        if raw.iter().any(|a| a == "--functions") {
            return Ok(Value::Array(kammi_shell::verbs::functions()));
        }
        args.only(&[], 0).map_err(Failure::Usage)?;
        let list: Vec<Value> = verbs::VERBS
            .iter()
            .map(|v| {
                let available = v.phase == 0 || kammi_shell::verbs::spec(v.name).is_some();
                serde_json::json!({"verb": v.name, "phase": v.phase, "writes": v.writes, "summary": v.summary,
                                   "mcp_tool": verbs::mcp_tool(v), "available": available})
            })
            .collect();
        return Ok(Value::Array(list));
    }
    let client = Client::from_environment().map_err(Failure::Client)?;
    let p = |i: usize| args.positional[i].as_str();
    let result = match command {
        "status" => {
            args.only(&[], 0).map_err(Failure::Usage)?;
            client.status()
        }
        "call" => {
            args.only(&["body"], 2).map_err(Failure::Usage)?;
            if !matches!(p(0), "GET" | "POST") {
                return Err(Failure::Usage("method must be GET or POST".into()));
            }
            let body = match args.many("body").first() {
                Some(path) => {
                    let text =
                        std::fs::read(path).map_err(|e| Failure::Usage(format!("{path}: {e}")))?;
                    Some(
                        kammi_jcs::strict_json(&text)
                            .map_err(|e| Failure::Usage(format!("{path}: {e}")))?,
                    )
                }
                None => None,
            };
            client.call(p(0), p(1), body.as_ref())
        }
        "artifact" => {
            args.only(&["kind", "actor"], 1).map_err(Failure::Usage)?;
            let bytes =
                std::fs::read(p(0)).map_err(|e| Failure::Usage(format!("{}: {e}", p(0))))?;
            let (kind, actor) = (
                args.one("kind").map_err(Failure::Usage)?,
                args.one("actor").map_err(Failure::Usage)?,
            );
            client.register_bytes(&bytes, &kind, &actor, &kammi_shell::request_id())
        }
        "run" => {
            args.only(&["actor"], 2).map_err(Failure::Usage)?;
            client.create_run(
                p(0),
                p(1),
                &args.one("actor").map_err(Failure::Usage)?,
                &kammi_shell::request_id(),
            )
        }
        "seal" => {
            args.only(&["member", "parent", "actor"], 0)
                .map_err(Failure::Usage)?;
            let actor = args.one("actor").map_err(Failure::Usage)?;
            client.create_seal(
                &args.many("member"),
                &args.many("parent"),
                &actor,
                &kammi_shell::request_id(),
            )
        }
        "lineage" => {
            args.only(&[], 1).map_err(Failure::Usage)?;
            client.lineage(p(0))
        }
        "history" => {
            args.only(&[], 1).map_err(Failure::Usage)?;
            client.history(p(0), args.switches.iter().any(|s| s == "summary"))
        }
        other => {
            return Err(Failure::Usage(match verbs::lookup(other) {
                Some(verb) => format!(
                    "{other}: not available until Phase {} ({})",
                    verb.phase, verb.summary
                ),
                None => format!("unknown verb {other}; `kammi verbs` lists the ABI"),
            }))
        }
    };
    result.map_err(Failure::Client)
}

/// The CLI session (`KAMMI_SESSION`, default `.kammi/session.json`): the workspace, session
/// and HEAD this agent last read, so writes carry the expected HEAD without being asked.
fn session_path() -> std::path::PathBuf {
    std::env::var_os("KAMMI_SESSION")
        .map(Into::into)
        .unwrap_or_else(|| std::path::Path::new(".kammi").join("session.json"))
}

fn load_session() -> serde_json::Map<String, Value> {
    std::fs::read(session_path())
        .ok()
        .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

fn save_session(session: &serde_json::Map<String, Value>) {
    let path = session_path();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let _ = std::fs::write(path, serde_json::to_vec_pretty(session).unwrap_or_default());
}

/// A Phase 1 workspace verb from the command line: positionals and `--flags` become the
/// verb's JSON arguments; the session fills `workspace`, `expected_head` and `session_id`.
fn workspace_verb(
    spec: &'static kammi_shell::verbs::VerbSpec,
    raw: &[String],
) -> Result<(Value, String), Failure> {
    use kammi_shell::verbs::Kind;
    let mut args = serde_json::Map::new();
    let mut positional = Vec::new();
    let mut json_out = false;
    let mut iter = raw.iter();
    while let Some(a) = iter.next() {
        if a == "--json" {
            json_out = true;
        } else if let Some(name) = a.strip_prefix("--") {
            let name = name.replace('-', "_");
            let def =
                spec.args.iter().find(|d| d.name == name).ok_or_else(|| {
                    Failure::Usage(format!("{}: unknown option --{name}", spec.verb))
                })?;
            match def.kind {
                Kind::Bool => {
                    args.insert(name, Value::Bool(true));
                }
                Kind::Text => {
                    let v = iter
                        .next()
                        .ok_or_else(|| Failure::Usage(format!("--{name} needs a value")))?;
                    args.insert(name, Value::from(v.clone()));
                }
                Kind::Texts => {
                    let v = iter
                        .next()
                        .ok_or_else(|| Failure::Usage(format!("--{name} needs a value")))?;
                    args.entry(name)
                        .or_insert_with(|| Value::Array(Vec::new()))
                        .as_array_mut()
                        .expect("a list")
                        .push(Value::from(v.clone()));
                }
            }
        } else {
            positional.push(a.clone());
        }
    }
    let positioned: Vec<_> = spec.args.iter().filter(|d| d.position.is_some()).collect();
    if positional.len() > positioned.len() {
        return Err(Failure::Usage(format!("{}: too many arguments", spec.verb)));
    }
    for def in positioned {
        if let Some(v) = positional.get(def.position.expect("positioned")) {
            args.insert(def.name.into(), Value::from(v.clone()));
        }
    }
    let mut session = load_session();
    let actor = std::env::var("KAMMI_ACTOR").ok().or_else(|| {
        session
            .get("actor")
            .and_then(Value::as_str)
            .map(str::to_string)
    });
    let takes_workspace = spec.args.iter().any(|d| d.name == "workspace");
    if spec.verb != "open" && takes_workspace && !args.contains_key("workspace") {
        if let Some(ws) = session.get("workspace").cloned() {
            args.insert("workspace".into(), ws);
        }
    }
    let same_workspace = args.get("workspace") == session.get("workspace");
    let takes_head = spec.args.iter().any(|d| d.name == "expected_head");
    if takes_head && !args.contains_key("expected_head") && same_workspace {
        if let Some(head) = session.get("head").cloned() {
            args.insert("expected_head".into(), head);
        }
    }
    if spec.verb == "close"
        && !args.contains_key("session_id")
        && !args.contains_key("end")
        && same_workspace
    {
        if let Some(sid) = session.get("session_id").cloned() {
            args.insert("session_id".into(), sid);
        }
    }
    let client = Client::from_environment().map_err(Failure::Client)?;
    let value = match kammi_shell::verbs::execute(&client, actor.as_deref(), spec.verb, &args) {
        Ok(v) => v,
        Err(kammi_shell::verbs::VerbError::Usage(m)) => return Err(Failure::Usage(m)),
        Err(kammi_shell::verbs::VerbError::Client(ClientError::Refused {
            status: 409,
            message,
        })) => {
            // Show what moved since the HEAD this session last read, then exit 3.
            let mut note = format!(
                "{message}\nHEAD moved since you last read the workspace. Run `kammi work`, then retry."
            );
            let ws = args.get("workspace").and_then(Value::as_str);
            if let (Some(ws), Some(head)) = (ws, session.get("head").and_then(Value::as_str)) {
                let mut log = serde_json::Map::new();
                log.insert("workspace".into(), ws.into());
                log.insert("after".into(), head.into());
                if let Ok(changes) =
                    kammi_shell::verbs::execute(&client, actor.as_deref(), "log", &log)
                {
                    for e in changes["events"].as_array().into_iter().flatten() {
                        note.push_str(&format!(
                            "\n  {} {} {}",
                            e["utc"].as_str().unwrap_or(""),
                            e["actor"].as_str().unwrap_or(""),
                            e["summary"].as_str().unwrap_or("")
                        ));
                    }
                }
            }
            return Err(Failure::Client(ClientError::Refused {
                status: 409,
                message: note,
            }));
        }
        Err(kammi_shell::verbs::VerbError::Client(e)) => return Err(Failure::Client(e)),
    };
    // Remember what this agent has now seen.
    let ws = args.get("workspace").cloned().unwrap_or(Value::Null);
    let seen_head = match spec.verb {
        "work" => value["workspace"]["head"].clone(),
        "open" => value["packet"]["workspace"]["head"].clone(),
        "log" => Value::Null,
        _ => value["head"].clone(),
    };
    if spec.verb == "open" {
        session = serde_json::Map::new();
        session.insert("session_id".into(), value["session_id"].clone());
        if let Some(a) = &actor {
            session.insert("actor".into(), Value::from(a.clone()));
        }
    }
    if !seen_head.is_null() {
        session.insert("workspace".into(), ws);
        session.insert("head".into(), seen_head);
        save_session(&session);
    }
    let text = |v: &Value| v.as_str().unwrap_or("").to_string();
    let human = match spec.verb {
        "work" => text(&value["text"]),
        "open" => format!(
            "attached as session {}\n{}",
            text(&value["session_id"]),
            text(&value["packet"]["text"])
        ),
        "recall" => {
            value["results"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|r| {
                    let m = &r["memory"];
                    format!(
                        "- {} {}: {} (fused {:.4}; {})\n",
                        text(&m["memory_id"]),
                        text(&m["kind"]),
                        text(&m["text"]),
                        r["scores"]["fused"].as_f64().unwrap_or(0.0),
                        r["reason"]
                            .as_array()
                            .map(|a| a
                                .iter()
                                .filter_map(Value::as_str)
                                .collect::<Vec<_>>()
                                .join("+"))
                            .unwrap_or_default()
                    )
                })
                .collect::<String>()
                + "(memory is contextual, not custody: check trace before relying on it)\n"
        }
        "remember" => format!("ok MemoryRecordedV2 {}\n", text(&value["memory_id"])),
        "trace" | "find" => kammi_shell::dumps_pretty(&value) + "\n",
        "log" => value["events"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|e| {
                format!(
                    "{} {} {} {}\n",
                    text(&e["utc"]),
                    text(&e["actor"]),
                    text(&e["summary"]),
                    text(&e["event"])
                )
            })
            .collect(),
        _ => format!(
            "ok {} {}; HEAD now {}\n",
            spec.event.unwrap_or(""),
            text(&value["event_id"]),
            text(&value["head"])
        ),
    };
    Ok((value, if json_out { String::new() } else { human }))
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(command) = argv.first() else {
        eprintln!("usage: kammi <verb> [args]; `kammi verbs` lists the ABI");
        std::process::exit(exit::USAGE);
    };
    let outcome = match kammi_shell::verbs::spec(command) {
        Some(spec) => workspace_verb(spec, &argv[1..]),
        None => run(command, &argv[1..]).map(|v| (v, String::new())),
    };
    match outcome {
        Ok((_, human)) if !human.is_empty() => print!("{human}"),
        Ok((value, _)) => println!("{}", kammi_shell::dumps_pretty(&value)),
        Err(Failure::Usage(message)) => {
            eprintln!("kammi: {message}");
            std::process::exit(exit::USAGE);
        }
        Err(Failure::Client(error)) => {
            eprintln!("kammi: {error}");
            std::process::exit(match error {
                ClientError::Refused { status: 409, .. } => exit::CONFLICT,
                ClientError::Refused { .. } => exit::REFUSED,
                ClientError::Usage(_) => exit::USAGE,
                ClientError::Unreachable(_) => exit::UNREACHABLE,
            });
        }
    }
}
