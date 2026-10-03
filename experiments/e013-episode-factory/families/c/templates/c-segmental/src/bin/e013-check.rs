use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("e013-check: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let family = env::var("E013_FAMILY_ID").map_err(|_| "missing E013_FAMILY_ID")?;
    let fixture = if let Ok(path) = env::var("E013_HIDDEN_ADJUDICATOR") {
        PathBuf::from(path)
    } else {
        let root = env::var("E013_VISIBLE_ROOT").map_err(|_| "missing fixture root")?;
        PathBuf::from(root).join("visible/cases.tsv")
    };
    let bytes = fs::read(fixture).map_err(|error| error.to_string())?;
    let mut cases = Vec::new();
    for (line_number, line) in bytes.split(|byte| *byte == b'\n').enumerate() {
        if line.is_empty() || line.starts_with(b"#") {
            continue;
        }
        let (input_hex, expected_hex) = split_record(line)
            .ok_or_else(|| format!("bad record at line {}", line_number + 1))?;
        let input = decode_hex(input_hex)?;
        let expected = decode_hex(expected_hex)?;
        cases.push((line_number + 1, input, expected));
    }
    for key in ["E013_HIDDEN_ADJUDICATOR", "E013_HIDDEN_ROOT", "E013_VISIBLE_ROOT", "E013_FAMILY_ID", "E013_CANDIDATE_ID"] {
        env::remove_var(key);
    }
    for (line_number, input, expected) in cases {
        let actual = c_segmental::dispatch(&family, &input)
            .ok_or_else(|| format!("unknown family {family}"))?;
        if actual != expected {
            return Err(format!("behavior mismatch at line {}", line_number + 1));
        }
    }
    Ok(())
}

fn split_record(line: &[u8]) -> Option<(&[u8], &[u8])> {
    let separator = line.iter().position(|byte| *byte == b'\t')?;
    Some((&line[..separator], &line[separator + 1..]))
}

fn decode_hex(input: &[u8]) -> Result<Vec<u8>, String> {
    if input.len() % 2 != 0 {
        return Err("odd-length hexadecimal field".to_string());
    }
    let mut output = Vec::with_capacity(input.len() / 2);
    for pair in input.chunks_exact(2) {
        let high = hex_nibble(pair[0]).ok_or_else(|| "invalid hexadecimal field".to_string())?;
        let low = hex_nibble(pair[1]).ok_or_else(|| "invalid hexadecimal field".to_string())?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

fn hex_nibble(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}
