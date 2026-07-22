use std::time::Duration;

use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::{AnalyticsInput, GraphAnalyticsError};

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub(crate) struct Params {
    pub node_count: u32,
    pub edge_count: u32,
    pub family_count: u32,
    pub family_mask: u32,
    pub minimum_weight: u32,
    pub source_count: u32,
    pub wcc_iterations: u32,
    pub diffusion_iterations: u32,
    pub damping: f32,
    pub restart: f32,
    pub pad0: u32,
    pub pad1: u32,
}

pub(crate) struct Buffers {
    pub params: wgpu::Buffer,
    pub edges: wgpu::Buffer,
    pub node_mask: wgpu::Buffer,
    pub partition: wgpu::Buffer,
    pub active: wgpu::Buffer,
    pub out_degree: wgpu::Buffer,
    pub in_degree: wgpu::Buffer,
    pub incident_degree: wgpu::Buffer,
    pub family_histogram: wgpu::Buffer,
    pub out_strength: wgpu::Buffer,
    pub total_strength: wgpu::Buffer,
    pub boundary_degree: wgpu::Buffer,
    pub boundary_strength: wgpu::Buffer,
    pub neighbor_degree_sum: wgpu::Buffer,
    pub labels: wgpu::Buffer,
    pub changed: wgpu::Buffer,
    pub incoming_offsets: wgpu::Buffer,
    pub incoming_edges: wgpu::Buffer,
    pub seeds: wgpu::Buffer,
    pub rank_a: wgpu::Buffer,
    pub rank_b: wgpu::Buffer,
    pub readback: wgpu::Buffer,
    pub resident_bytes: u64,
}

#[derive(Default)]
pub(crate) struct ReadbackLayout {
    pub active: (u64, u64),
    pub out_degree: (u64, u64),
    pub in_degree: (u64, u64),
    pub incident_degree: (u64, u64),
    pub family_histogram: (u64, u64),
    pub out_strength: (u64, u64),
    pub total_strength: (u64, u64),
    pub boundary_degree: (u64, u64),
    pub boundary_strength: (u64, u64),
    pub neighbor_degree_sum: (u64, u64),
    pub labels: (u64, u64),
    pub changed: (u64, u64),
    pub ranks: (u64, u64),
    pub total: u64,
}

impl Buffers {
    pub fn zeroed_outputs(&self) -> [&wgpu::Buffer; 12] {
        [
            &self.active,
            &self.out_degree,
            &self.in_degree,
            &self.incident_degree,
            &self.family_histogram,
            &self.out_strength,
            &self.total_strength,
            &self.boundary_degree,
            &self.boundary_strength,
            &self.neighbor_degree_sum,
            &self.labels,
            &self.changed,
        ]
    }
}

impl ReadbackLayout {
    pub fn new(input: AnalyticsInput<'_>, rank_count: u32) -> Result<Self, GraphAnalyticsError> {
        let mut next = 0_u64;
        let mut take = |count: u64| -> Result<(u64, u64), GraphAnalyticsError> {
            let bytes = count.checked_mul(4).ok_or_else(|| {
                GraphAnalyticsError::Residency("readback byte accounting overflow".to_owned())
            })?;
            let offset = next;
            next = next.checked_add(bytes).ok_or_else(|| {
                GraphAnalyticsError::Residency("readback byte accounting overflow".to_owned())
            })?;
            Ok((offset, bytes))
        };
        let active = take(input.edges.len() as u64)?;
        let out_degree = take(input.node_count as u64)?;
        let in_degree = take(input.node_count as u64)?;
        let incident_degree = take(input.node_count as u64)?;
        let family_histogram = take(input.relation_family_count as u64)?;
        let out_strength = take(input.node_count as u64)?;
        let total_strength = take(input.node_count as u64)?;
        let boundary_degree = take(input.node_count as u64)?;
        let boundary_strength = take(input.node_count as u64)?;
        let neighbor_degree_sum = take(input.node_count as u64)?;
        let labels = take(input.node_count as u64)?;
        let changed = take(1)?;
        let ranks = take(rank_count as u64)?;
        Ok(Self {
            active,
            out_degree,
            in_degree,
            incident_degree,
            family_histogram,
            out_strength,
            total_strength,
            boundary_degree,
            boundary_strength,
            neighbor_degree_sum,
            labels,
            changed,
            ranks,
            total: next,
        })
    }
}

pub(crate) fn validate_accumulator_bounds(
    input: AnalyticsInput<'_>,
) -> Result<(), GraphAnalyticsError> {
    let nodes = input.node_count as usize;
    let mut incident = vec![0_u64; nodes];
    let mut strength = vec![0_u64; nodes];
    let mut admitted = vec![false; input.edges.len()];
    for (index, edge) in input.edges.iter().enumerate() {
        admitted[index] = input.node_policy_mask[edge.source as usize] != 0
            && input.node_policy_mask[edge.target as usize] != 0
            && edge.weight >= input.edge_policy.minimum_weight
            && input.edge_policy.admitted_relation_families & (1 << edge.relation_family) != 0;
        if admitted[index] {
            incident[edge.source as usize] += 1;
            incident[edge.target as usize] += 1;
            strength[edge.source as usize] += u64::from(edge.weight);
            strength[edge.target as usize] += u64::from(edge.weight);
        }
    }
    if incident
        .iter()
        .chain(&strength)
        .any(|value| *value > u64::from(u32::MAX))
    {
        return Err(GraphAnalyticsError::Input(
            "integer analytics accumulator exceeds u32".to_owned(),
        ));
    }
    let mut neighbor_sum = vec![0_u64; nodes];
    for (index, edge) in input.edges.iter().enumerate() {
        if admitted[index] {
            neighbor_sum[edge.source as usize] = neighbor_sum[edge.source as usize]
                .checked_add(incident[edge.target as usize])
                .ok_or_else(|| {
                    GraphAnalyticsError::Input("neighbor degree sum exceeds u64".to_owned())
                })?;
            neighbor_sum[edge.target as usize] = neighbor_sum[edge.target as usize]
                .checked_add(incident[edge.source as usize])
                .ok_or_else(|| {
                    GraphAnalyticsError::Input("neighbor degree sum exceeds u64".to_owned())
                })?;
        }
    }
    if neighbor_sum
        .iter()
        .any(|value| *value > u64::from(u32::MAX))
    {
        return Err(GraphAnalyticsError::Input(
            "neighbor degree sum exceeds u32".to_owned(),
        ));
    }
    Ok(())
}

pub(crate) fn incoming_csr(
    input: AnalyticsInput<'_>,
) -> Result<(Vec<u32>, Vec<u32>), GraphAnalyticsError> {
    let mut counts = vec![0_u32; input.node_count as usize];
    for edge in input.edges {
        counts[edge.target as usize] = counts[edge.target as usize]
            .checked_add(1)
            .ok_or_else(|| GraphAnalyticsError::Input("incoming degree exceeds u32".to_owned()))?;
    }
    let mut offsets = Vec::with_capacity(counts.len() + 1);
    offsets.push(0_u32);
    for count in counts {
        offsets.push(
            offsets
                .last()
                .copied()
                .unwrap()
                .checked_add(count)
                .ok_or_else(|| GraphAnalyticsError::Input("incoming CSR exceeds u32".to_owned()))?,
        );
    }
    let mut cursor = offsets[..offsets.len() - 1].to_vec();
    let mut rows = vec![0_u32; input.edges.len()];
    for (index, edge) in input.edges.iter().enumerate() {
        let slot = cursor[edge.target as usize] as usize;
        rows[slot] = index as u32;
        cursor[edge.target as usize] += 1;
    }
    Ok((offsets, rows))
}

pub(crate) fn pipeline(
    device: &wgpu::Device,
    label: &'static str,
    source: &'static str,
    entry: &'static str,
) -> wgpu::ComputePipeline {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some(label),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
        label: Some(label),
        layout: None,
        module: &shader,
        entry_point: Some(entry),
        compilation_options: Default::default(),
        cache: None,
    })
}

pub(crate) fn bind_group(
    device: &wgpu::Device,
    pipeline: &wgpu::ComputePipeline,
    label: &'static str,
    buffers: &[(u32, &wgpu::Buffer)],
) -> wgpu::BindGroup {
    let layout = pipeline.get_bind_group_layout(0);
    let entries = buffers
        .iter()
        .map(|(binding, buffer)| wgpu::BindGroupEntry {
            binding: *binding,
            resource: buffer.as_entire_binding(),
        })
        .collect::<Vec<_>>();
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some(label),
        layout: &layout,
        entries: &entries,
    })
}

pub(crate) fn dispatch(
    encoder: &mut wgpu::CommandEncoder,
    pipeline: &wgpu::ComputePipeline,
    bind: &wgpu::BindGroup,
    groups: u32,
    label: &'static str,
) {
    if groups == 0 {
        return;
    }
    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
        label: Some(label),
        timestamp_writes: None,
    });
    pass.set_pipeline(pipeline);
    pass.set_bind_group(0, bind, &[]);
    pass.dispatch_workgroups(groups, 1, 1);
}

pub(crate) fn input_storage<T: Pod>(
    device: &wgpu::Device,
    label: &'static str,
    values: &[T],
) -> wgpu::Buffer {
    if values.is_empty() {
        return device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(label),
            size: 4,
            usage: wgpu::BufferUsages::STORAGE,
            mapped_at_creation: false,
        });
    }
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(label),
        contents: bytemuck::cast_slice(values),
        usage: wgpu::BufferUsages::STORAGE,
    })
}

pub(crate) fn uniform<T: Pod>(
    device: &wgpu::Device,
    label: &'static str,
    values: &[T],
) -> wgpu::Buffer {
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(label),
        contents: bytemuck::cast_slice(values),
        usage: wgpu::BufferUsages::UNIFORM,
    })
}

pub(crate) fn rank_storage<T: Pod>(
    device: &wgpu::Device,
    label: &'static str,
    values: &[T],
) -> wgpu::Buffer {
    if values.is_empty() {
        return output_storage(device, label, 4);
    }
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(label),
        contents: bytemuck::cast_slice(values),
        usage: wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_SRC
            | wgpu::BufferUsages::COPY_DST,
    })
}

pub(crate) fn output_storage(
    device: &wgpu::Device,
    label: &'static str,
    size: u64,
) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size: size.max(4),
        usage: wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_SRC
            | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

pub(crate) fn readback_buffer(
    device: &wgpu::Device,
    label: &'static str,
    size: u64,
) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

pub(crate) fn read_u32(bytes: &[u8], extent: (u64, u64)) -> Vec<u32> {
    read_pods(bytes, extent)
}

pub(crate) fn read_f32(bytes: &[u8], extent: (u64, u64)) -> Vec<f32> {
    read_pods(bytes, extent)
}

fn read_pods<T: Pod>(bytes: &[u8], (offset, length): (u64, u64)) -> Vec<T> {
    bytes[offset as usize..(offset + length) as usize]
        .chunks_exact(std::mem::size_of::<T>())
        .map(bytemuck::pod_read_unaligned)
        .collect()
}

pub(crate) fn micros(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}
