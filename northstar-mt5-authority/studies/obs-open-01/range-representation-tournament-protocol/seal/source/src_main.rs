use obs_open_03bp::{build_protocol, copy_seal, finalize_rebuild};
use std::path::PathBuf;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut a = std::env::args_os().skip(1);
    let cmd = a.next().ok_or("USAGE execute|finalize|seal")?;
    match cmd.to_string_lossy().as_ref() {
        "execute" => {
            let repo = PathBuf::from(a.next().ok_or("MISSING_REPO")?);
            let atlas = PathBuf::from(a.next().ok_or("MISSING_ATLAS")?);
            let out = PathBuf::from(a.next().ok_or("MISSING_OUT")?);
            println!(
                "OBS_OPEN_03BP_ROOT={}",
                build_protocol(&repo, &atlas, &out)?
            );
        }
        "finalize" => {
            let left = PathBuf::from(a.next().ok_or("MISSING_LEFT")?);
            let right = PathBuf::from(a.next().ok_or("MISSING_RIGHT")?);
            println!("OBS_OPEN_03BP_ROOT={}", finalize_rebuild(&left, &right)?);
        }
        "seal" => {
            let build = PathBuf::from(a.next().ok_or("MISSING_BUILD")?);
            let seal = PathBuf::from(a.next().ok_or("MISSING_SEAL")?);
            println!("OBS_OPEN_03BP_ROOT={}", copy_seal(&build, &seal)?);
        }
        _ => return Err("UNKNOWN_COMMAND".into()),
    }
    if a.next().is_some() {
        return Err("UNEXPECTED_ARGUMENT".into());
    }
    Ok(())
}
