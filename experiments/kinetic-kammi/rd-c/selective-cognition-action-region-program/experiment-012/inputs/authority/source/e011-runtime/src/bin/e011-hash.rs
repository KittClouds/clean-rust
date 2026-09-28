use std::{env, fs, io::Read};

fn main() {
    if let Err(error) = run() {
        eprintln!("e011-hash: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let bytes = match args.next() {
        Some(path) if path == "--stdin" => {
            let mut bytes = Vec::new();
            std::io::stdin().read_to_end(&mut bytes)?;
            bytes
        }
        Some(path) => fs::read(path)?,
        None => return Err("expected a file path or --stdin".into()),
    };
    if args.next().is_some() {
        return Err("expected exactly one input".into());
    }
    println!("{}", blake3::hash(&bytes).to_hex());
    Ok(())
}
