use overgraph::{DatabaseEngine, DbOptions, PropValue, UpsertNodeOptions, WalSyncMode};
use serde::Serialize;
use serde_json::json;
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io;
use std::path::Path;
use std::process::{Child, Command, Output, Stdio};
use std::thread;
use std::time::{Duration, Instant};

const TYPE_AUDIT_WRITER: u32 = 760_001;
const WRITER_A_KEY: &str = "audit:writer-a";
const WRITER_B_KEY: &str = "audit:writer-b";
const CHILD_TIMEOUT: Duration = Duration::from_secs(30);
const OVERLAP_TRIALS: usize = 3;

#[derive(Debug, Serialize)]
struct ChildEvidence {
    success: bool,
    exit_code: Option<i32>,
    stdout: String,
    stderr: String,
}

impl From<Output> for ChildEvidence {
    fn from(output: Output) -> Self {
        Self {
            success: output.status.success(),
            exit_code: output.status.code(),
            stdout: String::from_utf8_lossy(&output.stdout).trim().to_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        }
    }
}

#[derive(Debug, Serialize)]
struct FileEvidence {
    path: String,
    bytes: u64,
    blake3: String,
}

#[derive(Debug, Serialize)]
struct ProbeEvidence {
    opened: bool,
    writer_a_present: bool,
    writer_b_present: bool,
    error: Option<String>,
}

impl ProbeEvidence {
    fn both_present(&self) -> bool {
        self.opened && self.writer_a_present && self.writer_b_present
    }
}

#[derive(Debug, Serialize)]
struct TrialEvidence {
    name: String,
    store: String,
    writer_a: ChildEvidence,
    writer_b: ChildEvidence,
    files_before_probe: Vec<FileEvidence>,
    probe: ProbeEvidence,
    files_after_probe: Vec<FileEvidence>,
    concurrent_writer_hazard: bool,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let args = env::args_os().skip(1).collect::<Vec<_>>();
    match args.as_slice() {
        [mode, root] if mode == "--orchestrate" => orchestrate(Path::new(root)),
        [mode, store, key] if mode == "--write" => {
            write_once(Path::new(store), required_utf8(key, "writer key")?)
        }
        [mode, store, ready, release, key] if mode == "--hold" => hold_then_write(
            Path::new(store),
            Path::new(ready),
            Path::new(release),
            required_utf8(key, "writer key")?,
        ),
        _ => Err(
            "usage: overgraph-concurrent-writer-audit --orchestrate <fresh-run-root>".to_owned(),
        ),
    }
}

fn orchestrate(root: &Path) -> Result<(), String> {
    if root.exists() {
        return Err(format!(
            "refusing to reuse audit root {}; pass a path that does not exist",
            root.display()
        ));
    }
    fs::create_dir_all(root).map_err(display_io("create audit root", root))?;
    let executable = env::current_exe().map_err(|error| error.to_string())?;

    let control_store = root.join("sequential-control");
    let control_a = run_write_child(&executable, &control_store, WRITER_A_KEY)?;
    let control_b = run_write_child(&executable, &control_store, WRITER_B_KEY)?;
    let control_files_before_probe = census_files(&control_store)?;
    let control_probe = probe_store(&control_store);
    let control_files_after_probe = census_files(&control_store)?;
    let sequential_control_passed =
        control_a.success && control_b.success && control_probe.both_present();

    let mut trials = Vec::with_capacity(OVERLAP_TRIALS);
    for index in 1..=OVERLAP_TRIALS {
        trials.push(run_overlap_trial(
            &executable,
            root,
            &format!("stale-writer-{index:02}"),
        )?);
    }

    let reproduced =
        sequential_control_passed && trials.iter().any(|trial| trial.concurrent_writer_hazard);
    let exact_interleaving_cleared =
        sequential_control_passed && trials.iter().all(|trial| !trial.concurrent_writer_hazard);
    let report_path = root.join("audit-report.json");
    let result = json!({
        "schema_version": 1,
        "audit": "overgraph-0.4.1-two-process-stale-writer",
        "run_root": root,
        "report_path": report_path,
        "interleaving": "writer A opens and waits; writer B opens, writes, flushes, and closes; writer A then writes, flushes, and closes",
        "sequential_control": {
            "store": control_store,
            "writer_a": control_a,
            "writer_b": control_b,
            "files_before_probe": control_files_before_probe,
            "probe": control_probe,
            "files_after_probe": control_files_after_probe,
            "passed": sequential_control_passed,
        },
        "overlap_trials": trials,
        "verdict": {
            "concurrent_writer_hazard_reproduced": reproduced,
            "exact_stale_writer_interleaving_cleared": exact_interleaving_cleared,
            "scope": "This verdict covers only the exercised two-process interleaving; it does not prove a historical live-store event.",
        }
    });
    let encoded = serde_json::to_vec_pretty(&result).map_err(|error| error.to_string())?;
    fs::write(&report_path, &encoded).map_err(display_io("write audit report", &report_path))?;
    println!("{}", String::from_utf8_lossy(&encoded));

    if !sequential_control_passed {
        return Err("sequential control failed; overlap evidence is not authoritative".to_owned());
    }
    Ok(())
}

fn run_overlap_trial(executable: &Path, root: &Path, name: &str) -> Result<TrialEvidence, String> {
    let store = root.join(name);
    let ready = root.join(format!("{name}.ready"));
    let release = root.join(format!("{name}.release"));
    let mut writer_a = spawn_hold_child(executable, &store, &ready, &release, WRITER_A_KEY)?;
    wait_for_path_or_child(&ready, &mut writer_a, CHILD_TIMEOUT)?;

    let writer_b = run_write_child(executable, &store, WRITER_B_KEY)?;
    fs::write(&release, b"release\n").map_err(display_io("write release signal", &release))?;
    let writer_a = ChildEvidence::from(
        writer_a
            .wait_with_output()
            .map_err(|error| format!("wait for writer A: {error}"))?,
    );
    let files_before_probe = census_files(&store)?;
    let probe = probe_store(&store);
    let files_after_probe = census_files(&store)?;
    let hazard = !writer_a.success || !writer_b.success || !probe.both_present();

    Ok(TrialEvidence {
        name: name.to_owned(),
        store: store.display().to_string(),
        writer_a,
        writer_b,
        files_before_probe,
        probe,
        files_after_probe,
        concurrent_writer_hazard: hazard,
    })
}

fn spawn_hold_child(
    executable: &Path,
    store: &Path,
    ready: &Path,
    release: &Path,
    key: &str,
) -> Result<Child, String> {
    Command::new(executable)
        .arg("--hold")
        .arg(store)
        .arg(ready)
        .arg(release)
        .arg(key)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("spawn writer A: {error}"))
}

fn run_write_child(executable: &Path, store: &Path, key: &str) -> Result<ChildEvidence, String> {
    Command::new(executable)
        .arg("--write")
        .arg(store)
        .arg(key)
        .output()
        .map(ChildEvidence::from)
        .map_err(|error| format!("run writer child: {error}"))
}

fn hold_then_write(store: &Path, ready: &Path, release: &Path, key: &str) -> Result<(), String> {
    let mut engine = open_store(store)?;
    fs::write(ready, b"ready\n").map_err(display_io("write ready signal", ready))?;
    wait_for_path(release, CHILD_TIMEOUT)?;
    persist_node(&mut engine, key)?;
    engine
        .close()
        .map_err(|error| format!("close held writer store: {error}"))?;
    println!("held writer persisted {key}");
    Ok(())
}

fn write_once(store: &Path, key: &str) -> Result<(), String> {
    let mut engine = open_store(store)?;
    persist_node(&mut engine, key)?;
    engine
        .close()
        .map_err(|error| format!("close writer store: {error}"))?;
    println!("writer persisted {key}");
    Ok(())
}

fn open_store(store: &Path) -> Result<DatabaseEngine, String> {
    let options = DbOptions {
        compact_after_n_flushes: 0,
        wal_sync_mode: WalSyncMode::Immediate,
        memtable_hard_cap_bytes: 0,
        max_immutable_memtables: 0,
        ..DbOptions::default()
    };
    DatabaseEngine::open(store, &options)
        .map_err(|error| format!("open {}: {error}", store.display()))
}

fn persist_node(engine: &mut DatabaseEngine, key: &str) -> Result<(), String> {
    let mut props = BTreeMap::new();
    props.insert("writer".to_owned(), PropValue::String(key.to_owned()));
    engine
        .upsert_node(
            TYPE_AUDIT_WRITER,
            key,
            UpsertNodeOptions {
                props,
                ..UpsertNodeOptions::default()
            },
        )
        .map_err(|error| format!("upsert {key}: {error}"))?;
    engine
        .flush()
        .map_err(|error| format!("flush {key}: {error}"))?;
    Ok(())
}

fn probe_store(store: &Path) -> ProbeEvidence {
    let engine = match open_store(store) {
        Ok(engine) => engine,
        Err(error) => {
            return ProbeEvidence {
                opened: false,
                writer_a_present: false,
                writer_b_present: false,
                error: Some(error),
            };
        }
    };
    let writer_a = engine.get_node_by_key(TYPE_AUDIT_WRITER, WRITER_A_KEY);
    let writer_b = engine.get_node_by_key(TYPE_AUDIT_WRITER, WRITER_B_KEY);
    let close = engine.close();
    match (writer_a, writer_b, close) {
        (Ok(writer_a), Ok(writer_b), Ok(())) => ProbeEvidence {
            opened: true,
            writer_a_present: writer_a.is_some(),
            writer_b_present: writer_b.is_some(),
            error: None,
        },
        (writer_a, writer_b, close) => ProbeEvidence {
            opened: true,
            writer_a_present: writer_a.as_ref().is_ok_and(|node| node.is_some()),
            writer_b_present: writer_b.as_ref().is_ok_and(|node| node.is_some()),
            error: Some(format!(
                "read/close failure: writer_a={:?}; writer_b={:?}; close={close:?}",
                writer_a.err(),
                writer_b.err()
            )),
        },
    }
}

fn wait_for_path_or_child(path: &Path, child: &mut Child, timeout: Duration) -> Result<(), String> {
    let started = Instant::now();
    loop {
        if path.exists() {
            return Ok(());
        }
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("poll held writer: {error}"))?
        {
            return Err(format!(
                "held writer exited before ready signal with {status}"
            ));
        }
        if started.elapsed() >= timeout {
            return Err(format!("timed out waiting for {}", path.display()));
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn wait_for_path(path: &Path, timeout: Duration) -> Result<(), String> {
    let started = Instant::now();
    while !path.exists() {
        if started.elapsed() >= timeout {
            return Err(format!("timed out waiting for {}", path.display()));
        }
        thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}

fn census_files(root: &Path) -> Result<Vec<FileEvidence>, String> {
    let mut files = Vec::new();
    visit_files(root, root, &mut files)?;
    files.sort_unstable_by(|left, right| left.path.cmp(&right.path));
    Ok(files)
}

fn visit_files(root: &Path, directory: &Path, files: &mut Vec<FileEvidence>) -> Result<(), String> {
    for entry in fs::read_dir(directory).map_err(display_io("read audit directory", directory))? {
        let entry = entry.map_err(|error| error.to_string())?;
        let path = entry.path();
        let file_type = entry.file_type().map_err(|error| error.to_string())?;
        if file_type.is_dir() {
            visit_files(root, &path, files)?;
        } else if file_type.is_file() {
            let mut file =
                fs::File::open(&path).map_err(display_io("open evidence file", &path))?;
            let mut hasher = blake3::Hasher::new();
            io::copy(&mut file, &mut hasher).map_err(|error| error.to_string())?;
            let bytes = entry.metadata().map_err(|error| error.to_string())?.len();
            files.push(FileEvidence {
                path: path
                    .strip_prefix(root)
                    .unwrap_or(&path)
                    .to_string_lossy()
                    .replace('\\', "/"),
                bytes,
                blake3: hasher.finalize().to_hex().to_string(),
            });
        }
    }
    Ok(())
}

fn display_io<'a>(action: &'a str, path: &'a Path) -> impl FnOnce(io::Error) -> String + 'a {
    move |error| format!("{action} {}: {error}", path.display())
}

fn required_utf8<'a>(value: &'a std::ffi::OsStr, label: &str) -> Result<&'a str, String> {
    value
        .to_str()
        .ok_or_else(|| format!("{label} must be valid UTF-8"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_requires_both_writers() {
        let probe = ProbeEvidence {
            opened: true,
            writer_a_present: true,
            writer_b_present: false,
            error: None,
        };
        assert!(!probe.both_present());
    }

    #[test]
    fn audit_file_stays_below_repository_limit() {
        assert!(
            include_str!("overgraph-concurrent-writer-audit.rs")
                .lines()
                .count()
                < 800
        );
    }
}
