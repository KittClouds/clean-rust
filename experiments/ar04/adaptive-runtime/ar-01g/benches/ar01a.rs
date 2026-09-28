use std::hint::black_box;
use std::time::Instant;

use adaptive_runtime_ar_01g::{Arm, MappedDataset, SEEDS, run, write_dataset};

fn main() {
    let path = std::env::temp_dir().join("ar01a-bench.bin");
    write_dataset(&path).expect("write dataset");
    let dataset = MappedDataset::open(&path).expect("map dataset");
    for arm in Arm::ALL {
        let start = Instant::now();
        let result = run(black_box(dataset.samples()), arm, SEEDS[0]);
        black_box(result.final_validation_loss);
        println!(
            "{}: {} ms/run",
            arm.label(),
            start.elapsed().as_secs_f64() * 1_000.0
        );
    }
    let _ = std::fs::remove_file(path);
}
