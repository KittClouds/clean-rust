use std::{env, fs, path::PathBuf, process::ExitCode};

fn main() -> ExitCode {
    let mut any = false;
    for arg in env::args_os().skip(1) {
        any = true;
        let path: PathBuf = arg.into();
        let bytes = match fs::read(&path) {
            Ok(bytes) => bytes,
            Err(error) => {
                eprintln!("{}: {error}", path.display());
                return ExitCode::FAILURE;
            }
        };
        println!("{}\t{}", path.display(), blake3::hash(&bytes).to_hex());
    }
    if any { ExitCode::SUCCESS } else { ExitCode::FAILURE }
}
