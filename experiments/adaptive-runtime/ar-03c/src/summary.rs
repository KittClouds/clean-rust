use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

use crate::records::{CostFrontierRecord, QualityRecord};

#[derive(Default, Clone)]
struct Mean {
    count: usize,
    values: [f64; 7],
}

impl Mean {
    fn push(&mut self, values: [f64; 7]) {
        self.count += 1;
        for (sum, value) in self.values.iter_mut().zip(values) {
            *sum += value;
        }
    }

    fn mean(&self) -> [f64; 7] {
        std::array::from_fn(|index| self.values[index] / self.count as f64)
    }
}

pub fn write_all(
    root: &Path,
    quality: &[QualityRecord],
    frontier: &[CostFrontierRecord],
) -> std::io::Result<()> {
    write_quality(root, quality)?;
    write_frontier(root, frontier)
}

fn write_quality(root: &Path, rows: &[QualityRecord]) -> std::io::Result<()> {
    type CellKey = (u8, u8, usize, usize, String, String);
    type OverallKey = (usize, usize, String, String);
    let mut cells = BTreeMap::<CellKey, Mean>::new();
    for row in rows {
        cells
            .entry((
                row.dataset,
                row.initialization,
                row.anchor_step,
                row.age,
                row.method.clone(),
                row.mode.clone(),
            ))
            .or_default()
            .push([
                row.within_variance_v48,
                row.predicted_rmse_v48,
                row.observed_rmse_v48,
                row.sign_error_v48,
                row.cross_block_regret_v48,
                row.selected_regret_v48,
                row.false_authorization_v48,
            ]);
    }
    let mut out = BufWriter::new(File::create(root.join("quality-cell-summary.csv"))?);
    writeln!(
        out,
        "dataset_index,initialization_index,anchor_step,partition_age,method,mode,n_streams,within_variance_v48,predicted_rmse_v48,observed_rmse_v48,sign_error_v48,cross_block_regret_v48,selected_regret_v48,false_authorization_v48"
    )?;
    let mut overall = BTreeMap::<OverallKey, Mean>::new();
    for ((dataset, initialization, anchor, age, method, mode), value) in &cells {
        let average = value.mean();
        writeln!(
            out,
            "{dataset},{initialization},{anchor},{age},{method},{mode},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            value.count,
            average[0],
            average[1],
            average[2],
            average[3],
            average[4],
            average[5],
            average[6]
        )?;
        overall
            .entry((*anchor, *age, method.clone(), mode.clone()))
            .or_default()
            .push(average);
    }
    out.flush()?;
    let mut out = BufWriter::new(File::create(root.join("quality-equal-cell-summary.csv"))?);
    writeln!(
        out,
        "anchor_step,partition_age,method,mode,n_cells,within_variance_v48,predicted_rmse_v48,observed_rmse_v48,sign_error_v48,cross_block_regret_v48,selected_regret_v48,false_authorization_v48"
    )?;
    for ((anchor, age, method, mode), value) in overall {
        let average = value.mean();
        writeln!(
            out,
            "{anchor},{age},{method},{mode},{},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e},{:.12e}",
            value.count,
            average[0],
            average[1],
            average[2],
            average[3],
            average[4],
            average[5],
            average[6]
        )?;
    }
    out.flush()
}

fn write_frontier(root: &Path, rows: &[CostFrontierRecord]) -> std::io::Result<()> {
    type CellKey = (u8, u8, usize, usize, String);
    type OverallKey = (usize, usize, String);
    let mut cells = BTreeMap::<CellKey, Mean>::new();
    for row in rows {
        cells
            .entry((
                row.dataset,
                row.initialization,
                row.anchor_step,
                row.reuse_commits,
                row.method.clone(),
            ))
            .or_default()
            .push([
                row.amortized_proxy_ns,
                row.verifier_ns as f64,
                row.projected_total_ns,
                row.within_variance_v48,
                row.predicted_rmse_v48,
                row.observed_rmse_v48,
                row.selected_regret_v48,
            ]);
    }
    let mut out = BufWriter::new(File::create(root.join("cost-cell-summary.csv"))?);
    writeln!(
        out,
        "dataset_index,initialization_index,anchor_step,reuse_commits,method,n_streams,amortized_proxy_ns,verifier_ns,projected_total_ns,within_variance_v48,predicted_rmse_v48,observed_rmse_v48,selected_program_regret_v48"
    )?;
    let mut overall = BTreeMap::<OverallKey, Mean>::new();
    for ((dataset, initialization, anchor, reuse, method), value) in &cells {
        let average = value.mean();
        writeln!(
            out,
            "{dataset},{initialization},{anchor},{reuse},{method},{},{:.2},{:.2},{:.2},{:.12e},{:.12e},{:.12e},{:.12e}",
            value.count,
            average[0],
            average[1],
            average[2],
            average[3],
            average[4],
            average[5],
            average[6]
        )?;
        overall
            .entry((*anchor, *reuse, method.clone()))
            .or_default()
            .push(average);
    }
    out.flush()?;
    let mut out = BufWriter::new(File::create(root.join("cost-equal-cell-summary.csv"))?);
    writeln!(
        out,
        "anchor_step,reuse_commits,method,n_cells,amortized_proxy_ns,verifier_ns,projected_total_ns,within_variance_v48,predicted_rmse_v48,observed_rmse_v48,selected_program_regret_v48"
    )?;
    for ((anchor, reuse, method), value) in overall {
        let average = value.mean();
        writeln!(
            out,
            "{anchor},{reuse},{method},{},{:.2},{:.2},{:.2},{:.12e},{:.12e},{:.12e},{:.12e}",
            value.count,
            average[0],
            average[1],
            average[2],
            average[3],
            average[4],
            average[5],
            average[6]
        )?;
    }
    out.flush()
}
