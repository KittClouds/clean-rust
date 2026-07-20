use crate::{DiscoveryCandidateLedger, LedgerPublication};
use phoenix_discovery_query::{
    DiscoveryQueryError, PreparedDiscoveryQuery, PreparedQueryRequest, PreparedQueryResponse,
    PreparedSeedResolver, QueryScratch,
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
    if request.query.trim().is_empty() {
        return Err(Box::new(DiscoveryQueryError::Invalid(
            "discovery query must not be empty".to_owned(),
        )));
    }
    let query = request.query.to_owned();
    let response = prepared.execute(request, resolver, scratch)?;
    let publication = ledger.publish(&query, &response)?;
    Ok(PublishedDiscoveryQuery {
        response,
        publication,
    })
}
