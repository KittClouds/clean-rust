use super::*;

pub(super) fn all_legal_programs(
    model: &Model,
    train: &[Sample],
    group: Group,
) -> Vec<CandidateProgram> {
    let baseline = model.loss(train);
    let mut candidates = Vec::with_capacity(ACTION_VALUES.len() * ACTION_VALUES.len());
    for (left_index, &left_delta) in ACTION_VALUES.iter().enumerate() {
        for (right_index, &right_delta) in ACTION_VALUES.iter().enumerate() {
            let ordinal = left_index * ACTION_VALUES.len() + right_index;
            let program = Program {
                left: group.left,
                right: group.right,
                deltas: [left_delta, right_delta],
                len: 2,
                ..Program::default()
            };
            if program_is_legal(model, program) {
                candidates.push(CandidateProgram {
                    program,
                    utility: exact_program_value(model, train, baseline, program),
                    ordinal,
                });
            }
        }
    }
    candidates
}

#[allow(clippy::too_many_arguments)]
pub(super) fn find_control_counterpart(
    selected: Program,
    selected_utility: f32,
    control_1: MatchedProgram,
    candidates: &[CandidateProgram],
    domain: MatchDomain,
    seed: u64,
    snapshot: usize,
    slot: usize,
) -> Option<TripletMatch> {
    let mut best: Option<(f64, f32, f32, u64, CandidateProgram, [i16; 2], f64)> = None;
    for &candidate in candidates {
        if candidate.ordinal == program_ordinal(selected)
            || candidate.ordinal == program_ordinal(control_1.program)
            || !utility_matched(selected_utility, control_1.utility, candidate.utility)
        {
            continue;
        }
        let (admissible, residual, magnitude_error) =
            displacement_match(selected, control_1.program, candidate.program, domain);
        if !admissible {
            continue;
        }
        let utility_gap = (candidate.utility - selected_utility).abs();
        let control_gap = (candidate.utility - control_1.utility).abs();
        let primary = match domain {
            MatchDomain::ExactVector => f64::from(utility_gap),
            MatchDomain::MagnitudeOnly => magnitude_error,
        };
        let tie = deterministic_match_key(
            seed ^ domain.salt(),
            snapshot.wrapping_add(slot),
            candidate.ordinal,
        );
        let score = (
            primary,
            utility_gap,
            control_gap,
            tie,
            candidate,
            residual,
            magnitude_error,
        );
        if best
            .as_ref()
            .is_none_or(|current| candidate_score_less(&score, current))
        {
            best = Some(score);
        }
    }
    best.map(
        |(_, _, _, _, candidate, vector_residual_units, magnitude_error_units)| TripletMatch {
            control_1,
            control_2: candidate,
            vector_residual_units,
            magnitude_error_units,
        },
    )
}

fn candidate_score_less(
    left: &(f64, f32, f32, u64, CandidateProgram, [i16; 2], f64),
    right: &(f64, f32, f32, u64, CandidateProgram, [i16; 2], f64),
) -> bool {
    left.0
        .total_cmp(&right.0)
        .then_with(|| left.1.total_cmp(&right.1))
        .then_with(|| left.2.total_cmp(&right.2))
        .then_with(|| left.3.cmp(&right.3))
        .is_lt()
}

pub(super) fn action_units(program: Program) -> [i16; 2] {
    [
        delta_units(program.deltas[0]),
        delta_units(program.deltas[1]),
    ]
}

fn delta_units(delta: f32) -> i16 {
    ACTION_VALUES
        .iter()
        .position(|candidate| *candidate == delta)
        .map_or(0, |index| ACTION_UNITS[index])
}

pub(super) fn subtract_units(left: [i16; 2], right: [i16; 2]) -> [i16; 2] {
    [left[0] - right[0], left[1] - right[1]]
}

fn vector_norm(vector: [i16; 2]) -> f64 {
    f64::from(vector[0]).hypot(f64::from(vector[1]))
}

pub(super) fn displacement_match(
    selected: Program,
    control_1: Program,
    control_2: Program,
    domain: MatchDomain,
) -> (bool, [i16; 2], f64) {
    let first = subtract_units(action_units(selected), action_units(control_1));
    let second = subtract_units(action_units(control_1), action_units(control_2));
    let residual = subtract_units(first, second);
    let magnitude_error = (vector_norm(first) - vector_norm(second)).abs();
    let matches = match domain {
        MatchDomain::ExactVector => residual == [0, 0],
        MatchDomain::MagnitudeOnly => {
            residual != [0, 0] && magnitude_error <= D_MAGNITUDE_TOLERANCE_UNITS
        }
    };
    (matches, residual, magnitude_error)
}

pub(super) fn utility_matched(selected: f32, control_1: f32, control_2: f32) -> bool {
    utility_stratum(selected) == utility_stratum(control_1)
        && utility_stratum(selected) == utility_stratum(control_2)
        && (control_1 - selected).abs() <= MATCH_TOLERANCE
        && (control_2 - selected).abs() <= MATCH_TOLERANCE
        && (control_2 - control_1).abs() <= MATCH_TOLERANCE
}

pub(super) fn program_ordinal(program: Program) -> usize {
    let left = ACTION_VALUES
        .iter()
        .position(|value| *value == program.deltas[0])
        .expect("program action is in the frozen vocabulary");
    let right = ACTION_VALUES
        .iter()
        .position(|value| *value == program.deltas[1])
        .expect("program action is in the frozen vocabulary");
    left * ACTION_VALUES.len() + right
}

pub(super) fn program_from_ordinal(group: Group, ordinal: usize) -> Program {
    Program {
        left: group.left,
        right: group.right,
        deltas: [
            ACTION_VALUES[ordinal / ACTION_VALUES.len()],
            ACTION_VALUES[ordinal % ACTION_VALUES.len()],
        ],
        len: 2,
        ..Program::default()
    }
}
