use crate::{
    AnalyticsInput, AnalyticsOutput, AnalyticsTiming, GraphAnalyticsError, PackedEdge, RunConfig,
};

pub fn cpu_analyze(
    input: AnalyticsInput<'_>,
    config: RunConfig,
) -> Result<AnalyticsOutput, GraphAnalyticsError> {
    validate_input(input, config)?;
    let nodes = input.node_count as usize;
    let mut active_edge_mask = vec![0_u32; input.edges.len()];
    let mut out_degree = vec![0_u32; nodes];
    let mut in_degree = vec![0_u32; nodes];
    let mut incident_degree = vec![0_u32; nodes];
    let mut relation_family_histogram = vec![0_u32; input.relation_family_count as usize];
    let mut out_strength = vec![0_u32; nodes];
    let mut total_strength = vec![0_u32; nodes];
    let mut boundary_degree = vec![0_u32; nodes];
    let mut boundary_strength = vec![0_u32; nodes];

    for (index, edge) in input.edges.iter().enumerate() {
        if !edge_active(input, edge) {
            continue;
        }
        active_edge_mask[index] = 1;
        checked_add(&mut out_degree[edge.source as usize], 1, "out degree")?;
        checked_add(&mut in_degree[edge.target as usize], 1, "in degree")?;
        checked_add(
            &mut incident_degree[edge.source as usize],
            1,
            "incident degree",
        )?;
        checked_add(
            &mut incident_degree[edge.target as usize],
            1,
            "incident degree",
        )?;
        checked_add(
            &mut relation_family_histogram[edge.relation_family as usize],
            1,
            "relation histogram",
        )?;
        checked_add(
            &mut out_strength[edge.source as usize],
            edge.weight,
            "out strength",
        )?;
        checked_add(
            &mut total_strength[edge.source as usize],
            edge.weight,
            "total strength",
        )?;
        checked_add(
            &mut total_strength[edge.target as usize],
            edge.weight,
            "total strength",
        )?;
        let source_partition = input.partition_labels[edge.source as usize];
        let target_partition = input.partition_labels[edge.target as usize];
        if source_partition != u32::MAX
            && target_partition != u32::MAX
            && source_partition != target_partition
        {
            checked_add(
                &mut boundary_degree[edge.source as usize],
                1,
                "boundary degree",
            )?;
            checked_add(
                &mut boundary_degree[edge.target as usize],
                1,
                "boundary degree",
            )?;
            checked_add(
                &mut boundary_strength[edge.source as usize],
                edge.weight,
                "boundary strength",
            )?;
            checked_add(
                &mut boundary_strength[edge.target as usize],
                edge.weight,
                "boundary strength",
            )?;
        }
    }

    let mut neighbor_degree_sum = vec![0_u32; nodes];
    for (index, edge) in input.edges.iter().enumerate() {
        if active_edge_mask[index] == 0 {
            continue;
        }
        checked_add(
            &mut neighbor_degree_sum[edge.source as usize],
            incident_degree[edge.target as usize],
            "neighbor degree sum",
        )?;
        checked_add(
            &mut neighbor_degree_sum[edge.target as usize],
            incident_degree[edge.source as usize],
            "neighbor degree sum",
        )?;
    }

    let component_labels = weak_components(input, &active_edge_mask);
    let (incoming_offsets, incoming_edges) = incoming_csr(input, &active_edge_mask)?;
    let diffusion_ranks = diffuse(
        input,
        config,
        &active_edge_mask,
        &incoming_offsets,
        &incoming_edges,
        &out_strength,
    );
    Ok(AnalyticsOutput {
        active_edge_mask,
        out_degree,
        in_degree,
        incident_degree,
        relation_family_histogram,
        component_labels,
        out_strength,
        total_strength,
        boundary_degree,
        boundary_strength,
        neighbor_degree_sum,
        diffusion_ranks,
        timing: AnalyticsTiming::default(),
    })
}

pub(crate) fn validate_input(
    input: AnalyticsInput<'_>,
    config: RunConfig,
) -> Result<(), GraphAnalyticsError> {
    let nodes = input.node_count as usize;
    if nodes == 0 {
        return Err(GraphAnalyticsError::Input(
            "at least one node is required".to_owned(),
        ));
    }
    if input.relation_family_count == 0 || input.relation_family_count > 32 {
        return Err(GraphAnalyticsError::Input(
            "relation family count must be in 1..=32".to_owned(),
        ));
    }
    if input.node_policy_mask.len() != nodes || input.partition_labels.len() != nodes {
        return Err(GraphAnalyticsError::Input(
            "node masks and partition labels must match node_count".to_owned(),
        ));
    }
    let expected_seeds = nodes
        .checked_mul(input.diffusion_source_count as usize)
        .ok_or_else(|| GraphAnalyticsError::Input("diffusion seed extent overflow".to_owned()))?;
    if input.diffusion_seeds.len() != expected_seeds {
        return Err(GraphAnalyticsError::Input(format!(
            "diffusion seed count {} does not match expected {expected_seeds}",
            input.diffusion_seeds.len()
        )));
    }
    if config.weak_component_iterations == 0 {
        return Err(GraphAnalyticsError::Input(
            "weak component iterations must be nonzero".to_owned(),
        ));
    }
    if !(0.0..1.0).contains(&config.diffusion_damping) {
        return Err(GraphAnalyticsError::Input(
            "diffusion damping must be finite and in [0, 1)".to_owned(),
        ));
    }
    for (index, &seed) in input.diffusion_seeds.iter().enumerate() {
        if !seed.is_finite() || seed < 0.0 {
            return Err(GraphAnalyticsError::Input(format!(
                "diffusion seed {index} is not finite and non-negative"
            )));
        }
    }
    for (index, edge) in input.edges.iter().enumerate() {
        if edge.source >= input.node_count || edge.target >= input.node_count {
            return Err(GraphAnalyticsError::Input(format!(
                "edge {index} endpoint exceeds node_count"
            )));
        }
        if edge.relation_family >= input.relation_family_count {
            return Err(GraphAnalyticsError::Input(format!(
                "edge {index} relation family exceeds relation_family_count"
            )));
        }
    }
    Ok(())
}

pub(crate) fn incoming_csr(
    input: AnalyticsInput<'_>,
    active: &[u32],
) -> Result<(Vec<u32>, Vec<u32>), GraphAnalyticsError> {
    let mut counts = vec![0_u32; input.node_count as usize];
    for (index, edge) in input.edges.iter().enumerate() {
        if active[index] != 0 {
            checked_add(&mut counts[edge.target as usize], 1, "incoming degree")?;
        }
    }
    let mut offsets = Vec::with_capacity(counts.len() + 1);
    offsets.push(0_u32);
    for count in counts {
        let next = offsets
            .last()
            .copied()
            .unwrap()
            .checked_add(count)
            .ok_or_else(|| GraphAnalyticsError::Input("incoming CSR offset overflow".to_owned()))?;
        offsets.push(next);
    }
    let mut cursor = offsets[..offsets.len() - 1].to_vec();
    let mut rows = vec![0_u32; offsets.last().copied().unwrap() as usize];
    for (index, edge) in input.edges.iter().enumerate() {
        if active[index] == 0 {
            continue;
        }
        let slot = cursor[edge.target as usize] as usize;
        rows[slot] = index as u32;
        cursor[edge.target as usize] += 1;
    }
    Ok((offsets, rows))
}

fn edge_active(input: AnalyticsInput<'_>, edge: &PackedEdge) -> bool {
    input.node_policy_mask[edge.source as usize] != 0
        && input.node_policy_mask[edge.target as usize] != 0
        && edge.weight >= input.edge_policy.minimum_weight
        && input.edge_policy.admitted_relation_families & (1 << edge.relation_family) != 0
}

fn weak_components(input: AnalyticsInput<'_>, active: &[u32]) -> Vec<u32> {
    let mut parent = (0..input.node_count).collect::<Vec<_>>();
    for (index, edge) in input.edges.iter().enumerate() {
        if active[index] != 0 {
            union(&mut parent, edge.source, edge.target);
        }
    }
    for node in 0..input.node_count {
        if input.node_policy_mask[node as usize] == 0 {
            parent[node as usize] = u32::MAX;
        } else {
            parent[node as usize] = find(&mut parent, node);
        }
    }
    parent
}

fn find(parent: &mut [u32], node: u32) -> u32 {
    let mut root = node;
    while parent[root as usize] != root {
        root = parent[root as usize];
    }
    let mut current = node;
    while parent[current as usize] != current {
        let next = parent[current as usize];
        parent[current as usize] = root;
        current = next;
    }
    root
}

fn union(parent: &mut [u32], left: u32, right: u32) {
    let left = find(parent, left);
    let right = find(parent, right);
    if left != right {
        let (keep, merge) = (left.min(right), left.max(right));
        parent[merge as usize] = keep;
    }
}

fn diffuse(
    input: AnalyticsInput<'_>,
    config: RunConfig,
    active: &[u32],
    offsets: &[u32],
    incoming: &[u32],
    out_strength: &[u32],
) -> Vec<f32> {
    let nodes = input.node_count as usize;
    let restart = 1.0 - config.diffusion_damping;
    let mut current = input.diffusion_seeds.to_vec();
    let mut next = vec![0.0_f32; current.len()];
    for _ in 0..config.diffusion_iterations {
        for source in 0..input.diffusion_source_count as usize {
            for node in 0..nodes {
                let seed = input.diffusion_seeds[source * nodes + node];
                let mut incoming_rank = 0.0_f32;
                for &edge_index in &incoming[offsets[node] as usize..offsets[node + 1] as usize] {
                    if active[edge_index as usize] == 0 {
                        continue;
                    }
                    let edge = input.edges[edge_index as usize];
                    let denominator = out_strength[edge.source as usize];
                    if denominator != 0 {
                        incoming_rank += current[source * nodes + edge.source as usize]
                            * edge.weight as f32
                            / denominator as f32;
                    }
                }
                next[source * nodes + node] =
                    restart * seed + config.diffusion_damping * incoming_rank;
            }
        }
        std::mem::swap(&mut current, &mut next);
    }
    current
}

fn checked_add(target: &mut u32, value: u32, label: &str) -> Result<(), GraphAnalyticsError> {
    *target = target
        .checked_add(value)
        .ok_or_else(|| GraphAnalyticsError::Input(format!("{label} exceeds u32")))?;
    Ok(())
}
