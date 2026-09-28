use std::fs;
use std::path::PathBuf;

pub fn check_rows(path: PathBuf) {
    let contents = fs::read_to_string(path).expect("fixture must be readable");
    let mut seen = 0usize;
    for (line_no, line) in contents.lines().enumerate() {
        if line.is_empty() || line.starts_with('#') { continue; }
        let fields: Vec<&str> = line.split('\t').collect();
        assert_eq!(fields.len(), 9, "fixture row {} needs 9 fields", line_no + 1);
        let args: Vec<i64> = fields[2..8].iter().map(|value| value.parse().unwrap_or(0)).collect();
        let actual = e013_repo::evaluate(fields[0], fields[1], &args).expect("known family and case");
        assert_eq!(actual, fields[8], "fixture row {}", line_no + 1);
        seen += 1;
    }
    assert!(seen > 0, "fixture must contain at least one row");
}
