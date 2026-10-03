use std::collections::BTreeMap;
use std::sync::OnceLock;

use r1_stage1_stress_worlds_v05::{
    different_conflict_indices, generate_batch, load_config, make_support_manifest,
    private_diagnostics_bytes, private_task_bytes, public_projection_bytes,
    public_search_starts_bytes, sha256_hex, GeneratorConfig, SearchStartRow, StressBatch,
    EXPECTED_CANONICAL_CLASSES, EXPECTED_DECOY_CONFLICTS, EXPECTED_RAW_SOLUTIONS,
    EXPECTED_ROLE_AUTOMORPHISMS, K, N,
};
use r1_world::{validate, validate_independent, InferenceTask};

const SCENARIOS: [&str; 4] = [
    "base-random",
    "base-swap-trap",
    "dense-random",
    "dense-swap-trap",
];

fn config() -> &'static GeneratorConfig {
    static CONFIG: OnceLock<GeneratorConfig> = OnceLock::new();
    CONFIG.get_or_init(|| load_config(include_bytes!("../configs/stress-config-v05.json")).unwrap())
}

fn batch() -> &'static StressBatch {
    static BATCH: OnceLock<StressBatch> = OnceLock::new();
    BATCH.get_or_init(|| generate_batch(config()).unwrap())
}

#[test]
fn config_pins_the_balanced_paired_2x2_contract() {
    let config = config();
    assert_eq!(config.batch_size, 96);
    assert_eq!(config.underlying_worlds, 24);
    assert_eq!(config.scenarios.len(), 4);
    assert_eq!(config.split_counts.train, 64);
    assert_eq!(config.split_counts.validation, 16);
    assert_eq!(config.split_counts.qualification, 16);
}

#[test]
fn all_worlds_exhaust_exactly_54_raw_solutions_and_nine_role_classes() {
    let batch = batch();
    assert_eq!(batch.worlds.len(), 96);
    for world in &batch.worlds {
        assert_eq!(world.record.raw_solution_count, EXPECTED_RAW_SOLUTIONS);
        assert_eq!(
            world.record.canonical_solution_class_count,
            EXPECTED_CANONICAL_CLASSES
        );
        assert_eq!(
            world.record.role_automorphism_count,
            EXPECTED_ROLE_AUTOMORPHISMS
        );
        assert_eq!(
            world.record.independent_validator_checks,
            EXPECTED_RAW_SOLUTIONS
        );
        assert!(validate(
            &world.task,
            &world.private_diagnostics.planted_assignment
        ));
        assert!(validate_independent(
            &world.task,
            &world.private_diagnostics.planted_assignment
        ));
    }
}

#[test]
fn paired_worlds_stay_in_one_split_and_each_cell_is_16_4_4() {
    let batch = batch();
    let mut pairs = BTreeMap::<&str, Vec<_>>::new();
    for world in &batch.worlds {
        pairs
            .entry(&world.record.paired_world_id)
            .or_default()
            .push(world);
    }
    assert_eq!(pairs.len(), 24);
    for members in pairs.values() {
        assert_eq!(members.len(), 4);
        assert!(members
            .iter()
            .all(|world| world.record.split == members[0].record.split));
        assert_eq!(
            members[0].search_start.assignment,
            members[2].search_start.assignment
        );
        assert_eq!(
            members
                .iter()
                .map(|world| world.record.scenario_id.as_str())
                .collect::<Vec<_>>(),
            SCENARIOS
        );
    }
    for scenario in SCENARIOS {
        for (split, expected) in [("train", 16), ("validation", 4), ("qualification", 4)] {
            assert_eq!(
                batch
                    .worlds
                    .iter()
                    .filter(|world| {
                        world.record.scenario_id == scenario && world.record.split == split
                    })
                    .count(),
                expected,
                "{scenario}/{split}"
            );
        }
    }
    for (split, expected) in [("train", 64), ("validation", 16), ("qualification", 16)] {
        assert_eq!(
            batch
                .worlds
                .iter()
                .filter(|world| world.record.split == split)
                .count(),
            expected
        );
    }
}

#[test]
fn density_variants_add_ten_entailed_edges_without_changing_exact_classes() {
    for world in &batch().worlds {
        assert_eq!(
            world.record.edge_count,
            if world.record.density_level == "dense" {
                46
            } else {
                36
            }
        );
    }
}

#[test]
fn public_swap_traps_are_independently_validated_two_conflict_plateau_starts() {
    for world in &batch().worlds {
        let is_trap = world.record.start_kind == "witness_module1_swap_trap";
        let start = &world.search_start.assignment;
        if is_trap {
            assert_eq!(
                different_conflict_indices(&world.task, start).len(),
                EXPECTED_DECOY_CONFLICTS
            );
            assert!(!validate(&world.task, start));
            assert!(!validate_independent(&world.task, start));
            for entity in world.private_diagnostics.module_anchors[1]
                .into_iter()
                .take(2)
            {
                let mut one_edit = start.clone();
                one_edit[usize::from(entity)] =
                    world.private_diagnostics.planted_assignment[usize::from(entity)];
                assert_eq!(
                    different_conflict_indices(&world.task, &one_edit).len(),
                    EXPECTED_DECOY_CONFLICTS
                );
            }
            assert_eq!(world.search_start.initialization_seed, None);
        } else {
            assert_eq!(
                world.search_start.start_kind,
                "independent_random_assignment"
            );
            assert_eq!(
                world.search_start.initialization_seed,
                Some(world.record.seed ^ 0x5249535441525435)
            );
            assert!(start.iter().all(|role| *role < K));
        }
    }
}

#[test]
fn public_task_schema_stays_unchanged_and_search_state_is_separate() {
    let public = public_projection_bytes(&batch().worlds).unwrap();
    let forbidden = [
        b"\"seed\"".as_slice(),
        b"planted_assignment".as_slice(),
        b"decoy_conflict_clause_indices".as_slice(),
        b"raw_solution_count".as_slice(),
        b"search_start".as_slice(),
        b"assignment".as_slice(),
    ];
    assert!(forbidden
        .iter()
        .all(|needle| !public.windows(needle.len()).any(|window| window == *needle)));
    let decoded: Vec<InferenceTask> = public
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .map(|line| serde_json::from_slice(line).unwrap())
        .collect();
    assert_eq!(decoded.len(), 96);
    assert!(decoded
        .iter()
        .all(|task| task.n == N && task.k == K && !task.clauses.is_empty()));

    let starts = public_search_starts_bytes(&batch().worlds).unwrap();
    let rows: Vec<SearchStartRow> = starts
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .map(|line| serde_json::from_slice(line).unwrap())
        .collect();
    assert_eq!(rows.len(), 96);
    for row in rows {
        assert_eq!(row.schema, "R1_STAGE1_PUBLIC_SEARCH_START_V05");
        assert_eq!(row.assignment.len(), usize::from(N));
        assert!(row.assignment.iter().all(|role| *role < K));
        assert_eq!(sha256_hex(&row.assignment), row.assignment_sha256);
    }
}

#[test]
fn generation_is_byte_deterministic_and_uses_unique_versioned_ids() {
    let first = batch();
    let second = generate_batch(config()).unwrap();
    assert_eq!(
        public_projection_bytes(&first.worlds).unwrap(),
        public_projection_bytes(&second.worlds).unwrap()
    );
    assert_eq!(
        public_search_starts_bytes(&first.worlds).unwrap(),
        public_search_starts_bytes(&second.worlds).unwrap()
    );
    assert_eq!(
        private_task_bytes(&first.worlds).unwrap(),
        private_task_bytes(&second.worlds).unwrap()
    );
    assert_eq!(
        private_diagnostics_bytes(&first.worlds).unwrap(),
        private_diagnostics_bytes(&second.worlds).unwrap()
    );
    assert!(first
        .worlds
        .iter()
        .all(|world| world.task.id.starts_with("stress-v05-n20-")));
    assert!(first
        .worlds
        .iter()
        .all(|world| world.task.family_id.starts_with("r1-stress-v05-")));
    assert_eq!(
        first
            .worlds
            .iter()
            .map(|world| world.task.family_id.as_str())
            .collect::<std::collections::HashSet<_>>()
            .len(),
        96
    );
}

#[test]
fn support_manifest_binds_public_tasks_starts_config_and_pairing() {
    let public = public_projection_bytes(&batch().worlds).unwrap();
    let starts = public_search_starts_bytes(&batch().worlds).unwrap();
    let config_bytes = include_bytes!("../configs/stress-config-v05.json");
    let manifest = make_support_manifest(&public, &starts, config_bytes, &batch().worlds);
    assert_eq!(manifest.schema, "R1_STAGE1_STRESS_SENSOR_SUPPORT_V05_1");
    assert_eq!(manifest.source.rows, 96);
    assert_eq!(manifest.source.sha256, sha256_hex(&public));
    assert_eq!(
        manifest.search_starts.path,
        "public-search-starts-v05.jsonl"
    );
    assert_eq!(manifest.search_starts.rows, 96);
    assert_eq!(manifest.search_starts.bytes, starts.len());
    assert_eq!(manifest.search_starts.sha256, sha256_hex(&starts));
    assert!(manifest
        .search_starts
        .consumer
        .contains("excluded from sensor extraction"));
    assert_eq!(manifest.config.sha256, sha256_hex(config_bytes));
    assert_eq!(manifest.family_roster.len(), 96);
    assert_eq!(manifest.paired_world_count, 24);
    assert_eq!(manifest.scenario_counts.len(), 4);

    let value = serde_json::to_value(&manifest).unwrap();
    let split_counts = value["split_counts"].as_object().unwrap();
    assert_eq!(split_counts.len(), 3);
    assert!(split_counts.contains_key("train"));
    assert!(split_counts.contains_key("validation"));
    assert!(split_counts.contains_key("qualification"));
    assert_eq!(value["paired_world_count"].as_u64(), Some(24));
}
