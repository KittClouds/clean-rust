use super::*;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

pub(super) fn write_headers(
    matches: &mut impl Write,
    crossovers: &mut impl Write,
    paths: &mut impl Write,
    checkpoints: &mut impl Write,
) -> io::Result<()> {
    writeln!(
        matches,
        "seed,snapshot_step,matched,control_slot,left_parameter,right_parameter,g3_left_delta,g3_right_delta,g3_utility,control_left_delta,control_right_delta,control_utility,utility_gap,control_stratum,g3_stratum,match_tolerance"
    )?;
    writeln!(
        crossovers,
        "seed,snapshot_step,control_slot,horizon,pg_valid,pc_valid,delta_pg,delta_pc,source_interaction,cumulative_j_pg,cumulative_j_pc,distance_pg,distance_pc,pg_invalid_step,pc_invalid_step"
    )?;
    writeln!(
        paths,
        "seed,snapshot_step,control_slot,path_source,future_step,horizon,event,left_parameter,right_parameter,program_len,left_delta,right_delta,gap_before,gap_after,cumulative_mixed,replayed,invalid_step"
    )?;
    writeln!(checkpoints, "seed,step,train_loss,parameter_fingerprint")?;
    Ok(())
}

pub(super) fn write_report(
    path: impl AsRef<Path>,
    report: PathSourceReport,
    artifact_stem: &str,
) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(writer, "{{")?;
    writeln!(
        writer,
        "  \"schema\": \"adaptive-runtime-{artifact_stem}/v1\","
    )?;
    writeln!(writer, "  \"scope\": \"engineering-only, toy-scale\",")?;
    writeln!(
        writer,
        "  \"protocol\": \"P16 proposal; V48 cell-weighted verifier; frozen AR-02A K2 runtime; snapshots at commits 600, 2400, 4200; same-block full 7x7 utility-matched controls; 63-commit P_G/P_C source crossover\","
    )?;
    writeln!(writer, "  \"seeds\": {},", report.seeds)?;
    writeln!(writer, "  \"snapshots\": {},", report.snapshots)?;
    writeln!(
        writer,
        "  \"pair_program_snapshots\": {},",
        report.pair_program_snapshots
    )?;
    writeln!(
        writer,
        "  \"pair_snapshots_without_controls\": {},",
        report.pair_snapshots_without_controls
    )?;
    writeln!(
        writer,
        "  \"matched_controls\": {},",
        report.matched_controls
    )?;
    writeln!(writer, "  \"generated_paths\": {},", report.generated_paths)?;
    writeln!(
        writer,
        "  \"complete_crossovers_h64\": {},",
        report.complete_crossovers
    )?;
    writeln!(
        writer,
        "  \"invalid_source_paths\": {},",
        report.invalid_source_paths
    )?;
    writeln!(
        writer,
        "  \"invalid_replay_paths\": {},",
        report.invalid_replay_paths
    )?;
    writeln!(
        writer,
        "  \"mean_delta_selected_path_h64\": {},",
        json_number(report.mean_delta_selected_path_h64)
    )?;
    writeln!(
        writer,
        "  \"mean_delta_matched_control_path_h64\": {},",
        json_number(report.mean_delta_matched_control_path_h64)
    )?;
    writeln!(
        writer,
        "  \"mean_source_interaction_h64\": {},",
        json_number(report.mean_source_interaction_h64)
    )?;
    writeln!(
        writer,
        "  \"sign_categories_h64\": {{\"selected_better_under_both_paths\":{},\"selected_only_under_selected_path\":{},\"control_better_under_both_paths\":{},\"mixed_or_tied\":{}}},",
        report.g3_favored_under_both_paths,
        report.source_aligned_at_64,
        report.control_favored_under_both_paths,
        report.mixed_or_tied_at_64
    )?;
    writeln!(
        writer,
        "  \"max_telescoping_residual\": {},",
        json_number(report.max_telescoping_residual)
    )?;
    writeln!(
        writer,
        "  \"max_source_identity_residual\": {},",
        json_number(report.max_source_identity_residual)
    )?;
    writeln!(
        writer,
        "  \"max_parameter_distance_drift\": {}",
        json_number(report.max_parameter_distance_drift)
    )?;
    writeln!(writer, "}}")?;
    writer.flush()
}

pub(super) fn write_seed_summary(
    path: impl AsRef<Path>,
    outcomes: &[(u64, f64, f64)],
    seeds: &[u64],
) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "seed,n,mean_delta_selected_path_h64,mean_delta_control_path_h64,mean_source_interaction_h64,selected_better_selected_path,selected_better_control_path"
    )?;
    for &seed in seeds {
        let rows: Vec<_> = outcomes
            .iter()
            .copied()
            .filter(|row| row.0 == seed)
            .collect();
        if rows.is_empty() {
            writeln!(writer, "{seed:016x},0,,,,,")?;
            continue;
        }
        let count = rows.len() as f64;
        let mean_selected = rows.iter().map(|row| row.1).sum::<f64>() / count;
        let mean_control = rows.iter().map(|row| row.2).sum::<f64>() / count;
        let mean_interaction = rows.iter().map(|row| row.1 - row.2).sum::<f64>() / count;
        let selected_path_wins = rows.iter().filter(|row| row.1 < 0.0).count();
        let control_path_wins = rows.iter().filter(|row| row.2 < 0.0).count();
        writeln!(
            writer,
            "{seed:016x},{},{mean_selected:.12e},{mean_control:.12e},{mean_interaction:.12e},{selected_path_wins},{control_path_wins}",
            rows.len()
        )?;
    }
    writer.flush()
}

fn json_number(value: f64) -> String {
    if value.is_finite() {
        format!("{value:.12e}")
    } else {
        "null".to_owned()
    }
}
