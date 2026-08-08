use std::collections::HashMap;

use phoenix_reweight::cohort_miner::{mine_cohort, simulate_frozen_cohort, CohortMinerConfig};
use phoenix_reweight::curator_labeler::HumanCuratorEngine;
use phoenix_reweight::dataset::{
    append_to_ledger_jsonl, export_ledger_jsonl, load_ledger_jsonl, DatasetBuilder, FailureClass,
};
use phoenix_reweight::generator::InteractionGenerator;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let ledger_path = "phase4_reweighted_ledger.jsonl";

    // =========================================================================
    // STEP 0: Generate baseline synthetic interaction pairs
    // =========================================================================
    println!("=== Phoenix Reweight Engine: Human Labeling Pipeline ===\n");
    println!("--- Step 0: Baseline Synthetic Pairs ---");

    let synthetic_suite = InteractionGenerator::generate_suite(100);
    let builder = DatasetBuilder::new();
    let synthetic_pairs = builder.process_queries(&synthetic_suite);

    export_ledger_jsonl(ledger_path, &synthetic_pairs)?;
    println!(
        "Baseline ledger: {} pairs exported to '{}'",
        synthetic_pairs.len(),
        ledger_path
    );

    // =========================================================================
    // STEP 1: Mine V2-disagreement correction pairs from frozen release cohort
    // =========================================================================
    println!("\n--- Step 1: Cohort Mining (Frozen Release Cohort) ---");

    let frozen_cohort = simulate_frozen_cohort(500, 16.0);

    let config = CohortMinerConfig::default();
    let (correction_pairs, report) = mine_cohort(&frozen_cohort, &config);

    println!("Cohort: {} total queries", report.total_queries);
    println!(
        "  V2 correct:       {} ({:.1}%)",
        report.v2_correct,
        report.v2_correct as f64 / report.total_queries as f64 * 100.0
    );
    println!(
        "  V2 disagreements: {} ({:.1}%)",
        report.v2_disagreements,
        report.v2_disagreements as f64 / report.total_queries as f64 * 100.0
    );
    println!("  Correction pairs: {}", report.pairs_emitted);

    // =========================================================================
    // STEP 1.5: Human Curator Judgment Mode
    // =========================================================================
    println!("\n--- Step 1.5: Human Curator Judgment & Rationale Generation ---");

    let (judgments, curated_pairs) = HumanCuratorEngine::annotate_cohort(&frozen_cohort);
    println!(
        "Human Curator evaluated {} disagreement queries.",
        judgments.len()
    );

    println!("\nSample Human Judgments (First 3 cases):");
    for j in judgments.iter().take(3) {
        println!("  [Query ID: {}]", j.query_id);
        println!("    Query:     '{}'", j.query_text);
        println!("    Gold Doc:  {}", j.gold_doc_id);
        println!("    V2 Top-1:  {}", j.v2_top_doc_id);
        println!(
            "    Verdict:   {:?} (Weight: {:.1})",
            j.verdict, j.assigned_weight
        );
        println!("    Class:     {:?}", j.failure_class);
        println!("    Rationale: {}", j.curator_rationale);
        println!();
    }

    // =========================================================================
    // STEP 2: Append human curated pairs to ledger
    // =========================================================================
    println!("--- Step 2: Append Human Curated Pairs to Ledger ---");

    let appended = append_to_ledger_jsonl(ledger_path, &curated_pairs)?;
    println!(
        "Appended {} human-curated correction pairs (dedup filtered {} duplicates)",
        appended,
        correction_pairs.len() - appended
    );

    // =========================================================================
    // STEP 3: Verify augmented ledger composition
    // =========================================================================
    println!("\n--- Step 3: Augmented Ledger Summary ---");

    let full_ledger = load_ledger_jsonl(ledger_path)?;
    println!("Total ledger size: {} pairs", full_ledger.len());

    let mut source_counts: HashMap<String, usize> = HashMap::new();
    let mut source_weight_sums: HashMap<String, f32> = HashMap::new();
    let mut class_counts: HashMap<FailureClass, usize> = HashMap::new();

    for pair in &full_ledger {
        let source_key = format!("{:?}", pair.source);
        *source_counts.entry(source_key.clone()).or_default() += 1;
        *source_weight_sums.entry(source_key).or_default() += pair.weight;
        *class_counts.entry(pair.failure_class).or_default() += 1;
    }

    println!("\n  By Source:");
    for (source, count) in &source_counts {
        let avg_w = source_weight_sums.get(source).unwrap_or(&0.0) / *count as f32;
        println!(
            "    {:<30} | Pairs: {:<5} | Avg Weight: {:.3}",
            source, count, avg_w
        );
    }

    println!("\n  By Failure Class:");
    for (class, count) in &class_counts {
        println!("    {:?}: {}", class, count);
    }

    println!("\n=== Human Curated Ledger Ready for Phase 4 → 8 Pipeline ===");

    Ok(())
}
