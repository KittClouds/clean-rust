use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

#[path = "novel_full_manifold_smoke_v1.rs"]
mod smoke;

#[test]
fn regression_lock_against_blessed_baseline() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let out = root
        .join("target")
        .join("smoke")
        .join("novel_full_regression");
    let baseline = root
        .join("tests")
        .join("baselines")
        .join("novel_full_manifold_smoke_v1");
    let _ = fs::remove_dir_all(&out);
    fs::create_dir_all(&out).unwrap();

    let fresh = smoke::run_fixture_pipeline(&out, "regression");
    let base_summary = fs::read_to_string(baseline.join("smoke_summary.md")).unwrap();
    let base_total = summary_u64(&base_summary, "total_ms").max(1);
    let base_rss = summary_u64(&base_summary, "peak_rss_mib");
    let total_gate = ((base_total as f32 * 1.30).ceil() as u64).max(2_000);
    let rss_gate = ((base_rss as f32 * 1.25).ceil() as u64).max(base_rss + 128);
    assert!(fresh.total_ms <= total_gate);
    assert!(fresh.peak_rss_mib <= rss_gate);
    assert!(fresh.query_pack_ms <= 15_000);

    let second = smoke::run_fixture_pipeline(&out, "regression_repeat");
    assert_eq!(fresh.primary_cells, second.primary_cells);
    assert_eq!(fresh.chart_ids, second.chart_ids);
    assert_eq!(fresh.trace_hashes, second.trace_hashes);
    assert!(fs::read_to_string(baseline.join("determinism_diff.json"))
        .unwrap()
        .contains("\"changed_cone_trace_hashes\":0"));
}

#[test]
fn adversarial_novel_variants_keep_structural_bones() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let out = root.join("target").join("smoke").join("novel_adversarial");
    let _ = fs::remove_dir_all(&out);
    fs::create_dir_all(&out).unwrap();

    for (name, input) in adversarial_variants() {
        let first = smoke::run_pipeline(&out.join(name), "a", input.clone());
        let second = smoke::run_pipeline(&out.join(format!("{name}_repeat")), "b", input);
        assert_eq!(
            first.chunk_hashes, second.chunk_hashes,
            "{name}: chunks drifted"
        );
        assert_eq!(
            first.primary_cells, second.primary_cells,
            "{name}: projection drifted"
        );
        assert_eq!(
            first.trace_hashes, second.trace_hashes,
            "{name}: cone trace drifted"
        );
        assert_no_cell_collapse(name, &first.primary_cells);
        assert_no_duplicate_id_storm(name, &first.chart_ids);
    }
}

#[test]
fn quality_query_pack_is_present_and_metric_ready() {
    let body = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("quality_queries.toml"),
    )
    .unwrap();
    for id in [
        "character_identity_lookup",
        "event_causal_chain",
        "relationship_context",
        "setting_lookup",
        "contradiction_probe",
    ] {
        assert!(body.contains(&format!("id = \"{id}\"")));
    }
    for metric in [
        "precision_at_k",
        "context_lane_accuracy",
        "wrong_context_rate",
        "unsupported_bridge_rate",
        "evidence_coverage",
        "cone_trace_validity",
        "top_k_stability",
    ] {
        assert!(body.contains(metric));
    }
}

fn adversarial_variants() -> Vec<(&'static str, String)> {
    let clean = smoke::fixture_novel();
    vec![
        ("novel_clean", clean.clone()),
        (
            "novel_with_frontmatter",
            format!("---\ntitle: Smoke\nlang: en\n---\n\n{clean}"),
        ),
        (
            "novel_with_weird_unicode",
            clean.replace("storm", "storm - cafe naive resume facade"),
        ),
        (
            "novel_with_blank_sections",
            clean.replace("\n\n", "\n\n\n\n\n"),
        ),
        ("novel_with_repeated_chapters", repeated_chapters()),
        (
            "novel_with_extreme_dialogue",
            clean.replace('.', ".\n\"No.\" \"Yes.\" \"Why?\" \"Because.\""),
        ),
        (
            "novel_with_appendices",
            format!(
                "{clean}\n\nAPPENDIX A\n{}\nAPPENDIX B\n{}",
                clean_tail(),
                clean_tail()
            ),
        ),
        ("novel_scrambled_sections", scrambled_sections(&clean)),
    ]
}

fn repeated_chapters() -> String {
    let chapter =
        "Chapter R. Kai, Eureka, and Echo replay the same rupture with small witness changes. ";
    let mut text = String::with_capacity(260_000);
    for i in 0..3_800 {
        text.push_str(chapter);
        text.push_str(&format!(
            "Pass {i}: evidence lane {}, causal lane {}.\n",
            i % 17,
            i % 23
        ));
    }
    text
}

fn clean_tail() -> String {
    smoke::fixture_novel().chars().take(40_000).collect()
}

fn scrambled_sections(clean: &str) -> String {
    let mut sections = clean.split("\n\n").collect::<Vec<_>>();
    sections.reverse();
    sections.join("\n\n")
}

fn assert_no_cell_collapse(name: &str, cells: &[u32]) {
    let mut counts = BTreeMap::<u32, usize>::new();
    for cell in cells {
        *counts.entry(*cell).or_default() += 1;
    }
    let max = counts.values().copied().max().unwrap_or(0);
    assert!(
        max * 100 < cells.len().max(1) * 35,
        "{name}: projected too much mass into one cell"
    );
}

fn assert_no_duplicate_id_storm(name: &str, ids: &[String]) {
    let unique = ids.iter().collect::<std::collections::BTreeSet<_>>().len();
    assert_eq!(unique, ids.len(), "{name}: duplicate ID storm");
}

fn summary_u64(summary: &str, key: &str) -> u64 {
    summary
        .lines()
        .find(|line| line.starts_with(key))
        .and_then(|line| line.split_whitespace().last())
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(0)
}
