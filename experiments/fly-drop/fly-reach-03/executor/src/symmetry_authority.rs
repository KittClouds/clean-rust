use super::*;

pub(super) fn verify_preflight_manifest(study: &Path, out: &Path) -> Result<()> {
    let manifest_path = out.join("SOURCE-INPUT-MANIFEST.json");
    let receipt: Value = serde_json::from_slice(&fs::read(
        out.join("IMPLEMENTATION-PREFLIGHT-RECEIPT.json"),
    )?)?;
    ensure!(
        receipt["status"] == "PASS",
        "implementation preflight has not passed"
    );
    ensure!(
        receipt["controlling_contract_sha256"] == CONTRACT_SHA256,
        "preflight contract mismatch"
    );
    let raw = fs::read(&manifest_path)?;
    ensure!(
        sha256(&raw)
            == receipt["source_manifest_file_sha256"]
                .as_str()
                .context("source manifest file hash")?,
        "source manifest file hash mismatch"
    );
    let manifest: Value = serde_json::from_slice(&raw)?;
    ensure!(manifest["schema"] == "F4-SYMMETRY-01-source-input-manifest-v1");
    let canonical = serde_json::to_vec(&manifest)?;
    ensure!(
        sha256(&canonical)
            == receipt["source_manifest_sha256"]
                .as_str()
                .context("canonical source manifest hash")?,
        "canonical source manifest hash mismatch"
    );
    let repo = study
        .parent()
        .context("study parent")?
        .parent()
        .context("repo parent")?;
    for entry in manifest["entries"].as_array().context("manifest entries")? {
        let relative = entry["path"].as_str().context("manifest path")?;
        ensure!(
            !relative.split('/').any(|part| part == "." || part == ".."),
            "unsafe source path {relative}"
        );
        let path = repo.join(relative);
        let bytes =
            fs::read(&path).with_context(|| format!("source artifact {}", path.display()))?;
        ensure!(
            bytes.len() as u64
                == entry["byte_length"]
                    .as_u64()
                    .context("source byte length")?,
            "source length drift at {relative}"
        );
        ensure!(
            sha256(&bytes) == entry["sha256"].as_str().context("source hash")?,
            "source hash drift at {relative}"
        );
    }
    Ok(())
}
