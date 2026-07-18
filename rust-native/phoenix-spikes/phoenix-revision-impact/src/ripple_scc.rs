use std::cmp::Reverse;
use std::collections::BinaryHeap;

use super::{ConstraintGraph, RippleError};

pub(super) struct SccLayout {
    pub(super) component_of: Vec<usize>,
    pub(super) topological_order: Vec<usize>,
    pub(super) component_count: usize,
    pub(super) condensed_edges: usize,
}

pub(super) fn condense_scc(graph: &ConstraintGraph) -> Result<SccLayout, RippleError> {
    let node_count = graph.nodes().len();
    if node_count > u32::MAX as usize || graph.atoms().len() > u32::MAX as usize {
        return Err(RippleError::IndexOverflow);
    }
    let (incoming_offsets, incoming_nodes) = reverse_csr(graph, node_count)?;

    let mut visited = vec![false; node_count];
    let mut finish_order = Vec::with_capacity(node_count);
    let mut forward_stack = Vec::<(u32, usize)>::new();
    for start in 0..node_count as u32 {
        if visited[start as usize] {
            continue;
        }
        visited[start as usize] = true;
        forward_stack.push((start, 0));
        while let Some((node, edge_index)) = forward_stack.last_mut() {
            if let Some(atom) = graph.outgoing(*node).get(*edge_index) {
                *edge_index += 1;
                let next = atom.dependent;
                if !visited[next as usize] {
                    visited[next as usize] = true;
                    forward_stack.push((next, 0));
                }
            } else {
                finish_order.push(*node);
                forward_stack.pop();
            }
        }
    }

    let mut component_of = vec![usize::MAX; node_count];
    let mut component_minima = Vec::<u32>::new();
    let mut reverse_stack = Vec::<u32>::new();
    for &start in finish_order.iter().rev() {
        if component_of[start as usize] != usize::MAX {
            continue;
        }
        let component = component_minima.len();
        let mut minimum_node = start;
        component_of[start as usize] = component;
        reverse_stack.push(start);
        while let Some(node) = reverse_stack.pop() {
            minimum_node = minimum_node.min(node);
            let start = incoming_offsets[node as usize] as usize;
            let end = incoming_offsets[node as usize + 1] as usize;
            for &next in incoming_nodes[start..end].iter().rev() {
                if component_of[next as usize] == usize::MAX {
                    component_of[next as usize] = component;
                    reverse_stack.push(next);
                }
            }
        }
        component_minima.push(minimum_node);
    }

    let mut condensed = Vec::<(usize, usize)>::with_capacity(graph.atoms().len());
    for atom in graph.atoms() {
        let source = component_of[atom.source as usize];
        let target = component_of[atom.dependent as usize];
        if source != target {
            condensed.push((source, target));
        }
    }
    condensed.sort_unstable();
    condensed.dedup();

    let component_count = component_minima.len();
    let mut outgoing_offsets = vec![0_usize; component_count + 1];
    let mut indegree = vec![0_usize; component_count];
    for &(source, target) in &condensed {
        outgoing_offsets[source + 1] += 1;
        indegree[target] += 1;
    }
    for index in 1..outgoing_offsets.len() {
        outgoing_offsets[index] += outgoing_offsets[index - 1];
    }
    let outgoing_targets = condensed
        .iter()
        .map(|&(_, target)| target)
        .collect::<Vec<_>>();

    let mut ready = BinaryHeap::<Reverse<(u32, usize)>>::with_capacity(component_count);
    for (component, degree) in indegree.iter().enumerate() {
        if *degree == 0 {
            ready.push(Reverse((component_minima[component], component)));
        }
    }
    let mut topological_order = Vec::with_capacity(component_count);
    while let Some(Reverse((_, component))) = ready.pop() {
        topological_order.push(component);
        let start = outgoing_offsets[component];
        let end = outgoing_offsets[component + 1];
        for &target in &outgoing_targets[start..end] {
            indegree[target] -= 1;
            if indegree[target] == 0 {
                ready.push(Reverse((component_minima[target], target)));
            }
        }
    }
    Ok(SccLayout {
        component_of,
        topological_order,
        component_count,
        condensed_edges: condensed.len(),
    })
}

fn reverse_csr(
    graph: &ConstraintGraph,
    node_count: usize,
) -> Result<(Vec<u32>, Vec<u32>), RippleError> {
    let mut offsets = vec![0_u32; node_count + 1];
    for atom in graph.atoms() {
        offsets[atom.dependent as usize + 1] = offsets[atom.dependent as usize + 1]
            .checked_add(1)
            .ok_or(RippleError::IndexOverflow)?;
    }
    for index in 1..offsets.len() {
        offsets[index] = offsets[index]
            .checked_add(offsets[index - 1])
            .ok_or(RippleError::IndexOverflow)?;
    }
    let mut cursors = offsets[..node_count].to_vec();
    let mut incoming = vec![0_u32; graph.atoms().len()];
    for atom in graph.atoms() {
        let target = atom.dependent as usize;
        incoming[cursors[target] as usize] = atom.source;
        cursors[target] += 1;
    }
    Ok((offsets, incoming))
}
