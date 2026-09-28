use std::{
    fs::File,
    io::{self, BufRead, BufReader, BufWriter, Write},
    path::Path,
};

use hashbrown::{HashMap, HashSet};

pub const B_R1_SEEDS: [u64; 9] = [
    0x9f4a_7c15_d6e8_b301,
    0xc3a5_c85c_97cb_3127,
    0xb492_b66f_be98_f273,
    0x6a09_e667_f3bc_c909,
    0xbb67_ae85_84ca_a73b,
    0x3c6e_f372_fe94_f82b,
    0xa54f_f53a_5f1d_36f1,
    0x510e_527f_ade6_82d1,
    0x1f83_d9ab_fb41_bd6b,
];

const FUTURE_COMMITS: usize = 63;
const PARAMS: usize = 123;
const ACTION_EPSILON: f64 = 1.0e-9;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
struct Key {
    seed: u64,
    snapshot: usize,
    slot: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct Action {
    indices: [i16; 2],
    deltas: [f64; 2],
}

impl Action {
    fn delta_at(self, parameter: usize) -> f64 {
        self.indices
            .iter()
            .zip(self.deltas)
            .find_map(|(&index, delta)| (index == parameter as i16).then_some(delta))
            .unwrap_or(0.0)
    }
}

#[derive(Clone, Debug)]
struct Comparison {
    key: Key,
    complete: bool,
    reason: &'static str,
    delta_pg: f64,
    delta_pc: f64,
    interaction: f64,
    differing_programs: usize,
    first_difference: Option<usize>,
    cumulative_action_l1: f64,
    net_displacement_l1: f64,
}

#[derive(Clone, Copy, Debug, Default)]
struct Totals {
    matched: usize,
    complete: usize,
    censored: usize,
    divergent: usize,
    active_interaction: f64,
    total_interaction: f64,
    differing_programs: f64,
    active_differing_programs: f64,
    first_difference: f64,
    cumulative_action_l1: f64,
    active_cumulative_action_l1: f64,
    net_displacement_l1: f64,
    active_net_displacement_l1: f64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct AuditSummary {
    pub matched: usize,
    pub complete: usize,
    pub censored: usize,
    pub divergent: usize,
    pub divergence_probability: f64,
    pub mean_active_interaction: f64,
    pub mean_overall_interaction: f64,
}

pub fn audit_crossover(artifacts: impl AsRef<Path>, seeds: &[u64]) -> io::Result<AuditSummary> {
    audit_crossover_with_stem(artifacts, seeds, "ar-02b-r1")
}

pub fn audit_crossover_with_stem(
    artifacts: impl AsRef<Path>,
    seeds: &[u64],
    artifact_stem: &str,
) -> io::Result<AuditSummary> {
    if seeds.is_empty()
        || seeds
            .iter()
            .enumerate()
            .any(|(i, seed)| seeds[..i].contains(seed))
        || artifact_stem.is_empty()
        || !artifact_stem
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
    {
        return Err(invalid("seed list or artifact stem is invalid"));
    }
    let artifacts = artifacts.as_ref();
    let matched = read_matched_keys(
        artifacts.join(format!("{artifact_stem}-matches.csv")),
        seeds,
    )?;
    let (crossovers, complete_keys) = read_h64_crossovers(
        artifacts.join(format!("{artifact_stem}-crossovers.csv")),
        seeds,
        &matched,
    )?;
    let paths = read_complete_paths(
        artifacts.join(format!("{artifact_stem}-paths.csv")),
        &complete_keys,
    )?;

    let mut comparisons = Vec::with_capacity(matched.len());
    for key in matched.iter().copied() {
        let Some(crossover) = crossovers.get(&key).copied() else {
            comparisons.push(Comparison::censored(key, "missing_h64_crossover"));
            continue;
        };
        if !crossover.complete {
            comparisons.push(Comparison::censored(key, "bounds_or_incomplete_path"));
            continue;
        }
        let sources = paths
            .get(&key)
            .ok_or_else(|| invalid("complete crossover lacks path rows"))?;
        comparisons.push(compare_paths(key, crossover, sources)?);
    }
    write_comparisons(
        artifacts.join(format!("{artifact_stem}-divergence.csv")),
        &comparisons,
    )?;
    let rows = summaries(seeds, &comparisons);
    write_summaries(
        artifacts.join(format!("{artifact_stem}-source-summary.csv")),
        &rows,
    )?;

    let total = rows.last().map_or_else(Totals::default, |row| row.1);
    Ok(AuditSummary {
        matched: total.matched,
        complete: total.complete,
        censored: total.censored,
        divergent: total.divergent,
        divergence_probability: ratio(total.divergent, total.complete),
        mean_active_interaction: average(total.active_interaction, total.divergent),
        mean_overall_interaction: average(total.total_interaction, total.complete),
    })
}

#[derive(Clone, Copy)]
struct Crossover {
    complete: bool,
    delta_pg: f64,
    delta_pc: f64,
    interaction: f64,
}

impl Comparison {
    fn censored(key: Key, reason: &'static str) -> Self {
        Self {
            key,
            complete: false,
            reason,
            delta_pg: f64::NAN,
            delta_pc: f64::NAN,
            interaction: f64::NAN,
            differing_programs: 0,
            first_difference: None,
            cumulative_action_l1: f64::NAN,
            net_displacement_l1: f64::NAN,
        }
    }
}

fn compare_paths(
    key: Key,
    crossover: Crossover,
    sources: &[Vec<Action>; 2],
) -> io::Result<Comparison> {
    if sources.iter().any(|source| source.len() != FUTURE_COMMITS) {
        return Err(invalid("complete path does not contain 63 future commits"));
    }
    let mut differing_programs = 0;
    let mut first_difference = None;
    let mut cumulative_action_l1 = 0.0;
    let mut net_by_parameter = [0.0_f64; PARAMS];
    for (step, (pg, pc)) in sources[0]
        .iter()
        .copied()
        .zip(sources[1].iter().copied())
        .enumerate()
    {
        let mut step_l1 = 0.0;
        let mut touched = [i16::MIN; 4];
        let mut touched_len = 0;
        for index in pg.indices.into_iter().chain(pc.indices) {
            if index >= 0 && !touched[..touched_len].contains(&index) {
                touched[touched_len] = index;
                touched_len += 1;
            }
        }
        for &index in &touched[..touched_len] {
            let parameter = index as usize;
            let delta = pg.delta_at(parameter) - pc.delta_at(parameter);
            step_l1 += delta.abs();
            net_by_parameter[parameter] += delta;
        }
        if step_l1 > ACTION_EPSILON {
            differing_programs += 1;
            first_difference.get_or_insert(step + 1);
        }
        cumulative_action_l1 += step_l1;
    }
    let net_displacement_l1 = net_by_parameter.iter().map(|value| value.abs()).sum();
    Ok(Comparison {
        key,
        complete: true,
        reason: "",
        delta_pg: crossover.delta_pg,
        delta_pc: crossover.delta_pc,
        interaction: crossover.interaction,
        differing_programs,
        first_difference,
        cumulative_action_l1,
        net_displacement_l1,
    })
}

fn read_matched_keys(path: impl AsRef<Path>, seeds: &[u64]) -> io::Result<Vec<Key>> {
    let mut rows = Vec::new();
    let mut seen = HashSet::new();
    for_each_csv(path, |line| {
        let mut fields = line.split(',');
        let seed = parse_hex(next(&mut fields)?)?;
        let snapshot = parse(next(&mut fields)?)?;
        let is_matched = parse_bool(next(&mut fields)?)?;
        let slot = parse(next(&mut fields)?)?;
        if seeds.contains(&seed) && is_matched {
            let key = Key {
                seed,
                snapshot,
                slot,
            };
            if !seen.insert(key) {
                return Err(invalid("duplicate matched-control key"));
            }
            rows.push(key);
        }
        Ok(())
    })?;
    rows.sort_unstable_by_key(|key| (key.seed, key.snapshot, key.slot));
    Ok(rows)
}

fn read_h64_crossovers(
    path: impl AsRef<Path>,
    seeds: &[u64],
    matched: &[Key],
) -> io::Result<(HashMap<Key, Crossover>, HashSet<Key>)> {
    let matched_set: HashSet<_> = matched.iter().copied().collect();
    let mut rows = HashMap::with_capacity(matched.len());
    let mut complete = HashSet::with_capacity(matched.len());
    for_each_csv(path, |line| {
        let mut fields = line.split(',');
        let seed = parse_hex(next(&mut fields)?)?;
        let snapshot = parse(next(&mut fields)?)?;
        let slot = parse(next(&mut fields)?)?;
        let horizon: usize = parse(next(&mut fields)?)?;
        let pg_valid = parse_bool(next(&mut fields)?)?;
        let pc_valid = parse_bool(next(&mut fields)?)?;
        let delta_pg = parse_optional_float(next(&mut fields)?)?;
        let delta_pc = parse_optional_float(next(&mut fields)?)?;
        let interaction = parse_optional_float(next(&mut fields)?)?;
        let _cumulative_pg = next(&mut fields)?;
        let _cumulative_pc = next(&mut fields)?;
        let _distance_pg = next(&mut fields)?;
        let _distance_pc = next(&mut fields)?;
        let pg_invalid: usize = parse(next(&mut fields)?)?;
        let pc_invalid: usize = parse(next(&mut fields)?)?;
        if horizon != 64 || !seeds.contains(&seed) {
            return Ok(());
        }
        let key = Key {
            seed,
            snapshot,
            slot,
        };
        if !matched_set.contains(&key) {
            return Err(invalid("h64 crossover without matched-control receipt"));
        }
        let is_complete = pg_valid && pc_valid && pg_invalid == 0 && pc_invalid == 0;
        if is_complete {
            complete.insert(key);
        }
        let (delta_pg, delta_pc, interaction) = if is_complete {
            (
                delta_pg.ok_or_else(|| invalid("missing pg h64 loss gap"))?,
                delta_pc.ok_or_else(|| invalid("missing pc h64 loss gap"))?,
                interaction.ok_or_else(|| invalid("missing h64 source interaction"))?,
            )
        } else {
            (f64::NAN, f64::NAN, f64::NAN)
        };
        if rows
            .insert(
                key,
                Crossover {
                    complete: is_complete,
                    delta_pg,
                    delta_pc,
                    interaction,
                },
            )
            .is_some()
        {
            return Err(invalid("duplicate h64 crossover key"));
        }
        Ok(())
    })?;
    Ok((rows, complete))
}

fn read_complete_paths(
    path: impl AsRef<Path>,
    complete: &HashSet<Key>,
) -> io::Result<HashMap<Key, [Vec<Action>; 2]>> {
    let mut paths: HashMap<Key, [Vec<Action>; 2]> = HashMap::with_capacity(complete.len());
    for_each_csv(path, |line| {
        let mut fields = line.split(',');
        let seed = parse_hex(next(&mut fields)?)?;
        let snapshot = parse(next(&mut fields)?)?;
        let slot = parse(next(&mut fields)?)?;
        let source = next(&mut fields)?;
        let step: usize = parse(next(&mut fields)?)?;
        let _horizon = next(&mut fields)?;
        let event = next(&mut fields)?;
        let left: i16 = parse(next(&mut fields)?)?;
        let right: i16 = parse(next(&mut fields)?)?;
        let len: usize = parse(next(&mut fields)?)?;
        let left_delta: f64 = parse(next(&mut fields)?)?;
        let right_delta: f64 = parse(next(&mut fields)?)?;
        let _gap_before = next(&mut fields)?;
        let _gap_after = next(&mut fields)?;
        let _cumulative_mixed = next(&mut fields)?;
        let replayed = parse_bool(next(&mut fields)?)?;
        let _invalid_step = next(&mut fields)?;
        if step == 0 {
            return Ok(());
        }
        let key = Key {
            seed,
            snapshot,
            slot,
        };
        if !complete.contains(&key) {
            return Ok(());
        }
        if !replayed || event == "invalid" {
            return Err(invalid(
                "h64-complete comparison contains an invalid path row",
            ));
        }
        let source_index = match source {
            "selected" => 0,
            "matched_control" => 1,
            _ => return Err(invalid("unexpected path-source label")),
        };
        let action = match event {
            "noop" => Action::default(),
            "program" => match len {
                1 if (0..PARAMS as i16).contains(&left) => Action {
                    indices: [left, -1],
                    deltas: [left_delta, 0.0],
                },
                2 if (0..PARAMS as i16).contains(&left)
                    && (0..PARAMS as i16).contains(&right)
                    && left != right =>
                {
                    Action {
                        indices: [left, right],
                        deltas: [left_delta, right_delta],
                    }
                }
                _ => return Err(invalid("unsupported program width in path csv")),
            },
            _ => return Err(invalid("unexpected event in complete future path")),
        };
        let streams = paths.entry(key).or_insert_with(|| {
            [
                Vec::with_capacity(FUTURE_COMMITS),
                Vec::with_capacity(FUTURE_COMMITS),
            ]
        });
        let stream = &mut streams[source_index];
        if step != stream.len() + 1 {
            return Err(invalid(
                "path future steps are missing, duplicated, or unordered",
            ));
        }
        stream.push(action);
        Ok(())
    })?;
    Ok(paths)
}

fn summaries(seeds: &[u64], comparisons: &[Comparison]) -> Vec<(String, Totals)> {
    let mut rows = Vec::with_capacity(seeds.len() + 1);
    let mut all = Totals::default();
    for &seed in seeds {
        let mut totals = Totals::default();
        for comparison in comparisons.iter().filter(|row| row.key.seed == seed) {
            totals.add(comparison);
        }
        all.merge(totals);
        rows.push((format!("{seed:016x}"), totals));
    }
    rows.push(("ALL".to_owned(), all));
    rows
}

impl Totals {
    fn add(&mut self, row: &Comparison) {
        self.matched += 1;
        if !row.complete {
            self.censored += 1;
            return;
        }
        self.complete += 1;
        self.total_interaction += row.interaction;
        self.differing_programs += row.differing_programs as f64;
        self.cumulative_action_l1 += row.cumulative_action_l1;
        self.net_displacement_l1 += row.net_displacement_l1;
        if row.differing_programs > 0 {
            self.divergent += 1;
            self.active_interaction += row.interaction;
            self.active_differing_programs += row.differing_programs as f64;
            self.first_difference += row.first_difference.unwrap_or_default() as f64;
            self.active_cumulative_action_l1 += row.cumulative_action_l1;
            self.active_net_displacement_l1 += row.net_displacement_l1;
        }
    }

    fn merge(&mut self, other: Self) {
        self.matched += other.matched;
        self.complete += other.complete;
        self.censored += other.censored;
        self.divergent += other.divergent;
        self.active_interaction += other.active_interaction;
        self.total_interaction += other.total_interaction;
        self.differing_programs += other.differing_programs;
        self.active_differing_programs += other.active_differing_programs;
        self.first_difference += other.first_difference;
        self.cumulative_action_l1 += other.cumulative_action_l1;
        self.active_cumulative_action_l1 += other.active_cumulative_action_l1;
        self.net_displacement_l1 += other.net_displacement_l1;
        self.active_net_displacement_l1 += other.active_net_displacement_l1;
    }
}

fn write_comparisons(path: impl AsRef<Path>, rows: &[Comparison]) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "seed,snapshot_step,control_slot,complete,censor_reason,paths_diverged,differing_future_programs,first_difference_commit,cumulative_action_vector_l1,net_cumulative_displacement_l1,delta_pg,delta_pc,source_interaction"
    )?;
    for row in rows {
        writeln!(
            writer,
            "{:016x},{},{},{},{},{},{},{},{},{},{},{},{}",
            row.key.seed,
            row.key.snapshot,
            row.key.slot,
            row.complete,
            row.reason,
            row.differing_programs > 0,
            row.differing_programs,
            option_usize(row.first_difference),
            option_number(row.complete.then_some(row.cumulative_action_l1)),
            option_number(row.complete.then_some(row.net_displacement_l1)),
            option_number(row.complete.then_some(row.delta_pg)),
            option_number(row.complete.then_some(row.delta_pc)),
            option_number(row.complete.then_some(row.interaction))
        )?;
    }
    writer.flush()
}

fn write_summaries(path: impl AsRef<Path>, rows: &[(String, Totals)]) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    writeln!(
        writer,
        "seed,n_matched,n_complete,n_censored,n_divergent,p_div,mean_active_source_interaction,mean_overall_source_interaction,mean_differing_future_programs_all,mean_differing_future_programs_active,mean_first_difference_commit_active,mean_cumulative_action_vector_l1_all,mean_cumulative_action_vector_l1_active,mean_net_displacement_l1_all,mean_net_displacement_l1_active"
    )?;
    for (seed, totals) in rows {
        writeln!(
            writer,
            "{seed},{},{},{},{},{:.9},{:.12e},{:.12e},{:.6},{:.6},{:.6},{:.12e},{:.12e},{:.12e},{:.12e}",
            totals.matched,
            totals.complete,
            totals.censored,
            totals.divergent,
            ratio(totals.divergent, totals.complete),
            average(totals.active_interaction, totals.divergent),
            average(totals.total_interaction, totals.complete),
            average(totals.differing_programs, totals.complete),
            average(totals.active_differing_programs, totals.divergent),
            average(totals.first_difference, totals.divergent),
            average(totals.cumulative_action_l1, totals.complete),
            average(totals.active_cumulative_action_l1, totals.divergent),
            average(totals.net_displacement_l1, totals.complete),
            average(totals.active_net_displacement_l1, totals.divergent),
        )?;
    }
    writer.flush()
}

fn for_each_csv(
    path: impl AsRef<Path>,
    mut visit: impl FnMut(&str) -> io::Result<()>,
) -> io::Result<()> {
    let reader = BufReader::new(File::open(path)?);
    for (index, line) in reader.lines().enumerate() {
        let line = line?;
        if index > 0 {
            visit(&line)?;
        }
    }
    Ok(())
}

fn next<'a>(fields: &mut impl Iterator<Item = &'a str>) -> io::Result<&'a str> {
    fields.next().ok_or_else(|| invalid("truncated csv row"))
}

fn parse<T: std::str::FromStr>(field: &str) -> io::Result<T> {
    field.parse().map_err(|_| invalid("invalid csv value"))
}

fn parse_hex(field: &str) -> io::Result<u64> {
    u64::from_str_radix(field, 16).map_err(|_| invalid("invalid hexadecimal seed"))
}

fn parse_bool(field: &str) -> io::Result<bool> {
    match field {
        "true" => Ok(true),
        "false" => Ok(false),
        _ => Err(invalid("invalid boolean csv value")),
    }
}

fn parse_optional_float(field: &str) -> io::Result<Option<f64>> {
    if field.is_empty() {
        Ok(None)
    } else {
        parse(field).map(Some)
    }
}

fn ratio(numerator: usize, denominator: usize) -> f64 {
    if denominator == 0 {
        0.0
    } else {
        numerator as f64 / denominator as f64
    }
}

fn average(sum: f64, count: usize) -> f64 {
    if count == 0 {
        f64::NAN
    } else {
        sum / count as f64
    }
}

fn option_usize(value: Option<usize>) -> String {
    value.map_or_else(String::new, |number| number.to_string())
}

fn option_number(value: Option<f64>) -> String {
    value.map_or_else(String::new, |number| format!("{number:.12e}"))
}

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_action_paths_have_zero_divergence_and_interaction() {
        let action = Action {
            indices: [3, 8],
            deltas: [0.02, -0.01],
        };
        let paths = [vec![action; FUTURE_COMMITS], vec![action; FUTURE_COMMITS]];
        let result = compare_paths(
            Key {
                seed: 1,
                snapshot: 600,
                slot: 0,
            },
            Crossover {
                complete: true,
                delta_pg: 0.0,
                delta_pc: 0.0,
                interaction: 0.0,
            },
            &paths,
        )
        .expect("valid identical paths");
        assert_eq!(result.differing_programs, 0);
        assert_eq!(result.first_difference, None);
        assert_eq!(result.cumulative_action_l1, 0.0);
        assert_eq!(result.net_displacement_l1, 0.0);
    }

    #[test]
    fn vector_comparison_tracks_commit_count_first_change_and_net_displacement() {
        let left = Action {
            indices: [1, 5],
            deltas: [0.02, -0.01],
        };
        let right = Action {
            indices: [1, 7],
            deltas: [0.01, 0.01],
        };
        let pg = vec![left; FUTURE_COMMITS];
        let mut pc = pg.clone();
        pc[3] = right;
        let paths = [pg, pc];
        let result = compare_paths(
            Key {
                seed: 2,
                snapshot: 2400,
                slot: 1,
            },
            Crossover {
                complete: true,
                delta_pg: 0.0,
                delta_pc: 0.0,
                interaction: 0.0,
            },
            &paths,
        )
        .expect("valid action paths");
        assert_eq!(result.differing_programs, 1);
        assert_eq!(result.first_difference, Some(4));
        assert!((result.cumulative_action_l1 - 0.03).abs() < 1.0e-12);
        assert!((result.net_displacement_l1 - 0.03).abs() < 1.0e-12);
    }
}
