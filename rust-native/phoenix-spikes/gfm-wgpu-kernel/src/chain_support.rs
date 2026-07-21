use std::mem::size_of;
use std::sync::mpsc;
use std::time::Duration;

use bytemuck::Pod;
use wgpu::util::DeviceExt;

use crate::GpuError;

const GPU_WAIT: Duration = Duration::from_secs(60);

pub(crate) fn compute_2d(
    encoder: &mut wgpu::CommandEncoder,
    pipeline: &wgpu::ComputePipeline,
    bind_group: &wgpu::BindGroup,
    dispatch: [u32; 2],
    label: &'static str,
) {
    compute_3d(
        encoder,
        pipeline,
        bind_group,
        [dispatch[0], dispatch[1], 1],
        label,
    );
}

pub(crate) fn compute_3d(
    encoder: &mut wgpu::CommandEncoder,
    pipeline: &wgpu::ComputePipeline,
    bind_group: &wgpu::BindGroup,
    dispatch: [u32; 3],
    label: &'static str,
) {
    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
        label: Some(label),
        timestamp_writes: None,
    });
    pass.set_pipeline(pipeline);
    pass.set_bind_group(0, bind_group, &[]);
    pass.dispatch_workgroups(dispatch[0], dispatch[1], dispatch[2]);
}

pub(crate) fn bind_group(
    device: &wgpu::Device,
    pipeline: &wgpu::ComputePipeline,
    label: &'static str,
    buffers: &[&wgpu::Buffer],
) -> wgpu::BindGroup {
    let layout = pipeline.get_bind_group_layout(0);
    let entries = buffers
        .iter()
        .enumerate()
        .map(|(binding, buffer)| wgpu::BindGroupEntry {
            binding: binding as u32,
            resource: buffer.as_entire_binding(),
        })
        .collect::<Vec<_>>();
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some(label),
        layout: &layout,
        entries: &entries,
    })
}

pub(crate) fn storage<T: Pod>(
    device: &wgpu::Device,
    label: &'static str,
    values: &[T],
    copy_source: bool,
) -> wgpu::Buffer {
    let zero = T::zeroed();
    let values = if values.is_empty() {
        std::slice::from_ref(&zero)
    } else {
        values
    };
    let mut usage = wgpu::BufferUsages::STORAGE;
    if copy_source {
        usage |= wgpu::BufferUsages::COPY_SRC;
    }
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(label),
        contents: bytemuck::cast_slice(values),
        usage,
    })
}

pub(crate) fn empty_storage(
    device: &wgpu::Device,
    label: &'static str,
    size: u64,
    copy_source: bool,
) -> wgpu::Buffer {
    let mut usage = wgpu::BufferUsages::STORAGE;
    if copy_source {
        usage |= wgpu::BufferUsages::COPY_SRC;
    }
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size: size.max(4),
        usage,
        mapped_at_creation: false,
    })
}

pub(crate) fn readback(device: &wgpu::Device, label: &'static str, size: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size,
        usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

pub(crate) fn copy_and_map(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    copies: &[(&wgpu::Buffer, u64, u64)],
    target: &wgpu::Buffer,
    target_bytes: u64,
) -> Result<(Vec<u8>, Duration), GpuError> {
    let started = std::time::Instant::now();
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("gfm-chain-readback"),
    });
    let mut target_offset = 0;
    for (source, source_offset, byte_count) in copies {
        encoder.copy_buffer_to_buffer(source, *source_offset, target, target_offset, *byte_count);
        target_offset += byte_count;
    }
    debug_assert_eq!(target_offset, target_bytes);
    let submission = queue.submit([encoder.finish()]);
    let slice = target.slice(..target_bytes);
    let (sender, receiver) = mpsc::sync_channel(1);
    slice.map_async(wgpu::MapMode::Read, move |result| {
        let _ = sender.send(result);
    });
    device
        .poll(wgpu::PollType::Wait {
            submission_index: Some(submission),
            timeout: Some(GPU_WAIT),
        })
        .map_err(|error| GpuError::Execution(error.to_string()))?;
    receiver
        .recv_timeout(GPU_WAIT)
        .map_err(|error| GpuError::Execution(error.to_string()))?
        .map_err(|error| GpuError::Execution(error.to_string()))?;
    let mapped = slice
        .get_mapped_range()
        .map_err(|error| GpuError::Execution(error.to_string()))?;
    let bytes = mapped.to_vec();
    drop(mapped);
    target.unmap();
    Ok((bytes, started.elapsed()))
}

pub(crate) fn bytes<T>(values: &[T]) -> u64 {
    values.len() as u64 * size_of::<T>() as u64
}

pub(crate) fn read_pods<T: Pod>(bytes: &[u8]) -> Result<Vec<T>, GpuError> {
    let width = size_of::<T>();
    if width == 0 || !bytes.len().is_multiple_of(width) {
        return Err(GpuError::Execution(
            "chain readback extent does not match record width".to_owned(),
        ));
    }
    Ok(bytes
        .chunks_exact(width)
        .map(bytemuck::pod_read_unaligned)
        .collect())
}

pub(crate) fn micros(duration: Duration) -> u64 {
    duration.as_micros().min(u128::from(u64::MAX)) as u64
}
