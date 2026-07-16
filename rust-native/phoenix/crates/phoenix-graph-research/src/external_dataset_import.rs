use crate::{
    ExternalDatasetBundle, ExternalDatasetError, ExternalDatasetKind, ExternalDatasetPaths,
    ExternalDatasetSnapshot, ExternalFact, ExternalFactSplit, ExternalQualifier,
    ExternalSourceFile, ExternalSplitPolicy, STARE_WD50K_COMMIT, STARE_WD50K_URL,
    TGB_SMALLPEDIA_URL, TGB_SMALLPEDIA_VERSION,
};
use compact_str::CompactString;
use hashbrown::HashMap;
use memchr::memchr_iter;
use memmap2::Mmap;
use std::fs::File;
use std::path::{Path, PathBuf};

const SMALLPEDIA_DYNAMIC: &str = "tkgl-smallpedia_edgelist.csv";
const SMALLPEDIA_STATIC: &str = "tkgl-smallpedia_static_edgelist.csv";
const SMALLPEDIA_VALIDATION_NEGATIVES: &str = "tkgl-smallpedia_val_ns.pkl";
const SMALLPEDIA_TEST_NEGATIVES: &str = "tkgl-smallpedia_test_ns.pkl";

struct Dictionary {
    values: Vec<CompactString>,
    index: HashMap<CompactString, u32>,
}

impl Dictionary {
    fn with_capacity(capacity: usize) -> Self {
        Self {
            values: Vec::with_capacity(capacity),
            index: HashMap::with_capacity(capacity),
        }
    }

    fn intern(&mut self, raw: &[u8]) -> Result<u32, ExternalDatasetError> {
        let value = std::str::from_utf8(raw)?;
        if value.is_empty() {
            return Err(ExternalDatasetError::InvalidInput("empty identifier"));
        }
        if let Some(index) = self.index.get(value).copied() {
            return Ok(index);
        }
        let index =
            u32::try_from(self.values.len()).map_err(|_| ExternalDatasetError::IndexOverflow)?;
        let value = CompactString::from(value);
        self.values.push(value.clone());
        self.index.insert(value, index);
        Ok(index)
    }
}

pub fn import_tkgl_smallpedia(
    source_root: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
) -> Result<ExternalDatasetPaths, ExternalDatasetError> {
    let source_root = source_root.as_ref();
    let (dynamic, dynamic_receipt) = map_source(
        source_root.join(SMALLPEDIA_DYNAMIC),
        SMALLPEDIA_DYNAMIC,
        "temporalGraph",
    )?;
    let (static_graph, static_receipt) = map_source(
        source_root.join(SMALLPEDIA_STATIC),
        SMALLPEDIA_STATIC,
        "staticGraph",
    )?;
    let (_, validation_receipt) = map_source(
        source_root.join(SMALLPEDIA_VALIDATION_NEGATIVES),
        SMALLPEDIA_VALIDATION_NEGATIVES,
        "validationNegativesOpaquePkl",
    )?;
    let (_, test_receipt) = map_source(
        source_root.join(SMALLPEDIA_TEST_NEGATIVES),
        SMALLPEDIA_TEST_NEGATIVES,
        "testNegativesOpaquePkl",
    )?;

    let mut entities = Dictionary::with_capacity(48_000);
    let mut relations = Dictionary::with_capacity(1_000);
    let mut facts = Vec::with_capacity(1_530_000);
    let mut timestamps = Vec::with_capacity(560_000);
    parse_smallpedia_temporal(
        &dynamic,
        &mut entities,
        &mut relations,
        &mut facts,
        &mut timestamps,
    )?;
    if timestamps.is_empty() {
        return Err(ExternalDatasetError::InvalidInput("no temporal facts"));
    }
    timestamps.sort_unstable();
    let train_through = duplicated_linear_quantile_floor(&timestamps, 0.70)?;
    let validation_through = duplicated_linear_quantile_floor(&timestamps, 0.85)?;
    for fact in &mut facts {
        let observed_at = fact
            .observed_at
            .ok_or(ExternalDatasetError::InvalidInput("missing temporal value"))?;
        fact.split = if observed_at <= train_through {
            ExternalFactSplit::Train
        } else if observed_at <= validation_through {
            ExternalFactSplit::Validation
        } else {
            ExternalFactSplit::Test
        };
    }
    parse_smallpedia_static(&static_graph, &mut entities, &mut relations, &mut facts)?;
    ExternalDatasetBundle::write(
        &ExternalDatasetSnapshot {
            name: "tkgl-smallpedia".into(),
            kind: ExternalDatasetKind::TemporalKnowledgeGraph,
            upstream_url: TGB_SMALLPEDIA_URL.into(),
            upstream_version: TGB_SMALLPEDIA_VERSION.into(),
            license_notice: "Wikidata-derived dataset; upstream TGB documentation identifies the Wikidata license and TGB software is MIT".into(),
            split_policy: ExternalSplitPolicy::TemporalQuantile {
                train_through,
                validation_through,
                validation_basis_points: 1_500,
                test_basis_points: 1_500,
            },
            source_files: vec![
                dynamic_receipt,
                static_receipt,
                validation_receipt,
                test_receipt,
            ],
            entities: entities.values,
            relations: relations.values,
            facts,
            qualifiers: Vec::new(),
        },
        output_root,
    )
}

pub fn import_wd50k(
    source_root: impl AsRef<Path>,
    output_root: impl AsRef<Path>,
) -> Result<ExternalDatasetPaths, ExternalDatasetError> {
    let source_root = source_root.as_ref();
    let statements_root = if source_root.join("statements").is_dir() {
        source_root.join("statements")
    } else {
        source_root.to_path_buf()
    };
    let mut entities = Dictionary::with_capacity(48_000);
    let mut relations = Dictionary::with_capacity(600);
    let mut facts = Vec::with_capacity(237_000);
    let mut qualifiers = Vec::with_capacity(65_000);
    let mut receipts = Vec::with_capacity(3);
    for (file, role, split) in [
        ("train.txt", "officialTrain", ExternalFactSplit::Train),
        (
            "valid.txt",
            "officialValidation",
            ExternalFactSplit::Validation,
        ),
        ("test.txt", "officialTest", ExternalFactSplit::Test),
    ] {
        let (mapped, receipt) = map_source(statements_root.join(file), file, role)?;
        parse_wd50k_partition(
            &mapped,
            split,
            &mut entities,
            &mut relations,
            &mut facts,
            &mut qualifiers,
        )?;
        receipts.push(receipt);
    }
    ExternalDatasetBundle::write(
        &ExternalDatasetSnapshot {
            name: "wd50k".into(),
            kind: ExternalDatasetKind::HyperRelationalKnowledgeGraph,
            upstream_url: STARE_WD50K_URL.into(),
            upstream_version: STARE_WD50K_COMMIT.into(),
            license_notice: "Wikidata-derived dataset; StarE repository is MIT, but its dataset README does not separately declare dataset licensing".into(),
            split_policy: ExternalSplitPolicy::OfficialFixed {
                train_partition: "statements/train.txt".into(),
                validation_partition: "statements/valid.txt".into(),
                test_partition: "statements/test.txt".into(),
            },
            source_files: receipts,
            entities: entities.values,
            relations: relations.values,
            facts,
            qualifiers,
        },
        output_root,
    )
}

fn parse_smallpedia_temporal(
    bytes: &[u8],
    entities: &mut Dictionary,
    relations: &mut Dictionary,
    facts: &mut Vec<ExternalFact>,
    timestamps: &mut Vec<i64>,
) -> Result<(), ExternalDatasetError> {
    visit_lines(bytes, |line_number, line| {
        if line_number == 1 {
            return require_header(line, b"ts,head,tail,relation_type", line_number);
        }
        let [time, subject, object, predicate] = exact_fields(line, line_number)?;
        let observed_at = parse_positive_i64(time, line_number)?;
        let subject = entities.intern(subject)?;
        let object = entities.intern(object)?;
        let predicate = relations.intern(predicate)?;
        timestamps.push(observed_at);
        facts.push(ExternalFact {
            subject,
            predicate,
            object,
            qualifier_offset: 0,
            qualifier_count: 0,
            observed_at: Some(observed_at),
            split: ExternalFactSplit::Unsplit,
            is_static: false,
        });
        Ok(())
    })
}

fn parse_smallpedia_static(
    bytes: &[u8],
    entities: &mut Dictionary,
    relations: &mut Dictionary,
    facts: &mut Vec<ExternalFact>,
) -> Result<(), ExternalDatasetError> {
    visit_lines(bytes, |line_number, line| {
        if line_number == 1 {
            return require_header(line, b"head,tail,relation_type", line_number);
        }
        let [subject, object, predicate] = exact_fields(line, line_number)?;
        facts.push(ExternalFact {
            subject: entities.intern(subject)?,
            predicate: relations.intern(predicate)?,
            object: entities.intern(object)?,
            qualifier_offset: 0,
            qualifier_count: 0,
            observed_at: None,
            split: ExternalFactSplit::Unsplit,
            is_static: true,
        });
        Ok(())
    })
}

fn parse_wd50k_partition(
    bytes: &[u8],
    split: ExternalFactSplit,
    entities: &mut Dictionary,
    relations: &mut Dictionary,
    facts: &mut Vec<ExternalFact>,
    qualifiers: &mut Vec<ExternalQualifier>,
) -> Result<(), ExternalDatasetError> {
    visit_lines(bytes, |line_number, line| {
        let mut fields = line.split(|byte| *byte == b',');
        let subject = required_field(&mut fields, line_number)?;
        let predicate = required_field(&mut fields, line_number)?;
        let object = required_field(&mut fields, line_number)?;
        let subject = entities.intern(subject)?;
        let predicate = relations.intern(predicate)?;
        let object = entities.intern(object)?;
        let qualifier_offset =
            u32::try_from(qualifiers.len()).map_err(|_| ExternalDatasetError::IndexOverflow)?;
        let mut qualifier_count = 0_u32;
        while let Some(qualifier_predicate) = fields.next() {
            let qualifier_object = fields.next().ok_or(ExternalDatasetError::InvalidRow {
                line: line_number,
                reason: "unpaired qualifier",
            })?;
            qualifiers.push(ExternalQualifier {
                predicate: relations.intern(qualifier_predicate)?,
                object: entities.intern(qualifier_object)?,
            });
            qualifier_count = qualifier_count
                .checked_add(1)
                .ok_or(ExternalDatasetError::IndexOverflow)?;
        }
        facts.push(ExternalFact {
            subject,
            predicate,
            object,
            qualifier_offset,
            qualifier_count,
            observed_at: None,
            split,
            is_static: false,
        });
        Ok(())
    })
}

fn map_source(
    path: PathBuf,
    logical_name: &str,
    role: &str,
) -> Result<(Mmap, ExternalSourceFile), ExternalDatasetError> {
    let file = File::open(path)?;
    let bytes = file.metadata()?.len();
    if bytes == 0 {
        return Err(ExternalDatasetError::InvalidInput("empty source file"));
    }
    let mmap = unsafe { Mmap::map(&file)? };
    let receipt = ExternalSourceFile {
        logical_name: logical_name.into(),
        blake3: format!("b3-{}", blake3::hash(&mmap).to_hex()).into(),
        bytes,
        role: role.into(),
    };
    Ok((mmap, receipt))
}

fn visit_lines(
    bytes: &[u8],
    mut visit: impl FnMut(u64, &[u8]) -> Result<(), ExternalDatasetError>,
) -> Result<(), ExternalDatasetError> {
    let mut start = 0;
    let mut line_number = 1;
    for end in memchr_iter(b'\n', bytes) {
        let line = trim_cr(&bytes[start..end]);
        if !line.is_empty() {
            visit(line_number, line)?;
        }
        start = end + 1;
        line_number += 1;
    }
    if start < bytes.len() {
        let line = trim_cr(&bytes[start..]);
        if !line.is_empty() {
            visit(line_number, line)?;
        }
    }
    Ok(())
}

fn exact_fields<const N: usize>(
    line: &[u8],
    line_number: u64,
) -> Result<[&[u8]; N], ExternalDatasetError> {
    let mut output = [&[][..]; N];
    let mut fields = line.split(|byte| *byte == b',');
    for output_field in &mut output {
        *output_field = required_field(&mut fields, line_number)?;
    }
    if fields.next().is_some() {
        return Err(ExternalDatasetError::InvalidRow {
            line: line_number,
            reason: "field count",
        });
    }
    Ok(output)
}

fn required_field<'a>(
    fields: &mut impl Iterator<Item = &'a [u8]>,
    line_number: u64,
) -> Result<&'a [u8], ExternalDatasetError> {
    match fields.next() {
        Some(field) if !field.is_empty() => Ok(field),
        _ => Err(ExternalDatasetError::InvalidRow {
            line: line_number,
            reason: "missing field",
        }),
    }
}

fn require_header(actual: &[u8], expected: &[u8], line: u64) -> Result<(), ExternalDatasetError> {
    if actual == expected {
        Ok(())
    } else {
        Err(ExternalDatasetError::InvalidRow {
            line,
            reason: "header",
        })
    }
}

fn parse_positive_i64(raw: &[u8], line: u64) -> Result<i64, ExternalDatasetError> {
    let mut value = 0_i64;
    if raw.is_empty() {
        return Err(ExternalDatasetError::InvalidRow {
            line,
            reason: "timestamp",
        });
    }
    for digit in raw {
        if !digit.is_ascii_digit() {
            return Err(ExternalDatasetError::InvalidRow {
                line,
                reason: "timestamp",
            });
        }
        value = value
            .checked_mul(10)
            .and_then(|current| current.checked_add(i64::from(digit - b'0')))
            .ok_or(ExternalDatasetError::InvalidRow {
                line,
                reason: "timestamp overflow",
            })?;
    }
    (value > 0)
        .then_some(value)
        .ok_or(ExternalDatasetError::InvalidRow {
            line,
            reason: "timestamp",
        })
}

fn duplicated_linear_quantile_floor(
    sorted: &[i64],
    quantile: f64,
) -> Result<i64, ExternalDatasetError> {
    let logical_len = sorted
        .len()
        .checked_mul(2)
        .ok_or(ExternalDatasetError::IndexOverflow)?;
    if logical_len == 0 || !(0.0..=1.0).contains(&quantile) {
        return Err(ExternalDatasetError::InvalidInput("quantile"));
    }
    let position = (logical_len - 1) as f64 * quantile;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    let fraction = position - lower as f64;
    let lower_value = sorted[lower / 2] as f64;
    let upper_value = sorted[upper / 2] as f64;
    Ok((lower_value + (upper_value - lower_value) * fraction).floor() as i64)
}

fn trim_cr(line: &[u8]) -> &[u8] {
    line.strip_suffix(b"\r").unwrap_or(line)
}
