use crate::DiscoveryQueryError;
use serde::{Deserialize, Serialize};

pub const SCORE_SCALE: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SeedChannel {
    Lexical,
    Vector,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SeedHit {
    pub node: u32,
    pub raw_score_micros: i64,
    pub score_micros: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SeedChannelReceipt {
    pub channel: SeedChannel,
    pub index_generation: u64,
    pub index_digest: String,
    pub source_discovery_digest: String,
    pub encoder_id: String,
    pub encoder_version: String,
    pub examined: u32,
    pub accepted: u32,
    pub truncated: bool,
    pub hits: Vec<SeedHit>,
}

pub struct BoundedSeedSink<'a> {
    channel: SeedChannel,
    node_count: u64,
    cap: usize,
    accepted: u32,
    invalid: u32,
    truncated: bool,
    output: &'a mut Vec<(SeedChannel, SeedHit)>,
}

impl<'a> BoundedSeedSink<'a> {
    pub(crate) fn new(
        channel: SeedChannel,
        node_count: u64,
        cap: usize,
        output: &'a mut Vec<(SeedChannel, SeedHit)>,
    ) -> Self {
        Self {
            channel,
            node_count,
            cap,
            accepted: 0,
            invalid: 0,
            truncated: false,
            output,
        }
    }

    pub fn push(&mut self, hit: SeedHit) -> bool {
        if u64::from(hit.node) >= self.node_count || !(1..=SCORE_SCALE).contains(&hit.score_micros)
        {
            self.invalid = self.invalid.saturating_add(1);
            return false;
        }
        if self.len() >= self.cap {
            self.truncated = true;
            return false;
        }
        self.output.push((self.channel, hit));
        self.accepted = self.accepted.saturating_add(1);
        true
    }

    pub fn remaining(&self) -> usize {
        self.cap.saturating_sub(self.len())
    }

    pub fn len(&self) -> usize {
        self.output
            .iter()
            .filter(|(channel, _)| *channel == self.channel)
            .count()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub(crate) fn stats(&self) -> (u32, u32, bool) {
        (self.accepted, self.invalid, self.truncated)
    }
}

pub trait PreparedSeedResolver {
    fn generation(&self) -> u64;
    fn discovery_digest(&self) -> &str;

    fn resolve_lexical(
        &self,
        query: &str,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError>;

    fn resolve_vector(
        &self,
        query_vector: Option<&[f32]>,
        sink: &mut BoundedSeedSink<'_>,
    ) -> Result<SeedChannelReceipt, DiscoveryQueryError>;
}
