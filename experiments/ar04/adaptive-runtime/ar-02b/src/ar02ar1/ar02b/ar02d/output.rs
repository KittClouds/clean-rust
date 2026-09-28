use super::*;

use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

pub(super) fn write_headers(
    matches: &mut impl Write,
    paths: &mut impl Write,
    crossovers: &mut impl Write,
    checkpoints: &mut impl Write,
) -> io::Result<()> {
    writeln!(
        matches,
        "seed,snapshot,domain,slot,selected_ordinal,c1_ordinal,c2_ordinal,selected_utility,c1_utility,c2_utility,utility_stratum,first_dx_units,first_dy_units,second_dx_units,second_dy_units,vector_residual_x,vector_residual_y,magnitude_error_units,selected_c1_utility_gap,c1_c2_utility_gap,status,duplicate_cc"
    )?;
    writeln!(
        paths,
        "seed,snapshot,source_kind,source_program_ordinal,step_offset,global_commit,step_status,program_present,program_left,program_right,program_len,delta_left,delta_right,invalid_source_step"
    )?;
    writeln!(
        crossovers,
        "seed,snapshot,domain,slot,pair_kind,horizon,program_a_ordinal,program_b_ordinal,complete_horizon,delta_a,delta_ancestor,delta_b,source_interaction,identity_residual,path_divergent,differing_commits,first_difference,cumulative_action_l1,net_displacement_l1,invalid_path_a,invalid_path_ancestor,invalid_path_b"
    )?;
    writeln!(
        checkpoints,
        "seed,snapshot,train_loss,parameter_fingerprint,left_parameter,right_parameter,delta_left,delta_right,selected_utility"
    )?;
    Ok(())
}

pub(super) fn write_match_row(
    writer: &mut impl Write,
    plan: &PlannedSnapshot,
    domain: MatchDomain,
    slot: usize,
    control: Option<MatchedProgram>,
    triplet: Option<TripletMatch>,
    duplicate: bool,
) -> io::Result<()> {
    let selected = plan.selected;
    let selected_id = selected.map_or(-1_i32, |item| program_ordinal(item) as i32);
    let c1_id = control.map_or(-1_i32, |item| program_ordinal(item.program) as i32);
    let c2_id = triplet.map_or(-1_i32, |item| item.control_2.ordinal as i32);
    let selected_utility = selected.map(|_| plan.selected_utility);
    let c1_utility = control.map(|item| item.utility);
    let c2_utility = triplet.map(|item| item.control_2.utility);
    let domain_index = usize::from(domain == MatchDomain::MagnitudeOnly);
    let match_row = plan.triplets[domain_index * MATCH_COUNT + slot];
    let status = if duplicate {
        "DUPLICATE_CC_PAIR"
    } else if match_row.is_some() {
        "MATCHED"
    } else if control.is_none() {
        "NO_C1"
    } else {
        "NO_C2"
    };
    let first = selected
        .zip(control)
        .map(|(a, b)| subtract_units(action_units(a), action_units(b.program)));
    let second = control
        .zip(triplet)
        .map(|(a, b)| subtract_units(action_units(a.program), action_units(b.control_2.program)));
    let residual = triplet.map_or([0, 0], |item| item.vector_residual_units);
    let magnitude_error = triplet.map_or(f64::NAN, |item| item.magnitude_error_units);
    let selected_c1_gap = selected_utility.zip(c1_utility).map(|(a, b)| (a - b).abs());
    let c1_c2_gap = c1_utility.zip(c2_utility).map(|(a, b)| (a - b).abs());
    let stratum = selected_utility.map_or(-1, utility_stratum_i16);
    writeln!(
        writer,
        "{:016x},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
        plan.seed,
        plan.snapshot.step,
        domain.as_str(),
        slot,
        selected_id,
        c1_id,
        c2_id,
        csv_f32(selected_utility),
        csv_f32(c1_utility),
        csv_f32(c2_utility),
        stratum,
        first.map_or(-1, |value| value[0]),
        first.map_or(-1, |value| value[1]),
        second.map_or(-1, |value| value[0]),
        second.map_or(-1, |value| value[1]),
        residual[0],
        residual[1],
        csv_f64(Some(magnitude_error)),
        csv_f32(selected_c1_gap),
        csv_f32(c1_c2_gap),
        status,
        bool_csv(duplicate)
    )
}

pub(super) fn write_unmatched_rows(
    writer: &mut impl Write,
    plan: &PlannedSnapshot,
    reason: &str,
) -> io::Result<()> {
    for domain in MatchDomain::ALL {
        for slot in 0..MATCH_COUNT {
            writeln!(
                writer,
                "{:016x},{},{},{},-1,-1,-1,,,,,-1,-1,-1,-1,0,0,,,,{},false",
                plan.seed,
                plan.snapshot.step,
                domain.as_str(),
                slot,
                reason
            )?;
        }
    }
    Ok(())
}

pub(super) fn write_path_rows(
    writer: &mut impl Write,
    plan: &PlannedSnapshot,
    source_id: i16,
    source_kind: &str,
    path: &FrozenPath,
) -> io::Result<()> {
    for offset in 1..=FUTURE_COMMITS {
        let program = path.programs.get(offset - 1).copied().flatten();
        let step_status = if offset <= path.programs.len() {
            "generated"
        } else if offset == path.invalid_source_step {
            "illegal_source_action"
        } else {
            "not_generated_after_censor"
        };
        writeln!(
            writer,
            "{:016x},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            plan.seed,
            plan.snapshot.step,
            source_kind,
            source_id,
            offset,
            plan.snapshot.step + offset,
            step_status,
            bool_csv(program.is_some()),
            program.map_or(-1, |item| item.left as i32),
            program.map_or(-1, |item| item.right as i32),
            program.map_or(0, |item| item.len as i32),
            program.map_or(0.0, |item| item.deltas[0]),
            program.map_or(0.0, |item| item.deltas[1]),
            path.invalid_source_step
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub(super) fn write_crossover_rows(
    writer: &mut impl Write,
    plan: &PlannedSnapshot,
    domain: MatchDomain,
    slot: usize,
    pair_kind: PairKind,
    horizon: usize,
    program_a_id: i16,
    program_b_id: i16,
    values: Option<(f64, f64, f64, f64, f64)>,
    point_a: Option<PathPoint>,
    point_ancestor: Option<PathPoint>,
    point_b: Option<PathPoint>,
    difference: PathDifference,
    invalid_a: usize,
    invalid_ancestor: usize,
    invalid_b: usize,
) -> io::Result<()> {
    let (delta_a, delta_ancestor, delta_b, interaction, identity) =
        values.map_or((None, None, None, None, None), |value| {
            (
                Some(value.0),
                Some(value.1),
                Some(value.2),
                Some(value.3),
                Some(value.4),
            )
        });
    let complete = point_a.is_some() && point_ancestor.is_some() && point_b.is_some();
    writeln!(
        writer,
        "{:016x},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
        plan.seed,
        plan.snapshot.step,
        domain.as_str(),
        slot,
        pair_kind.as_str(),
        horizon,
        program_a_id,
        program_b_id,
        bool_csv(complete),
        csv_f64(delta_a),
        csv_f64(delta_ancestor),
        csv_f64(delta_b),
        csv_f64(interaction),
        csv_f64(identity),
        bool_csv(difference.differing_commits > 0),
        difference.differing_commits,
        difference.first_difference,
        difference.cumulative_action_l1,
        difference.net_displacement_l1,
        invalid_a,
        invalid_ancestor,
        invalid_b
    )
}

pub(super) fn write_seed_summaries(
    path: impl AsRef<Path>,
    seeds: &[u64],
    outcomes: &[PairOutcome],
) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "seed,domain,pair_kind,matched,complete,censored,divergent,p_div,mean_I_all,mean_I_active,mean_delta_A,mean_delta_ancestor,mean_delta_B,ancestor_order_fraction,mean_differing_commits_all,mean_differing_commits_active,mean_action_l1_all,mean_action_l1_active,mean_net_l1_all,mean_net_l1_active"
    )?;
    for seed in seeds {
        for domain in MatchDomain::ALL {
            for pair_kind in PairKind::ALL {
                write_summary_row(
                    &mut writer,
                    &format!("{seed:016x}"),
                    domain,
                    pair_kind,
                    summarize(outcomes, Some(*seed), domain, pair_kind),
                )?;
            }
        }
    }
    for domain in MatchDomain::ALL {
        for pair_kind in PairKind::ALL {
            write_summary_row(
                &mut writer,
                "POOLED",
                domain,
                pair_kind,
                summarize(outcomes, None, domain, pair_kind),
            )?;
        }
    }
    writer.flush()
}

pub(super) fn write_paired_summaries(
    path: impl AsRef<Path>,
    seeds: &[u64],
    outcomes: &[PairOutcome],
) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "seed,domain,paired_complete,p_div_G_C1,p_div_C1_C2,mean_I_G_C1,mean_I_C1_C2,mean_I_difference_G_minus_CC,mean_I_G_C1_active,mean_I_C1_C2_active,G_C1_more_negative,C1_C2_more_negative,tied"
    )?;
    for seed in seeds {
        for domain in MatchDomain::ALL {
            write_paired_row(
                &mut writer,
                &format!("{seed:016x}"),
                domain,
                summarize_paired(outcomes, Some(*seed), domain),
            )?;
        }
    }
    for domain in MatchDomain::ALL {
        write_paired_row(
            &mut writer,
            "POOLED",
            domain,
            summarize_paired(outcomes, None, domain),
        )?;
    }
    writer.flush()
}

#[derive(Clone, Copy, Debug, Default)]
struct PairedSummary {
    pairs: usize,
    divergent_gc: usize,
    divergent_cc: usize,
    interaction_gc: f64,
    interaction_cc: f64,
    interaction_difference: f64,
    active_gc: f64,
    active_cc: f64,
    active_gc_n: usize,
    active_cc_n: usize,
    gc_more_negative: usize,
    cc_more_negative: usize,
    tied: usize,
}

fn summarize_paired(
    outcomes: &[PairOutcome],
    seed: Option<u64>,
    domain: MatchDomain,
) -> PairedSummary {
    let mut summary = PairedSummary::default();
    for gc in outcomes.iter().filter(|item| {
        seed.is_none_or(|value| item.seed == value)
            && item.domain == domain
            && item.pair_kind == PairKind::SelectedControl
            && item.complete
    }) {
        let Some(cc) = outcomes.iter().find(|item| {
            item.seed == gc.seed
                && item.domain == gc.domain
                && item.slot == gc.slot
                && item.pair_kind == PairKind::ControlControl
                && item.complete
        }) else {
            continue;
        };
        summary.pairs += 1;
        summary.interaction_gc += gc.interaction;
        summary.interaction_cc += cc.interaction;
        summary.interaction_difference += gc.interaction - cc.interaction;
        summary.divergent_gc += usize::from(gc.divergent);
        summary.divergent_cc += usize::from(cc.divergent);
        if gc.divergent {
            summary.active_gc += gc.interaction;
            summary.active_gc_n += 1;
        }
        if cc.divergent {
            summary.active_cc += cc.interaction;
            summary.active_cc_n += 1;
        }
        if gc.interaction < cc.interaction {
            summary.gc_more_negative += 1;
        } else if cc.interaction < gc.interaction {
            summary.cc_more_negative += 1;
        } else {
            summary.tied += 1;
        }
    }
    summary
}

fn write_paired_row(
    writer: &mut impl Write,
    seed: &str,
    domain: MatchDomain,
    summary: PairedSummary,
) -> io::Result<()> {
    writeln!(
        writer,
        "{seed},{},{},{},{},{},{},{},{},{},{},{},{}",
        domain.as_str(),
        summary.pairs,
        ratio(summary.divergent_gc, summary.pairs),
        ratio(summary.divergent_cc, summary.pairs),
        mean(summary.interaction_gc, summary.pairs as f64),
        mean(summary.interaction_cc, summary.pairs as f64),
        mean(summary.interaction_difference, summary.pairs as f64),
        mean(summary.active_gc, summary.active_gc_n as f64),
        mean(summary.active_cc, summary.active_cc_n as f64),
        summary.gc_more_negative,
        summary.cc_more_negative,
        summary.tied
    )
}

pub(super) fn write_report(
    path: impl AsRef<Path>,
    report: SourceConditioningReport,
    exact_matches: usize,
    magnitude_matches: usize,
) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(writer, "{{")?;
    writeln!(
        writer,
        "  \"experiment\": \"AR-02D generic source-conditioning null\","
    )?;
    writeln!(writer, "  \"seeds\": {},", report.seeds)?;
    writeln!(writer, "  \"snapshots\": {},", report.snapshots)?;
    writeln!(writer, "  \"pair_snapshots\": {},", report.pair_snapshots)?;
    writeln!(
        writer,
        "  \"matched_selected_control_controls\": {},",
        report.matched_selected_control_controls
    )?;
    writeln!(writer, "  \"D1_exact_vector_triplets\": {},", exact_matches)?;
    writeln!(
        writer,
        "  \"D2_magnitude_only_triplets\": {},",
        magnitude_matches
    )?;
    writeln!(
        writer,
        "  \"generated_source_paths\": {},",
        report.generated_source_paths
    )?;
    writeln!(
        writer,
        "  \"invalid_source_paths\": {},",
        report.invalid_source_paths
    )?;
    writeln!(writer, "  \"invalid_replays\": {},", report.invalid_replays)?;
    writeln!(
        writer,
        "  \"complete_G_C1\": {},",
        report.complete_selected_control
    )?;
    writeln!(
        writer,
        "  \"complete_C1_C2\": {},",
        report.complete_control_control
    )?;
    writeln!(
        writer,
        "  \"divergent_G_C1\": {},",
        report.divergent_selected_control
    )?;
    writeln!(
        writer,
        "  \"divergent_C1_C2\": {},",
        report.divergent_control_control
    )?;
    writeln!(
        writer,
        "  \"max_telescoping_residual\": {:.12e},",
        report.max_telescoping_residual
    )?;
    writeln!(
        writer,
        "  \"max_source_identity_residual\": {:.12e},",
        report.max_source_identity_residual
    )?;
    writeln!(
        writer,
        "  \"max_parameter_distance_drift\": {:.12e},",
        report.max_parameter_distance_drift
    )?;
    writeln!(
        writer,
        "  \"elapsed_seconds\": {:.6}",
        report.elapsed_seconds
    )?;
    writeln!(writer, "}}")?;
    writer.flush()
}

fn summarize(
    outcomes: &[PairOutcome],
    seed: Option<u64>,
    domain: MatchDomain,
    pair_kind: PairKind,
) -> Summary {
    let mut result = Summary::default();
    for outcome in outcomes.iter().filter(|item| {
        seed.is_none_or(|value| item.seed == value)
            && item.domain == domain
            && item.pair_kind == pair_kind
    }) {
        result.matched += 1;
        if !outcome.complete {
            result.censored += 1;
            continue;
        }
        result.complete += 1;
        result.interaction_all += outcome.interaction;
        result.delta_a += outcome.delta_a;
        result.delta_ancestor += outcome.delta_ancestor;
        result.delta_b += outcome.delta_b;
        result.ancestor_order += usize::from(outcome.ancestor_order);
        result.differing_all += outcome.path_difference.differing_commits as f64;
        result.action_l1_all += outcome.path_difference.cumulative_action_l1;
        result.net_l1_all += outcome.path_difference.net_displacement_l1;
        if outcome.divergent {
            result.divergent += 1;
            result.interaction_active += outcome.interaction;
            result.differing_active += outcome.path_difference.differing_commits as f64;
            result.action_l1_active += outcome.path_difference.cumulative_action_l1;
            result.net_l1_active += outcome.path_difference.net_displacement_l1;
        }
    }
    result
}

fn write_summary_row(
    writer: &mut impl Write,
    seed: &str,
    domain: MatchDomain,
    pair_kind: PairKind,
    summary: Summary,
) -> io::Result<()> {
    let completed = summary.complete as f64;
    let active = summary.divergent as f64;
    writeln!(
        writer,
        "{seed},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
        domain.as_str(),
        pair_kind.as_str(),
        summary.matched,
        summary.complete,
        summary.censored,
        summary.divergent,
        ratio(summary.divergent, summary.complete),
        mean(summary.interaction_all, completed),
        mean(summary.interaction_active, active),
        mean(summary.delta_a, completed),
        mean(summary.delta_ancestor, completed),
        mean(summary.delta_b, completed),
        ratio(summary.ancestor_order, summary.complete),
        mean(summary.differing_all, completed),
        mean(summary.differing_active, active),
        mean(summary.action_l1_all, completed),
        mean(summary.action_l1_active, active),
        mean(summary.net_l1_all, completed),
        mean(summary.net_l1_active, active)
    )
}

fn csv_f32(value: Option<f32>) -> String {
    value.map_or_else(String::new, |number| format!("{number:.9e}"))
}

fn csv_f64(value: Option<f64>) -> String {
    value.map_or_else(String::new, |number| format!("{number:.12e}"))
}

fn mean(sum: f64, count: f64) -> f64 {
    if count == 0.0 { f64::NAN } else { sum / count }
}

fn ratio(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        f64::NAN
    } else {
        numerator as f64 / denominator as f64
    }
}

fn utility_stratum_i16(value: f32) -> i16 {
    i16::from(utility_stratum(value))
}

fn bool_csv(value: bool) -> &'static str {
    if value { "true" } else { "false" }
}
