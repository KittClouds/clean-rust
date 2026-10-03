mod audit;
mod materialize;
mod types;

use std::path::PathBuf;

fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    let result = match args.as_slice() {
        [_, command, output] if command == "qualify" => {
            materialize::qualify(PathBuf::from(output).as_path())
        }
        _ => Err("usage: fas00-phase1 qualify <new-empty-output-directory>".to_owned()),
    };
    if let Err(error) = result {
        eprintln!("FAS00_PHASE1_FAIL_CLOSED: {error}");
        std::process::exit(1);
    }
}
