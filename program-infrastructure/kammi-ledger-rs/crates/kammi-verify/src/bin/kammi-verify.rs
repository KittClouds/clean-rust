//! `kammi-verify <store>`: prints the independent verification report; exit 0 only on PASS.

fn main() {
    let Some(root) = std::env::args().nth(1) else {
        eprintln!("usage: kammi-verify <v2 store>");
        std::process::exit(2);
    };
    let report = kammi_verify::verify(std::path::Path::new(&root));
    println!(
        "{}",
        serde_json::to_string_pretty(&report.value).expect("report serializes")
    );
    std::process::exit(if report.errors.is_empty() { 0 } else { 1 });
}
