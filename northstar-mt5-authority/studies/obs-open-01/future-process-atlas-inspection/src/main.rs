use obs_open_03ai::{compare_builds, copy_compact_seal, execute};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut a = std::env::args_os().skip(1);
    let cmd = a.next().ok_or("USAGE: execute|compare|seal")?;
    match cmd.to_string_lossy().as_ref() {
        "execute" => {
            let repo = PathBuf::from(a.next().ok_or("MISSING_REPOSITORY")?);
            let parent = PathBuf::from(a.next().ok_or("MISSING_PARENT_ATLAS")?);
            let out = PathBuf::from(a.next().ok_or("MISSING_OUTPUT")?);
            if a.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            println!("OBS_OPEN_03AI_ROOT={}", execute(&repo, &parent, &out)?);
        }
        "compare" => {
            let left = PathBuf::from(a.next().ok_or("MISSING_LEFT")?);
            let right = PathBuf::from(a.next().ok_or("MISSING_RIGHT")?);
            let receipt = PathBuf::from(a.next().ok_or("MISSING_RECEIPT")?);
            if a.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            let r = compare_builds(&left, &right, &receipt)?;
            println!(
                "ARTIFACT_COUNT={}\nMISMATCH_COUNT={}\nROOT={}",
                r.artifact_count, r.mismatch_count, r.left_root
            );
            if r.mismatch_count != 0 {
                return Err("REBUILD_MISMATCH".into());
            }
        }
        "seal" => {
            let build = PathBuf::from(a.next().ok_or("MISSING_BUILD")?);
            let seal = PathBuf::from(a.next().ok_or("MISSING_SEAL")?);
            let receipt = PathBuf::from(a.next().ok_or("MISSING_REBUILD_RECEIPT")?);
            if a.next().is_some() {
                return Err("UNEXPECTED_ARGUMENT".into());
            }
            println!(
                "OBS_OPEN_03AI_ROOT={}",
                copy_compact_seal(&build, &seal, &receipt)?
            );
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    }
    Ok(())
}
