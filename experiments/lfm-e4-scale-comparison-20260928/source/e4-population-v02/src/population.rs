use std::borrow::Cow;
use std::fs::File;
use std::path::{Path, PathBuf};

use fas_frozen_observer_bundle_panel_v04::generate::{
    self, EXPECTED_FACTORIAL_QUARTETS, for_each_quartet,
};
use fas_frozen_observer_bundle_panel_v04::model::{Quartet, TermInventory};
use hashbrown::HashSet;
use memchr::memchr_iter;
use memmap2::MmapOptions;
use serde::Deserialize;
use serde_json::Value;

use crate::identity::{
    E1_GENERATOR_SOURCE_SHA256, E1_INPUT_SHA256, E1_ROOT_SHA256, E1_ROW_MANIFEST_SHA256,
    E1_TERM_INVENTORY_SHA256, FreshnessIndex, POPULATION_NAMESPACE, SELECTED_PREFIX,
    WORLD_RENDER_SEED, choose_collision_free, hex, sha256, sha256_hex,
};
use crate::render::{
    ESCROW_TRUTH_PARTITION, HELDOUT_SURFACE_ID, PRIMARY_SURFACE_ID, PRIMARY_TRUTH_PARTITION,
    RenderedSurface, TemplateSurface, TermInventoryView, load_heldout_surface, primary_surface,
    render_surface,
};
use crate::schema::{
    CollisionSkip, FitEligibility, GeneratedQuartet, GeneratedRow, ModelInputRow,
    PopulationReceipt, PrimarySupport, RenderChoice, RowManifestEntry, SemanticQuartet,
    TerminalLabel,
};
use crate::support::{frozen_support_expectation, lexical_stratum};

const E1_INPUTS_RELATIVE: &str = "panel/panel-inputs-v01.jsonl";
const E1_ROWS_RELATIVE: &str = "panel/row-manifest-v01.jsonl";
const E1_TERMS_RELATIVE: &str = "corpus/term-inventory-v01.json";
const E1_INPUTS_BYTES: u64 = 33_781_760;
const E1_ROWS_BYTES: u64 = 23_126_310;
const E1_TERMS_BYTES: u64 = 1_412;
const E1_SEAL_FILE: &str = "e1-seal-v01.json";
const AUTH_SCHEMA_SHA256: &str = "73a7cb5e4bb23463bc73e0591f903644c46ad17129f1bc3c1b1f58bccb87aed3";
const AUTH_SCHEMA_BYTES: &str =
    include_str!("../../../contracts/e4-0-stage-authorization-schema-v01.json");
const QUARTETS_PER_SURFACE: usize = 4;
const SURFACE_COUNT: usize = 2;
const ROWS_PER_QUARTET: usize = QUARTETS_PER_SURFACE * SURFACE_COUNT;

#[derive(Clone, Debug)]
pub struct PopulationPaths {
    pub e1_root: PathBuf,
    pub heldout_template_manifest: PathBuf,
}

impl PopulationPaths {
    pub fn workstation_defaults() -> Self {
        let experiment_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(2)
            .expect("crate is nested under experiment/source")
            .to_path_buf();
        Self {
            e1_root: PathBuf::from(
                r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04",
            ),
            heldout_template_manifest: experiment_root
                .join("plans/E4-0-HELDOUT-TEMPLATES-v02.json"),
        }
    }
}

#[derive(Deserialize)]
struct SealManifest {
    root_sha256: String,
    status: String,
    model_contact_authorized: bool,
    entries: Vec<SealEntry>,
}

#[derive(Deserialize)]
struct SealEntry {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Deserialize)]
struct InputRow<'a> {
    #[serde(borrow)]
    input_text: Cow<'a, str>,
}

#[derive(Deserialize)]
struct E1IdentityRow<'a> {
    #[serde(borrow)]
    quartet_id: &'a str,
    #[serde(borrow)]
    row_id: &'a str,
}

struct E1Assets {
    terms: TermInventory,
    heldout_surface: TemplateSurface,
    freshness: FreshnessIndex,
}

#[derive(Clone, Copy, Debug)]
struct AcceptedDesign {
    semantic: SemanticQuartet,
    quartet_digest: [u8; 32],
    candidate_counter: u64,
    primary_choice: RenderChoice,
    heldout_choice: RenderChoice,
}

#[derive(Clone, Copy)]
struct SurfaceBinding<'a> {
    code: u8,
    surface_id: &'a str,
    truth_partition: &'a str,
}

#[derive(Clone, Debug)]
pub struct PopulationPlan {
    pub receipt: PopulationReceipt,
    decisions: Vec<AcceptedDesign>,
    terms: TermInventory,
    primary_surface: TemplateSurface,
    heldout_surface: TemplateSurface,
}

impl PopulationPlan {
    pub fn quartet_count(&self) -> usize {
        self.decisions.len()
    }

    pub fn collision_skips(&self) -> &[CollisionSkip] {
        &self.receipt.collision_skips
    }

    /// Emits row groups only after the caller supplies a validated stage permit.
    /// The population planner itself never writes E4 rows.
    pub fn emit_quartets<F>(&self, permit: &PopulationPermit, mut emit: F) -> Result<(), String>
    where
        F: FnMut(GeneratedQuartet) -> Result<(), String>,
    {
        if permit.stage != "POPULATION_GENERATION" {
            return Err(
                "population emission requires the POPULATION_GENERATION stage permit".into(),
            );
        }
        let term_view = TermInventoryView {
            context_terms: &self.terms.context_terms,
            entity_terms: &self.terms.entity_terms,
        };
        for (population_ordinal, design) in self.decisions.iter().enumerate() {
            let primary = render_surface(
                &self.primary_surface,
                &term_view,
                design.semantic,
                design.primary_choice,
            )?;
            let heldout = render_surface(
                &self.heldout_surface,
                &term_view,
                design.semantic,
                design.heldout_choice,
            )?;
            let generated = build_quartet(population_ordinal as u64, *design, primary, heldout);
            emit(generated)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct PopulationPermit {
    contract_root: String,
    authorization_id: String,
    output_root: PathBuf,
    stage: String,
}

impl PopulationPermit {
    /// Independent engineering population only; never used for E4-0 custody.
    pub fn scale_comparison(output_root: PathBuf) -> Self {
        Self {
            contract_root: "ENGINEERING_SCALE_COMPARISON".to_owned(),
            authorization_id: "USER_REQUEST_20260928".to_owned(),
            output_root,
            stage: "POPULATION_GENERATION".to_owned(),
        }
    }

    pub fn output_root(&self) -> &Path {
        &self.output_root
    }

    pub fn contract_root(&self) -> &str {
        &self.contract_root
    }

    pub fn authorization_id(&self) -> &str {
        &self.authorization_id
    }
}

pub fn verify_population_stage_authorization(
    receipt_path: &Path,
    expected_contract_sha256: &str,
    expected_seal_manifest_sha256: &str,
    expected_contract_root: &str,
    expected_output_root: &Path,
    now_unix_seconds: u64,
) -> Result<PopulationPermit, String> {
    if sha256_hex(AUTH_SCHEMA_BYTES.as_bytes()) != AUTH_SCHEMA_SHA256 {
        return Err("stage authorization schema bytes differ from the bound v01 identity".into());
    }
    let bytes = std::fs::read(receipt_path)
        .map_err(|error| format!("read stage authorization receipt: {error}"))?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("decode stage authorization receipt: {error}"))?;
    let scope = value["scope"]
        .as_object()
        .ok_or("stage scope object missing")?;
    let roots = value["exact_predecessor_roots"]
        .as_object()
        .ok_or("stage predecessor roots missing")?;
    let output_root = value["output_root"]
        .as_str()
        .ok_or("stage authorization output_root missing")?;
    let issued = value["issued_utc_unix_seconds"]
        .as_u64()
        .ok_or("stage authorization issue time missing")?;
    let valid_from = value["valid_from_utc_unix_seconds"]
        .as_u64()
        .ok_or("stage authorization start time missing")?;
    let valid_until = value["valid_until_utc_unix_seconds"]
        .as_u64()
        .ok_or("stage authorization expiry missing")?;
    let expected_scope = [
        ("population_generation", true),
        ("tokenizer_contact", false),
        ("model_contact", false),
        ("feature_extraction", false),
        ("evaluation_label_opening", false),
        ("scoring", false),
        ("fitting", false),
        ("e4_a", false),
        ("heldout_template_label_opening", false),
        ("joint_template_label_opening", false),
    ];
    let scope_matches = scope.len() == expected_scope.len()
        && expected_scope
            .iter()
            .all(|(key, expected)| scope.get(*key).and_then(Value::as_bool) == Some(*expected));
    let predecessor_matches = roots.len() == 4
        && roots.get("e0_v10_root_sha256").and_then(Value::as_str)
            == Some("899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd")
        && roots.get("e1_v04_root_sha256").and_then(Value::as_str) == Some(E1_ROOT_SHA256)
        && roots.get("e2_v07_root_sha256").and_then(Value::as_str)
            == Some("a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a")
        && roots
            .get("e3_v02_bundle_root_sha256")
            .and_then(Value::as_str)
            == Some("899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1");
    let auth_id = value["authorization_id"].as_str().unwrap_or_default();
    if value["schema"] != "FAS_E4_0_STAGE_AUTH_V01"
        || auth_id.is_empty()
        || value["status"] != "AUTHORIZED"
        || value["stage"] != "POPULATION_GENERATION"
        || value["contract_sha256"] != expected_contract_sha256
        || value["contract_seal_manifest_sha256"] != expected_seal_manifest_sha256
        || value["contract_seal_root_sha256"] != expected_contract_root
        || !predecessor_matches
        || output_root != expected_output_root.to_string_lossy()
        || value["authorized_by"] != "ACTIVE_USER_REQUEST"
        || issued > valid_from
        || valid_from > now_unix_seconds
        || valid_until <= valid_from
        || valid_until < now_unix_seconds
        || !scope_matches
    {
        return Err(
            "stage receipt does not authorize only this sealed population-generation stage".into(),
        );
    }
    Ok(PopulationPermit {
        contract_root: expected_contract_root.to_owned(),
        authorization_id: auth_id.to_owned(),
        output_root: PathBuf::from(output_root),
        stage: "POPULATION_GENERATION".to_owned(),
    })
}
pub fn prepare_population(paths: &PopulationPaths) -> Result<PopulationPlan, String> {
    verify_generator_reference_source()?;
    let (assets, provenance) = load_e1_assets(paths)?;
    let expectation = frozen_support_expectation()?;
    let E1Assets {
        terms,
        heldout_surface: heldout_templates,
        mut freshness,
    } = assets;
    let term_view = TermInventoryView {
        context_terms: &terms.context_terms,
        entity_terms: &terms.entity_terms,
    };
    let primary_templates = primary_surface();
    let mut decisions = Vec::with_capacity(expectation.selected_prefix);
    let mut skips = Vec::new();
    let mut support = PrimarySupport::default();
    let mut ordinal = 0_u64;

    let generation = for_each_quartet(|quartet| -> Result<(), Box<dyn std::error::Error>> {
        if ordinal >= expectation.selected_prefix as u64 {
            return Ok(());
        }
        if quartet.track_id != "FACTORIAL_BALANCED" {
            return Err(std::io::Error::other(
                "E1 factorial schedule ended before the frozen selected prefix",
            )
            .into());
        }
        let semantic = semantic_from_e1(ordinal, &quartet).map_err(std::io::Error::other)?;
        let accepted = choose_collision_free(
            &mut freshness,
            semantic,
            |_, primary_choice, heldout_choice| {
                let primary =
                    render_surface(&primary_templates, &term_view, semantic, primary_choice)?;
                let heldout =
                    render_surface(&heldout_templates, &term_view, semantic, heldout_choice)?;
                Ok(std::array::from_fn(|index| {
                    if index < 4 {
                        primary.inputs[index].clone()
                    } else {
                        heldout.inputs[index - 4].clone()
                    }
                }))
            },
        )
        .map_err(std::io::Error::other)?;
        let primary = render_surface(
            &primary_templates,
            &term_view,
            semantic,
            accepted.primary_choice,
        )
        .map_err(std::io::Error::other)?;
        for variant in 0..4 {
            support.record_row(
                primary.context_term_ids[variant],
                primary.entity_term_ids[variant],
                semantic.relation_id,
                semantic.state_id,
                primary.exact_target,
            );
        }
        skips.extend(accepted.skipped);
        decisions.push(AcceptedDesign {
            semantic,
            quartet_digest: accepted.quartet_digest,
            candidate_counter: accepted.candidate_counter,
            primary_choice: accepted.primary_choice,
            heldout_choice: accepted.heldout_choice,
        });
        ordinal += 1;
        Ok(())
    })
    .map_err(|error| format!("replay frozen E1 factorial schedule: {error}"))?;

    if generation.factorial != EXPECTED_FACTORIAL_QUARTETS
        || decisions.len() != expectation.selected_prefix
    {
        return Err(
            "E1 factorial schedule count or selected E4 prefix differs from the contract".into(),
        );
    }
    if !support.meets_target() {
        return Err(format!(
            "selected prefix support differs from frozen v11 receipt (actual minimum {}, expected {})",
            support.minimum_class_count(),
            expectation.selected.minimum_class_count()
        ));
    }
    let candidate_counter_sum = decisions
        .iter()
        .map(|decision| decision.candidate_counter)
        .sum::<u64>();
    let maximum_candidate_counter = decisions
        .iter()
        .map(|decision| decision.candidate_counter)
        .max()
        .unwrap_or(0);
    // Fresh namespace changes the collision walk. Its counts are recorded, not
    // compared to E4-0's reserved population receipt.
    let computed_previous_minimum = recompute_previous_prefix_minimum(&decisions, &terms)?;
    // This independent fixed-size TEST uses E4's prefix length and support
    // floor. It does not borrow E4-0's exact previous-prefix receipt.
    let primary_rows = expectation.selected_prefix as u64 * 4;
    let heldout_rows = primary_rows;
    let mut receipt = PopulationReceipt {
        receipt_id: "FAS_E4_0_POPULATION_GENERATION_V01".into(),
        status: "PREPARED_MODEL_FREE_NO_ROWS_WRITTEN".into(),
        contract_seal_root_sha256: None,
        authorization_id: None,
        output_root: None,
        population_rows_written: false,
        e1_root_sha256: E1_ROOT_SHA256.into(),
        e1_input_sha256: provenance.input_sha256,
        e1_row_manifest_sha256: provenance.rows_sha256,
        e1_term_inventory_sha256: provenance.terms_sha256,
        heldout_template_manifest_sha256: provenance.template_sha256,
        population_namespace: POPULATION_NAMESPACE.into(),
        world_render_seed_u64: WORLD_RENDER_SEED,
        selected_whole_quartet_prefix: expectation.selected_prefix as u64,
        shared_candidate_counter_sum: candidate_counter_sum,
        maximum_candidate_counter,
        selected_primary_support: support,
        previous_prefix_minimum_class_count: computed_previous_minimum,
        primary_rows,
        heldout_template_rows: heldout_rows,
        unique_feature_rows: primary_rows + heldout_rows,
        row_order: "schedule ordinal ascending; primary surface then heldout surface; variants A,C,E,P".into(),
        input_schema: "row_id,quartet_id,variant_id,input_text; label-free".into(),
        row_manifest_schema: "row_index,row_id,quartet_id,variant_id,surface_id,truth_partition; custody-only and label-free".into(),
        terminal_label_schema: "row_id,quartet_id,variant_id,context_term_id,entity_term_id,relation_id,state_id,exact_target,target_candidate_identity,candidate_identity_order,both_terms_train_side,fit_eligibility,score_strata".into(),
        escrow_label_schema: "terminal label fields plus joint_template_lexical; TEMPLATE_ESCROW custody".into(),
        template_truth_opened: false,
        template_joint_support_emitted: false,
        predictions_emitted: false,
        tokenizer_contacted: false,
        model_contacted: false,
        cuda_initialized: false,
        files: Vec::new(),
        collision_skips: skips.clone(),
    };
    receipt.status = "PREPARED_MODEL_FREE_NO_ROWS_WRITTEN".into();
    Ok(PopulationPlan {
        receipt,
        decisions,
        terms,
        primary_surface: primary_templates,
        heldout_surface: heldout_templates,
    })
}

#[derive(Clone, Debug)]
pub struct E1Provenance {
    pub input_sha256: String,
    pub rows_sha256: String,
    pub terms_sha256: String,
    pub template_sha256: String,
}

fn load_e1_assets(paths: &PopulationPaths) -> Result<(E1Assets, E1Provenance), String> {
    let seal_path = paths.e1_root.join(E1_SEAL_FILE);
    let seal_bytes = std::fs::read(&seal_path)
        .map_err(|error| format!("read sealed E1 manifest {}: {error}", seal_path.display()))?;
    let seal: SealManifest = serde_json::from_slice(&seal_bytes)
        .map_err(|error| format!("decode sealed E1 manifest: {error}"))?;
    if seal.root_sha256 != E1_ROOT_SHA256
        || seal.status != "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED"
        || seal.model_contact_authorized
    {
        return Err(
            "E1 seal identity or no-model-contact status differs from frozen predecessor".into(),
        );
    }

    let inputs_path = paths.e1_root.join(E1_INPUTS_RELATIVE);
    let rows_path = paths.e1_root.join(E1_ROWS_RELATIVE);
    let terms_path = paths.e1_root.join(E1_TERMS_RELATIVE);
    let inputs = load_e1_input_hashes(&inputs_path)?;
    let (quartets, row_ids) = load_e1_row_identities(&rows_path)?;
    let term_bytes =
        std::fs::read(&terms_path).map_err(|error| format!("read E1 term inventory: {error}"))?;
    if term_bytes.len() as u64 != E1_TERMS_BYTES
        || sha256_hex(&term_bytes) != E1_TERM_INVENTORY_SHA256
    {
        return Err("E1 term inventory size/hash differs from the sealed v04 identity".into());
    }
    let terms: TermInventory = serde_json::from_slice(&term_bytes)
        .map_err(|error| format!("decode E1 term inventory: {error}"))?;
    let generated_terms = generate::term_inventory();
    if terms != generated_terms || terms.context_terms.len() != 32 || terms.entity_terms.len() != 32
    {
        return Err(
            "E1 term ID-to-term table differs from the byte-pinned frozen inventory".into(),
        );
    }
    if inputs.len() != 103_206 || quartets.len() != 26_624 || row_ids.len() != 106_496 {
        return Err(
            "E1 freshness index cardinalities differ from the sealed v04 population".into(),
        );
    }
    let (heldout_surface, template_sha256, _) =
        load_heldout_surface(&paths.heldout_template_manifest)?;

    let expected_entries = [
        (E1_INPUTS_RELATIVE, E1_INPUTS_BYTES, E1_INPUT_SHA256),
        (E1_ROWS_RELATIVE, E1_ROWS_BYTES, E1_ROW_MANIFEST_SHA256),
        (E1_TERMS_RELATIVE, E1_TERMS_BYTES, E1_TERM_INVENTORY_SHA256),
    ];
    for (path, expected_bytes, expected_hash) in expected_entries {
        let entry = seal
            .entries
            .iter()
            .find(|entry| entry.path == path)
            .ok_or_else(|| format!("E1 seal manifest omits allowed input {path}"))?;
        if entry.bytes != expected_bytes || entry.sha256 != expected_hash {
            return Err(format!("E1 seal manifest identity differs for {path}"));
        }
    }

    let mut freshness = FreshnessIndex::with_capacity(
        inputs.len(),
        quartets.len() + SELECTED_PREFIX,
        row_ids.len() + SELECTED_PREFIX * ROWS_PER_QUARTET,
    );
    freshness.rendered_input_hashes = inputs;
    freshness.quartet_ids = quartets;
    freshness.row_ids = row_ids;
    Ok((
        E1Assets {
            terms,
            heldout_surface,
            freshness,
        },
        E1Provenance {
            input_sha256: E1_INPUT_SHA256.into(),
            rows_sha256: E1_ROW_MANIFEST_SHA256.into(),
            terms_sha256: E1_TERM_INVENTORY_SHA256.into(),
            template_sha256,
        },
    ))
}

fn verify_generator_reference_source() -> Result<(), String> {
    let bytes = include_bytes!("../../panel-generator-v04/src/generate.rs");
    if sha256_hex(bytes) != E1_GENERATOR_SOURCE_SHA256 {
        return Err(
            "E1 generator reference source bytes differ from the source-map identity".into(),
        );
    }
    Ok(())
}

fn load_e1_input_hashes(path: &Path) -> Result<HashSet<[u8; 32]>, String> {
    let (map, digest, length) = mapped_sha256(path)?;
    if hex(&digest) != E1_INPUT_SHA256 || length as u64 != E1_INPUTS_BYTES {
        return Err("E1 panel input file hash/size differs from the sealed E1 v04 identity".into());
    }
    let mut hashes = HashSet::with_capacity(110_000);
    for line in lines(&map) {
        let row: InputRow<'_> = serde_json::from_slice(line)
            .map_err(|error| format!("decode label-free E1 input row: {error}"))?;
        hashes.insert(sha256(row.input_text.as_bytes()));
    }
    Ok(hashes)
}

fn load_e1_row_identities(path: &Path) -> Result<(HashSet<String>, HashSet<String>), String> {
    let (map, digest, length) = mapped_sha256(path)?;
    if hex(&digest) != E1_ROW_MANIFEST_SHA256 || length as u64 != E1_ROWS_BYTES {
        return Err(
            "E1 row manifest file hash/size differs from the sealed E1 v04 identity".into(),
        );
    }
    let mut quartets = HashSet::with_capacity(30_000);
    let mut rows = HashSet::with_capacity(110_000);
    for line in lines(&map) {
        let row: E1IdentityRow<'_> = serde_json::from_slice(line)
            .map_err(|error| format!("decode label-free E1 row identity: {error}"))?;
        quartets.insert(row.quartet_id.to_owned());
        rows.insert(row.row_id.to_owned());
    }
    Ok((quartets, rows))
}

fn mapped_sha256(path: &Path) -> Result<(memmap2::Mmap, [u8; 32], usize), String> {
    let file =
        File::open(path).map_err(|error| format!("open read-only {}: {error}", path.display()))?;
    let map = unsafe { MmapOptions::new().map(&file) }
        .map_err(|error| format!("read-only map {}: {error}", path.display()))?;
    let digest = sha256(&map);
    let length = map.len();
    Ok((map, digest, length))
}

fn lines(bytes: &[u8]) -> impl Iterator<Item = &[u8]> {
    let mut start = 0;
    memchr_iter(b'\n', bytes).map(move |newline| {
        let mut line = &bytes[start..newline];
        if line.last() == Some(&b'\r') {
            line = &line[..line.len() - 1];
        }
        start = newline + 1;
        line
    })
}

fn semantic_from_e1(ordinal: u64, quartet: &Quartet) -> Result<SemanticQuartet, String> {
    if quartet.track_id != "FACTORIAL_BALANCED"
        || quartet.variants.len() != 4
        || quartet.variants[0].variant_id != "A"
        || quartet.variants[0].context_term_id / 16 > 1
        || quartet.variants[0].entity_term_id / 16 > 1
    {
        return Err(
            "E1 semantic quartet does not match the frozen factorial/A-C-E-P schema".into(),
        );
    }
    Ok(SemanticQuartet {
        schedule_ordinal: ordinal,
        track_code: 0,
        context_split: quartet.variants[0].context_term_id / 16,
        entity_split: quartet.variants[0].entity_term_id / 16,
        family_id: quartet.world_family_id,
        relation_id: quartet.relation_id,
        state_id: quartet.state_id,
        context_pair_id: quartet.context_pair_id,
        entity_pair_id: quartet.entity_pair_id,
    })
}

fn build_quartet(
    population_ordinal: u64,
    design: AcceptedDesign,
    primary: RenderedSurface,
    heldout: RenderedSurface,
) -> GeneratedQuartet {
    let qid = hex(&design.quartet_digest);
    let primary_binding = SurfaceBinding {
        code: 0,
        surface_id: PRIMARY_SURFACE_ID,
        truth_partition: PRIMARY_TRUTH_PARTITION,
    };
    let heldout_binding = SurfaceBinding {
        code: 1,
        surface_id: HELDOUT_SURFACE_ID,
        truth_partition: ESCROW_TRUTH_PARTITION,
    };
    let primary_rows = std::array::from_fn(|variant| {
        build_row(
            population_ordinal,
            design,
            &qid,
            &primary,
            variant,
            primary_binding,
        )
    });
    let heldout_rows = std::array::from_fn(|variant| {
        build_row(
            population_ordinal,
            design,
            &qid,
            &heldout,
            variant,
            heldout_binding,
        )
    });
    GeneratedQuartet {
        quartet_id: qid,
        semantic: design.semantic,
        candidate_counter: design.candidate_counter,
        primary_choice: design.primary_choice,
        heldout_choice: design.heldout_choice,
        primary_rows,
        heldout_rows,
    }
}

fn build_row(
    population_ordinal: u64,
    design: AcceptedDesign,
    quartet_id: &str,
    rendered: &RenderedSurface,
    variant_index: usize,
    binding: SurfaceBinding<'_>,
) -> GeneratedRow {
    let row_id = crate::identity::row_id(&design.quartet_digest, binding.code, variant_index as u8);
    let context_term_id = rendered.context_term_ids[variant_index];
    let entity_term_id = rendered.entity_term_ids[variant_index];
    let both_train = context_term_id < 16 && entity_term_id < 16;
    let variant_id = crate::render::VARIANT_IDS[variant_index].to_owned();
    let row_index = population_ordinal * ROWS_PER_QUARTET as u64
        + binding.code as u64 * QUARTETS_PER_SURFACE as u64
        + variant_index as u64;
    let label = TerminalLabel {
        row_id: row_id.clone(),
        quartet_id: quartet_id.to_owned(),
        variant_id: variant_id.clone(),
        context_term_id,
        entity_term_id,
        relation_id: design.semantic.relation_id,
        state_id: design.semantic.state_id,
        exact_target: rendered.exact_target,
        target_candidate_identity: design.semantic.state_id,
        candidate_identity_order: rendered.candidate_identity_order,
        both_terms_train_side: both_train,
        fit_eligibility: FitEligibility {
            context_identity: true,
            entity_identity: true,
            relation_identity: both_train,
            observed_state: both_train,
            exact_target: both_train,
        },
        score_strata: lexical_stratum(context_term_id, entity_term_id).to_owned(),
        joint_template_lexical: if binding.code == 1 {
            Some(context_term_id >= 16 || entity_term_id >= 16)
        } else {
            None
        },
    };
    GeneratedRow {
        input: ModelInputRow {
            row_id: row_id.clone(),
            quartet_id: quartet_id.to_owned(),
            variant_id: variant_id.clone(),
            input_text: rendered.inputs[variant_index].clone(),
        },
        manifest: RowManifestEntry {
            row_index,
            row_id,
            quartet_id: quartet_id.to_owned(),
            variant_id,
            surface_id: binding.surface_id.to_owned(),
            truth_partition: binding.truth_partition.to_owned(),
        },
        label,
    }
}

fn recompute_previous_prefix_minimum(
    decisions: &[AcceptedDesign],
    terms: &TermInventory,
) -> Result<u64, String> {
    let term_view = TermInventoryView {
        context_terms: &terms.context_terms,
        entity_terms: &terms.entity_terms,
    };
    let surface = primary_surface();
    let mut support = PrimarySupport::default();
    for design in &decisions[..decisions.len() - 1] {
        let rendered =
            render_surface(&surface, &term_view, design.semantic, design.primary_choice)?;
        for variant in 0..4 {
            support.record_row(
                rendered.context_term_ids[variant],
                rendered.entity_term_ids[variant],
                design.semantic.relation_id,
                design.semantic.state_id,
                rendered.exact_target,
            );
        }
    }
    Ok(support.minimum_class_count())
}

#[cfg(test)]
mod tests {
    use super::{PopulationPaths, prepare_population, verify_population_stage_authorization};
    use crate::identity::E1_ROOT_SHA256;
    use std::path::Path;

    #[test]
    fn malformed_or_missing_stage_receipt_cannot_create_a_population_permit() {
        let error = verify_population_stage_authorization(
            Path::new("missing-e4-population-auth.json"),
            &"a".repeat(64),
            &"b".repeat(64),
            &"c".repeat(64),
            Path::new("D:\\codex-runs\\e4-0"),
            1,
        )
        .unwrap_err();
        assert!(error.contains("read stage authorization"));
    }

    #[test]
    fn model_free_independent_prefix_meets_support_and_freshness() {
        let paths = PopulationPaths::workstation_defaults();
        if !paths.e1_root.join("e1-seal-v01.json").exists() {
            panic!("sealed E1 public inputs are required for the registered source replay test");
        }
        let plan = prepare_population(&paths).unwrap();
        assert_eq!(plan.receipt.e1_root_sha256, E1_ROOT_SHA256);
        assert_eq!(plan.quartet_count(), 18_667);
        assert_eq!(plan.receipt.primary_rows, 74_668);
        assert_eq!(plan.receipt.heldout_template_rows, 74_668);
        assert_eq!(plan.receipt.unique_feature_rows, 149_336);
        assert!(plan.receipt.selected_primary_support.minimum_class_count() >= 250);
        assert!(!plan.receipt.template_truth_opened);
        assert!(!plan.receipt.template_joint_support_emitted);
        assert!(!plan.receipt.predictions_emitted);
        assert!(
            !plan.receipt.model_contacted
                && !plan.receipt.tokenizer_contacted
                && !plan.receipt.cuda_initialized
        );
        assert_eq!(
            plan.receipt.heldout_template_manifest_sha256,
            "e3b8a70b90b06fc4185d2e379cbfc7cf3724238d9505590add1cf8bba2e9b068"
        );
        assert!(plan.receipt.shared_candidate_counter_sum > 0);
        assert!(plan.receipt.maximum_candidate_counter > 0);
    }
}
