use std::{
    collections::HashMap,
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

use rdc_runtime_contracts_v1::{
    CrashPoint, EndpointResponse, PaidActionEndpoint, QueryJournal, RequestId, ResultBytes,
};

static NEXT: AtomicU64 = AtomicU64::new(0);

#[derive(Default)]
struct CachedEndpoint {
    cache: HashMap<RequestId, ResultBytes>,
    attempts: usize,
    charges: usize,
}

impl PaidActionEndpoint for CachedEndpoint {
    fn invoke(
        &mut self,
        id: RequestId,
        _cost_units: u32,
        request: &[u8],
    ) -> Result<EndpointResponse, String> {
        self.attempts += 1;
        let (result, charged) = match self.cache.get(&id).copied() {
            Some(result) => (result, true),
            None => {
                self.charges += 1;
                let hash = blake3::hash(request);
                let mut bytes = [0; 64];
                bytes[..32].copy_from_slice(hash.as_bytes());
                bytes[32..].copy_from_slice(hash.as_bytes());
                let result = ResultBytes::from_array(bytes);
                self.cache.insert(id, result);
                (result, true)
            }
        };
        Ok(EndpointResponse {
            result,
            charged_for_request: charged,
        })
    }
}

fn journal_path() -> PathBuf {
    let serial = NEXT.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "rdc-paid-action-{}-{serial}.rdi",
        std::process::id()
    ))
}

fn inputs() -> (RequestId, Vec<u8>) {
    (
        RequestId::derive(b"unit-test", 9, 3, 2, 16, 41),
        b"inspection request bytes survive local restart".to_vec(),
    )
}

#[test]
fn paid_response_crash_retries_by_id_without_a_second_charge_or_effect() {
    let path = journal_path();
    let (id, request) = inputs();
    let mut endpoint = CachedEndpoint::default();
    {
        let mut journal = QueryJournal::create(&path).unwrap();
        assert!(
            journal
                .execute(
                    &mut endpoint,
                    id,
                    3,
                    &request,
                    CrashPoint::AfterEndpointResponse
                )
                .is_err()
        );
    }
    let mut journal = QueryJournal::resume(&path).unwrap();
    let result = journal
        .execute(&mut endpoint, id, 3, &request, CrashPoint::None)
        .unwrap();
    assert_eq!(endpoint.attempts, 2);
    assert_eq!(endpoint.charges, 1);
    let stats = journal.stats();
    assert_eq!(stats.intents, 1);
    assert_eq!(stats.endpoint_attempts, 2);
    assert_eq!(stats.retries, 1);
    assert_eq!(stats.paid_requests, 1);
    assert_eq!(stats.paid_cost_units, 3);
    assert_eq!(stats.result_receipts, 1);
    assert_eq!(journal.result(id), Some(result));
    fs::remove_file(path).unwrap();
}

#[test]
fn durable_outcome_replays_without_endpoint_contact_and_intent_is_resumeable() {
    let path = journal_path();
    let (id, request) = inputs();
    let mut endpoint = CachedEndpoint::default();
    {
        let mut journal = QueryJournal::create(&path).unwrap();
        assert!(
            journal
                .execute(&mut endpoint, id, 2, &request, CrashPoint::AfterIntent)
                .is_err()
        );
    }
    {
        let mut journal = QueryJournal::resume(&path).unwrap();
        assert!(
            journal
                .execute(
                    &mut endpoint,
                    id,
                    2,
                    &request,
                    CrashPoint::AfterOutcomeReceipt
                )
                .is_err()
        );
    }
    let attempts_before_replay = endpoint.attempts;
    let journal = QueryJournal::resume(&path).unwrap();
    let cached = journal.result(id).unwrap();
    assert_eq!(endpoint.attempts, attempts_before_replay);
    assert_eq!(endpoint.charges, 1);
    assert_eq!(journal.stats().endpoint_attempts, 1);
    assert_eq!(journal.stats().result_receipts, 1);
    assert_eq!(
        cached.into_array()[..32],
        blake3::hash(&request).as_bytes()[..]
    );
    fs::remove_file(path).unwrap();
}

#[test]
fn request_id_reuse_with_changed_payload_is_rejected() {
    let path = journal_path();
    let (id, request) = inputs();
    let mut endpoint = CachedEndpoint::default();
    let mut journal = QueryJournal::create(&path).unwrap();
    journal
        .execute(&mut endpoint, id, 2, &request, CrashPoint::None)
        .unwrap();
    assert!(
        journal
            .execute(&mut endpoint, id, 2, b"changed request", CrashPoint::None)
            .is_err()
    );
    assert_eq!(endpoint.attempts, 1);
    fs::remove_file(path).unwrap();
}
