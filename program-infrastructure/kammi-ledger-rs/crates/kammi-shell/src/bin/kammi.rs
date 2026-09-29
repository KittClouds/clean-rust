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
    let args = Args::parse(raw, &["summary", "json"]).map_err(usage)?;
    if command == "verbs" {
        args.only(&[], 0).map_err(Failure::Usage)?;
        let list: Vec<Value> = verbs::VERBS
            .iter()
            .map(|v| serde_json::json!({"verb": v.name, "phase": v.phase, "writes": v.writes, "summary": v.summary,
                                        "mcp_tool": verbs::mcp_tool(v), "available": v.phase == 0}))
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

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(command) = argv.first() else {
        eprintln!("usage: kammi <verb> [args]; `kammi verbs` lists the ABI");
        std::process::exit(exit::USAGE);
    };
    match run(command, &argv[1..]) {
        Ok(value) => println!("{}", kammi_shell::dumps_pretty(&value)),
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
