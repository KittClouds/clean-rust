//! Appends synthetic but fully valid custody history to a v2 store (Phase 4 scale tests).
//!
//! `kammi-synth <store> <events> [batch]`
//!
//! Each event is an `ArtifactRegistered` for a distinct small artifact, with exactly the
//! envelope and payload `Ledger::register_bytes` produces. Events and objects are written in
//! batches (one flush per batch) instead of one flush per event; replay validates every
//! event as usual, so the result is indistinguishable from API-written history.

use kammi_core::{Clock, SystemClock};
use kammi_jcs::{canonical, raw_id};
use kammi_store::{NewEvent, Store, StoreOptions};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    let (Some(root), Some(count)) = (args.get(1), args.get(2)) else {
        return Err("usage: kammi-synth <store> <events> [batch]".into());
    };
    let count: u64 = count.parse()?;
    let batch: u64 = args.get(3).map(|b| b.parse()).transpose()?.unwrap_or(2000);
    let mut store = Store::open(std::path::Path::new(root), StoreOptions::default())?;
    let started = std::time::Instant::now();
    let first = store.main.seq() + 1;
    let mut written = 0u64;
    while written < count {
        let n = batch.min(count - written);
        let blobs: Vec<Vec<u8>> = (0..n)
            .map(|i| {
                format!(
                    "synthetic artifact {} {}",
                    first + written + i,
                    "x".repeat(((first + written + i) % 97) as usize)
                )
                .into_bytes()
            })
            .collect();
        let ids = store
            .objects
            .put_many(&blobs.iter().map(Vec::as_slice).collect::<Vec<_>>())?;
        let mut prev = store.main.head();
        let mut built = Vec::with_capacity(n as usize);
        for (i, (blob, id)) in blobs.iter().zip(&ids).enumerate() {
            let seq = store.main.seq() + 1 + i as u64;
            let payload = kammi_core::obj! {
                "artifact_id" => id.to_string(), "byte_count" => blob.len(), "kind" => "synthetic",
                "media_type" => "application/octet-stream", "schema_id" => "raw-v1", "source_location" => "api-upload",
            };
            let payload_bytes = canonical(&payload)?;
            let event = kammi_core::obj! {
                "schema" => "KAMMI_EVENT_V1", "seq" => seq, "prev" => prev.to_string(), "type" => "ArtifactRegistered",
                "payload_artifact" => raw_id(&payload_bytes).to_string(), "actor" => "synth",
                "request_id" => format!("synth-{seq}"), "utc" => SystemClock.now().event_utc(),
            };
            let event_bytes = canonical(&event)?;
            prev = kammi_jcs::typed_id_of_canonical(kammi_jcs::Domain::Event, &event_bytes);
            built.push((event_bytes, payload_bytes));
        }
        let events: Vec<NewEvent> = built
            .iter()
            .map(|(e, p)| NewEvent {
                event: e,
                payload: p,
            })
            .collect();
        store.main.append_batch(&events)?;
        written += n;
    }
    let seconds = started.elapsed().as_secs_f64();
    println!(
        "{}",
        kammi_core::obj! {"appended" => written, "seq" => store.main.seq(), "head" => store.main.head().to_string(),
        "seconds" => seconds, "events_per_second" => written as f64 / seconds.max(1e-9)}
    );
    Ok(())
}
