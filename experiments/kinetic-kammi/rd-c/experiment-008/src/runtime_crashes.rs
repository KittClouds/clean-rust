use crate::{
    runtime::{FixtureEndpoint, fixture_request},
    runtime_receipts::{CRASH_SEED, OfferLog, decode_offer, verify_offer_log},
};
use rdc_runtime_contracts_v1::InspectionReply;
use rdc_runtime_contracts_v1::paid_action::{CrashPoint, QueryJournal, RequestId};
use std::{fs, path::Path};

#[derive(Clone, Debug)]
pub struct CrashResult {
    pub boundary: String,
    pub result: String,
    pub endpoint_attempts: usize,
    pub retries: usize,
    pub paid_charges: usize,
    pub paid_cost_units: u64,
    pub journal_paid_requests: usize,
    pub endpoint_effects: usize,
    pub duplicate_charges: usize,
    pub replay_identity_ok: bool,
}

pub fn crash_recovery(root: &Path) -> Result<Vec<CrashResult>, Box<dyn std::error::Error>> {
    fs::create_dir_all(root)?;
    let mut results = Vec::with_capacity(5);
    let bank = crate::domain::development_banks().remove(0);
    for (index, point, boundary) in [
        (0u8, CrashPoint::AfterIntent, "paid_intent_before_call"),
        (
            1u8,
            CrashPoint::AfterEndpointResponse,
            "paid_response_before_receipt",
        ),
        (
            2u8,
            CrashPoint::AfterOutcomeReceipt,
            "durable_outcome_receipt",
        ),
    ] {
        let path = root.join(format!("crash-{boundary}.rdj"));
        let mut journal = QueryJournal::create(&path).map_err(std::io::Error::other)?;
        let mut endpoint = FixtureEndpoint::new(&bank);
        let episode = bank.public[0].id;
        let offer = bank.current_offers[0].offers[1];
        let request = fixture_request(b'Q', episode, 1, offer);
        let id = RequestId::derive(
            b"rdc-e008-crash",
            CRASH_SEED,
            bank.recipe.world_id * crate::domain::SOURCE_COUNT as u32 + 1,
            index,
            1,
            episode,
        );
        let cost = 7;
        let _ = journal.execute(&mut endpoint, id, cost, &request, point);
        drop(journal);
        let mut resumed = QueryJournal::resume(&path).map_err(std::io::Error::other)?;
        let recovered = resumed
            .execute(&mut endpoint, id, cost, &request, CrashPoint::None)
            .map_err(std::io::Error::other)?;
        let stats = resumed.stats();
        drop(resumed);
        let verified = QueryJournal::resume(&path).map_err(std::io::Error::other)?;
        let replay = verified.stats();
        let _recovered_reply = InspectionReply::decode(&recovered.into_array())?;
        results.push(CrashResult {
            boundary: boundary.to_owned(),
            result: "resumed_from_stable_request_id".to_owned(),
            endpoint_attempts: endpoint.endpoint_attempts,
            retries: stats.retries,
            paid_charges: endpoint.charges,
            paid_cost_units: endpoint.paid_cost,
            journal_paid_requests: stats.paid_requests,
            endpoint_effects: endpoint.charges,
            duplicate_charges: endpoint.charges.saturating_sub(1),
            replay_identity_ok: stats.identity == replay.identity
                && stats.bytes == replay.bytes
                && replay.unresolved == 0,
        });
    }
    // Crash after the paid quote refresh returns but before its durable offer receipt exists.
    let episode = bank.public[0].id;
    let source = bank.offers[0].offers[1].source_id;
    let initial_offer = bank.offers[0].offers[1];
    let request = fixture_request(b'O', episode, source, initial_offer);
    let id = RequestId::derive(
        b"rdc-e008-crash-offer",
        CRASH_SEED,
        bank.recipe.world_id * crate::domain::SOURCE_COUNT as u32 + source as u32,
        4,
        1,
        episode,
    );
    let path = root.join("crash-offer-response-before-receipt.rdj");
    let mut journal = QueryJournal::create(&path).map_err(std::io::Error::other)?;
    let mut endpoint = FixtureEndpoint::new(&bank);
    let _ = journal.execute(
        &mut endpoint,
        id,
        bank.recipe.offer_request_cost_units,
        &request,
        CrashPoint::AfterEndpointResponse,
    );
    drop(journal);
    let mut resumed = QueryJournal::resume(&path).map_err(std::io::Error::other)?;
    let response = resumed
        .execute(
            &mut endpoint,
            id,
            bank.recipe.offer_request_cost_units,
            &request,
            CrashPoint::None,
        )
        .map_err(std::io::Error::other)?;
    let refreshed = decode_offer(&response.into_array())?;
    let stats = resumed.stats();
    drop(resumed);
    let offer_path = root.join("crash-offer-response-before-receipt.offers.rdj");
    let mut log = OfferLog::create(&offer_path)?;
    log.append(
        bank.recipe.world_id,
        episode,
        refreshed,
        "costed_refresh_request",
        bank.recipe.offer_request_cost_units,
    )?;
    let offer_stats = log.finish()?;
    let verified = QueryJournal::resume(&path).map_err(std::io::Error::other)?;
    let replay = verified.stats();
    results.push(CrashResult {
        boundary: "offer_response_before_receipt".to_owned(),
        result: "resumed_stable_quote_request_then_receipted_offer".to_owned(),
        endpoint_attempts: endpoint.endpoint_attempts,
        retries: stats.retries,
        paid_charges: endpoint.charges,
        paid_cost_units: endpoint.paid_cost,
        journal_paid_requests: stats.paid_requests,
        endpoint_effects: endpoint.charges,
        duplicate_charges: endpoint.charges.saturating_sub(1),
        replay_identity_ok: stats.identity == replay.identity
            && stats.bytes == replay.bytes
            && replay.unresolved == 0
            && offer_stats.replay_ok
            && offer_stats.receipts == 1,
    });
    // Crash after durable offer receipt: reopen by verifying the immutable chain before recovery continues.
    let path = root.join("crash-after-offer-receipt.offers.rdj");
    let mut log = OfferLog::create(&path)?;
    let offer = bank.offers[0].offers[0];
    log.append(
        bank.recipe.world_id,
        bank.public[0].id,
        offer,
        "pushed_or_cached",
        0,
    )?;
    log.sync()?;
    drop(log);
    let offer_stats = verify_offer_log(&path)?;
    results.push(CrashResult {
        boundary: "offer_receipt_durable".to_owned(),
        result: "verified_then_resume_without_repurchase".to_owned(),
        endpoint_attempts: 0,
        retries: 0,
        paid_charges: 0,
        paid_cost_units: 0,
        journal_paid_requests: 0,
        endpoint_effects: 0,
        duplicate_charges: 0,
        replay_identity_ok: offer_stats.replay_ok && offer_stats.receipts == 1,
    });
    Ok(results)
}
