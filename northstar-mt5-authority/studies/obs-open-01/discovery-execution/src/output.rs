use crate::authority::{ParentVerification, SourceAccess};
use crate::corpus::{CandidateSummary, CorpusProducts};
use crate::stats::Analysis;
use crate::{
    AnyResult, CONFIRMATION_SESSIONS, DISC02P_ROOT, DISCOVERY_SESSIONS, MEAS02_ROOT,
    OBSERVER_INSTANCE, RAW_BAR_HASH,
};
use obs_open_disc02p::{
    RANDOM_SEED, RANDOMIZATIONS, canonical_json_bytes, sha256_bytes, sha256_file,
};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactMember {
    pub relative_path: String,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SealResult {
    pub root: String,
    pub manifest_sha256: String,
    pub artifact_set_hash: String,
    pub artifact_count: usize,
    pub members: Vec<ArtifactMember>,
}

pub fn write_products(
    out: &Path,
    parent: &ParentVerification,
    access: &SourceAccess,
    corpus: &CorpusProducts,
    analysis: &Analysis,
    execution_code_hash: &str,
) -> AnyResult<()> {
    prepare_output(out)?;
    for dir in ["descriptive", "formal", "randomization", "receipts"] {
        std::fs::create_dir_all(out.join(dir))?;
    }
    write_json(
        out.join("DISC02E_CORPUS_MANIFEST.json"),
        &json!({
            "schema":"DISC02E_CORPUS_MANIFEST_V1",
            "authority":"OBS_OPEN_DISC02E_DISCOVERY_V1",
            "observer_instance":OBSERVER_INSTANCE,
            "parents":{"disc02p_root":DISC02P_ROOT,"meas02_root":MEAS02_ROOT},
            "raw_source":{"sha256":RAW_BAR_HASH,"storage":"D_DRIVE_LOCAL_ONLY","decoded_prefix_sha256":parent.discovery_prefix_sha256},
            "discovery_population":{"requested":DISCOVERY_SESSIONS,"resolved":corpus.census.sessions,"admitted":corpus.census.sessions,"excluded":0},
            "corpus":corpus.census,
            "confirmation":{"sessions":CONFIRMATION_SESSIONS,"state":"FROZEN_UNOPENED","membership_rows_decoded":0,"observation_rows_decoded":0}
        }),
    )?;
    write_access_audit(out, parent, access, corpus)?;
    write_descriptive(out, corpus, analysis)?;
    write_support(out, analysis)?;
    write_formal(out, analysis)?;
    let (candidates, contracts) = build_candidates(analysis)?;
    write_json(
        out.join("DISC02E_CANDIDATE_REGISTRY.json"),
        &json!({
            "schema":"DISC02E_CANDIDATE_REGISTRY_V1",
            "authority":"DISCOVERY_ONLY_UNCONFIRMED",
            "candidate_count":candidates.len(),
            "candidates":candidates
        }),
    )?;
    write_json(
        out.join("DISC02E_CONFIRMATION_CONTRACTS.json"),
        &json!({
            "schema":"DISC02E_CONFIRMATION_CONTRACTS_V1",
            "confirmation_state":"FROZEN_UNOPENED",
            "confirmation_rows_read":0,
            "contract_count":contracts.len(),
            "contracts":contracts
        }),
    )?;
    write_typed_findings(out, analysis)?;
    write_json(
        out.join("receipts/DISC02E_MULTIPLICITY_RECEIPT.json"),
        &json!({
            "schema":"DISC02E_MULTIPLICITY_RECEIPT_V1",
            "within_surface":"STUDENTIZED_MAX_ABSOLUTE_STATISTIC",
            "between_families":"HOLM_BONFERRONI",
            "alpha":0.05,
            "formal_family_count":3,
            "randomizations":RANDOMIZATIONS,
            "seed":RANDOM_SEED,
            "minimum_attainable_p":1.0/(RANDOMIZATIONS as f64+1.0),
            "results":analysis.results
        }),
    )?;
    write_json(
        out.join("receipts/DISC02E_LOCALIZATION_RECEIPTS.json"),
        &json!({
            "schema":"DISC02E_LOCALIZATION_RECEIPTS_V1",
            "receipts":analysis.results.iter().filter_map(|r|r.localization.as_ref()).collect::<Vec<_>>()
        }),
    )?;
    write_json(
        out.join("receipts/DISC02E_ROBUSTNESS_RECEIPTS.json"),
        &json!({
            "schema":"DISC02E_ROBUSTNESS_RECEIPTS_V1",
            "families":analysis.results.iter().map(|r|json!({"family_id":r.family_id,"temporal_status":r.temporal_status,"slices":r.robustness})).collect::<Vec<_>>()
        }),
    )?;
    write_json(
        out.join("receipts/DISC02E_CONFIRMATION_FIREWALL_RECEIPT.json"),
        &json!({
            "schema":"DISC02E_CONFIRMATION_FIREWALL_RECEIPT_V1",
            "status":"PASS",
            "confirmation_sessions_read":0,
            "confirmation_membership_rows_decoded":0,
            "confirmation_observations_read":0,
            "confirmation_state":"FROZEN_UNOPENED",
            "next_source_row_requested":false
        }),
    )?;
    write_json(
        out.join("receipts/DISC02E_EXECUTION_RECEIPT.json"),
        &json!({
            "schema":"DISC02E_EXECUTION_RECEIPT_V1",
            "disc02p_root":DISC02P_ROOT,
            "meas02_root":MEAS02_ROOT,
            "execution_code_sha256":execution_code_hash,
            "protocol_interpretation":"READ_ONLY",
            "formal_families":3,
            "descriptive_authority":"DESCRIPTIVE_ONLY",
            "economic_authority":false,
            "trading_authority":false
        }),
    )?;
    Ok(())
}

fn prepare_output(out: &Path) -> AnyResult<()> {
    if out.exists() {
        let resolved = std::fs::canonicalize(out)?;
        let normalized = resolved
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        let allowed = normalized.starts_with("d:/obs-open-01/discovery/")
            || normalized.starts_with("//?/d:/obs-open-01/discovery/");
        if !allowed {
            return Err(format!("REFUSE_OUTPUT_REMOVAL:{}", resolved.display()).into());
        }
        std::fs::remove_dir_all(&resolved)?;
    }
    std::fs::create_dir_all(out)?;
    Ok(())
}

fn write_access_audit(
    out: &Path,
    parent: &ParentVerification,
    access: &SourceAccess,
    corpus: &CorpusProducts,
) -> AnyResult<()> {
    write_json(
        out.join("DISC02E_ACCESS_AUDIT.json"),
        &json!({
            "schema":"DISC02E_ACCESS_AUDIT_V1",
            "requested_sessions":DISCOVERY_SESSIONS,
            "resolved_sessions":corpus.census.sessions,
            "admitted_sessions":corpus.census.sessions,
            "excluded_sessions":0,
            "source_prefix_rows_decoded":access.source_prefix_rows_decoded,
        "selected_m1_observations_read":access.selected_m1_observations_read,
        "retained_causal_m1_observations":access.retained_causal_m1_observations,
        "sessions_with_path_gap":access.sessions_with_path_gap,
        "path_gaps":access.path_gaps,
            "measurement_objects_read":{
                "session_bars":corpus.census.m1_session_bars,
                "range_objects":corpus.census.range_objects,
                "strict_candidates":corpus.census.strict_upper_candidates+corpus.census.strict_lower_candidates,
                "candidate_range_relations":corpus.census.candidate_range_relations
            },
            "source_artifact_ids":[RAW_BAR_HASH,parent.discovery_prefix_sha256],
            "first_read_source_time":access.first_selected_open_epoch,
            "last_read_source_time":access.last_selected_close_epoch,
            "read_time_semantics":"CAUSAL_SOURCE_TIME_NOT_NONDETERMINISTIC_WALL_CLOCK",
            "partition_discovery_prefix_sha256":parent.partition_discovery_prefix_sha256,
            "confirmation_sessions_read":0,
            "confirmation_membership_rows_decoded":parent.confirmation_membership_rows_decoded,
            "confirmation_observations_read":access.confirmation_observation_rows_decoded,
            "next_source_row_requested":access.next_source_row_requested
        }),
    )
}

fn write_descriptive(out: &Path, corpus: &CorpusProducts, analysis: &Analysis) -> AnyResult<()> {
    write_candidate_summaries(
        out.join("descriptive/candidate_summaries.tsv"),
        &corpus.candidate_summaries,
    )?;
    write_binary(
        out.join("descriptive/candidate_path_surface.bin"),
        bytemuck::cast_slice(&corpus.candidate_paths),
    )?;
    write_binary(
        out.join("descriptive/range_process_surface.bin"),
        bytemuck::cast_slice(&corpus.range_surface),
    )?;
    write_scale_curvature(out.join("descriptive/scale_curvature.tsv"), analysis)?;
    write_terminal_strata(
        out.join("descriptive/terminal_status_strata.tsv"),
        &corpus.candidate_summaries,
    )?;
    write_json(
        out.join("descriptive/DISC02E_DESCRIPTIVE_SURFACES.json"),
        &json!({
            "schema":"DISC02E_DESCRIPTIVE_SURFACES_V1",
            "classification":"DESCRIPTIVE_ONLY",
            "candidate_path_rows":corpus.candidate_paths.len(),
            "range_process_rows":corpus.range_surface.len(),
            "scale_curvature_rows":analysis.scale_curvature.len(),
            "binary_layouts":{
                "candidate_path_surface.bin":{"record":"PackedCandidatePath","bytes_per_record":std::mem::size_of::<crate::corpus::PackedCandidatePath>(),"endianness":"LITTLE_ENDIAN","missing":"NO_PADDING_OR_FABRICATED_SUFFIX"},
                "range_process_surface.bin":{"record":"PackedRangeSurface","bytes_per_record":std::mem::size_of::<crate::corpus::PackedRangeSurface>(),"endianness":"LITTLE_ENDIAN","non_evaluable_z":"IEEE_NAN_WITH_STATUS_0"}
            },
            "representation_views":["RAW_PRICE","MIRRORED_SIDE_CANONICAL","RANGE_RELATIVE_Z","CROSS_SCALE_SECOND_DIFFERENCE"],
            "grammar":"GRAMMAR_EXCLUDED_BY_PROTOCOL"
        }),
    )
}

fn write_candidate_summaries(path: PathBuf, rows: &[CandidateSummary]) -> AnyResult<()> {
    let file = File::create(path)?;
    let mut out = BufWriter::new(file);
    writeln!(
        out,
        "candidate_index\tcandidate_id\tsession_index\tsession_id\tside\tsequence_number\tbirth_knowledge_time\textreme_price\tterminal_state\tlifetime_minutes\tpath_observations\tfinal_same_direction_extension\tfinal_opposite_displacement\tfinal_path_length\tfinal_side_oriented_displacement\tcensor_state\tauthority_classification"
    )?;
    for row in rows {
        writeln!(
            out,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            row.candidate_index,
            row.candidate_id,
            row.session_index,
            row.session_id,
            row.side,
            row.sequence_number,
            row.birth_knowledge_time,
            row.extreme_price,
            row.terminal_state,
            row.lifetime_minutes,
            row.path_observations,
            opt(row.final_same_direction_extension),
            opt(row.final_opposite_displacement),
            opt(row.final_path_length),
            opt(row.final_side_oriented_displacement),
            row.censor_state,
            row.authority_classification
        )?;
    }
    out.flush()?;
    Ok(())
}

fn write_terminal_strata(path: PathBuf, rows: &[CandidateSummary]) -> AnyResult<()> {
    let mut strata: BTreeMap<(String, String), (usize, f64, usize)> = BTreeMap::new();
    for row in rows {
        let entry = strata
            .entry((row.side.clone(), row.terminal_state.clone()))
            .or_default();
        entry.0 += 1;
        entry.1 += f64::from(row.lifetime_minutes);
        entry.2 += usize::from(row.censor_state == "SESSION_END_CENSORED");
    }
    let mut out = BufWriter::new(File::create(path)?);
    writeln!(
        out,
        "side\tterminal_state\tcandidate_count\tmean_lifetime_minutes\tcensored_count\tclassification"
    )?;
    for ((side, state), (n, total, censored)) in strata {
        writeln!(
            out,
            "{side}\t{state}\t{n}\t{}\t{censored}\tDESCRIPTIVE_ONLY_RETROSPECTIVE_STRATUM",
            total / n as f64
        )?;
    }
    out.flush()?;
    Ok(())
}

fn write_scale_curvature(path: PathBuf, analysis: &Analysis) -> AnyResult<()> {
    let mut out = BufWriter::new(File::create(path)?);
    writeln!(
        out,
        "k\ttau_minutes\teligible_sessions\tmean_second_difference\tclassification"
    )?;
    for row in &analysis.scale_curvature {
        writeln!(
            out,
            "{}\t{}\t{}\t{}\t{}",
            row.k,
            row.tau_minutes,
            row.eligible_sessions,
            row.mean_second_difference,
            row.classification
        )?;
    }
    out.flush()?;
    Ok(())
}

fn write_support(out: &Path, analysis: &Analysis) -> AnyResult<()> {
    let mut writer = BufWriter::new(File::create(out.join("DISC02E_SUPPORT_CENSUS.tsv"))?);
    writeln!(
        writer,
        "family_id\tcell_id\teligible_sessions\tsupported_month_count\tmonth_counts\toffset_120\toffset_180\tchronological_blocks\tleave_one_month\tformal_support_state\tobserved_mean\tobserved_t"
    )?;
    for family in &analysis.support {
        for row in family {
            writeln!(
                writer,
                "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
                row.family_id,
                row.cell_id,
                row.eligible_sessions,
                row.supported_month_count,
                serde_json::to_string(&row.month_counts)?,
                row.offset_120_sessions,
                row.offset_180_sessions,
                serde_json::to_string(&row.chronological_block_counts)?,
                serde_json::to_string(&row.leave_one_month_statuses)?,
                row.formal_support_state,
                row.observed_mean,
                row.observed_t
            )?;
        }
    }
    writer.flush()?;
    Ok(())
}

fn write_formal(out: &Path, analysis: &Analysis) -> AnyResult<()> {
    let mut writer = BufWriter::new(File::create(
        out.join("formal/DISC02E_FORMAL_SURFACES.tsv"),
    )?);
    writeln!(
        writer,
        "family_id\trepresentation_id\tauthority_classification\tcell_id\teligible_sessions\tsupport_state\tobserved_contrast\tstudentized_statistic"
    )?;
    for (surface, support) in analysis.surfaces.iter().zip(&analysis.support) {
        for row in support {
            writeln!(
                writer,
                "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
                surface.family_id,
                surface.representation_id,
                surface.authority_classification,
                row.cell_id,
                row.eligible_sessions,
                row.formal_support_state,
                row.observed_mean,
                row.observed_t
            )?;
        }
    }
    writer.flush()?;
    for result in &analysis.results {
        let name = format!(
            "randomization/{}.f64le",
            result.family_id.to_ascii_lowercase()
        );
        write_binary(
            out.join(name),
            bytemuck::cast_slice(&result.reference_distribution),
        )?;
    }
    write_json(
        out.join("formal/DISC02E_RANDOMIZATION_RECEIPTS.json"),
        &json!({
            "schema":"DISC02E_RANDOMIZATION_RECEIPTS_V1",
            "algorithm":"DETERMINISTIC_SESSION_SIGN_REFLECTION_STUDENTIZED_MAX_T",
            "randomizations":RANDOMIZATIONS,
            "seed":RANDOM_SEED,
            "plus_one":true,
            "wilson_interval":"99_PERCENT",
            "families":analysis.results
        }),
    )?;
    write_json(
        out.join("formal/DISC02E_FORMAL_FAMILY_RESULTS.json"),
        &json!({
            "schema":"DISC02E_FORMAL_FAMILY_RESULTS_V1",
            "results":analysis.results
        }),
    )
}

fn build_candidates(analysis: &Analysis) -> AnyResult<(Vec<Value>, Vec<Value>)> {
    let mut candidates = Vec::new();
    let mut contracts = Vec::new();
    for result in analysis
        .results
        .iter()
        .filter(|r| r.terminal_state == "PROMOTED_DISCOVERY_ONLY")
    {
        let localization = result
            .localization
            .as_ref()
            .ok_or("PROMOTED_WITHOUT_LOCALIZATION")?;
        let seed = json!({
            "formal_estimand_id":result.family_id,
            "representation_id":result.representation_id,
            "anchor_cell":localization.anchor_cell,
            "direction":localization.direction,
            "disc02p_root":DISC02P_ROOT,
            "meas02_root":MEAS02_ROOT
        });
        let candidate_id = format!(
            "DISC02E:{}",
            &sha256_bytes(&canonical_json_bytes(&seed)?)[..24]
        );
        let contract_body = json!({
            "schema":"DISC02E_PROSPECTIVE_CONFIRMATION_CONTRACT_V1",
            "candidate_id":candidate_id,
            "discovery_family":result.family_id,
            "representation":result.representation_id,
            "support_domain":"EXACT_DISC02P_FORMAL_SUPPORT_CONTRACT",
            "localized_cell_set":localization.simultaneously_qualified_cells,
            "anchor_cell":localization.anchor_cell,
            "direction":localization.direction,
            "null":"JOINT_SESSION_REFLECTION_SYMMETRY_EQUALS_ZERO",
            "statistic":"STUDENTIZED_MAX_ABSOLUTE_STATISTIC_OVER_FROZEN_LOCALIZED_CELL_SET",
            "randomization":{"unit":"SESSION","count":RANDOMIZATIONS,"seed":RANDOM_SEED,"plus_one":true},
            "multiplicity":"HOLM_BONFERRONI_ALPHA_0_05_ACROSS_FROZEN_PROMOTED_REGISTRY",
            "numerical_decision":"WILSON_99_PERCENT_FAIL_CLOSED",
            "robustness":"FROZEN_DISC02P_TEMPORAL_VIEWS",
            "confirmation_support":{"sessions":35,"months":2,"sessions_per_month":10,"offsets":[120,180],"sessions_per_offset":10},
            "confirmation_decision":"ONE_SHOT_SAME_NONZERO_DIRECTION_AND_FROZEN_FAMILYWISE_RULE",
            "parent_discovery_receipt":{"disc02p_root":DISC02P_ROOT,"meas02_root":MEAS02_ROOT}
        });
        let contract_hash = sha256_bytes(&canonical_json_bytes(&contract_body)?);
        let contract = json!({"contract_id":format!("CONFIRM:{}",&contract_hash[..24]),"sha256":contract_hash,"body":contract_body});
        candidates.push(json!({
            "candidate_id":candidate_id,
            "status":"DISCOVERY_ONLY_UNCONFIRMED",
            "formal_estimand_id":result.family_id,
            "family_id":result.family_id,
            "representation_id":result.representation_id,
            "eligible_session_count":localization.eligible_sessions,
            "surface_domain":"FROZEN_SUPPORTED_CELLS",
            "omnibus_statistic":result.observed_max_abs_t,
            "raw_monte_carlo_p":result.corrected_p_value,
            "monte_carlo_interval":[result.wilson_99_lower,result.wilson_99_upper],
            "holm_decision":result.holm_decision,
            "anchor_cell":localization.anchor_cell,
            "simultaneously_qualified_cells":localization.simultaneously_qualified_cells,
            "frozen_cell_signs":localization.direction,
            "temporal_support_receipt":result.temporal_status,
            "insufficiencies":[],
            "future_confirmation_contract_sha256":contract_hash
        }));
        contracts.push(contract);
    }
    Ok((candidates, contracts))
}

fn write_typed_findings(out: &Path, analysis: &Analysis) -> AnyResult<()> {
    let findings: Vec<Value> = analysis.results.iter().map(|result| json!({
        "finding_id":format!("DISC02E:{}",result.family_id),
        "source_kind":"MACHINE_DERIVED",
        "evidence_class":result.authority_classification,
        "formal_family":result.family_id,
        "typed_state":result.terminal_state,
        "observed_max_abs_t":result.observed_max_abs_t,
        "corrected_p_value":result.corrected_p_value,
        "wilson_99":[result.wilson_99_lower,result.wilson_99_upper],
        "holm":{"rank":result.holm_rank,"threshold":result.holm_threshold,"pass":result.holm_decision},
        "temporal_status":result.temporal_status,
        "interpretation_limit":"STRUCTURE_ONLY_NO_MECHANISM_ECONOMIC_OR_TRADING_AUTHORITY"
    })).collect();
    write_json(
        out.join("DISC02E_TYPED_FINDINGS.json"),
        &json!({
            "schema":"DISC02E_TYPED_FINDINGS_V1",
            "findings":findings,
            "descriptive_nonclaims":[
                {"source_kind":"ARTIFACT_DECLARED","class":"DESCRIPTIVE_ONLY","scope":"candidate_lifetime_path_length_terminal_displacement_terminal_status_raw_price_scale_curvature"},
                {"source_kind":"ARTIFACT_DECLARED","class":"GRAMMAR_EXCLUDED_BY_PROTOCOL"},
                {"source_kind":"ARTIFACT_DECLARED","class":"NEAR_NULL_NOT_EVALUABLE"}
            ]
        }),
    )
}

pub fn write_rebuild_receipt(out: &Path, preseal: &[ArtifactMember]) -> AnyResult<String> {
    let set_hash = artifact_set_hash(preseal);
    write_json(
        out.join("DISC02E_REBUILD_RECEIPT.json"),
        &json!({
            "schema":"DISC02E_REBUILD_RECEIPT_V1",
            "status":"PASS",
            "independent_builds":2,
            "preseal_artifact_count":preseal.len(),
            "mismatch_count":0,
            "preseal_artifact_set_hash":set_hash,
            "byte_identity_required":true
        }),
    )?;
    Ok(set_hash)
}

pub fn seal(out: &Path, execution_code_hash: &str) -> AnyResult<SealResult> {
    let members = artifact_members(
        out,
        &["DISC02E_CONTENT_MANIFEST.tsv", "DISC02E_ROOT_RECEIPT.json"],
    )?;
    let mut manifest = BufWriter::new(File::create(out.join("DISC02E_CONTENT_MANIFEST.tsv"))?);
    writeln!(manifest, "relative_path\tbytes\tsha256")?;
    for member in &members {
        writeln!(
            manifest,
            "{}\t{}\t{}",
            member.relative_path, member.bytes, member.sha256
        )?;
    }
    manifest.flush()?;
    drop(manifest);
    let manifest_hash = sha256_file(&out.join("DISC02E_CONTENT_MANIFEST.tsv"))?;
    let set_hash = artifact_set_hash(&members);
    let preimage = json!({
        "schema":"DISC02E_ROOT_PREIMAGE_V1",
        "authority":"OBS_OPEN_DISC02E_DISCOVERY_V1",
        "disc02p_root":DISC02P_ROOT,
        "meas02_root":MEAS02_ROOT,
        "execution_code_sha256":execution_code_hash,
        "content_manifest_sha256":manifest_hash,
        "physical_artifact_set_sha256":set_hash,
        "confirmation_rows_read":0
    });
    let root = sha256_bytes(&canonical_json_bytes(&preimage)?);
    write_json(
        out.join("DISC02E_ROOT_RECEIPT.json"),
        &json!({
            "schema":"DISC02E_ROOT_RECEIPT_V1",
            "status":"PASS",
            "authority":"OBS_OPEN_DISC02E_DISCOVERY_V1",
            "disc02e_root":root,
            "disc02p_root":DISC02P_ROOT,
            "meas02_root":MEAS02_ROOT,
            "execution_code_sha256":execution_code_hash,
            "artifact_count":members.len(),
            "content_manifest_sha256":manifest_hash,
            "physical_artifact_set_sha256":set_hash,
            "discovery_sessions":DISCOVERY_SESSIONS,
            "confirmation_sessions_read":0,
            "confirmation_observations_read":0,
            "confirmation_state":"FROZEN_UNOPENED",
            "economic_authority":false,
            "trading_authority":false
        }),
    )?;
    Ok(SealResult {
        root,
        manifest_sha256: manifest_hash,
        artifact_set_hash: set_hash,
        artifact_count: members.len(),
        members,
    })
}

pub fn artifact_members(out: &Path, exclusions: &[&str]) -> AnyResult<Vec<ArtifactMember>> {
    let mut paths = Vec::new();
    collect_files(out, out, &mut paths)?;
    let mut members = Vec::new();
    for relative in paths {
        let normalized = relative.to_string_lossy().replace('\\', "/");
        if exclusions.contains(&normalized.as_str()) {
            continue;
        }
        let path = out.join(&relative);
        members.push(ArtifactMember {
            relative_path: normalized,
            bytes: std::fs::metadata(&path)?.len(),
            sha256: sha256_file(&path)?,
        });
    }
    members.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
    Ok(members)
}

pub fn compare_artifacts(left: &[ArtifactMember], right: &[ArtifactMember]) -> Vec<String> {
    let a: BTreeMap<_, _> = left
        .iter()
        .map(|m| (&m.relative_path, (m.bytes, &m.sha256)))
        .collect();
    let b: BTreeMap<_, _> = right
        .iter()
        .map(|m| (&m.relative_path, (m.bytes, &m.sha256)))
        .collect();
    a.keys()
        .chain(b.keys())
        .filter(|key| a.get(*key) != b.get(*key))
        .map(|key| (*key).clone())
        .collect()
}

pub fn publish_compact_seal(source: &Path, destination: &Path) -> AnyResult<()> {
    if destination.exists() {
        std::fs::remove_dir_all(destination)?;
    }
    std::fs::create_dir_all(destination)?;
    let members = artifact_members(source, &[])?;
    for member in &members {
        let from = source.join(&member.relative_path);
        let extension = from.extension().and_then(|x| x.to_str()).unwrap_or("");
        if member.bytes <= 5_000_000 && extension != "bin" && extension != "f64le" {
            let to = destination.join(&member.relative_path);
            if let Some(parent) = to.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::copy(from, to)?;
        }
    }
    write_json(
        destination.join("D_DRIVE_PAYLOAD_POINTER.json"),
        &json!({
            "schema":"DISC02E_D_DRIVE_PAYLOAD_POINTER_V1",
            "storage":"D_DRIVE_LOCAL_ONLY",
            "canonical_payload":source.to_string_lossy(),
            "artifact_count":members.len(),
            "members":members,
            "online_bulk_publication":false
        }),
    )
}

fn collect_files(root: &Path, current: &Path, out: &mut Vec<PathBuf>) -> AnyResult<()> {
    for entry in std::fs::read_dir(current)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(root, &path, out)?;
        } else {
            out.push(path.strip_prefix(root)?.to_path_buf());
        }
    }
    Ok(())
}

fn artifact_set_hash(members: &[ArtifactMember]) -> String {
    let mut h = Sha256::new();
    for member in members {
        h.update(member.relative_path.as_bytes());
        h.update([0]);
        h.update(member.bytes.to_le_bytes());
        h.update(member.sha256.as_bytes());
        h.update([b'\n']);
    }
    format!("{:x}", h.finalize())
}

fn write_binary(path: PathBuf, bytes: &[u8]) -> AnyResult<()> {
    let mut out = BufWriter::with_capacity(1 << 20, File::create(path)?);
    out.write_all(bytes)?;
    out.flush()?;
    Ok(())
}

fn write_json(path: PathBuf, value: &impl Serialize) -> AnyResult<()> {
    let bytes = canonical_json_bytes(value)?;
    std::fs::write(path, bytes)?;
    Ok(())
}

fn opt(value: Option<f64>) -> String {
    value.map(|x| x.to_string()).unwrap_or_else(|| "NA".into())
}
