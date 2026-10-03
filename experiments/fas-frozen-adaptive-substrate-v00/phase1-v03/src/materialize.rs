use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::{BufWriter, Write},
    path::Path,
};

use fas00::world::{DEFAULT_EVENTS, Family, Feedback, Split, Track, WorldConfig, generate};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::{
    audit::{
        AuditReport, baseline_correct, context_pair_counts, drift_rates, family_name,
        leakage_audit, observation_identity, query_identity, render_seed, return_identity,
        summaries, transition_gate, validate_serialized_corpus, validate_world,
    },
    types::{Gate, Phase1Status, QualificationEvent, ResourceBasis, WorldRecord},
};

const SEEDS: u64 = 32;
const PARENT_SEAL_SHA256: &str = "c7227d2a10da05f902ed5d16e94a8e12866d2e0ae6b2b2a357ed2da93431b3e6";
const SUPERSEDED_V02_SHA256: &str =
    "af42320abe28885d20a07c2c936ac130da707bf6347dd5bfe24644b06978bf21";

#[derive(Serialize)]
struct CorpusManifest {
    manifest_id: &'static str,
    project_id: &'static str,
    purpose: &'static str,
    parent_pre_model_seal_sha256: &'static str,
    parent_seal_superseded: bool,
    supersedes_phase1_version: &'static str,
    supersedes_phase1_artifact_sha256: &'static str,
    supersession_reason: &'static str,
    split: &'static str,
    family_count: usize,
    task_structure_count: usize,
    feedback_condition_count: usize,
    seed_count: u64,
    world_count: usize,
    events_per_world: u32,
    event_count: usize,
    world_seed_policy: &'static str,
    label_rotation_policy: &'static str,
    generator_crate: &'static str,
    phase5_reuse_authorized: bool,
    model_contact_authorized: bool,
}

#[derive(Serialize)]
struct LatentStep<'a> {
    step: u32,
    regime: &'a str,
    regime_phase: u8,
    world_state: &'a [fas00::world::KeyState],
    target: u8,
}

fn sha_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut text = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut text, "{byte:02x}").unwrap();
    }
    text
}

fn world_id(config: &WorldConfig) -> Result<String, String> {
    serde_json::to_vec(config)
        .map(|bytes| sha_hex(&bytes))
        .map_err(|error| error.to_string())
}

fn term_ids(seed: u64, context_id: u8, entity_id: u8) -> (u8, u8) {
    fn draw(seed: u64, domain: u64, modulo: u64) -> usize {
        let mut value = (seed ^ domain).wrapping_add(0x9e3779b97f4a7c15);
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
        ((value ^ (value >> 31)) % modulo) as usize
    }
    let context_slot = (context_id as usize + draw(seed, 12, 2)) % 2;
    let entity_slot = (entity_id as usize + draw(seed, 11, 4)) % 4;
    (2 + context_slot as u8, 4 + entity_slot as u8)
}

fn write_jsonl<T: Serialize>(path: &Path, rows: &[T]) -> Result<(), String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    let mut writer = BufWriter::with_capacity(1024 * 1024, file);
    for row in rows {
        serde_json::to_writer(&mut writer, row).map_err(|error| error.to_string())?;
        writer.write_all(b"\n").map_err(|error| error.to_string())?;
    }
    writer.flush().map_err(|error| error.to_string())?;
    Ok(())
}

fn build_once() -> Result<(Vec<QualificationEvent>, Vec<WorldRecord>, AuditReport), String> {
    let mut all_events = Vec::with_capacity(1024 * DEFAULT_EVENTS as usize);
    let mut world_records = Vec::with_capacity(1024);
    let mut report = AuditReport::default();
    let mut phase_transitions: BTreeMap<String, u64> = BTreeMap::new();
    let mut baseline_rows = Vec::with_capacity(1024);
    let mut context_baseline_rows = Vec::with_capacity(512);
    let mut transition_ok = true;
    let mut target_ok = true;
    let mut timing_ok = true;
    let mut observation_ok = true;
    let mut return_ok = true;
    let mut context_pairs_ok = true;
    let mut surface_split_ok = true;

    for seed in 0..SEEDS {
        for family in Family::ALL {
            for track in [Track::GlobalRule, Track::ContextBound] {
                for feedback in [Feedback::Immediate, Feedback::Delayed8] {
                    let config = WorldConfig {
                        world_seed: seed,
                        split: Split::Qualification,
                        family,
                        track,
                        feedback,
                        events: DEFAULT_EVENTS,
                        label_rotation: (seed % 3) as u8,
                    };
                    let raw = generate(&config)?;
                    let id = world_id(&config)?;
                    let mut events = Vec::with_capacity(raw.len());
                    let mut latent_hash = Sha256::new();
                    let mut rendered_hash = Sha256::new();
                    for source in &raw {
                        let x = &source.exposure;
                        let (context_term_id, entity_term_id) =
                            term_ids(seed, x.context_id, x.entity_id);
                        let visible_feedback_ids_after_score = raw
                            .iter()
                            .filter(|candidate| candidate.feedback_due_step == x.step)
                            .map(|candidate| format!("{}:{:02}", id, candidate.exposure.step))
                            .collect();
                        let mut event = QualificationEvent {
                            event_id: format!("{}:{:02}", id, x.step),
                            world_id: id.clone(),
                            world_family: family,
                            world_seed: seed,
                            task_structure: track,
                            feedback_condition: feedback,
                            time_step: x.step,
                            latent_regime_id: source.regime_identity.clone(),
                            latent_regime_phase: source.regime_phase,
                            key_id: x.key_id,
                            context_id: x.context_id,
                            entity_id: x.entity_id,
                            relation_id: x.relation_id,
                            current_exact_world_state: source.world_state.clone(),
                            observation_identity: observation_identity(x.observation.as_deref()),
                            observation_text: x.observation.clone(),
                            observation_answer_index: x.observed_answer_index,
                            query_identity: query_identity(&x.query),
                            query_text: x.query.clone(),
                            candidate_identities_in_order: std::array::from_fn(|index| {
                                fas00::world::LABELS
                                    .iter()
                                    .position(|label| *label == x.candidates[index])
                                    .unwrap() as u8
                            }),
                            candidate_text_in_order: x.candidates.clone(),
                            exact_target: source.target_index,
                            feedback_reveal_step: source.feedback_due_step,
                            visible_feedback_ids_after_score,
                            surface_template_id: x.template_id,
                            context_term_id,
                            entity_term_id,
                            render_seed: render_seed(seed, x.step),
                            rendered_event_sha256: String::new(),
                        };
                        let mut event_bytes =
                            serde_json::to_vec(&event).map_err(|error| error.to_string())?;
                        event.rendered_event_sha256 = sha_hex(&event_bytes);
                        event_bytes =
                            serde_json::to_vec(&event).map_err(|error| error.to_string())?;
                        rendered_hash.update(&event_bytes);
                        rendered_hash.update(b"\n");
                        let latent = LatentStep {
                            step: source.exposure.step,
                            regime: &source.regime_identity,
                            regime_phase: source.regime_phase,
                            world_state: &source.world_state,
                            target: source.target_index,
                        };
                        latent_hash.update(
                            serde_json::to_vec(&latent).map_err(|error| error.to_string())?,
                        );
                        latent_hash.update(b"\n");
                        events.push(event);
                    }
                    let transitions = match validate_world(&events) {
                        Ok(result) => result,
                        Err(_) => {
                            target_ok = false;
                            u64::MAX
                        }
                    };
                    let expected_transition_count = match family {
                        Family::Stable | Family::ContradictoryNoise | Family::PoisonBurst => 0,
                        Family::SingleSwitch | Family::GradualDrift => 1,
                        Family::Return | Family::TemporaryRule => 2,
                        Family::Cyclic => 3,
                    };
                    if transitions != expected_transition_count {
                        transition_ok = false;
                    }
                    *phase_transitions
                        .entry(family_name(family).to_owned())
                        .or_default() += transitions;
                    if events.iter().any(|event| {
                        event.feedback_reveal_step
                            != event.time_step
                                + if feedback == Feedback::Immediate {
                                    0
                                } else {
                                    8
                                }
                    }) {
                        timing_ok = false;
                    }
                    for (step, event) in events.iter().enumerate() {
                        let expected_ids: Vec<_> = events
                            .iter()
                            .filter(|candidate| candidate.feedback_reveal_step == step as u32)
                            .map(|candidate| candidate.event_id.clone())
                            .collect();
                        let actual_ids = &event.visible_feedback_ids_after_score;
                        if actual_ids.as_slice() != expected_ids.as_slice() {
                            timing_ok = false;
                        }
                    }
                    if family == Family::Return {
                        match return_identity(&events) {
                            Ok((latent_equal, surface_equal, rule_equal, query_different))
                                if latent_equal
                                    && !surface_equal
                                    && rule_equal
                                    && query_different =>
                            {
                                report.return_identity_cases += 1;
                                report.return_latent_equal += u64::from(latent_equal);
                                report.return_surface_equal += u64::from(surface_equal);
                                report.return_semantic_rule_equal += u64::from(rule_equal);
                                report.return_query_different += u64::from(query_different);
                            }
                            _ => return_ok = false,
                        }
                    }
                    let (ct, cd, et, ed) = context_pair_counts(&events);
                    report.context_counterfactual_pairs += ct;
                    report.context_pairs_different += cd;
                    report.entity_counterfactual_pairs += et;
                    report.entity_pairs_different += ed;
                    if track == Track::ContextBound && (ct == 0 || ct != cd || et == 0 || et != ed)
                    {
                        context_pairs_ok = false;
                    }
                    if events.iter().any(|event| {
                        !(3..=5).contains(&event.surface_template_id)
                            || !(2..=3).contains(&event.context_term_id)
                            || !(4..=7).contains(&event.entity_term_id)
                    }) {
                        surface_split_ok = false;
                    }
                    let correct = baseline_correct(&events);
                    baseline_rows.push(correct);
                    if track == Track::ContextBound {
                        context_baseline_rows.push(correct);
                    }
                    world_records.push(WorldRecord {
                        world_id: id,
                        world_family: family,
                        world_seed: seed,
                        task_structure: track,
                        feedback_condition: feedback,
                        label_rotation: config.label_rotation,
                        event_count: events.len(),
                        latent_world_sha256: hex_digest(latent_hash.finalize().as_slice()),
                        rendered_events_sha256: hex_digest(rendered_hash.finalize().as_slice()),
                        baseline_correct: correct,
                        baseline_accuracy: correct.map(|n| n as f64 / events.len() as f64),
                        resource_basis: ResourceBasis {
                            key_count: 8,
                            possible_current_fact_count: 24,
                            current_fact_count: 8,
                            regime_identity_count: 3,
                            generator_regime_bits: 2,
                            arbitrary_per_key_state_bits_lower_bound: 13,
                            arbitrary_per_key_state_bytes_lower_bound: 2,
                            stream_length: DEFAULT_EVENTS,
                            feedback_event_count_delivered_within_world: raw
                                .iter()
                                .filter(|event| event.feedback_due_step < DEFAULT_EVENTS)
                                .count()
                                as u32,
                        },
                    });
                    observation_ok &= events.iter().all(|event| {
                        event.observation_answer_index
                            == crate::audit::expected_observation_for_gate(event)
                    });
                    all_events.extend(events);
                }
            }
        }
    }

    report.transition_counts = phase_transitions;
    report.leakage = leakage_audit(&all_events);
    report.baselines = summaries(&baseline_rows, &context_baseline_rows);
    report.drift_evidence_rates_by_bin = drift_rates(&all_events);
    let mut gates = vec![
        gate(
            "WORLD_TARGETS_EXACT",
            target_ok,
            "Independent lookup from serialized world state and parsed query key.",
        ),
        gate(
            "TRANSITIONS_EXACT",
            transition_ok,
            "Every adjacent serialized world state was checked against the independent transition rule.",
        ),
        gate(
            "RETURN_IDENTITY",
            return_ok,
            "A return restores identical latent state and target for a matched key while query wording differs.",
        ),
        gate(
            "CONTEXT_BINDING",
            context_pairs_ok,
            "Changing context and changing entity each change the target in the declared counterfactual pairs.",
        ),
        gate(
            "FEEDBACK_TIMING",
            timing_ok,
            "Post-score visible feedback IDs exactly match fixed reveal steps; current delayed target is absent.",
        ),
        gate(
            "SURFACE_SPLIT_INTEGRITY",
            surface_split_ok,
            "Qualification templates and invented-term IDs stay in their split allocation.",
        ),
        gate(
            "OBSERVATION_AUTHORITY",
            observation_ok,
            "Noise/drift/poison observations match frozen rules while latent state is checked independently.",
        ),
    ];
    gates.extend(transition_gate(&report.transition_counts));
    let monotonic_drift = report
        .drift_evidence_rates_by_bin
        .windows(2)
        .all(|pair| pair[1] + 0.08 >= pair[0]);
    gates.push(gate(
        "GRADUAL_DRIFT_DISTRIBUTION",
        monotonic_drift,
        &format!(
            "observed B-evidence rates across four time bins={:?}; tolerance=0.08",
            report.drift_evidence_rates_by_bin
        ),
    ));
    let max_public = report
        .leakage
        .iter()
        .filter(|row| row.feature_group != "family_time_key_bundle")
        .map(|row| row.held_out_accuracy)
        .fold(0.0f64, f64::max);
    gates.push(gate("CHEAP_TARGET_LEAKAGE", max_public <= 0.45,
        &format!("maximum held-out accuracy across cheap surface/metadata groups={max_public:.4}; threshold=0.45")));
    let last_global = report
        .baselines
        .iter()
        .find(|row| row.name == "LAST_GLOBAL_OBSERVATION")
        .and_then(|row| row.context_bound_accuracy)
        .unwrap_or(1.0);
    gates.push(gate("TRIVIAL_BASELINE_DIAGNOSTIC", last_global < 0.98,
        &format!("context-bound LAST_GLOBAL_OBSERVATION accuracy={last_global:.4}; failure threshold=0.98")));
    let label_counts = all_events.iter().fold([0u64; 3], |mut counts, event| {
        counts[event.exact_target as usize] += 1;
        counts
    });
    let balance_tolerance = all_events.len().div_ceil(100) as u64;
    gates.push(gate(
        "COUNTERFACTUAL_LABEL_BALANCE",
        label_counts.iter().max().unwrap() - label_counts.iter().min().unwrap() <= balance_tolerance,
        &format!("canonical target counts={label_counts:?}; maximum class-count spread={balance_tolerance} (1% of events)"),
    ));
    gates.push(gate(
        "SEED_DETERMINISM",
        true,
        "Second full build is compared against this build before writing.",
    ));
    report.gates = gates;
    Ok((all_events, world_records, report))
}

fn gate(name: &str, passed: bool, detail: &str) -> Gate {
    Gate {
        gate: name.into(),
        status: if passed { "PASS" } else { "FAIL" }.into(),
        detail: detail.into(),
    }
}

fn hex_digest(bytes: &[u8]) -> String {
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut text, "{byte:02x}").unwrap();
    }
    text
}

pub fn qualify(output: &Path) -> Result<(), String> {
    if output.exists()
        && fs::read_dir(output)
            .map_err(|e| e.to_string())?
            .next()
            .is_some()
    {
        return Err("refusing to overwrite nonempty qualification output".into());
    }
    fs::create_dir_all(output).map_err(|e| e.to_string())?;
    let (events, worlds, mut report) = build_once()?;
    let (events_again, worlds_again, _) = build_once()?;
    let deterministic = events.len() == events_again.len()
        && events.iter().zip(&events_again).all(|(a, b)| {
            a.world_id == b.world_id && a.rendered_event_sha256 == b.rendered_event_sha256
        })
        && worlds.iter().zip(&worlds_again).all(|(a, b)| {
            a.latent_world_sha256 == b.latent_world_sha256
                && a.rendered_events_sha256 == b.rendered_events_sha256
        });
    if let Some(gate) = report
        .gates
        .iter_mut()
        .find(|g| g.gate == "SEED_DETERMINISM")
    {
        gate.status = if deterministic { "PASS" } else { "FAIL" }.into();
        gate.detail = format!(
            "two complete 1,024-world builds match byte-derived IDs and latent/rendered hashes; result={deterministic}"
        );
    }
    let manifest = CorpusManifest {
        manifest_id: "FAS00_WORLD_QUALIFICATION_V03",
        project_id: "fas-frozen-adaptive-substrate-v00",
        purpose: "Phase 1 qualification only; diagnostic corpus, not the Phase 5 stream",
        parent_pre_model_seal_sha256: PARENT_SEAL_SHA256,
        parent_seal_superseded: false,
        supersedes_phase1_version: "phase1-v02 partial diagnostic materialization",
        supersedes_phase1_artifact_sha256: SUPERSEDED_V02_SHA256,
        supersession_reason: "v02 failed closed during serialized readback because its validator used the v01 event filename after versioning the output; v03 fixes the versioned readback path and reruns full serialized-corpus validation.",
        split: "QUALIFICATION",
        family_count: 8,
        task_structure_count: 2,
        feedback_condition_count: 2,
        seed_count: SEEDS,
        world_count: worlds.len(),
        events_per_world: DEFAULT_EVENTS,
        event_count: events.len(),
        world_seed_policy: "u64 values 0..31, repeated across family/track/feedback cells",
        label_rotation_policy: "world_seed mod 3; balanced over the 32 seeds",
        generator_crate: "sealed sibling crate fas00 0.1.0; no other experiment imports",
        phase5_reuse_authorized: false,
        model_contact_authorized: false,
    };
    write_jsonl(&output.join("qualification-events-v03.jsonl"), &events)?;
    write_jsonl(&output.join("world-manifest-v03.jsonl"), &worlds)?;
    write_json(&output.join("corpus-manifest-v03.json"), &manifest)?;
    validate_serialized_corpus(output, &worlds)?;
    write_json(&output.join("audit-v03.json"), &report)?;
    let all_non_hash_gates_pass = report.gates.iter().all(|gate| gate.status == "PASS");
    let status = Phase1Status {
        project_id: "fas-frozen-adaptive-substrate-v00".into(),
        phase: "FAS00_PHASE1_WORLD_QUALIFICATION_V03".into(),
        qualification_world_count: worlds.len(),
        scored_event_count: events.len(),
        phase1_ready: false,
        model_contact_authorized: false,
        model_contact_performed: false,
        qualification_corpus_reusable_for_phase5: false,
        gates: report.gates.clone(),
    };
    write_json(&output.join("phase1-check-status-v03.json"), &status)?;
    if !deterministic {
        return Err("determinism failed; corpus remains diagnostic and unsealed".into());
    }
    if !all_non_hash_gates_pass {
        eprintln!("one or more gates failed; no model contact is permitted");
    }
    Ok(())
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut writer, value).map_err(|e| e.to_string())?;
    writer.write_all(b"\n").map_err(|e| e.to_string())?;
    writer.flush().map_err(|e| e.to_string())?;
    Ok(())
}
