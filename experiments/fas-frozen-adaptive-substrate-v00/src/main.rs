use fas00::{
    validate::{validate, validate_split_integrity, validate_triplet},
    world::{DEFAULT_EVENTS, Family, Feedback, Split, Track, WorldConfig, generate},
};
use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};

fn smoke() -> Result<(), String> {
    let mut configs = Vec::new();
    for split in [
        Split::Initialization,
        Split::Qualification,
        Split::Evaluation,
    ] {
        for family in Family::ALL {
            for track in [Track::GlobalRule, Track::ContextBound] {
                for feedback in [Feedback::Immediate, Feedback::Delayed8] {
                    let config = WorldConfig {
                        world_seed: 7101,
                        split,
                        family,
                        track,
                        feedback,
                        events: DEFAULT_EVENTS,
                        label_rotation: 0,
                    };
                    let first = generate(&config)?;
                    let second = generate(&config)?;
                    if first != second {
                        return Err("seed determinism failed".into());
                    }
                    validate(&config, &first)?;
                    validate_triplet(&config)?;
                    configs.push(config);
                }
            }
        }
    }
    validate_split_integrity(&configs)?;
    println!(
        "GENERATOR_SMOKE_PASS worlds={} events_per_world={}",
        configs.len(),
        DEFAULT_EVENTS
    );
    Ok(())
}

fn write_world(config_path: &Path, output_path: &Path) -> Result<(), String> {
    if output_path.exists() {
        return Err("refusing to overwrite output".into());
    }
    let input = std::fs::read(config_path).map_err(|e| e.to_string())?;
    let config: WorldConfig = serde_json::from_slice(&input).map_err(|e| e.to_string())?;
    let events = generate(&config)?;
    validate(&config, &events)?;
    let file = File::create_new(output_path).map_err(|e| e.to_string())?;
    let mut writer = BufWriter::new(file);
    for event in events {
        serde_json::to_writer(&mut writer, &event).map_err(|e| e.to_string())?;
        writer.write_all(b"\n").map_err(|e| e.to_string())?;
    }
    writer.flush().map_err(|e| e.to_string())?;
    Ok(())
}

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let result = match args.as_slice() {
        [_, command] if command == "smoke" => smoke(),
        [_, command, config, output] if command == "generate" => {
            write_world(Path::new(config), Path::new(output))
        }
        _ => Err("usage: fas00 smoke | fas00 generate <config.json> <new-output.jsonl>".into()),
    };
    if let Err(error) = result {
        eprintln!("FAS00_FAIL: {error}");
        std::process::exit(1);
    }
}
