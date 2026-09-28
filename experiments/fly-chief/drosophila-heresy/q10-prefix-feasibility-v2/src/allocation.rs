use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
};
struct Counter;
thread_local! {static N:Cell<u64>=const{Cell::new(0)};}
// SAFETY: layouts, pointers and requests are passed unchanged to System.
unsafe impl GlobalAlloc for Counter {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let _ = N.try_with(|n| n.set(n.get() + 1));
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let _ = N.try_with(|n| n.set(n.get() + 1));
        unsafe { System.realloc(ptr, layout, size) }
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let _ = N.try_with(|n| n.set(n.get() + 1));
        unsafe { System.alloc_zeroed(layout) }
    }
}
#[global_allocator]
static ALLOCATOR: Counter = Counter;
pub fn allocations() -> u64 {
    N.with(Cell::get)
}
