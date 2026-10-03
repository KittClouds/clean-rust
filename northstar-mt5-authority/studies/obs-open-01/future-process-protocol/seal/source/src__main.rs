use obs_open_03ap::{build_protocol, compare_builds};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .ok_or("USAGE: obs-open-03ap build|compare ...")?;
    match command.to_string_lossy().as_ref() {
        "build" => {
            let repo = PathBuf::from(args.next().ok_or("MISSING_REPOSITORY_ROOT")?);
            let output = PathBuf::from(args.next().ok_or("MISSING_OUTPUT_DIRECTORY")?);
            if args.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            let root = build_protocol(&repo, &output)?;
            println!("OBS_OPEN_03AP_ROOT={root}");
        }
        "compare" => {
            let left = PathBuf::from(args.next().ok_or("MISSING_LEFT_BUILD")?);
            let right = PathBuf::from(args.next().ok_or("MISSING_RIGHT_BUILD")?);
            if args.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            let result = compare_builds(&left, &right)?;
            println!("ARTIFACT_COUNT={}", result.artifact_count);
            println!("MISMATCH_COUNT={}", result.mismatch_count);
            println!("ROOT={}", result.root);
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    }
    Ok(())
}
