use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};

use crate::domain::{SOURCE_COUNT, WorldBank};

pub fn write_world_recipes(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(32 * 1024, File::create(path)?);
    serde_json::to_writer_pretty(
        &mut writer,
        &banks.iter().map(|bank| &bank.recipe).collect::<Vec<_>>(),
    )?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn write_public(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(32 * 1024, File::create(path)?);
    writeln!(
        writer,
        "world_id,episode_id,domain_id,active,shadow,confidence_milli,warning,source_age,revision_gap,audit_selected,base_action_cost"
    )?;
    for bank in banks {
        for row in &bank.public {
            writeln!(
                writer,
                "{},{},{},{},{},{},{},{},{},{},{}",
                bank.recipe.world_id,
                row.id,
                row.domain_id,
                row.active.0,
                row.shadow.0,
                row.confidence_milli,
                row.warning,
                row.source_age,
                row.revision_gap,
                row.audit_selected,
                row.base_action_cost
            )?;
        }
    }
    flush_sync(writer)
}

pub fn write_offers(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
    current: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(64 * 1024, File::create(path)?);
    writeln!(
        writer,
        "world_id,episode_id,offer_schema_version,offer_version,source_id,availability,source_local_age_bucket,provenance_family,independence_from_active_source,historical_reliability_bucket,quoted_query_price,offer_expiry,acquisition_provenance,acquisition_cost_units"
    )?;
    for bank in banks {
        let bundles = if current {
            &bank.current_offers
        } else {
            &bank.offers
        };
        for bundle in bundles {
            for offer in bundle.offers {
                let (provenance, cost) = if current {
                    (
                        "costed_refresh_fixture",
                        bank.recipe.offer_request_cost_units,
                    )
                } else {
                    ("pushed_or_cached", 0)
                };
                writeln!(
                    writer,
                    "{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
                    bank.recipe.world_id,
                    bundle.episode_id,
                    offer.schema_version,
                    offer.version,
                    offer.source_id,
                    offer.availability.label(),
                    offer.source_local_age_bucket,
                    offer.provenance_family,
                    offer.independence_from_active_source,
                    offer.historical_reliability_bucket,
                    offer.quoted_query_price,
                    offer.offer_expiry,
                    provenance,
                    cost
                )?;
            }
        }
    }
    flush_sync(writer)
}

pub fn write_labels(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(32 * 1024, File::create(path)?);
    writeln!(writer, "world_id,episode_id,correct_action")?;
    for bank in banks {
        for hidden in &bank.hidden {
            writeln!(
                writer,
                "{},{},{}",
                bank.recipe.world_id, hidden.episode_id, hidden.correct_action.0
            )?;
        }
    }
    flush_sync(writer)
}

pub fn write_source_fixture(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(64 * 1024, File::create(path)?);
    writeln!(
        writer,
        "world_id,episode_id,source_id,reply_offer_version,transport,candidate,competing_candidate,confidence_milli,signature_valid,source_revision,payload_digest,source_is_stale"
    )?;
    for bank in banks {
        for hidden in &bank.hidden {
            for source_id in 0..SOURCE_COUNT {
                let reply = hidden.replies[source_id];
                let offer = bank
                    .current_offers
                    .iter()
                    .find(|bundle| bundle.episode_id == hidden.episode_id)
                    .unwrap()
                    .offers[source_id];
                writeln!(
                    writer,
                    "{},{},{},{},{},{},{},{},{},{},{},{}",
                    bank.recipe.world_id,
                    hidden.episode_id,
                    source_id,
                    offer.version,
                    reply.transport as u8,
                    reply.candidate,
                    reply.competing_candidate,
                    reply.confidence_milli,
                    reply.signature_valid,
                    reply.source_revision,
                    hex(&reply.payload_digest),
                    hidden.source_is_stale[source_id]
                )?;
            }
        }
    }
    flush_sync(writer)
}

fn flush_sync(mut writer: BufWriter<File>) -> Result<(), Box<dyn std::error::Error>> {
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
