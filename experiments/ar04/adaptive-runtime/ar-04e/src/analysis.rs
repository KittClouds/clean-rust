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
    write_summary(output_dir, outcomes)?;
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
    let mut grouped: BTreeMap<&'static str, Vec<&Outcome>> = BTreeMap::new();
    for row in outcomes
        .iter()
        .filter(|row| row.step == protocol::RUNTIME_STEPS)
    {
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
        writeln!(
            output,
            "{arm},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.9},{:.9},{:.12e}",
            rows.len(),
            mean(&final_values),
            median(&final_values),
            mean(&population_values),
            median(&population_values),
            rows.iter()
                .map(|row| f64::from(row.final_accuracy))
                .sum::<f64>()
                / rows.len() as f64,
            rows.iter()
                .map(|row| f64::from(row.population_accuracy))
                .sum::<f64>()
                / rows.len() as f64,
            rows.iter()
                .map(|row| f64::from(row.operational_gap))
                .sum::<f64>()
                / rows.len() as f64,
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
            for panel_id in 0..protocol::MAX_BASE_PANELS {
                let index =
                    (cell_id * Arm::ALL.len() + arm_index) * protocol::MAX_BASE_PANELS + panel_id;
                let expected = expected_rounds(arm, panel_id);
                let exposure = exposures[index];
                if expected == 0 && exposure.decisions == 0 {
                    continue;
                }
                writeln!(
                    output,
                    "{cell_id},{},{panel_id},{expected},{},{},{},{}",
                    arm.name(),
                    exposure.decisions,
                    exposure.scored_candidates,
                    arm.panel_size(),
                    arm.support_size(panel_id.min(arm.rounds() - 1)),
                )?;
            }
        }
    }
    output.flush()
}

fn expected_rounds(arm: Arm, panel_id: usize) -> usize {
    if arm.is_fixed() {
        usize::from(panel_id == 0) * arm.rounds()
    } else {
        usize::from(panel_id < arm.rounds())
    }
}

fn write_summary(output_dir: &Path, outcomes: &[Outcome]) -> io::Result<()> {
    let terminal: Vec<&Outcome> = outcomes
        .iter()
        .filter(|row| row.step == protocol::RUNTIME_STEPS)
        .collect();
    let mut output = BufWriter::new(File::create(output_dir.join("summary.json"))?);
    writeln!(output, "{{")?;
    writeln!(
        output,
        "  \"protocol\": \"AR-04E-verifier-size-reuse-2026-09-26\","
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
        let rows: Vec<&Outcome> = terminal
            .iter()
            .copied()
            .filter(|row| row.arm == arm)
            .collect();
        let value = rows
            .iter()
            .map(|row| f64::from(row.final_loss))
            .sum::<f64>()
            / rows.len() as f64;
        let comma = if index + 1 == Arm::ALL.len() { "" } else { "," };
        writeln!(output, "    \"{}\": {:.12e}{comma}", arm.name(), value)?;
    }
    writeln!(output, "  }}")?;
    writeln!(output, "}}")?;
    output.flush()
}

fn mean(values: &[f64]) -> f64 {
    values.iter().sum::<f64>() / values.len() as f64
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
