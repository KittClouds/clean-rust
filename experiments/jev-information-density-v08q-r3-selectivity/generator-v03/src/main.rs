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
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use base_generator::{Triplet, build_triplet};
use families::{FamilySpec, TRAIN_FAMILY_COUNT};

const PARTITION: &str = "eval_v08q_r3_confirmatory_v03";
const FAMILY_ORDER: [&str; 4] = [
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
];
const NEIGHBORHOODS_PER_FAMILY: usize = 500;
const CANDIDATE_BUDGET_PER_FAMILY: usize = 800;
const IDENTITY_FIELDS: [&str; 5] = [
    "world_id",
    "root_id",
    "episode_id",
    "full_rendered_input_hash",
    "selector_input_hash",
];

#[derive(Deserialize)]
struct ExclusionSets {
    schema: String,
    fields: BTreeMap<String, Vec<String>>,
    e1_neighborhood_hashes: Vec<String>,
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

struct PendingView<'a> {
    view: &'static str,
    episode_id: String,
    text: &'a str,
    target: Vec<f64>,
    world_id: String,
    root_id: String,
    rendered_hash: String,
    selector_hash: String,
}

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let out = PathBuf::from(args.next().context("output directory required")?);
    let seed: u64 = args
        .next()
        .context("panel seed required")?
        .parse()
        .context("panel seed must be u64")?;
    let exclusion_path = PathBuf::from(args.next().context("field exclusion set path required")?);
    let expected_exclusion_sha256 = args
        .next()
        .context("expected exclusion-set SHA-256 required")?;
    ensure!(args.next().is_none(), "unexpected positional argument");
    generate(&out, seed, &exclusion_path, &expected_exclusion_sha256)
}

fn generate(
    out: &std::path::Path,
    seed: u64,
    exclusion_path: &std::path::Path,
    expected_exclusion_sha256: &str,
) -> Result<()> {
    ensure!(
        !out.exists(),
        "refusing to reuse output directory: {}",
        out.display()
    );
    let exclusion_bytes = fs::read(exclusion_path).context("read exact field exclusion set")?;
    let exclusion_sha256 = sha256(&exclusion_bytes);
    ensure!(
        exclusion_sha256 == expected_exclusion_sha256,
        "field exclusion set hash mismatch"
    );
    let exclusions: ExclusionSets = serde_json::from_slice(&exclusion_bytes)?;
    ensure!(
        exclusions.schema == "jev-v08q-r3-field-exclusion-domain-hash-sets-v02"
            && exclusions.fields.len() == IDENTITY_FIELDS.len()
            && exclusions.e1_neighborhood_hashes.len() == 2_000,
        "field exclusion schema/cardinality mismatch"
    );
    let mut external = BTreeMap::<String, BTreeSet<String>>::new();
    for field in IDENTITY_FIELDS {
        let values = exclusions
            .fields
            .get(field)
            .context("required exclusion field absent")?;
        ensure!(!values.is_empty(), "empty exclusion field: {field}");
        let set = values.iter().cloned().collect::<BTreeSet<_>>();
        ensure!(
            set.len() == values.len(),
            "duplicate exclusion digest: {field}"
        );
        external.insert(field.to_owned(), set);
    }
    let e1_neighborhoods = exclusions
        .e1_neighborhood_hashes
        .into_iter()
        .collect::<BTreeSet<_>>();
    ensure!(
        e1_neighborhoods.len() == 2_000,
        "E1 neighborhood digest duplication"
    );
    fs::create_dir_all(out)?;
    let mut panel = writer(out.join("r3-panel-views.jsonl"))?;
    let mut candidates = writer(out.join("candidate-texts.jsonl"))?;
    let mut admission = writer(out.join("candidate-admission-receipts.jsonl"))?;
    let all = families::all_families();
    let mut rows_written = 0usize;
    let mut direction_counts = [[0usize; 2]; 4];
    let mut admitted = IDENTITY_FIELDS
        .iter()
        .map(|field| ((*field).to_owned(), BTreeSet::<String>::new()))
        .collect::<BTreeMap<_, _>>();
    let mut rejected = 0usize;
    let mut admission_rows = 0usize;
    let mut quota_skips = 0usize;

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
                write_jsonl(
                    &mut admission,
                    &json!({
                        "candidate_ordinal": candidate_ordinal,
                        "family_candidate_ordinal": candidate_ordinal,
                        "stream_ordinal": family_index * CANDIDATE_BUDGET_PER_FAMILY + candidate_ordinal,
                        "family_slug": spec.slug,
                        "direction": if high_to_low { "high_to_low" } else { "low_to_high" },
                        "status": "skipped_direction_quota_full",
                        "evaluated_candidate": false,
                        "accepted": false,
                        "collision_field_names": [],
                        "collision_value_hashes": [],
                    }),
                )?;
                admission_rows += 1;
                quota_skips += 1;
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

            let world_id = format!("world:{}", triplet.anchor_id);
            let root_id = format!("r3-root:{}", triplet.anchor_id);
            let mut pending = Vec::with_capacity(2);
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
                let selector =
                    selector_hash(triplet.anchor_id.as_str(), spec.slug, view, &candidate_ids);
                pending.push(PendingView {
                    view,
                    episode_id: episode.episode_id.clone(),
                    text,
                    target,
                    world_id: world_id.clone(),
                    root_id: root_id.clone(),
                    rendered_hash,
                    selector_hash: selector,
                });
            }
            ensure!(
                pending[0].rendered_hash != pending[1].rendered_hash,
                "anchor and fact view rendered to identical model input"
            );
            let mut candidate_digests = IDENTITY_FIELDS
                .iter()
                .map(|field| ((*field).to_owned(), BTreeSet::<String>::new()))
                .collect::<BTreeMap<_, _>>();
            for item in &pending {
                let values = [
                    ("world_id", item.world_id.as_str()),
                    ("root_id", item.root_id.as_str()),
                    ("episode_id", item.episode_id.as_str()),
                    ("full_rendered_input_hash", item.rendered_hash.as_str()),
                    ("selector_input_hash", item.selector_hash.as_str()),
                ];
                for (field, value) in values {
                    candidate_digests
                        .get_mut(field)
                        .expect("field list and candidate digest map agree")
                        .insert(domain_digest(field, value));
                }
            }
            let mut collisions = identity_collisions(&external, &admitted, &candidate_digests);
            if e1_neighborhoods.contains(&sha256(triplet.anchor_id.as_bytes())) {
                collisions
                    .entry("e1_neighborhood_id".to_owned())
                    .or_default()
                    .insert(sha256(triplet.anchor_id.as_bytes()));
            }
            if !collisions.is_empty() {
                write_jsonl(
                    &mut admission,
                    &json!({
                        "candidate_ordinal": candidate_ordinal,
                        "family_candidate_ordinal": candidate_ordinal,
                        "stream_ordinal": family_index * CANDIDATE_BUDGET_PER_FAMILY + candidate_ordinal,
                        "family_slug": spec.slug,
                        "direction": direction,
                        "status": "rejected_identity_collision",
                        "evaluated_candidate": true,
                        "accepted": false,
                        "collision_field_names": collisions.keys().collect::<Vec<_>>(),
                        "collision_value_hashes": collisions,
                    }),
                )?;
                rejected += 1;
                admission_rows += 1;
                continue;
            }

            for (field, values) in candidate_digests {
                admitted
                    .get_mut(&field)
                    .expect("validated internal field")
                    .extend(values);
            }
            direction_counts[family_index][direction_index] += 1;
            write_jsonl(
                &mut admission,
                &json!({
                    "candidate_ordinal": candidate_ordinal,
                    "family_candidate_ordinal": candidate_ordinal,
                    "stream_ordinal": family_index * CANDIDATE_BUDGET_PER_FAMILY + candidate_ordinal,
                    "family_slug": spec.slug,
                    "direction": direction,
                    "status": "admitted",
                    "evaluated_candidate": true,
                    "accepted": true,
                    "collision_field_names": [],
                    "collision_value_hashes": [],
                }),
            )?;
            admission_rows += 1;

            for item in pending {
                let row = PanelRow {
                    neighborhood_id: triplet.anchor_id.as_str(),
                    world_id: item.world_id,
                    root_id: item.root_id,
                    episode_id: &item.episode_id,
                    family_slug: spec.slug,
                    sequence,
                    direction,
                    view: item.view,
                    old_semantic_id: candidate_ids[old_index].clone(),
                    new_semantic_id: candidate_ids[new_index].clone(),
                    candidate_semantic_ids: candidate_ids.clone(),
                    candidate_order_sha256: sha256(candidate_ids.join("\n").as_bytes()),
                    selector_input_hash: item.selector_hash,
                    full_rendered_input_hash: item.rendered_hash,
                    text: item.text,
                    target: item.target,
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
    ensure!(rows_written == 4_000, "confirmatory view count mismatch");
    ensure!(
        direction_counts.iter().all(|counts| *counts == [250, 250]),
        "polarity balance mismatch"
    );
    write_json(
        &out.join("panel-generation-receipt.json"),
        &json!({
            "status": "R3_V03_CONFIRMATORY_PANEL_GENERATED_FIELDWISE_ADMISSION_PASS",
            "partition": PARTITION,
            "seed": seed,
            "neighborhoods": 2_000,
            "view_rows": rows_written,
            "family_direction_neighborhood_counts": direction_counts,
            "candidate_budget_per_family": CANDIDATE_BUDGET_PER_FAMILY,
            "candidate_stream_rows": admission_rows,
            "candidate_rejections": rejected,
            "candidate_quota_skips": quota_skips,
            "field_exclusion_sha256": exclusion_sha256,
            "e1_neighborhood_id_denylist_count": e1_neighborhoods.len(),
            "admitted_identity_digest_counts": admitted.iter().map(|(field, values)| (field, values.len())).collect::<BTreeMap<_, _>>(),
            "identity_fields_checked_before_admission": IDENTITY_FIELDS,
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
        "schema": "jev-v08q-r3-confirmatory-selector-v03",
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

fn domain_digest(field: &str, value: &str) -> String {
    sha256(format!("jev-v08q-exclusion-v01:{field}:{value}").as_bytes())
}

fn identity_collisions(
    external: &BTreeMap<String, BTreeSet<String>>,
    admitted: &BTreeMap<String, BTreeSet<String>>,
    candidate: &BTreeMap<String, BTreeSet<String>>,
) -> BTreeMap<String, BTreeSet<String>> {
    let mut collisions = BTreeMap::<String, BTreeSet<String>>::new();
    for field in IDENTITY_FIELDS {
        let values = candidate
            .get(field)
            .expect("candidate field missing from identity vector");
        let external_values = external.get(field).expect("external field missing");
        let admitted_values = admitted.get(field).expect("admitted field missing");
        for digest in values {
            if external_values.contains(digest) || admitted_values.contains(digest) {
                collisions
                    .entry(field.to_owned())
                    .or_default()
                    .insert(digest.clone());
            }
        }
    }
    collisions
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
    fn fieldwise_admission_rejects_any_one_of_five_identity_collisions() {
        let mut external = BTreeMap::new();
        let mut admitted = BTreeMap::new();
        let mut candidate = BTreeMap::new();
        for field in IDENTITY_FIELDS {
            external.insert(field.to_owned(), BTreeSet::new());
            admitted.insert(field.to_owned(), BTreeSet::new());
            candidate.insert(
                field.to_owned(),
                BTreeSet::from([format!("{field}-digest")]),
            );
        }
        for field in IDENTITY_FIELDS {
            external
                .get_mut(field)
                .unwrap()
                .insert(format!("{field}-digest"));
            let collisions = identity_collisions(&external, &admitted, &candidate);
            assert_eq!(collisions.len(), 1);
            assert!(collisions.contains_key(field));
            external.get_mut(field).unwrap().clear();
        }
        assert!(identity_collisions(&external, &admitted, &candidate).is_empty());
        admitted
            .get_mut("selector_input_hash")
            .unwrap()
            .insert("selector_input_hash-digest".to_owned());
        let collisions = identity_collisions(&external, &admitted, &candidate);
        assert_eq!(
            collisions.keys().map(String::as_str).collect::<Vec<_>>(),
            ["selector_input_hash"]
        );
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
