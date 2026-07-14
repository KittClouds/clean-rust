use crate::gradient_pressure_model::NegativePressureKind;
use crate::hyper_encoder_examples::PreparedHyperExamples;
use crate::CandleTrainerError;
use compact_str::CompactString;
use hashbrown::{HashMap, HashSet};
use phoenix_graph_research::{ExternalDatasetMapped, HyperEncoderStagedInput};

pub(crate) const AUDIT_SAMPLE_PAIRS: usize = 8;
const REAL_BATCH_SIZE: usize = 65_536;

pub(crate) struct DiagnosticSchedule {
    pub name: CompactString,
    pub kind: Option<NegativePressureKind>,
    pub examples: PreparedHyperExamples,
    pub qualifier_value_rows: Vec<u32>,
    pub qualifier_role_rows: Vec<u32>,
}

pub(crate) fn build_diagnostic_schedules(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    base: &PreparedHyperExamples,
) -> Result<(Vec<DiagnosticSchedule>, Vec<DiagnosticSchedule>), CandleTrainerError> {
    let qualifiers = source.qualifiers()?;
    let positive_contexts = train_positive_contexts(base, staged, source)?;
    let mut by_role = HashMap::<u32, Vec<usize>>::new();
    let mut by_value = HashMap::<u32, Vec<usize>>::new();
    for (position, reference) in staged.canonical_qualifier_refs.iter().copied().enumerate() {
        let qualifier = qualifiers[reference as usize];
        by_role
            .entry(qualifier.predicate())
            .or_default()
            .push(position);
        by_value
            .entry(qualifier.object())
            .or_default()
            .push(position);
    }
    let mut anchors = Vec::<(usize, usize, usize, usize)>::with_capacity(AUDIT_SAMPLE_PAIRS);
    for positive in pair_starts(base) {
        if base.qualifier_counts[positive] != 1 {
            continue;
        }
        let position = base.qualifier_offsets[positive] as usize;
        let reference = staged.canonical_qualifier_refs[position];
        let qualifier = qualifiers[reference as usize];
        let value = by_role[&qualifier.predicate()]
            .iter()
            .copied()
            .find(|candidate| {
                let q = qualifiers[staged.canonical_qualifier_refs[*candidate] as usize];
                q.object() != qualifier.object()
                    && !positive_contexts.contains(&(
                        base.sources[positive],
                        base.relations[positive],
                        single_context(q.predicate(), q.object()),
                        base.targets[positive],
                    ))
            });
        let role = by_value[&qualifier.object()]
            .iter()
            .copied()
            .find(|candidate| {
                let q = qualifiers[staged.canonical_qualifier_refs[*candidate] as usize];
                q.predicate() != qualifier.predicate()
                    && !positive_contexts.contains(&(
                        base.sources[positive],
                        base.relations[positive],
                        single_context(q.predicate(), q.object()),
                        base.targets[positive],
                    ))
            });
        let mixed = staged
            .canonical_qualifier_refs
            .iter()
            .copied()
            .enumerate()
            .find_map(|(candidate, reference)| {
                let q = qualifiers[reference as usize];
                (q.predicate() != qualifier.predicate()
                    && q.object() != qualifier.object()
                    && !positive_contexts.contains(&(
                        base.sources[positive],
                        base.relations[positive],
                        single_context(q.predicate(), q.object()),
                        base.targets[positive + 1],
                    )))
                .then_some(candidate)
            });
        if let (Some(value), Some(role), Some(mixed)) = (value, role, mixed) {
            anchors.push((positive, value, role, mixed));
            if anchors.len() == AUDIT_SAMPLE_PAIRS {
                break;
            }
        }
    }
    if anchors.len() != AUDIT_SAMPLE_PAIRS {
        return Err(CandleTrainerError::Contract(
            "qualified corruption diagnostic anchors",
        ));
    }
    let mut pressure = Vec::with_capacity(base.len().div_ceil(REAL_BATCH_SIZE) + 4);
    for (batch, start) in (0..base.len()).step_by(REAL_BATCH_SIZE).enumerate() {
        pressure.push(finish_schedule(
            format!("frozen-real-batch-{batch}").as_str(),
            Some(NegativePressureKind::FrozenRealBatch),
            slice_examples(base, start..(start + REAL_BATCH_SIZE).min(base.len())),
            staged,
            source,
        )?);
    }
    pressure.extend([
        corruption_schedule(
            "primary-target",
            NegativePressureKind::PrimaryTarget,
            base,
            staged,
            source,
            &anchors,
        )?,
        corruption_schedule(
            "qualifier-value",
            NegativePressureKind::QualifierValue,
            base,
            staged,
            source,
            &anchors,
        )?,
        corruption_schedule(
            "qualifier-role",
            NegativePressureKind::QualifierRole,
            base,
            staged,
            source,
            &anchors,
        )?,
        corruption_schedule(
            "mixed",
            NegativePressureKind::Mixed,
            base,
            staged,
            source,
            &anchors,
        )?,
    ]);
    let qualifier_value = pressure
        .iter()
        .find(|schedule| schedule.kind == Some(NegativePressureKind::QualifierValue))
        .ok_or(CandleTrainerError::Contract(
            "qualifier value pressure schedule",
        ))?;
    let qualifier_role = pressure
        .iter()
        .find(|schedule| schedule.kind == Some(NegativePressureKind::QualifierRole))
        .ok_or(CandleTrainerError::Contract(
            "qualifier role pressure schedule",
        ))?;
    let mixed = pressure
        .iter()
        .find(|schedule| schedule.kind == Some(NegativePressureKind::Mixed))
        .ok_or(CandleTrainerError::Contract("mixed pressure schedule"))?;
    let cancellation = vec![
        selected_primary_schedule("all-examples", base, staged, source, |_| true)?,
        selected_primary_schedule("qualified-count-1", base, staged, source, |count| {
            count == 1
        })?,
        selected_primary_schedule("unqualified-count-0", base, staged, source, |count| {
            count == 0
        })?,
        selected_primary_schedule("qualified-count-2-plus", base, staged, source, |count| {
            count >= 2
        })?,
        clone_schedule("qualifier-value", qualifier_value),
        clone_schedule("qualifier-role", qualifier_role),
        clone_schedule("mixed", mixed),
    ];
    Ok((pressure, cancellation))
}

fn corruption_schedule(
    name: &str,
    kind: NegativePressureKind,
    base: &PreparedHyperExamples,
    staged: &HyperEncoderStagedInput,
    source: &ExternalDatasetMapped,
    anchors: &[(usize, usize, usize, usize)],
) -> Result<DiagnosticSchedule, CandleTrainerError> {
    let mut output = empty_examples(anchors.len() * 2);
    for &(positive, value, role, mixed) in anchors {
        push_from(&mut output, base, positive, None, None, true);
        let (target, qualifier_offset) = match kind {
            NegativePressureKind::FrozenRealBatch => {
                return Err(CandleTrainerError::Contract(
                    "real batch corruption builder",
                ));
            }
            NegativePressureKind::PrimaryTarget => (base.targets[positive + 1], None),
            NegativePressureKind::QualifierValue => (base.targets[positive], Some(value as u32)),
            NegativePressureKind::QualifierRole => (base.targets[positive], Some(role as u32)),
            NegativePressureKind::Mixed => (base.targets[positive + 1], Some(mixed as u32)),
        };
        push_from(
            &mut output,
            base,
            positive,
            Some(target),
            qualifier_offset,
            false,
        );
    }
    finish_schedule(name, Some(kind), output, staged, source)
}

fn selected_primary_schedule(
    name: &str,
    base: &PreparedHyperExamples,
    staged: &HyperEncoderStagedInput,
    source: &ExternalDatasetMapped,
    predicate: impl Fn(u32) -> bool,
) -> Result<DiagnosticSchedule, CandleTrainerError> {
    let mut output = empty_examples(AUDIT_SAMPLE_PAIRS * 2);
    for positive in pair_starts(base).filter(|index| predicate(base.qualifier_counts[*index])) {
        push_from(&mut output, base, positive, None, None, true);
        push_from(&mut output, base, positive + 1, None, None, false);
        if output.len() == AUDIT_SAMPLE_PAIRS * 2 {
            break;
        }
    }
    if output.len() != AUDIT_SAMPLE_PAIRS * 2 {
        return Err(CandleTrainerError::Contract(
            "cancellation diagnostic schedule",
        ));
    }
    finish_schedule(name, None, output, staged, source)
}

fn finish_schedule(
    name: &str,
    kind: Option<NegativePressureKind>,
    mut examples: PreparedHyperExamples,
    staged: &HyperEncoderStagedInput,
    source: &ExternalDatasetMapped,
) -> Result<DiagnosticSchedule, CandleTrainerError> {
    examples.schedule_blake3 = schedule_identity(&examples);
    let qualifiers = source.qualifiers()?;
    let mut values = Vec::new();
    let mut roles = Vec::new();
    for index in 0..examples.len() {
        let start = examples.qualifier_offsets[index] as usize;
        let end = start + examples.qualifier_counts[index] as usize;
        for reference in &staged.canonical_qualifier_refs[start..end] {
            let qualifier = qualifiers[*reference as usize];
            values.push(qualifier.object());
            roles.push(qualifier.predicate());
        }
    }
    values.sort_unstable();
    values.dedup();
    roles.sort_unstable();
    roles.dedup();
    Ok(DiagnosticSchedule {
        name: name.into(),
        kind,
        examples,
        qualifier_value_rows: values,
        qualifier_role_rows: roles,
    })
}

fn clone_schedule(name: &str, source: &DiagnosticSchedule) -> DiagnosticSchedule {
    DiagnosticSchedule {
        name: name.into(),
        kind: source.kind,
        examples: clone_examples(&source.examples),
        qualifier_value_rows: source.qualifier_value_rows.clone(),
        qualifier_role_rows: source.qualifier_role_rows.clone(),
    }
}

pub(crate) fn clone_examples(source: &PreparedHyperExamples) -> PreparedHyperExamples {
    PreparedHyperExamples {
        sources: source.sources.clone(),
        targets: source.targets.clone(),
        relations: source.relations.clone(),
        qualifier_offsets: source.qualifier_offsets.clone(),
        qualifier_counts: source.qualifier_counts.clone(),
        labels: source.labels.clone(),
        schedule_blake3: source.schedule_blake3.clone(),
    }
}

pub(crate) fn slice_examples(
    source: &PreparedHyperExamples,
    range: std::ops::Range<usize>,
) -> PreparedHyperExamples {
    let mut output = PreparedHyperExamples {
        sources: source.sources[range.clone()].to_vec(),
        targets: source.targets[range.clone()].to_vec(),
        relations: source.relations[range.clone()].to_vec(),
        qualifier_offsets: source.qualifier_offsets[range.clone()].to_vec(),
        qualifier_counts: source.qualifier_counts[range.clone()].to_vec(),
        labels: source.labels[range].to_vec(),
        schedule_blake3: String::new(),
    };
    output.schedule_blake3 = schedule_identity(&output);
    output
}

fn empty_examples(capacity: usize) -> PreparedHyperExamples {
    PreparedHyperExamples {
        sources: Vec::with_capacity(capacity),
        targets: Vec::with_capacity(capacity),
        relations: Vec::with_capacity(capacity),
        qualifier_offsets: Vec::with_capacity(capacity),
        qualifier_counts: Vec::with_capacity(capacity),
        labels: Vec::with_capacity(capacity),
        schedule_blake3: String::new(),
    }
}

fn push_from(
    output: &mut PreparedHyperExamples,
    source: &PreparedHyperExamples,
    index: usize,
    target: Option<u32>,
    qualifier_offset: Option<u32>,
    label: bool,
) {
    output.sources.push(source.sources[index]);
    output.targets.push(target.unwrap_or(source.targets[index]));
    output.relations.push(source.relations[index]);
    output
        .qualifier_offsets
        .push(qualifier_offset.unwrap_or(source.qualifier_offsets[index]));
    output.qualifier_counts.push(source.qualifier_counts[index]);
    output.labels.push(label);
}

fn pair_starts(examples: &PreparedHyperExamples) -> impl Iterator<Item = usize> + '_ {
    (0..examples.len().saturating_sub(1)).filter(|index| {
        examples.labels[*index]
            && !examples.labels[*index + 1]
            && examples.sources[*index] == examples.sources[*index + 1]
            && examples.relations[*index] == examples.relations[*index + 1]
    })
}

fn schedule_identity(examples: &PreparedHyperExamples) -> String {
    let mut hasher = blake3::Hasher::new();
    for index in 0..examples.len() {
        hasher.update(&examples.sources[index].to_le_bytes());
        hasher.update(&examples.relations[index].to_le_bytes());
        hasher.update(&examples.targets[index].to_le_bytes());
        hasher.update(&examples.qualifier_offsets[index].to_le_bytes());
        hasher.update(&examples.qualifier_counts[index].to_le_bytes());
        hasher.update(&[u8::from(examples.labels[index])]);
    }
    format!("b3-{}", hasher.finalize().to_hex())
}

fn train_positive_contexts(
    base: &PreparedHyperExamples,
    staged: &HyperEncoderStagedInput,
    source: &ExternalDatasetMapped,
) -> Result<HashSet<(u32, u32, u64, u32)>, CandleTrainerError> {
    let qualifiers = source.qualifiers()?;
    let mut positives = HashSet::with_capacity(base.len() / 2);
    for index in 0..base.len() {
        if !base.labels[index] {
            continue;
        }
        let start = base.qualifier_offsets[index] as usize;
        let end = start + base.qualifier_counts[index] as usize;
        let mut hasher = blake3::Hasher::new();
        for reference in &staged.canonical_qualifier_refs[start..end] {
            let qualifier = qualifiers[*reference as usize];
            hasher.update(&qualifier.predicate().to_le_bytes());
            hasher.update(&qualifier.object().to_le_bytes());
        }
        positives.insert((
            base.sources[index],
            base.relations[index],
            u64::from_le_bytes(
                hasher.finalize().as_bytes()[..8]
                    .try_into()
                    .expect("digest"),
            ),
            base.targets[index],
        ));
    }
    Ok(positives)
}

fn single_context(role: u32, value: u32) -> u64 {
    let mut hasher = blake3::Hasher::new();
    hasher.update(&role.to_le_bytes());
    hasher.update(&value.to_le_bytes());
    u64::from_le_bytes(
        hasher.finalize().as_bytes()[..8]
            .try_into()
            .expect("digest"),
    )
}
