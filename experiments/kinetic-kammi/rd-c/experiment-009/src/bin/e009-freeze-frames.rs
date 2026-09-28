use std::{env, fs};

use rdc_experiment_009::frame::CodingObservationFrame;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    frames: Vec<CodingObservationFrame>,
}

#[derive(Serialize)]
struct LockedFrame {
    frame: CodingObservationFrame,
    blake3: String,
}

#[derive(Serialize)]
struct Output {
    schema_version: u16,
    frames: Vec<LockedFrame>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let input_path = args.next().ok_or("missing input path")?;
    let output_path = args.next().ok_or("missing output path")?;
    if args.next().is_some() {
        return Err("expected exactly two paths".into());
    }

    let input: Input = serde_json::from_slice(&fs::read(input_path)?)?;
    let mut frames = Vec::with_capacity(input.frames.len());
    for mut frame in input.frames {
        frame.normalize();
        for evidence in &mut frame.evidence {
            evidence.content_blake3 = blake3::hash(evidence.content.as_bytes())
                .to_hex()
                .to_string();
        }
        frame
            .validate()
            .map_err(|error| format!("frame validation failed: {error:?}"))?;
        let digest = blake3::Hash::from_bytes(frame.frame_hash()?);
        frames.push(LockedFrame {
            frame,
            blake3: digest.to_hex().to_string(),
        });
    }

    let output = Output {
        schema_version: 1,
        frames,
    };
    fs::write(output_path, serde_json::to_vec_pretty(&output)?)?;
    Ok(())
}
