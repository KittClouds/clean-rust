#![allow(dead_code)]

#[path = "../../../jev-information-density-v08n/generator/src/generator.rs"]
mod base_generator;
#[path = "../../../jev-information-density-v08n/generator/src/families.rs"]
mod families;

use anyhow::{Context, Result, ensure};
use jev_decision_world_v01 as world;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use base_generator::{Triplet, build_triplet};
use families::{FamilySpec, TRAIN_FAMILY_COUNT};

const PARTITION: &str = "eval_v08q_r3_calibration_v02";
const FAMILY_ORDER: [&str; 4] = [
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
];
const NEIGHBORHOODS_PER_FAMILY: usize = 500;
const CANDIDATE_BUDGET_PER_FAMILY: usize = 800;

#[derive(Deserialize)]
struct RenderedDenylist {
    schema: String,
    count: usize,
    identity_sha256: Vec<String>,
}

#[derive(Serialize)]
struct PanelRow<'a> {
    neighborhood_id: &'a str,
    world_id: String,
    root_id: String,
    episode_id: &'a str,
    family_slug: &'a str,
    sequence: usize,
    direction: &'static str,
    view: &'static str,
    old_semantic_id: String,
    new_semantic_id: String,
    candidate_semantic_ids: Vec<String>,
    candidate_order_sha256: String,
    selector_input_hash: String,
    full_rendered_input_hash: String,
    text: &'a str,
    target: Vec<f64>,
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let out = PathBuf::from(args.next().context("output directory required")?);
    let seed: u64 = args
        .next()
        .context("panel seed required")?
        .parse()
        .context("panel seed must be u64")?;
    let denylist_path = PathBuf::from(
        args.next()
            .context("rendered-input denylist path required")?,
    );
    let expected_denylist_sha256 = args.next().context("expected denylist SHA-256 required")?;
    ensure!(args.next().is_none(), "unexpected positional argument");
    generate(&out, seed, &denylist_path, &expected_denylist_sha256)
}

fn generate(
    out: &std::path::Path,
    seed: u64,
    denylist_path: &std::path::Path,
    expected_denylist_sha256: &str,
) -> Result<()> {
    ensure!(
        !out.exists(),
        "refusing to reuse output directory: {}",
        out.display()
    );
    let denylist_bytes = fs::read(denylist_path).context("read exact rendered-input denylist")?;
    let denylist_sha256 = sha256(&denylist_bytes);
    ensure!(
        denylist_sha256 == expected_denylist_sha256,
        "rendered-input denylist hash mismatch"
    );
    let denylist: RenderedDenylist = serde_json::from_slice(&denylist_bytes)?;
    let external = denylist
        .identity_sha256
        .into_iter()
        .collect::<BTreeSet<_>>();
    ensure!(
        denylist.schema == "r3-full-rendered-input-domain-hash-set-v01"
            && denylist.count == external.len(),
        "rendered-input denylist schema/count mismatch"
    );
    fs::create_dir_all(out)?;
    let mut panel = writer(out.join("calibration-panel-views.jsonl"))?;
    let mut candidates = writer(out.join("candidate-texts.jsonl"))?;
    let mut admission = writer(out.join("candidate-admission-receipts.jsonl"))?;
    let all = families::all_families();
    let mut rows_written = 0usize;
    let mut direction_counts = [[0usize; 2]; 4];
    let mut admitted_rendered = BTreeSet::new();
    let mut rejected = 0usize;

    for (family_index, slug) in FAMILY_ORDER.iter().enumerate() {
        let spec = all[TRAIN_FAMILY_COUNT..]
            .iter()
            .find(|candidate| candidate.slug == *slug)
            .with_context(|| format!("held-out family not found: {slug}"))?;
        write_candidate_texts(&mut candidates, spec)?;

        for candidate_ordinal in 0..CANDIDATE_BUDGET_PER_FAMILY {
            if direction_counts[family_index]
                .iter()
                .all(|count| *count == 250)
            {
                break;
            }
            // Cycle all four generative profiles within each direction. Direction
            // is fixed by stream blocks, not candidate slot or profile identity.
            let high_to_low = (candidate_ordinal / 4) % 2 == 0;
            let direction_index = usize::from(!high_to_low);
            if direction_counts[family_index][direction_index] == 250 {
                continue;
            }
            let sequence = candidate_ordinal;
            let triplet = build_triplet(spec, PARTITION, sequence, seed)?;
            let (anchor_index, fact_index, old_index, new_index, direction) = if high_to_low {
                (0, 1, 0, 1, "high_to_low")
            } else {
                (1, 0, 1, 0, "low_to_high")
            };
            let candidate_ids = candidate_ids(spec);
            let anchor_target = target(&triplet, anchor_index)?;
            let fact_target = target(&triplet, fact_index)?;
            ensure!(
                winner(&anchor_target) == old_index,
                "anchor target violates semantic old role"
            );
            ensure!(
                winner(&fact_target) == new_index,
                "fact target violates semantic new role"
            );

            let mut pending = Vec::with_capacity(2);
            let mut collisions = BTreeSet::new();
            for (view, episode_index, target) in [
                ("anchor", anchor_index, anchor_target),
                ("fact", fact_index, fact_target),
            ] {
                let episode = &triplet.exact_episodes[episode_index];
                let text = episode
                    .renderings
                    .first()
                    .context("exact episode rendering missing")?
                    .text
                    .as_str();
                let rendered_hash = sha256(text.as_bytes());
                let identity_digest = rendered_identity_digest(&rendered_hash);
                if external.contains(&identity_digest)
                    || admitted_rendered.contains(&identity_digest)
                {
                    collisions.insert(identity_digest.clone());
                }
                pending.push((view, episode_index, target, text, rendered_hash));
            }
            ensure!(
                pending[0].4 != pending[1].4,
                "anchor and fact view rendered to identical model input"
            );
            if !collisions.is_empty() {
                write_jsonl(
                    &mut admission,
                    &json!({
                        "candidate_ordinal": candidate_ordinal,
                        "family_slug": spec.slug,
                        "direction": direction,
                        "accepted": false,
                        "collision_field_names": ["full_rendered_input_hash"],
                        "collision_value_hashes": collisions,
                    }),
                )?;
                rejected += 1;
                continue;
            }

            for (_, _, _, _, rendered_hash) in &pending {
                admitted_rendered.insert(rendered_identity_digest(rendered_hash));
            }
            direction_counts[family_index][direction_index] += 1;
            write_jsonl(
                &mut admission,
                &json!({
                    "candidate_ordinal": candidate_ordinal,
                    "family_slug": spec.slug,
                    "direction": direction,
                    "accepted": true,
                    "collision_field_names": [],
                    "collision_value_hashes": [],
                }),
            )?;

            for (view, episode_index, target, text, rendered_hash) in pending {
                let episode = &triplet.exact_episodes[episode_index];
                let episode_id = episode.episode_id.as_str();
                let row = PanelRow {
                    neighborhood_id: triplet.anchor_id.as_str(),
                    world_id: format!("world:{}", triplet.anchor_id),
                    root_id: format!("r3-root:{}", triplet.anchor_id),
                    episode_id,
                    family_slug: spec.slug,
                    sequence,
                    direction,
                    view,
                    old_semantic_id: candidate_ids[old_index].clone(),
                    new_semantic_id: candidate_ids[new_index].clone(),
                    candidate_semantic_ids: candidate_ids.clone(),
                    candidate_order_sha256: sha256(candidate_ids.join("\n").as_bytes()),
                    selector_input_hash: selector_hash(
                        triplet.anchor_id.as_str(),
                        spec.slug,
                        view,
                        &candidate_ids,
                    ),
                    full_rendered_input_hash: rendered_hash,
                    text,
                    target,
                };
                serde_json::to_writer(&mut panel, &row)?;
                panel.write_all(b"\n")?;
                rows_written += 1;
            }
        }
        if direction_counts[family_index] != [250, 250] {
            panel.flush()?;
            panel.get_ref().sync_all()?;
            candidates.flush()?;
            candidates.get_ref().sync_all()?;
            admission.flush()?;
            admission.get_ref().sync_all()?;
            write_failure(
                out,
                &json!({
                    "status": "R3_PANEL_ADMISSION_BUDGET_EXHAUSTED",
                    "family_slug": slug,
                    "accepted_direction_counts": direction_counts[family_index],
                    "candidate_budget": CANDIDATE_BUDGET_PER_FAMILY,
                    "rejected_candidates_total": rejected,
                    "no_reseed_or_budget_extension": true,
                }),
            )?;
            anyhow::bail!("candidate admission budget exhausted for {slug}");
        }
    }
    panel.flush()?;
    panel.get_ref().sync_all()?;
    candidates.flush()?;
    candidates.get_ref().sync_all()?;
    admission.flush()?;
    admission.get_ref().sync_all()?;
    ensure!(rows_written == 4_000, "calibration view count mismatch");
    ensure!(
        direction_counts.iter().all(|counts| *counts == [250, 250]),
        "polarity balance mismatch"
    );
    write_json(
        &out.join("panel-generation-receipt.json"),
        &json!({
            "status": "R3_CALIBRATION_PANEL_GENERATED_POLARITY_BALANCED",
            "partition": PARTITION,
            "seed": seed,
            "neighborhoods": 2_000,
            "view_rows": rows_written,
            "family_direction_neighborhood_counts": direction_counts,
            "candidate_budget_per_family": CANDIDATE_BUDGET_PER_FAMILY,
            "candidate_rejections": rejected,
            "rendered_denylist_sha256": denylist_sha256,
            "admitted_rendered_identity_count": admitted_rendered.len(),
            "head_loaded": false,
            "features_extracted": false,
            "training": false,
            "evaluation": false,
        }),
    )?;
    Ok(())
}

fn write_candidate_texts(writer: &mut BufWriter<File>, spec: &FamilySpec) -> Result<()> {
    for (index, candidate) in spec.candidates.iter().enumerate() {
        let id = format!("{}::{}", spec.slug, candidate.suffix);
        let text = format!("{} — {}", candidate.name, candidate.description);
        let row = json!({
            "family_slug": spec.slug,
            "candidate_semantic_id": id,
            "candidate_order": index,
            "name": candidate.name,
            "description": candidate.description,
            "text": text,
            "text_sha256": sha256(text.as_bytes())
        });
        serde_json::to_writer(&mut *writer, &row)?;
        writer.write_all(b"\n")?;
    }
    Ok(())
}

fn candidate_ids(spec: &FamilySpec) -> Vec<String> {
    spec.candidates
        .iter()
        .map(|candidate| format!("{}::{}", spec.slug, candidate.suffix))
        .collect()
}

fn target(triplet: &Triplet, index: usize) -> Result<Vec<f64>> {
    let episode = &triplet.exact_episodes[index];
    let gold = episode
        .gold_targets
        .first()
        .context("choice target missing")?;
    match &gold.value {
        world::GoldValue::Choice { probabilities, .. } => {
            let mut values = vec![0.0; 4];
            for item in probabilities {
                ensure!(
                    (item.value as usize) < values.len(),
                    "candidate target index out of range"
                );
                values[item.value as usize] = item.probability;
            }
            ensure!(
                values.iter().all(|value| value.is_finite()),
                "nonfinite target probability"
            );
            ensure!(
                (values.iter().sum::<f64>() - 1.0).abs() <= 1e-12,
                "target does not sum to one"
            );
            Ok(values)
        }
        _ => anyhow::bail!("non-choice target in calibration panel"),
    }
}

fn winner(values: &[f64]) -> usize {
    values
        .iter()
        .enumerate()
        .max_by(|left, right| left.1.total_cmp(right.1))
        .map(|(index, _)| index)
        .unwrap_or(usize::MAX)
}

fn selector_hash(neighborhood: &str, family: &str, view: &str, candidates: &[String]) -> String {
    let payload = json!({
        "schema": "jev-v08q-r3-calibration-selector-v01",
        "partition": PARTITION,
        "neighborhood_id": neighborhood,
        "family_slug": family,
        "view": view,
        "candidate_order_sha256": sha256(candidates.join("\n").as_bytes())
    });
    sha256(&serde_json::to_vec(&payload).expect("selector payload serializes"))
}

fn sha256(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    let mut result = String::with_capacity(64);
    for byte in digest.finalize() {
        use std::fmt::Write as _;
        let _ = write!(result, "{byte:02x}");
    }
    result
}

fn rendered_identity_digest(rendered_sha256: &str) -> String {
    sha256(format!("jev-v08q-exclusion-v01:full_rendered_input_hash:{rendered_sha256}").as_bytes())
}

fn write_jsonl<T: Serialize>(writer: &mut BufWriter<File>, value: &T) -> Result<()> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn write_failure(out: &std::path::Path, value: &serde_json::Value) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(out.join("generation-failure.json"))?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

fn write_json(path: &std::path::Path, value: &serde_json::Value) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

fn writer(path: PathBuf) -> Result<BufWriter<File>> {
    Ok(BufWriter::with_capacity(
        1 << 20,
        OpenOptions::new().write(true).create_new(true).open(path)?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn both_polarities_preserve_semantic_role_targets() {
        let all = families::all_families();
        let spec = all[TRAIN_FAMILY_COUNT..]
            .iter()
            .find(|family| family.slug == "exposure_control")
            .unwrap();
        for sequence in [0, 1] {
            let triplet = build_triplet(spec, PARTITION, sequence, 81_730_419).unwrap();
            let (anchor, fact, old, new) = if sequence % 2 == 0 {
                (0, 1, 0, 1)
            } else {
                (1, 0, 1, 0)
            };
            assert_eq!(winner(&target(&triplet, anchor).unwrap()), old);
            assert_eq!(winner(&target(&triplet, fact).unwrap()), new);
            assert_ne!(
                triplet.exact_episodes[anchor].episode_id,
                triplet.exact_episodes[fact].episode_id
            );
        }
    }

    #[test]
    fn reverse_orientation_sham_preserves_low_anchor_target() {
        let all = families::all_families();
        for spec in &all {
            for sequence in 0..4 {
                let triplet = build_triplet(spec, PARTITION, sequence, 81_730_419).unwrap();
                let low_anchor = &triplet.exact_episodes[1];
                let mut evidence = low_anchor.evidence_state.clone();
                let marker = evidence
                    .facts
                    .iter_mut()
                    .find(|fact| fact.fact_id == "ev-sham")
                    .unwrap();
                marker.observed_value = Some(1 - marker.observed_value.unwrap());
                let template = base_generator::template(spec, PARTITION, sequence);
                let posterior = world::solve_exact(&template, &evidence).unwrap();
                let changed = posterior.marginals.first().unwrap();
                let baseline = target(&triplet, 1).unwrap();
                assert!(
                    changed
                        .iter()
                        .zip(baseline)
                        .all(|(left, right)| (left - right).abs() <= 1e-12)
                );

                let low_text = low_anchor.renderings[0].text.as_str();
                assert!(low_text.contains("Independent panel marker: +."));
                let low_sham_text = low_text.replace(
                    "Independent panel marker: +.",
                    "Independent panel marker: -.",
                );
                assert_ne!(low_text, low_sham_text);
            }
        }
    }

    #[test]
    fn selector_identity_binds_semantic_view_not_storage_position() {
        let ids = vec!["family::high".to_string(), "family::low".to_string()];
        let a = selector_hash("world-1", "family", "anchor", &ids);
        let b = selector_hash("world-1", "family", "fact", &ids);
        assert_ne!(a, b);
        assert_eq!(a, selector_hash("world-1", "family", "anchor", &ids));
    }
}
