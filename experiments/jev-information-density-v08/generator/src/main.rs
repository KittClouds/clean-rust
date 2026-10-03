mod generate;
mod metadata;
mod project;
mod worlds;

use anyhow::{Context, Result, bail};
use std::path::PathBuf;

fn main() -> Result<()> {
    let mut roots = 31_250_usize;
    let mut seed = 0x4a45_565f_4944_5638_u64;
    let mut output: Option<PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--roots" => roots = args.next().context("--roots needs an integer")?.parse()?,
            "--seed" => seed = args.next().context("--seed needs an integer")?.parse()?,
            "--out" => output = Some(PathBuf::from(args.next().context("--out needs a path")?)),
            "--help" | "-h" => {
                println!("jev-information-density-v08-generator --out PATH [--roots N] [--seed N]");
                return Ok(());
            }
            unknown => bail!("unknown argument {unknown}"),
        }
    }
    let output =
        output.context("--out is required; generated data must remain outside the repository")?;
    anyhow::ensure!(roots > 0, "--roots must be nonzero");
    generate::run(roots, seed, &output)
}
