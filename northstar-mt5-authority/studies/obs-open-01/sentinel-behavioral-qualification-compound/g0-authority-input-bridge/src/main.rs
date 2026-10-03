use obs_open_04a_g0::seal::{build, copy_seal, finalize, verify};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().collect::<Vec<_>>();
    match args.get(1).map(String::as_str) {
        Some("build") if args.len() == 5 => println!(
            "{}",
            build(
                &PathBuf::from(&args[2]),
                &PathBuf::from(&args[3]),
                &PathBuf::from(&args[4])
            )?
        ),
        Some("finalize") if args.len() == 4 => println!(
            "{}",
            finalize(&PathBuf::from(&args[2]), &PathBuf::from(&args[3]))?
        ),
        Some("copy-seal") if args.len() == 4 => println!(
            "{}",
            copy_seal(&PathBuf::from(&args[2]), &PathBuf::from(&args[3]))?
        ),
        Some("verify") if args.len() == 3 => println!("{}", verify(&PathBuf::from(&args[2]))?),
        _ => {
            return Err(
                "usage: obs-open-04a-g0 <build REPO CANONICAL_REPO OUT|finalize LEFT RIGHT|copy-seal BUILD SEAL|verify ROOT>"
                    .into(),
            );
        }
    }
    Ok(())
}
