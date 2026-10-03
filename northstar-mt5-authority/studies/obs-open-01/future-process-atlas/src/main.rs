use obs_open_03a::{compare_builds, copy_compact_seal, execute};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .ok_or("USAGE: obs-open-03a execute|compare|seal ...")?;
    match command.to_string_lossy().as_ref() {
        "execute" => {
            let repo = PathBuf::from(args.next().ok_or("MISSING_REPOSITORY_ROOT")?);
            let out = PathBuf::from(args.next().ok_or("MISSING_OUTPUT_DIRECTORY")?);
            if args.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            let root = execute(&repo, &out)?;
            println!("OBS_OPEN_03A_ROOT={root}");
        }
        "compare" => {
            let left = PathBuf::from(args.next().ok_or("MISSING_LEFT_BUILD")?);
            let right = PathBuf::from(args.next().ok_or("MISSING_RIGHT_BUILD")?);
            if args.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            let receipt = compare_builds(&left, &right)?;
            println!("ARTIFACT_COUNT={}", receipt.artifact_count);
            println!("MISMATCH_COUNT={}", receipt.mismatch_count);
            println!("ROOT={}", receipt.root);
            if receipt.mismatch_count != 0 {
                return Err("REBUILD_MISMATCH".into());
            }
        }
        "seal" => {
            let build = PathBuf::from(args.next().ok_or("MISSING_BUILD")?);
            let seal = PathBuf::from(args.next().ok_or("MISSING_SEAL")?);
            if args.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            println!("OBS_OPEN_03A_ROOT={}", copy_compact_seal(&build, &seal)?);
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    }
    Ok(())
}
