use std::collections::BTreeMap;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

use crate::experiment::{Exposure, Outcome};
use crate::protocol::{self, Arm};

pub fn analyze(output_dir: &Path, outcomes: &[Outcome], exposures: &[Exposure]) -> io::Result<()> {
    write_cell_outcomes(output_dir, outcomes)?;
    write_arm_summary(output_dir, outcomes)?;
    write_exposure_summary(output_dir, exposures)?;
    write_results(output_dir, outcomes)?;
    Ok(())
}

fn write_cell_outcomes(output_dir: &Path, outcomes: &[Outcome]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("cell-contrasts.csv"))?);
    writeln!(
        output,
        "cell_id,dataset_id,initialization_id,arm,final_loss,population_loss,final_accuracy,population_accuracy,operational_gap"
    )?;
    for row in outcomes
        .iter()
        .filter(|row| row.step == protocol::RUNTIME_STEPS)
    {
        writeln!(
            output,
            "{},{},{},{},{:.12e},{:.12e},{:.9},{:.9},{:.12e}",
            row.cell_id,
            row.dataset_id,
            row.initialization_id,
            row.arm.name(),
            row.final_loss,
            row.population_loss,
            row.final_accuracy,
            row.population_accuracy,
            row.operational_gap,
        )?;
    }
    output.flush()
}

fn write_arm_summary(output_dir: &Path, outcomes: &[Outcome]) -> io::Result<()> {
    let terminal = outcomes
        .iter()
        .filter(|row| row.step == protocol::RUNTIME_STEPS);
    let mut grouped: BTreeMap<&'static str, Vec<&Outcome>> = BTreeMap::new();
    for row in terminal {
        grouped.entry(row.arm.name()).or_default().push(row);
    }
    let mut output = BufWriter::new(File::create(output_dir.join("arm-summary.csv"))?);
    writeln!(
        output,
        "arm,cells,mean_final_loss,median_final_loss,mean_population_loss,median_population_loss,mean_final_accuracy,mean_population_accuracy,mean_operational_gap"
    )?;
    for (arm, rows) in grouped {
        let mut final_values: Vec<f64> = rows.iter().map(|row| f64::from(row.final_loss)).collect();
        let mut population_values: Vec<f64> = rows
            .iter()
            .map(|row| f64::from(row.population_loss))
            .collect();
        final_values.sort_by(f64::total_cmp);
        population_values.sort_by(f64::total_cmp);
        let mean_final = final_values.iter().sum::<f64>() / final_values.len() as f64;
        let mean_population =
            population_values.iter().sum::<f64>() / population_values.len() as f64;
        let mean_final_accuracy = rows
            .iter()
            .map(|row| f64::from(row.final_accuracy))
            .sum::<f64>()
            / rows.len() as f64;
        let mean_population_accuracy = rows
            .iter()
            .map(|row| f64::from(row.population_accuracy))
            .sum::<f64>()
            / rows.len() as f64;
        let mean_gap = rows
            .iter()
            .map(|row| f64::from(row.operational_gap))
            .sum::<f64>()
            / rows.len() as f64;
        writeln!(
            output,
            "{arm},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.9},{:.9},{:.12e}",
            rows.len(),
            mean_final,
            median(&final_values),
            mean_population,
            median(&population_values),
            mean_final_accuracy,
            mean_population_accuracy,
            mean_gap,
        )?;
    }
    output.flush()
}

fn write_exposure_summary(output_dir: &Path, exposures: &[Exposure]) -> io::Result<()> {
    let mut output = BufWriter::new(File::create(output_dir.join("exposure-summary.csv"))?);
    writeln!(
        output,
        "cell_id,arm,panel_id,scheduled_rounds,decision_count,scored_candidates,verifier_size,support_size"
    )?;
    for cell_id in 0..protocol::CELL_COUNT {
        for (arm_index, arm) in Arm::ALL.into_iter().enumerate() {
            for panel_id in 0..protocol::MASTER_PANEL_COUNT {
                let index = (cell_id * Arm::ALL.len() + arm_index) * protocol::MASTER_PANEL_COUNT
                    + panel_id;
                let expected = expected_rounds(arm, panel_id);
                let exposure = exposures[index];
                if expected == 0 && exposure.decisions == 0 {
                    continue;
                }
                let support = if arm.is_pooled() {
                    protocol::POOLED_PANEL_SIZE
                } else {
                    arm.support_size(panel_id.min(protocol::EVIDENCE_ROUNDS - 1))
                };
                writeln!(
                    output,
                    "{cell_id},{},{panel_id},{expected},{},{},{},{}",
                    arm.name(),
                    exposure.decisions,
                    exposure.scored_candidates,
                    if arm.is_pooled() {
                        protocol::POOLED_PANEL_SIZE
                    } else {
                        protocol::PANEL_SIZE
                    },
                    support,
                )?;
            }
        }
    }
    output.flush()
}

fn expected_rounds(arm: Arm, panel_id: usize) -> usize {
    match arm {
        Arm::SentinelK1 => usize::from(panel_id == 0) * protocol::EVIDENCE_ROUNDS,
        Arm::SentinelK4Cyclic => {
            if panel_id < 4 {
                protocol::cyclic_exposure_count(panel_id, 4)
            } else {
                0
            }
        }
        Arm::SentinelK16Cyclic => {
            if panel_id < 16 {
                protocol::cyclic_exposure_count(panel_id, 16)
            } else {
                0
            }
        }
        Arm::SentinelK16Pooled => usize::from(panel_id == 0) * protocol::EVIDENCE_ROUNDS,
        Arm::SentinelK16Blocked => {
            if panel_id < 16 {
                protocol::blocked_exposure_count(panel_id)
            } else {
                0
            }
        }
        Arm::SentinelK64Cyclic => {
            if panel_id < 64 {
                protocol::cyclic_exposure_count(panel_id, 64)
            } else {
                0
            }
        }
        Arm::SentinelFresh => usize::from(panel_id < protocol::EVIDENCE_ROUNDS),
    }
}

fn write_results(output_dir: &Path, outcomes: &[Outcome]) -> io::Result<()> {
    let terminal: Vec<&Outcome> = outcomes
        .iter()
        .filter(|row| row.step == protocol::RUNTIME_STEPS)
        .collect();
    let mut means = BTreeMap::new();
    for arm in Arm::ALL {
        let rows: Vec<&Outcome> = terminal
            .iter()
            .copied()
            .filter(|row| row.arm == arm)
            .collect();
        let mean_final = rows
            .iter()
            .map(|row| f64::from(row.final_loss))
            .sum::<f64>()
            / rows.len() as f64;
        let mean_population = rows
            .iter()
            .map(|row| f64::from(row.population_loss))
            .sum::<f64>()
            / rows.len() as f64;
        means.insert(arm.name(), (mean_final, mean_population));
    }
    let baseline = means[Arm::SentinelK1.name()].0;
    let mut output = BufWriter::new(File::create(output_dir.join("summary.json"))?);
    writeln!(output, "{{")?;
    writeln!(
        output,
        "  \"protocol\": \"AR-04D-sentinel-exposure-2026-09-26\","
    )?;
    writeln!(output, "  \"cells\": {},", protocol::CELL_COUNT)?;
    writeln!(output, "  \"arms\": {},", Arm::ALL.len())?;
    writeln!(
        output,
        "  \"population_size\": {},",
        protocol::POPULATION_SIZE
    )?;
    writeln!(output, "  \"mean_final_loss\": {{")?;
    for (index, arm) in Arm::ALL.into_iter().enumerate() {
        let comma = if index + 1 == Arm::ALL.len() { "" } else { "," };
        writeln!(
            output,
            "    \"{}\": {:.12e}{comma}",
            arm.name(),
            means[arm.name()].0
        )?;
    }
    writeln!(output, "  }},")?;
    writeln!(output, "  \"mean_population_loss\": {{")?;
    for (index, arm) in Arm::ALL.into_iter().enumerate() {
        let comma = if index + 1 == Arm::ALL.len() { "" } else { "," };
        writeln!(
            output,
            "    \"{}\": {:.12e}{comma}",
            arm.name(),
            means[arm.name()].1
        )?;
    }
    writeln!(output, "  }},")?;
    writeln!(output, "  \"terminal_difference_vs_k1\": {{")?;
    for (index, arm) in Arm::ALL.into_iter().enumerate() {
        let comma = if index + 1 == Arm::ALL.len() { "" } else { "," };
        writeln!(
            output,
            "    \"{}\": {:.12e}{comma}",
            arm.name(),
            means[arm.name()].0 - baseline
        )?;
    }
    writeln!(output, "  }}")?;
    writeln!(output, "}}")?;
    output.flush()?;

    let mut results = BufWriter::new(File::create(output_dir.join("RESULTS.md"))?);
    writeln!(results, "# AR-04D Results")?;
    writeln!(results)?;
    writeln!(
        results,
        "This report is descriptive only. AR-04D has no automatic promotion rule."
    )?;
    results.write_all(b"\n")?;
    writeln!(results, "- crossed cells: {}", protocol::CELL_COUNT)?;
    writeln!(results, "- exposure arms: {}", Arm::ALL.len())?;
    writeln!(
        results,
        "- runtime steps per trajectory: {}",
        protocol::RUNTIME_STEPS
    )?;
    writeln!(results, "- primary measurement: untouched V96 final set")?;
    writeln!(
        results,
        "- secondary measurement: untouched population reference of {} examples",
        protocol::POPULATION_SIZE
    )?;
    writeln!(results)?;
    writeln!(
        results,
        "The exposure curve and cyclic-versus-blocked contrast must be interpreted from the cell-level outputs, not from a pooled terminal mean alone."
    )?;
    writeln!(results)?;
    writeln!(
        results,
        "The K=1 and fresh arms are the built-in AR-04C fixed/rotating replication arms. The AR-04C ordering is a predeclared historical check, not a license to pool experiments or tune this run."
    )?;
    results.flush()
}

fn median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return f64::NAN;
    }
    let middle = values.len() / 2;
    if values.len().is_multiple_of(2) {
        (values[middle - 1] + values[middle]) * 0.5
    } else {
        values[middle]
    }
}
