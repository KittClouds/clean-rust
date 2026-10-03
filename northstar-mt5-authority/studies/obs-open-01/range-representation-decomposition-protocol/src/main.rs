use obs_open_03b2p::seal::{build, copy_seal, finalize, verify};
use std::path::PathBuf;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a = std::env::args().collect::<Vec<_>>();
    match a.get(1).map(String::as_str){Some("build")if a.len()==4=>println!("{}",build(&PathBuf::from(&a[2]),&PathBuf::from(&a[3]))?),Some("finalize")if a.len()==4=>println!("{}",finalize(&PathBuf::from(&a[2]),&PathBuf::from(&a[3]))?),Some("copy-seal")if a.len()==4=>println!("{}",copy_seal(&PathBuf::from(&a[2]),&PathBuf::from(&a[3]))?),Some("verify")if a.len()==3=>println!("{}",verify(&PathBuf::from(&a[2]))?),_=>return Err("usage: obs-open-03b2p <build REPO OUT|finalize LEFT RIGHT|copy-seal BUILD SEAL|verify ROOT>".into())}
    Ok(())
}
