//! ```text
//! kammi-migrate import    --v1 <python store> --v2 <rust store>   create or resume
//! kammi-migrate verify    --v2 <rust store>                        deep verification
//! kammi-migrate export-v1 --v2 <rust store> --out <new dir>        exact v1 layout
//! kammi-migrate compare   --v1 <store a> --v1 <store b>            byte-level equality
//! ```
//! The v1 store is only ever read, with shared handles and positional reads.

use std::path::PathBuf;
use std::process::ExitCode;

use kammi_migrate::{compare_v1, export_v1, sync};
use kammi_store::{Store, StoreOptions};
use kammi_v1::V1Store;

fn flag(args: &[String], name: &str) -> Vec<PathBuf> {
    args.windows(2)
        .filter(|w| w[0] == name)
        .map(|w| PathBuf::from(&w[1]))
        .collect()
}

fn run(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let command = args.get(1).map(String::as_str).unwrap_or("");
    let v2 = flag(args, "--v2");
    let v1 = flag(args, "--v1");
    match command {
        "import" => {
            let source = V1Store::open(v1.first().ok_or("--v1 required")?)?;
            let root = v2.first().ok_or("--v2 required")?;
            let mut store = if root.join("STORE.json").exists() {
                Store::open(root, StoreOptions::default())?
            } else {
                Store::create(root, StoreOptions::default())?
            };
            let report = sync(&source, &mut store)?;
            println!(
                "main {} (+{}), memory {} (+{}), objects copied {} ({} bytes), payloads inlined {}, {:.2}s",
                store.main.head(),
                report.main.appended,
                store.memory.head(),
                report.memory.appended,
                report.objects_copied,
                report.object_bytes_copied,
                report.payload_objects_inlined,
                report.seconds
            );
        }
        "verify" => {
            let store = Store::open(v2.first().ok_or("--v2 required")?, StoreOptions::default())?;
            let report = store.verify_deep()?;
            println!("{report:#?}");
        }
        "export-v1" => {
            let store = Store::open(v2.first().ok_or("--v2 required")?, StoreOptions::default())?;
            let out = flag(args, "--out");
            let report = export_v1(&store, out.first().ok_or("--out required")?)?;
            println!("{report:?}");
        }
        "compare" => {
            let [a, b] = v1.as_slice() else {
                return Err("compare needs two --v1 roots".into());
            };
            let (main, memory, objects) = compare_v1(&V1Store::open(a)?, &V1Store::open(b)?)?;
            println!("identical: main {main} bytes, memory {memory} bytes, {objects} objects");
        }
        _ => return Err("usage: kammi-migrate import|verify|export-v1|compare ...".into()),
    }
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
