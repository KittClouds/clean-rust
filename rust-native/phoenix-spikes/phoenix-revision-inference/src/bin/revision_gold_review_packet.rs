use std::path::PathBuf;

use phoenix_revision_inference::{build_gold_review_packet, render_gold_review_markdown};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let packet = build_gold_review_packet()?;
    let directory = std::env::var_os("PHOENIX_REVISION_REVIEW_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"D:\phoenix-target-revision-impact-duel\reviews"));
    std::fs::create_dir_all(&directory)?;
    let stem = packet.review_token.replace(':', "-");
    let json_path = directory.join(format!("{stem}.json"));
    let markdown_path = directory.join(format!("{stem}.md"));
    write_new_or_identical(&json_path, &serde_json::to_vec_pretty(&packet)?)?;
    write_new_or_identical(
        &markdown_path,
        render_gold_review_markdown(&packet).as_bytes(),
    )?;
    println!("review_token={}", packet.review_token);
    println!("json={}", json_path.display());
    println!("markdown={}", markdown_path.display());
    Ok(())
}

fn write_new_or_identical(path: &std::path::Path, contents: &[u8]) -> std::io::Result<()> {
    use std::io::Write;

    if path.is_file() {
        let existing = std::fs::read(path)?;
        if existing == contents {
            return Ok(());
        }
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            format!("review artifact differs at {}", path.display()),
        ));
    }
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)?;
    file.write_all(contents)?;
    file.sync_all()
}
