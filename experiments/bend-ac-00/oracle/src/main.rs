use daachorse::{DoubleArrayAhoCorasickBuilder, MatchKind};
use serde::Serialize;
use std::{env, fs, path::PathBuf};

const PATTERNS: &[(&str, &[u8])] = &[
    ("a", &b"a"[..]),
    ("aa", &b"aa"[..]),
    ("aaa", &b"aaa"[..]),
    ("aaaa", &b"aaaa"[..]),
    ("he", &b"he"[..]),
    ("she", &b"she"[..]),
    ("his", &b"his"[..]),
    ("hers", &b"hers"[..]),
    ("abc", &b"abc"[..]),
    ("bc", &b"bc"[..]),
    ("c", &b"c"[..]),
    ("foo", &b"foo"[..]),
    ("foobar", &b"foobar"[..]),
    ("bar", &b"bar"[..]),
];

const CASES: &[(&str, &[u8])] = &[
    ("prefix_chain", &b"aaaaa"[..]),
    ("he_she_his_hers", &b"ushers|his|hers"[..]),
    ("suffix_chain", &b"zabc"[..]),
    ("shared_foo_bar", &b"xfoobarbar"[..]),
    ("combined", &b"aaabushershisxabcfoobar"[..]),
];

#[derive(Serialize)]
struct PatternRecord {
    id: usize,
    label: &'static str,
    bytes_hex: String,
}

#[derive(Serialize)]
struct MatchRecord {
    pattern_id: usize,
    start_byte: usize,
    end_byte: usize,
}

#[derive(Serialize)]
struct CaseRecord {
    id: &'static str,
    text_hex: String,
    matches: Vec<MatchRecord>,
}

#[derive(Serialize)]
struct OracleRecord {
    crate_name: &'static str,
    crate_version: &'static str,
    implementation: &'static str,
    match_kind: &'static str,
    iterator: &'static str,
    offset_unit: &'static str,
    overlap_policy: &'static str,
    internal_state_summary: &'static str,
}

#[derive(Serialize)]
struct Fixture {
    schema: &'static str,
    oracle: OracleRecord,
    patterns: Vec<PatternRecord>,
    cases: Vec<CaseRecord>,
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        out.push(DIGITS[(byte >> 4) as usize] as char);
        out.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    out
}

fn make_fixture() -> Fixture {
    let patterns: Vec<&[u8]> = PATTERNS.iter().map(|(_, bytes)| *bytes).collect();
    let matcher = DoubleArrayAhoCorasickBuilder::new()
        .match_kind(MatchKind::LeftmostLongest)
        .build(&patterns)
        .expect("fixed synthetic patterns build");

    let pattern_records = PATTERNS
        .iter()
        .enumerate()
        .map(|(id, (label, bytes))| PatternRecord {
            id,
            label,
            bytes_hex: hex(bytes),
        })
        .collect();

    let case_records = CASES
        .iter()
        .map(|(id, text)| CaseRecord {
            id,
            text_hex: hex(text),
            matches: matcher
                .leftmost_find_iter(*text)
                .map(|matched| MatchRecord {
                    pattern_id: matched.value(),
                    start_byte: matched.start(),
                    end_byte: matched.end(),
                })
                .collect(),
        })
        .collect();

    Fixture {
        schema: "BEND_AC_MATCH_FIXTURE_V1",
        oracle: OracleRecord {
            crate_name: "daachorse",
            crate_version: "0.4.1",
            implementation: "DoubleArrayAhoCorasickBuilder",
            match_kind: "LeftmostLongest",
            iterator: "leftmost_find_iter",
            offset_unit: "byte",
            overlap_policy: "non-overlapping-leftmost-longest",
            internal_state_summary:
                "not-publicly-enumerable-from-the-Alex-oracle-use-site",
        },
        patterns: pattern_records,
        cases: case_records,
    }
}

fn main() {
    let output = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("../fixtures/oracle-small-v01.json"));
    let bytes = serde_json::to_vec_pretty(&make_fixture()).expect("fixture serializes");
    fs::write(&output, bytes).unwrap_or_else(|error| {
        panic!("cannot write fixture {}: {error}", output.display())
    });
    println!("wrote {}", output.display());
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn synthetic_fixture_patterns_are_nonempty_and_unique() {
        let mut seen = HashSet::with_capacity(PATTERNS.len());
        for (_, pattern) in PATTERNS {
            assert!(!pattern.is_empty());
            assert!(seen.insert(*pattern));
        }
    }

    #[test]
    fn oracle_emits_only_in_range_byte_spans_with_registered_ids() {
        let fixture = make_fixture();
        for case in fixture.cases {
            let text_len = case.text_hex.len() / 2;
            for matched in case.matches {
                assert!(matched.pattern_id < PATTERNS.len());
                assert!(matched.start_byte < matched.end_byte);
                assert!(matched.end_byte <= text_len);
            }
        }
    }
}
