use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;
use std::sync::atomic::{AtomicU64, Ordering};

static ALLOCATION_BYTES: AtomicU64 = AtomicU64::new(0);
static ALLOCATION_COUNT: AtomicU64 = AtomicU64::new(0);

thread_local! {
    static THREAD_ALLOCATION_BYTES: Cell<u64> = const { Cell::new(0) };
    static THREAD_ALLOCATION_COUNT: Cell<u64> = const { Cell::new(0) };
}

struct CountingAllocator;

// The isolated trainer owns its executable and uses the system allocator while
// accumulating process-wide request volume. Candle worker-thread allocations are
// therefore included without adding instrumentation inside Candle itself.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // SAFETY: forwarding the exact layout to the system allocator.
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            record(layout.size());
        }
        pointer
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        // SAFETY: forwarding the exact layout to the system allocator.
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            record(layout.size());
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: pointer and layout originate from this allocator.
        unsafe { System.dealloc(pointer, layout) };
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        // SAFETY: pointer and layout originate from this allocator and new_size is
        // forwarded unchanged.
        let resized = unsafe { System.realloc(pointer, layout, new_size) };
        if !resized.is_null() {
            record(new_size);
        }
        resized
    }
}

#[global_allocator]
static GLOBAL_ALLOCATOR: CountingAllocator = CountingAllocator;

#[derive(Clone, Copy)]
pub(crate) struct AllocationSnapshot {
    bytes: u64,
    count: u64,
}

#[derive(Clone, Copy)]
pub(crate) struct AllocationDelta {
    pub bytes: u64,
    pub count: u64,
}

#[derive(Clone, Copy)]
pub(crate) struct ThreadAllocationSnapshot {
    bytes: u64,
    count: u64,
}

impl AllocationSnapshot {
    pub fn now() -> Self {
        Self {
            bytes: ALLOCATION_BYTES.load(Ordering::Relaxed),
            count: ALLOCATION_COUNT.load(Ordering::Relaxed),
        }
    }

    pub fn elapsed(self) -> AllocationDelta {
        Self::now().since(self)
    }

    fn since(self, earlier: Self) -> AllocationDelta {
        AllocationDelta {
            bytes: self.bytes.saturating_sub(earlier.bytes),
            count: self.count.saturating_sub(earlier.count),
        }
    }
}

impl ThreadAllocationSnapshot {
    pub fn now() -> Self {
        Self {
            bytes: THREAD_ALLOCATION_BYTES.get(),
            count: THREAD_ALLOCATION_COUNT.get(),
        }
    }

    pub fn elapsed(self) -> AllocationDelta {
        AllocationDelta {
            bytes: THREAD_ALLOCATION_BYTES.get().saturating_sub(self.bytes),
            count: THREAD_ALLOCATION_COUNT.get().saturating_sub(self.count),
        }
    }
}

fn record(bytes: usize) {
    ALLOCATION_BYTES.fetch_add(bytes as u64, Ordering::Relaxed);
    ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
    THREAD_ALLOCATION_BYTES.set(THREAD_ALLOCATION_BYTES.get().saturating_add(bytes as u64));
    THREAD_ALLOCATION_COUNT.set(THREAD_ALLOCATION_COUNT.get().saturating_add(1));
}

#[cfg(windows)]
pub(crate) fn peak_working_set_bytes() -> std::io::Result<u64> {
    Ok(process_memory_counters()?.PeakWorkingSetSize as u64)
}

#[cfg(windows)]
pub(crate) fn working_set_bytes() -> std::io::Result<u64> {
    Ok(process_memory_counters()?.WorkingSetSize as u64)
}

#[cfg(windows)]
fn process_memory_counters(
) -> std::io::Result<windows_sys::Win32::System::ProcessStatus::PROCESS_MEMORY_COUNTERS> {
    use windows_sys::Win32::System::ProcessStatus::{
        K32GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;

    let mut counters = PROCESS_MEMORY_COUNTERS {
        cb: std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
        ..PROCESS_MEMORY_COUNTERS::default()
    };
    // SAFETY: GetCurrentProcess returns the current process pseudo-handle and the
    // counter buffer is valid for the declared byte length.
    let succeeded = unsafe {
        K32GetProcessMemoryInfo(
            GetCurrentProcess(),
            &mut counters,
            std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
        )
    };
    if succeeded == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(counters)
}

#[cfg(not(windows))]
pub(crate) fn peak_working_set_bytes() -> std::io::Result<u64> {
    Ok(0)
}

#[cfg(not(windows))]
pub(crate) fn working_set_bytes() -> std::io::Result<u64> {
    Ok(0)
}
