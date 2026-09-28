# Kammi store v2: physical format and invariants

Status: implemented in `kammi-store`, qualified by the Phase 1 suite. This changes the
physical representation only. Identities and authority rules are exactly v1's, and it grants
nothing new. It is the draft basis for architecture amendment v3.

## Invariants

1. Packed segments and object packs are storage, not new identity domains. Event IDs are
   `SHA256("kammi-event-v1\0" || JCS(event))` over the unchanged v1 envelope bytes. Objects are
   `SHA256(raw bytes)`.
2. Imported history keeps its exact v1 bytes. An export back to v1 layout is byte-identical.
3. The head is always the last committed journal frame. There is no separate HEAD or
   current-state marker that could disagree with the journal.
4. A committed prefix is never shortened or rewritten. Only an incomplete (torn) tail of the
   active segment or pack is moved to `recovery/` and cut. A complete frame or record that fails
   its checksum is corruption and refuses to open. Zero-filled space after the last frame is
   treated as torn.
5. Objects are durable before the event that names them is appended, because `put_*` returns
   only after the flush.
6. Segment indexes, the object index log and lookup tables are derived data. They are rebuilt
   from authoritative bytes when missing, torn, stale or inconsistent.
7. Checkpoints are accelerators. A checkpoint is trusted only if both bound heads equal the
   journal events at those sequence numbers and its payload digest verifies. Otherwise it is
   skipped and reported, and replay from genesis is always valid.
8. One writer per root. The lock is an OS-held lock on `locks/writer.lock` and is released by
   the OS when the owner dies.

## Layout

```text
STORE.json                         {"schema":"KAMMI_STORE_V2","version":1}
locks/writer.lock                  OS lock (authority); owner.json is diagnostic only
journal/{main,memory}/
  seg-00000001.seg                 "KMJSEG02" | first_seq u64 | frames...
  seg-00000001.idx                 "KMJIDX02" | first_seq u64 | 104-byte records   (derived)
  requests.tbl, payloads.tbl       sorted lookup tables                           (derived)
  recovery/                        torn tails preserved byte-exactly
objects/
  packs/pack-00000001.pack         "KMPACK02" | pack_no u64 | len u32 | id [32] | bytes ...
  packs/index.log                  id [32] | location u64 | len u32 | reserved u32 (derived)
  packs/packs.tbl                  sorted id -> location                          (derived)
  sha256/ab/cdef...                loose objects >= 256 KiB, v1 path rule
checkpoints/ckpt-<main>-<memory>.ckpt   newest 3 kept
genesis/v1-import.json             v1 root, heads and object count at the last sync
```

Frame: `body_len u32 LE | kind u8 (=1) | event_len u32 LE | event JCS | payload | sha256(body)`.
Index record (`#[repr(C)]`, little-endian, memory-mapped for sealed segments):
`seq u64, offset u64, frame_len u32, reserved u32, event_id [32], payload_id [32], request [16]`.
`request` is the first 16 bytes of `SHA256(request_id)`. A lookup confirms the full string by
reading the event.

## Commit order and fault points

```text
object bytes written      cas.before_write / cas.after_write
object durable            cas.after_fsync, cas.after_rename (loose)
object index logged       cas.after_index                       (derived)
journal frame appended    journal.before_write / journal.mid_frame / journal.before_fsync
journal durable           journal.after_fsync                    <- commit point
segment index appended    journal.after_index                    (derived)
segment rollover          journal.after_rollover
tables published          index.after_table                      (derived)
checkpoint published      checkpoint.after_write / checkpoint.after_rename
```

`KAMMI_ACCEPTANCE_FAULTS=1 KAMMI_FAULT_POINT=<p> KAMMI_FAULT_HIT=<n>` exits with code 91 at the
n-th hit, without unwinding or flushing.

## Platform notes

Windows has no directory flush. NTFS journals metadata, and file data is flushed with
`FlushFileBuffers` before every rename or acknowledgement. Big-endian targets are refused at
compile time because index files are mapped directly.
