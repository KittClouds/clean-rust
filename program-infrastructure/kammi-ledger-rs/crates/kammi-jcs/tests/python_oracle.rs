//! Differential test against the unmodified Python `ledgerd.identity` functions.
//!
//! Set `KAMMI_JCS_PYTHON` to an interpreter that has `jcs==0.2.1` installed and
//! `KAMMI_LEDGER_PY` to the `kammi-ledger` directory. Optional `KAMMI_JCS_ORACLE_CASES`
//! sets the random case count (default 20,000). Without the variables the test is skipped.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use kammi_jcs::{canonical, strict_json};
use proptest::prelude::*;
use proptest::strategy::ValueTree;
use proptest::test_runner::{Config, RngAlgorithm, TestRng, TestRunner};
use serde_json::{Map, Number, Value};

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Inputs chosen to hit every refusal and formatting edge the Python code has.
fn adversarial() -> Vec<Vec<u8>> {
    let texts: &[&str] = &[
        "0",
        "-0",
        "-0.0",
        "0.0",
        "1.0",
        "1e0",
        "1E+2",
        "1e-7",
        "1e-6",
        "1e21",
        "1e20",
        "1e16",
        "9007199254740991",
        "9007199254740992",
        "-9007199254740991",
        "-9007199254740992",
        "12345678901234567890",
        "1e400",
        "-1e400",
        "1e-400",
        "0e-400",
        "0.000e5",
        "2.2250738585072014e-308",
        "4.9e-324",
        "5e-324",
        "1.7976931348623157e308",
        "0.1",
        "0.2",
        "0.30000000000000004",
        "123456789012345.67",
        "1.5e-5",
        "100.0",
        "NaN",
        "Infinity",
        "-Infinity",
        "01",
        "1.",
        ".5",
        "-",
        "+1",
        "1e",
        "1e+",
        "--1",
        "\"a\\u0000b\"",
        "\"\\ud800\"",
        "\"\\udc00\"",
        "\"\\ud83d\\ude00\"",
        "\"\\ud83d\\u0041\"",
        "\"\\ud83dx\"",
        "\"\\/\"",
        "\"\\x\"",
        "\"\t\"",
        "\"\u{7f}\"",
        "\"\u{e000}\u{1f600}\"",
        "{\"a\":1,\"a\":2}",
        "{\"a\":1,\"b\":{\"a\":1,\"a\":1}}",
        "{}",
        "[]",
        " [ 1 , 2 ] ",
        "{\"\u{e000}\":1,\"\u{1f600}\":2,\"z\":3,\"A\":4}",
        "[1,]",
        "{\"a\":1,}",
        "{'a':1}",
        "true",
        "false",
        "null",
        "tru",
        "nul",
        "[true false]",
        "\u{feff}1",
        "1 2",
        "",
        "{\"k\":[1,2,{\"x\":-0.0}]}",
        "[1e-06, 1e-07]",
        "[0.000001]",
    ];
    let mut inputs: Vec<Vec<u8>> = texts.iter().map(|t| t.as_bytes().to_vec()).collect();
    inputs.push(vec![b'"', 0xff, b'"']); // invalid UTF-8
    inputs.push(vec![b'"', 0xed, 0xa0, 0x80, b'"']); // encoded surrogate (invalid UTF-8)
    inputs
}

fn number() -> impl Strategy<Value = Value> {
    prop_oneof![
        any::<i64>().prop_map(|n| Value::Number(Number::from(n % (1i64 << 54)))),
        any::<f64>().prop_filter_map("finite", |f| Number::from_f64(f).map(Value::Number)),
        (-30i32..30, 1u32..999_999).prop_map(|(e, m)| {
            Value::Number(Number::from_f64(f64::from(m) * 10f64.powi(e)).unwrap())
        }),
    ]
}

fn text() -> impl Strategy<Value = String> {
    prop_oneof![
        "[a-zA-Z0-9 _:./-]{0,12}",
        "\\PC{0,8}",
        proptest::collection::vec(
            prop_oneof![
                (0u32..0x20).prop_map(|c| char::from_u32(c).unwrap()),
                Just('"'),
                Just('\\'),
                Just('\u{7f}'),
                Just('\u{e000}'),
                Just('\u{ffff}'),
                Just('\u{1f600}'),
                Just('\u{10ffff}'),
            ],
            0..6
        )
        .prop_map(|chars| chars.into_iter().collect()),
    ]
}

fn json_value() -> impl Strategy<Value = Value> {
    let leaf = prop_oneof![
        Just(Value::Null),
        any::<bool>().prop_map(Value::Bool),
        number(),
        text().prop_map(Value::String),
    ];
    leaf.prop_recursive(4, 48, 6, |inner| {
        prop_oneof![
            proptest::collection::vec(inner.clone(), 0..6).prop_map(Value::Array),
            proptest::collection::vec((text(), inner), 0..6)
                .prop_map(|pairs| Value::Object(pairs.into_iter().collect::<Map<_, _>>())),
        ]
    })
}

#[test]
fn rust_matches_python_identity_functions() {
    let (Ok(python), Ok(ledger)) = (
        std::env::var("KAMMI_JCS_PYTHON"),
        std::env::var("KAMMI_LEDGER_PY"),
    ) else {
        eprintln!("skipped: set KAMMI_JCS_PYTHON and KAMMI_LEDGER_PY");
        return;
    };
    let cases: usize = std::env::var("KAMMI_JCS_ORACLE_CASES")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(20_000);

    let mut inputs = adversarial();
    let mut runner = TestRunner::new_with_rng(
        Config::default(),
        TestRng::deterministic_rng(RngAlgorithm::ChaCha),
    );
    let strategy = json_value();
    for _ in 0..cases {
        let value = strategy.new_tree(&mut runner).unwrap().current();
        // serde_json's writer is not canonical, which is exactly what the oracle should see.
        inputs.push(serde_json::to_vec(&value).unwrap());
    }

    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tools/jcs_oracle.py");
    let mut child = Command::new(python)
        .arg(script)
        .arg(ledger)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("PYTHONIOENCODING", "ascii")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("start Python oracle");
    let mut stdin = child.stdin.take().unwrap();
    let feed = inputs.clone();
    let writer = std::thread::spawn(move || {
        for input in feed {
            writeln!(stdin, "{}", hex(&input)).unwrap();
        }
    });
    let reader = BufReader::new(child.stdout.take().unwrap());
    let mut mismatches = Vec::new();
    let mut lines = 0usize;
    for (input, line) in inputs.iter().zip(reader.lines()) {
        let line = line.unwrap();
        lines += 1;
        let rust = strict_json(input).and_then(|v| canonical(&v));
        let agrees = match (&rust, line.split_once(' ')) {
            (Ok(bytes), Some(("OK", expected))) => hex(bytes) == expected,
            (Err(_), Some(("ERR", _))) => true,
            _ => false,
        };
        if !agrees {
            mismatches.push(format!(
                "input {:?}: rust {:?} python {line}",
                String::from_utf8_lossy(input),
                rust.map(|b| String::from_utf8_lossy(&b).into_owned())
            ));
        }
    }
    writer.join().unwrap();
    assert!(child.wait().unwrap().success(), "oracle process failed");
    assert_eq!(
        lines,
        inputs.len(),
        "oracle answered {lines} of {} inputs",
        inputs.len()
    );
    assert!(
        mismatches.is_empty(),
        "{} mismatches:\n{}",
        mismatches.len(),
        mismatches
            .iter()
            .take(20)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
    eprintln!("oracle agreed on {} inputs", inputs.len());
}
