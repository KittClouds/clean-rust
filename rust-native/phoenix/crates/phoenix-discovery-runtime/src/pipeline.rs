use crate::{DiscoveryCandidateLedger, LedgerPublication};
use phoenix_discovery_query::{
    CancellationProbe, DiscoveryQueryError, NeverCancel, PreparedDiscoveryQuery,
    PreparedQueryRequest, PreparedQueryResponse, PreparedSeedResolver, QueryScratch,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PublishedDiscoveryQuery {
    pub response: PreparedQueryResponse,
    pub publication: LedgerPublication,
}

pub fn execute_and_publish<R: PreparedSeedResolver>(
    prepared: &PreparedDiscoveryQuery<'_>,
    request: PreparedQueryRequest<'_>,
    resolver: &R,
    scratch: &mut QueryScratch,
    ledger: &DiscoveryCandidateLedger,
) -> Result<PublishedDiscoveryQuery, Box<dyn std::error::Error>> {
    execute_and_publish_with_cancellation(
        prepared,
        request,
        resolver,
        scratch,
        ledger,
        &NeverCancel,
    )
}

pub fn execute_and_publish_with_cancellation<R: PreparedSeedResolver>(
    prepared: &PreparedDiscoveryQuery<'_>,
    request: PreparedQueryRequest<'_>,
    resolver: &R,
    scratch: &mut QueryScratch,
    ledger: &DiscoveryCandidateLedger,
    cancellation: &dyn CancellationProbe,
) -> Result<PublishedDiscoveryQuery, Box<dyn std::error::Error>> {
    if request.query.trim().is_empty() {
        return Err(Box::new(DiscoveryQueryError::Invalid(
            "discovery query must not be empty".to_owned(),
        )));
    }
    let query = request.query.to_owned();
    let response = prepared.execute_with_cancellation(request, resolver, scratch, cancellation)?;
    let publication = ledger.publish(&query, &response)?;
    Ok(PublishedDiscoveryQuery {
        response,
        publication,
    })
}
