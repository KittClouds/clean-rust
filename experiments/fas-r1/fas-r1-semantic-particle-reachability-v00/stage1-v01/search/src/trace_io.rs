use crate::Stage1Run;
use serde::Serialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

const TRACE_SCHEMA: &str = "r1-stage1-hookable-trace-v2";
const DIAGNOSTICS_SCHEMA: &str = "r1-stage1-merge-diagnostics-v1";

/// Write the Stage 1 trace extension while preserving all frozen Stage 0
/// header, event, and footer fields except the superseded allocation flag.
/// The versioned event records add exact allocation diagnostics and snapshots
/// of both assignment-merge participants before either state is mutated.
pub fn write_stage1_trace_v2(path: impl AsRef<Path>, run: &Stage1Run) -> io::Result<()> {
    if run.trace.events.len() != run.event_diagnostics.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Stage 1 trace and diagnostic event counts differ",
        ));
    }
    let file = File::create(path.as_ref())?;
    let mut writer = BufWriter::new(file);

    let mut header = serde_json::to_value(&run.trace.header).map_err(invalid_data)?;
    let header = header.as_object_mut().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidData, "trace header is not an object")
    })?;
    header.insert("schema".to_owned(), json!(TRACE_SCHEMA));
    header.insert("diagnostics_schema".to_owned(), json!(DIAGNOSTICS_SCHEMA));
    write_record(&mut writer, "header", &Value::Object(header.clone()))?;

    for (event, diagnostic) in run.trace.events.iter().zip(&run.event_diagnostics) {
        let mut payload = serde_json::to_value(event).map_err(invalid_data)?;
        let fields = payload.as_object_mut().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "trace event is not an object")
        })?;
        fields.remove("value_allocation_non_nominal");
        fields.insert(
            "scheduler_slot_mismatch".to_owned(),
            json!(diagnostic.scheduler_slot_mismatch),
        );
        fields.insert(
            "value_based_allocation".to_owned(),
            json!(diagnostic.value_based_allocation),
        );
        fields.insert(
            "merge_loser".to_owned(),
            serde_json::to_value(&diagnostic.merge_loser).map_err(invalid_data)?,
        );
        fields.insert(
            "merge_kept".to_owned(),
            serde_json::to_value(&diagnostic.merge_kept).map_err(invalid_data)?,
        );
        fields.insert(
            "merge_retired_particle_id".to_owned(),
            json!(diagnostic.merge_retired_particle_id),
        );
        write_record(&mut writer, "event", &payload)?;
    }

    let footer = json!({
        "ledger": run.trace.ledger,
        "selected_event": run.trace.selected_event,
        "selected_initial_particle": run.trace.selected_initial_particle,
        "selected_q_terminal": run.trace.selected_q_terminal,
        "diagnostics_schema": DIAGNOSTICS_SCHEMA,
    });
    write_record(&mut writer, "footer", &footer)?;
    writer.flush()
}

fn write_record(writer: &mut impl Write, kind: &str, payload: &impl Serialize) -> io::Result<()> {
    serde_json::to_writer(&mut *writer, &json!({ "record": kind, "payload": payload }))
        .map_err(invalid_data)?;
    writer.write_all(b"\n")
}

fn invalid_data(error: serde_json::Error) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, error)
}
