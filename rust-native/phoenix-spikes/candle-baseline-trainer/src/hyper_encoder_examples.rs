use crate::CandleTrainerError;
use hashbrown::HashSet;
use phoenix_graph_research::{
    ExternalDatasetMapped, ExternalFactSplit, ExternalQualifierRecord, HyperEncoderStagedInput,
    HyperEncoderTrainingConfig,
};

pub(crate) struct PreparedHyperExamples {
    pub sources: Vec<u32>,
    pub targets: Vec<u32>,
    pub relations: Vec<u32>,
    pub qualifier_offsets: Vec<u32>,
    pub qualifier_counts: Vec<u32>,
    pub labels: Vec<bool>,
    pub schedule_blake3: String,
}

impl PreparedHyperExamples {
    pub fn len(&self) -> usize {
        self.labels.len()
    }
}

pub(crate) fn prepare_hyper_examples(
    source: &ExternalDatasetMapped,
    staged: &HyperEncoderStagedInput,
    config: HyperEncoderTrainingConfig,
    seed: u64,
) -> Result<PreparedHyperExamples, CandleTrainerError> {
    config.validate()?;
    let facts = source.facts()?;
    let qualifiers = source.qualifiers()?;
    let base = staged.base_relation_count;
    let nodes = staged.candidate_universe;
    let train = facts
        .iter()
        .filter(|fact| fact.split() == ExternalFactSplit::Train as u8)
        .count();
    let directions = train * 2;
    let capacity = directions * (1 + config.negatives_per_positive as usize);
    let mut positives = HashSet::with_capacity(directions * 2);
    for fact in facts
        .iter()
        .copied()
        .filter(|fact| fact.split() == ExternalFactSplit::Train as u8)
    {
        let context = context_key(
            &qualifiers,
            &staged.canonical_qualifier_refs,
            fact.qualifier_offset(),
            fact.qualifier_count(),
        )?;
        positives.insert((fact.subject(), fact.predicate(), context, fact.object()));
        positives.insert((
            fact.object(),
            fact.predicate() + base,
            context,
            fact.subject(),
        ));
    }
    let mut examples = PreparedHyperExamples {
        sources: Vec::with_capacity(capacity),
        targets: Vec::with_capacity(capacity),
        relations: Vec::with_capacity(capacity),
        qualifier_offsets: Vec::with_capacity(capacity),
        qualifier_counts: Vec::with_capacity(capacity),
        labels: Vec::with_capacity(capacity),
        schedule_blake3: String::new(),
    };
    let mut random = SplitMix64(seed ^ 0x6879_7065_722d_7631);
    for fact in facts
        .iter()
        .copied()
        .filter(|fact| fact.split() == ExternalFactSplit::Train as u8)
    {
        let context = context_key(
            &qualifiers,
            &staged.canonical_qualifier_refs,
            fact.qualifier_offset(),
            fact.qualifier_count(),
        )?;
        push_direction(
            &mut examples,
            &positives,
            &mut random,
            nodes,
            fact.subject(),
            fact.predicate(),
            fact.object(),
            fact.qualifier_offset(),
            fact.qualifier_count(),
            context,
            config.negatives_per_positive,
        )?;
        push_direction(
            &mut examples,
            &positives,
            &mut random,
            nodes,
            fact.object(),
            fact.predicate() + base,
            fact.subject(),
            fact.qualifier_offset(),
            fact.qualifier_count(),
            context,
            config.negatives_per_positive,
        )?;
    }
    let mut hasher = blake3::Hasher::new();
    for index in 0..examples.len() {
        hasher.update(&examples.sources[index].to_le_bytes());
        hasher.update(&examples.relations[index].to_le_bytes());
        hasher.update(&examples.targets[index].to_le_bytes());
        hasher.update(&examples.qualifier_offsets[index].to_le_bytes());
        hasher.update(&examples.qualifier_counts[index].to_le_bytes());
        hasher.update(&[examples.labels[index] as u8]);
    }
    examples.schedule_blake3 = format!("b3-{}", hasher.finalize().to_hex());
    Ok(examples)
}

#[allow(clippy::too_many_arguments)]
fn push_direction(
    output: &mut PreparedHyperExamples,
    positives: &HashSet<(u32, u32, u64, u32)>,
    random: &mut SplitMix64,
    nodes: u32,
    source: u32,
    relation: u32,
    target: u32,
    qualifier_offset: u32,
    qualifier_count: u32,
    context: u64,
    negatives: u8,
) -> Result<(), CandleTrainerError> {
    push_example(
        output,
        source,
        relation,
        target,
        qualifier_offset,
        qualifier_count,
        true,
    );
    for _ in 0..negatives {
        let mut candidate = random.next_u32() % nodes;
        let mut attempts = 0_u32;
        while positives.contains(&(source, relation, context, candidate)) {
            candidate = candidate.wrapping_add(1) % nodes;
            attempts += 1;
            if attempts == nodes {
                return Err(CandleTrainerError::Contract("hyper negative universe"));
            }
        }
        push_example(
            output,
            source,
            relation,
            candidate,
            qualifier_offset,
            qualifier_count,
            false,
        );
    }
    Ok(())
}

fn push_example(
    output: &mut PreparedHyperExamples,
    source: u32,
    relation: u32,
    target: u32,
    offset: u32,
    count: u32,
    label: bool,
) {
    output.sources.push(source);
    output.relations.push(relation);
    output.targets.push(target);
    output.qualifier_offsets.push(offset);
    output.qualifier_counts.push(count);
    output.labels.push(label);
}

fn context_key(
    qualifiers: &[ExternalQualifierRecord],
    refs: &[u32],
    offset: u32,
    count: u32,
) -> Result<u64, CandleTrainerError> {
    let end = offset
        .checked_add(count)
        .ok_or(CandleTrainerError::Contract("hyper qualifier range"))? as usize;
    let mut hasher = blake3::Hasher::new();
    for reference in refs
        .get(offset as usize..end)
        .ok_or(CandleTrainerError::Contract("hyper qualifier range"))?
    {
        let qualifier = qualifiers[*reference as usize];
        hasher.update(&qualifier.predicate().to_le_bytes());
        hasher.update(&qualifier.object().to_le_bytes());
    }
    Ok(u64::from_le_bytes(
        hasher.finalize().as_bytes()[..8]
            .try_into()
            .expect("digest"),
    ))
}

struct SplitMix64(u64);
impl SplitMix64 {
    fn next_u32(&mut self) -> u32 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        (z ^ (z >> 31)) as u32
    }
}
