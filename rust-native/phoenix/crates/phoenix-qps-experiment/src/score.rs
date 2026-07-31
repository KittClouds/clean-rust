#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct Coherence {
    pub proximity: f32,
    pub order: f32,
    pub phrase: f32,
    pub segment: f32,
    pub exact_field: f32,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct PositionedGroup {
    pub position: u32,
    pub segment: u32,
    pub group: u8,
}

pub(crate) fn measure_field(
    occurrences: &mut [PositionedGroup],
    chosen_terms: &[Option<u32>],
    field_terms: &[u32],
    exact_bonus: f32,
    proximity_decay: f32,
) -> Coherence {
    if occurrences.is_empty() {
        return Coherence::default();
    }
    occurrences.sort_unstable_by_key(|occurrence| (occurrence.position, occurrence.group));
    let matched_total = chosen_terms
        .iter()
        .filter(|term| term.is_some())
        .count()
        .max(1);
    let mut field_mask = 0_u32;
    for occurrence in occurrences.iter() {
        field_mask |= 1_u32 << occurrence.group;
    }
    let field_groups = field_mask.count_ones() as usize;
    let field_coverage = field_groups as f32 / matched_total as f32;
    let span = minimum_covering_span(occurrences, field_mask);
    let excess = span.saturating_sub(field_groups as u32) as f32;
    let proximity = field_coverage / (1.0 + excess / proximity_decay.max(1.0));
    let order = ordered_fraction(occurrences, chosen_terms) * field_coverage;
    let phrase = if exact_phrase(occurrences, chosen_terms) {
        1.0
    } else {
        0.0
    };
    let segment = segment_concentration(occurrences, matched_total);
    let exact_field = if exact_field_match(field_terms, chosen_terms) {
        exact_bonus
    } else {
        0.0
    };
    Coherence {
        proximity,
        order,
        phrase,
        segment,
        exact_field,
    }
}

fn minimum_covering_span(occurrences: &[PositionedGroup], required_mask: u32) -> u32 {
    let required = required_mask.count_ones();
    if required <= 1 {
        return 1;
    }
    let mut counts = [0_u16; 32];
    let mut present = 0_u32;
    let mut left = 0;
    let mut best = u32::MAX;
    for right in 0..occurrences.len() {
        let group = occurrences[right].group as usize;
        if counts[group] == 0 {
            present += 1;
        }
        counts[group] = counts[group].saturating_add(1);
        while present == required {
            best = best.min(
                occurrences[right]
                    .position
                    .saturating_sub(occurrences[left].position)
                    .saturating_add(1),
            );
            let left_group = occurrences[left].group as usize;
            counts[left_group] -= 1;
            if counts[left_group] == 0 {
                present -= 1;
            }
            left += 1;
        }
    }
    best
}

fn ordered_fraction(occurrences: &[PositionedGroup], chosen: &[Option<u32>]) -> f32 {
    let expected = chosen.iter().filter(|term| term.is_some()).count();
    if expected <= 1 {
        return 1.0;
    }
    let mut previous = None;
    let mut ordered = 0;
    for (group, term) in chosen.iter().enumerate() {
        if term.is_none() {
            continue;
        }
        let next = occurrences
            .iter()
            .filter(|occurrence| occurrence.group as usize == group)
            .map(|occurrence| occurrence.position)
            .filter(|position| previous.is_none_or(|prior| *position > prior))
            .min();
        if let Some(position) = next {
            previous = Some(position);
            ordered += 1;
        }
    }
    ordered as f32 / expected as f32
}

fn exact_phrase(occurrences: &[PositionedGroup], chosen: &[Option<u32>]) -> bool {
    if chosen.is_empty() || chosen.iter().any(Option::is_none) {
        return false;
    }
    occurrences.iter().any(|start| {
        start.group == 0
            && (1..chosen.len()).all(|group| {
                occurrences.iter().any(|occurrence| {
                    occurrence.group as usize == group
                        && occurrence.position == start.position.saturating_add(group as u32)
                })
            })
    })
}

fn segment_concentration(occurrences: &[PositionedGroup], matched_total: usize) -> f32 {
    let mut best = 0_u32;
    let mut cursor = 0;
    while cursor < occurrences.len() {
        let segment = occurrences[cursor].segment;
        let mut mask = 0_u32;
        while cursor < occurrences.len() && occurrences[cursor].segment == segment {
            mask |= 1_u32 << occurrences[cursor].group;
            cursor += 1;
        }
        best = best.max(mask.count_ones());
    }
    best as f32 / matched_total.max(1) as f32
}

fn exact_field_match(field_terms: &[u32], chosen: &[Option<u32>]) -> bool {
    field_terms.len() == chosen.len()
        && field_terms
            .iter()
            .zip(chosen)
            .all(|(field, query)| Some(*field) == *query)
}

#[cfg(test)]
mod tests {
    use super::{measure_field, PositionedGroup};

    #[test]
    fn exact_phrase_beats_scattered_terms() {
        let chosen = [Some(1), Some(2), Some(3)];
        let terms = [1, 2, 3];
        let mut phrase = vec![
            PositionedGroup {
                position: 4,
                segment: 0,
                group: 0,
            },
            PositionedGroup {
                position: 5,
                segment: 0,
                group: 1,
            },
            PositionedGroup {
                position: 6,
                segment: 0,
                group: 2,
            },
        ];
        let measured = measure_field(&mut phrase, &chosen, &terms, 0.4, 12.0);
        assert_eq!(measured.phrase, 1.0);
        assert_eq!(measured.proximity, 1.0);
        assert_eq!(measured.exact_field, 0.4);
    }
}
