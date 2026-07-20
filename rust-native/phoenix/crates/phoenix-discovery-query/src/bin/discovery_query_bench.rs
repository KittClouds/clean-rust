use phoenix_discovery_community::DeterministicCommunityArtifact;
use phoenix_discovery_query::{
    BoundedSeedSink, DiscoveryQueryError, DiscoveryScorePolicy, PreparedDiscoveryQuery,
    PreparedQueryRequest, PreparedSeedResolver, QueryLimits, QueryScratch, SeedChannel,
    SeedChannelReceipt, SeedHit,
};
use phoenix_discovery_view::{AssertedDiscoveryView, DiscoveryRelationPolicy};
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;

struct BenchResolver {
    generation: u64,
    digest: String,
    seed: u32,
}

impl PreparedSeedResolver for BenchResolver {
    fn generation(&self) -> u64 {
        self.generation
    }

    fn discovery_digest(&self) -> &str {
        &self.digest
    }

    fn resolve_lexical(
        &self,
        _query: &str,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        sink.push(SeedHit {
            node: self.seed,
            raw_score_micros: 1_000_000,
            score_micros: 1_000_000,
        });
        Ok(receipt(self, SeedChannel::Lexical, 1))
    }

    fn resolve_vector(
        &self,
        _query_vector: Option<&[f32]>,
        _sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError> {
        Ok(receipt(self, SeedChannel::Vector, 0))
    }
}

fn receipt(resolver: &BenchResolver, channel: SeedChannel, examined: u32) -> SeedChannelReceipt {
    SeedChannelReceipt {
        channel,
        index_generation: resolver.generation,
        index_digest: resolver.digest.clone(),
        source_discovery_digest: resolver.digest.clone(),
        encoder_id: "benchmark".to_owned(),
        encoder_version: "1".to_owned(),
        examined,
        accepted: 0,
        truncated: false,
        hits: Vec::new(),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let discovery_root = PathBuf::from(args.next().ok_or(
        "usage: discovery-query-bench <discovery-artifact> <community-artifact> [iterations] [seed]",
    )?);
    let community_root = PathBuf::from(args.next().ok_or("missing community artifact")?);
    let iterations = args
        .next()
        .and_then(|value| value.to_string_lossy().parse::<usize>().ok())
        .unwrap_or(1_000)
        .max(1);
    let seed = args
        .next()
        .and_then(|value| value.to_string_lossy().parse::<u32>().ok())
        .unwrap_or(0);

    let discovery = AssertedDiscoveryView::open(discovery_root)?;
    let communities = DeterministicCommunityArtifact::open(community_root)?;
    let limits = QueryLimits::interactive();
    let runtime = PreparedDiscoveryQuery::prepare(
        &discovery,
        &communities,
        &DiscoveryRelationPolicy::phoenix_asserted_v1(),
        &DiscoveryScorePolicy::phoenix_discovery_v1(),
        limits,
    )?;
    let resolver = BenchResolver {
        generation: discovery.manifest().generation,
        digest: discovery.manifest().artifact_digest.clone(),
        seed,
    };
    let request = PreparedQueryRequest {
        query: "prepared-benchmark",
        query_vector: None,
        narrative_time: None,
    };
    let mut scratch = QueryScratch::new(limits)?;
    black_box(runtime.execute(request.clone(), &resolver, &mut scratch)?);

    let mut samples = Vec::with_capacity(iterations);
    let mut last = None;
    for _ in 0..iterations {
        let started = Instant::now();
        let response = runtime.execute(request.clone(), &resolver, &mut scratch)?;
        samples.push(started.elapsed().as_nanos() as u64);
        last = Some(response.receipt);
    }
    samples.sort_unstable();
    let p50 = samples[iterations / 2];
    let p95 = samples[(iterations * 95 / 100).min(iterations - 1)];
    let receipt = last.expect("at least one benchmark iteration");
    println!(
        "iterations={iterations} min_us={:.3} p50_us={:.3} p95_us={:.3} max_us={:.3} nodes={} edges={} examined={} paths={} fallback={}",
        samples[0] as f64 / 1_000.0,
        p50 as f64 / 1_000.0,
        p95 as f64 / 1_000.0,
        samples[iterations - 1] as f64 / 1_000.0,
        discovery.node_count(),
        discovery.edge_count(),
        receipt.total_examined_edges,
        receipt.returned_paths,
        receipt.fallback_used,
    );
    Ok(())
}
