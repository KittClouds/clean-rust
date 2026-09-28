use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use anyhow::{Context, Result};
use jev_decision_world_v01::{
    GenerationConfig, all_templates, generate_episode, generate_pilot_report, validate_jsonl,
};

fn main() -> Result<()> {
    let options = Options::parse(std::env::args().skip(1))?;
    let config = GenerationConfig {
        seed: options.seed,
        count: options.count,
        visibility_probability: options.visibility_probability,
    };
    let templates = all_templates();
    let report = generate_pilot_report(&config)?;
    if let Some(output) = options.output.as_ref() {
        let file =
            File::create(output).with_context(|| format!("creating {}", output.display()))?;
        let mut writer = BufWriter::new(file);
        for sequence in 0..config.count {
            let template = &templates[sequence % templates.len()];
            let episode = generate_episode(template, sequence, &config)?;
            serde_json::to_writer(&mut writer, &episode)?;
            writer.write_all(b"\n")?;
        }
        writer.flush()?;
        let validation = validate_jsonl(output, &templates)?;
        eprintln!(
            "JSONL validation: {}/{} episodes passed",
            validation.episodes - validation.failed,
            validation.episodes
        );
        if validation.failed != 0 {
            anyhow::bail!("generated JSONL failed validation: {:?}", validation.errors);
        }
    }
    let rendered = serde_json::to_string_pretty(&report)?;
    if let Some(report_path) = options.report.as_ref() {
        std::fs::write(report_path, rendered.as_bytes())
            .with_context(|| format!("writing {}", report_path.display()))?;
    } else {
        println!("{rendered}");
    }
    Ok(())
}

#[derive(Debug)]
struct Options {
    count: usize,
    seed: u64,
    visibility_probability: f64,
    output: Option<PathBuf>,
    report: Option<PathBuf>,
}

impl Options {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self> {
        let mut options = Self {
            count: 1_000,
            seed: 0x4a_45_56_00_01,
            visibility_probability: 0.80,
            output: None,
            report: None,
        };
        while let Some(argument) = args.next() {
            match argument.as_str() {
                "--count" => {
                    options.count = args.next().context("--count needs a value")?.parse()?
                }
                "--seed" => options.seed = args.next().context("--seed needs a value")?.parse()?,
                "--visibility" => {
                    options.visibility_probability =
                        args.next().context("--visibility needs a value")?.parse()?
                }
                "--output" => {
                    options.output =
                        Some(PathBuf::from(args.next().context("--output needs a path")?))
                }
                "--report" => {
                    options.report =
                        Some(PathBuf::from(args.next().context("--report needs a path")?))
                }
                "--help" | "-h" => {
                    println!(
                        "jev-decision-world-v01 --count N --seed N --visibility P --output FILE --report FILE"
                    );
                    std::process::exit(0);
                }
                other => anyhow::bail!("unknown argument {other}"),
            }
        }
        Ok(options)
    }
}
