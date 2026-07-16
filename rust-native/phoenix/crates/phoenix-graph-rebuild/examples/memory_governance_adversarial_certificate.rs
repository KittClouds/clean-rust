use std::process;

use phoenix_graph_rebuild::build_memory_governance_adversarial_certificate;

fn main() {
    let certificate = build_memory_governance_adversarial_certificate();
    println!(
        "{}",
        serde_json::to_string_pretty(&certificate).expect("adversarial certificate json")
    );
    if certificate.failed_fixtures > 0 || certificate.no_topology_violations > 0 {
        process::exit(1);
    }
}
