use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};

use rdc_runtime_contracts_v1::{
    ActionCode, InspectionReply, TransportStatus, inspection::NO_ACTION,
};
use serde::{Deserialize, Serialize};

pub const DEVELOPMENT_SEED: u64 = 0xE007_2026_0925;
pub const HELDOUT_SEED: u64 = 0xE007_2026_0926;
pub const DEVELOPMENT_WORLDS: usize = 8;
pub const HELDOUT_WORLDS: usize = 16;
pub const EPISODES_PER_DOMAIN: usize = 32;
pub const DEVELOPMENT_DOMAINS: usize = 8;
pub const HELDOUT_DOMAINS: usize = 12;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum WorldStratum {
    Development,
    FamiliarIds,
    NewIds,
    ReliabilityShift,
    StaleSources,
}

impl WorldStratum {
    pub fn label(self) -> &'static str {
        match self {
            Self::Development => "development",
            Self::FamiliarIds => "familiar_ids",
            Self::NewIds => "new_ids",
            Self::ReliabilityShift => "reliability_shift",
            Self::StaleSources => "stale_sources",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorldParams {
    pub base_error: f32,
    pub shadow_error: f32,
    pub shared_error: f32,
    pub helpful_accuracy: f32,
    pub harmful_contradiction: f32,
    pub unknown_rate: f32,
    pub failed_rate: f32,
    pub staleness_rate: f32,
    pub stale_penalty: f32,
    pub warning_rate: f32,
    pub base_query_cost: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FamilyProfile {
    pub domain_id: u32,
    pub family_key: u16,
    pub observer_error_shift: f32,
    pub helpful_shift: f32,
    pub harmful_shift: f32,
    pub stale_shift: f32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorldRecipe {
    pub world_id: u32,
    pub seed: u64,
    pub stratum: WorldStratum,
    pub params: WorldParams,
    pub families: Vec<FamilyProfile>,
}

/// Only this public surface is passed to routing policies.
#[derive(Clone, Copy, Debug)]
pub struct PublicEpisode {
    pub id: u32,
    pub domain_id: u32,
    pub active: ActionCode,
    pub shadow: ActionCode,
    pub confidence_milli: u16,
    pub warning: bool,
    pub source_age: u8,
    pub revision_gap: u8,
    pub audit_selected: bool,
    pub query_cost_units: u32,
}

impl PublicEpisode {
    pub fn features(self) -> [f32; 8] {
        let disagreement = (self.active != self.shadow) as u8 as f32;
        let warning = self.warning as u8 as f32;
        let age = self.source_age.min(3) as f32 / 2.0;
        let confidence_gap = 1.0 - self.confidence_milli.min(1000) as f32 / 1000.0;
        let revision_gap = self.revision_gap.min(3) as f32 / 3.0;
        let audit_selected = self.audit_selected as u8 as f32;
        let stale_visible = (self.source_age > 0 || self.warning) as u8 as f32;
        [
            1.0,
            disagreement,
            warning,
            age,
            confidence_gap,
            revision_gap,
            audit_selected,
            stale_visible,
        ]
    }
}

/// Kept in a separate fixture from `PublicEpisode` and loaded only after plans freeze.
#[derive(Clone, Copy, Debug)]
pub struct HiddenEpisode {
    pub episode_id: u32,
    pub correct_action: ActionCode,
    pub reply: InspectionReply,
    pub source_is_stale: bool,
}

#[derive(Clone, Debug)]
pub struct WorldBank {
    pub recipe: WorldRecipe,
    pub public: Vec<PublicEpisode>,
    pub hidden: Vec<HiddenEpisode>,
}

pub fn validate_source_reply(episode_id: u32, reply: InspectionReply) -> bool {
    reply.payload_digest == source_reply_digest(episode_id, reply)
}

pub fn development_banks() -> Vec<WorldBank> {
    (0..DEVELOPMENT_WORLDS)
        .map(|index| generate_world(index as u32, DEVELOPMENT_SEED, WorldStratum::Development))
        .collect()
}

pub fn heldout_banks() -> Vec<WorldBank> {
    (0..HELDOUT_WORLDS)
        .map(|index| {
            let stratum = match index / 4 {
                0 => WorldStratum::FamiliarIds,
                1 => WorldStratum::NewIds,
                2 => WorldStratum::ReliabilityShift,
                _ => WorldStratum::StaleSources,
            };
            generate_world(100 + index as u32, HELDOUT_SEED, stratum)
        })
        .collect()
}

pub fn write_world_recipes(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
) -> Result<(), Box<dyn std::error::Error>> {
    let file = File::create(path)?;
    let mut writer = BufWriter::with_capacity(32 * 1024, file);
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
        "world_id,episode_id,domain_id,active,shadow,confidence_milli,warning,source_age,revision_gap,audit_selected,query_cost_units"
    )?;
    for bank in banks {
        for episode in &bank.public {
            writeln!(
                writer,
                "{},{},{},{},{},{},{},{},{},{},{}",
                bank.recipe.world_id,
                episode.id,
                episode.domain_id,
                episode.active.0,
                episode.shadow.0,
                episode.confidence_milli,
                episode.warning,
                episode.source_age,
                episode.revision_gap,
                episode.audit_selected,
                episode.query_cost_units
            )?;
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn write_source_fixture(
    path: impl AsRef<Path>,
    banks: &[WorldBank],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = BufWriter::with_capacity(32 * 1024, File::create(path)?);
    writeln!(
        writer,
        "world_id,episode_id,transport,candidate,competing_candidate,confidence_milli,signature_valid,source_revision,payload_digest,source_is_stale"
    )?;
    for bank in banks {
        for hidden in &bank.hidden {
            let reply = hidden.reply;
            writeln!(
                writer,
                "{},{},{},{},{},{},{},{},{},{}",
                bank.recipe.world_id,
                hidden.episode_id,
                reply.transport as u8,
                reply.candidate,
                reply.competing_candidate,
                reply.confidence_milli,
                reply.signature_valid,
                reply.source_revision,
                hex(&reply.payload_digest),
                hidden.source_is_stale
            )?;
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
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
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn generate_world(world_id: u32, root_seed: u64, stratum: WorldStratum) -> WorldBank {
    let seed = root_seed ^ (world_id as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    let mut config_rng = SplitMix64::new(seed ^ 0xA076_1D64_78BD_642F);
    let params = make_params(stratum, &mut config_rng);
    let domain_count = if stratum == WorldStratum::Development {
        DEVELOPMENT_DOMAINS
    } else {
        HELDOUT_DOMAINS
    };
    let mut families = Vec::with_capacity(domain_count);
    for index in 0..domain_count {
        let domain_id = if stratum == WorldStratum::Development || index < 4 {
            index as u32
        } else {
            1000 + world_id * 16 + index as u32
        };
        families.push(FamilyProfile {
            domain_id,
            family_key: if index < 4 {
                index as u16
            } else {
                100 + index as u16
            },
            observer_error_shift: config_rng.range(-0.12, 0.12),
            helpful_shift: config_rng.range(-0.18, 0.14),
            harmful_shift: config_rng.range(-0.10, 0.16),
            stale_shift: config_rng.range(-0.15, 0.20),
        });
    }
    let recipe = WorldRecipe {
        world_id,
        seed,
        stratum,
        params,
        families,
    };
    let mut rng = SplitMix64::new(seed ^ 0xE703_7ED1_A0B4_28DB);
    let mut public = Vec::with_capacity(domain_count * EPISODES_PER_DOMAIN);
    let mut hidden = Vec::with_capacity(domain_count * EPISODES_PER_DOMAIN);
    for (domain_index, family) in recipe.families.iter().enumerate() {
        for within in 0..EPISODES_PER_DOMAIN {
            let id = world_id * 100_000
                + domain_index as u32 * EPISODES_PER_DOMAIN as u32
                + within as u32;
            let correct = ActionCode((rng.next_u64() & 1) as u16);
            let base_error = clamp(
                recipe.params.base_error + family.observer_error_shift,
                0.03,
                0.85,
            );
            let active_wrong = rng.unit() < base_error;
            let active = if active_wrong {
                invert(correct)
            } else {
                correct
            };
            let shadow_wrong = if active_wrong {
                rng.unit() < recipe.params.shared_error
            } else {
                rng.unit() < recipe.params.shadow_error
            };
            let shadow = if shadow_wrong {
                invert(correct)
            } else {
                correct
            };
            let confidence = if active == shadow {
                rng.range_u16(650, 1000)
            } else {
                rng.range_u16(430, 850)
            };
            let source_age = rng.range_u8(0, 4);
            let warning = rng.unit() < recipe.params.warning_rate && source_age >= 2;
            let revision_gap = rng.range_u8(0, 4);
            let audit_selected = rng.unit() < 0.35;
            let cost_factor = 1 + (rng.next_u64() % 3) as u32;
            let public_episode = PublicEpisode {
                id,
                domain_id: family.domain_id,
                active,
                shadow,
                confidence_milli: confidence,
                warning,
                source_age,
                revision_gap,
                audit_selected,
                query_cost_units: recipe.params.base_query_cost * cost_factor,
            };
            let source_is_stale =
                rng.unit() < clamp(recipe.params.staleness_rate + family.stale_shift, 0.0, 0.95);
            let reply = make_reply(
                active,
                correct,
                source_is_stale,
                &recipe.params,
                family,
                &mut rng,
                id,
            );
            public.push(public_episode);
            hidden.push(HiddenEpisode {
                episode_id: id,
                correct_action: correct,
                reply,
                source_is_stale,
            });
        }
    }
    WorldBank {
        recipe,
        public,
        hidden,
    }
}

fn make_params(stratum: WorldStratum, rng: &mut SplitMix64) -> WorldParams {
    let ranges = match stratum {
        WorldStratum::Development => (
            0.15, 0.48, 0.15, 0.85, 0.03, 0.28, 0.01, 0.14, 0.01, 0.12, 0.05, 0.38, 0.08, 0.42,
            0.04, 0.30, 1, 2,
        ),
        WorldStratum::FamiliarIds => (
            0.14, 0.46, 0.18, 0.82, 0.58, 0.94, 0.03, 0.24, 0.01, 0.13, 0.05, 0.34, 0.08, 0.38,
            0.04, 0.24, 1, 2,
        ),
        WorldStratum::NewIds => (
            0.18, 0.54, 0.16, 0.82, 0.56, 0.92, 0.04, 0.28, 0.02, 0.16, 0.06, 0.42, 0.10, 0.42,
            0.05, 0.31, 2, 3,
        ),
        WorldStratum::ReliabilityShift => (
            0.24, 0.62, 0.30, 0.88, 0.34, 0.63, 0.20, 0.51, 0.08, 0.25, 0.07, 0.22, 0.16, 0.56,
            0.06, 0.35, 3, 4,
        ),
        WorldStratum::StaleSources => (
            0.16, 0.56, 0.18, 0.84, 0.56, 0.92, 0.05, 0.38, 0.02, 0.17, 0.03, 0.19, 0.46, 0.86,
            0.24, 0.55, 4, 5,
        ),
    };
    WorldParams {
        base_error: rng.range(ranges.0, ranges.1),
        shadow_error: rng.range(ranges.2, ranges.3),
        shared_error: rng.range(0.15, 0.88),
        helpful_accuracy: rng.range(ranges.4, ranges.5),
        harmful_contradiction: rng.range(ranges.6, ranges.7),
        unknown_rate: rng.range(ranges.8, ranges.9),
        failed_rate: rng.range(ranges.10, ranges.11),
        staleness_rate: rng.range(ranges.12, ranges.13),
        stale_penalty: rng.range(ranges.14, ranges.15),
        warning_rate: rng.range(0.15, 0.85),
        base_query_cost: if ranges.16 == ranges.17 {
            ranges.16
        } else {
            rng.range_u32(ranges.16, ranges.17 + 1)
        },
    }
}

fn make_reply(
    active: ActionCode,
    correct: ActionCode,
    source_is_stale: bool,
    params: &WorldParams,
    family: &FamilyProfile,
    rng: &mut SplitMix64,
    episode_id: u32,
) -> InspectionReply {
    let transport = if rng.unit() < params.failed_rate {
        if rng.next_u64() & 1 == 0 {
            TransportStatus::Timeout
        } else {
            TransportStatus::Unavailable
        }
    } else if rng.unit() < params.unknown_rate {
        TransportStatus::Malformed
    } else {
        TransportStatus::Complete
    };
    let mut confidence = rng.range_u16(780, 1000);
    let (candidate, competing, signature_valid) = if transport != TransportStatus::Complete {
        (NO_ACTION, NO_ACTION, false)
    } else {
        let stale_penalty = if source_is_stale {
            params.stale_penalty
        } else {
            0.0
        };
        if active == correct {
            let harmful = clamp(
                params.harmful_contradiction + family.harmful_shift + stale_penalty,
                0.0,
                0.85,
            );
            if rng.unit() < harmful {
                (invert(active).0, NO_ACTION, true)
            } else {
                (active.0, NO_ACTION, true)
            }
        } else {
            let helpful = clamp(
                params.helpful_accuracy + family.helpful_shift - stale_penalty,
                0.05,
                0.99,
            );
            if rng.unit() < helpful {
                (correct.0, NO_ACTION, true)
            } else {
                (active.0, NO_ACTION, true)
            }
        }
    };
    if transport == TransportStatus::Malformed {
        confidence = 0;
    }
    let mut reply = InspectionReply {
        transport,
        candidate,
        competing_candidate: competing,
        confidence_milli: confidence,
        signature_valid,
        source_revision: 1 + (rng.next_u64() % 5) as u32,
        payload_digest: [0; 32],
    };
    reply.payload_digest = source_reply_digest(episode_id, reply);
    reply
}

fn source_reply_digest(episode_id: u32, reply: InspectionReply) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E007-INSPECTION-SOURCE-V1\0");
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[reply.transport as u8, reply.signature_valid as u8]);
    hasher.update(&reply.candidate.to_le_bytes());
    hasher.update(&reply.competing_candidate.to_le_bytes());
    hasher.update(&reply.confidence_milli.to_le_bytes());
    hasher.update(&reply.source_revision.to_le_bytes());
    *hasher.finalize().as_bytes()
}

fn invert(action: ActionCode) -> ActionCode {
    ActionCode(1 - action.0)
}
fn clamp(value: f32, min: f32, max: f32) -> f32 {
    value.max(min).min(max)
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }
    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        value ^ (value >> 31)
    }
    fn unit(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / ((1u32 << 24) as f32)
    }
    fn range(&mut self, min: f32, max: f32) -> f32 {
        min + (max - min) * self.unit()
    }
    fn range_u16(&mut self, min: u16, max: u16) -> u16 {
        min + (self.next_u64() % (max - min) as u64) as u16
    }
    fn range_u8(&mut self, min: u8, max: u8) -> u8 {
        min + (self.next_u64() % (max - min) as u64) as u8
    }
    fn range_u32(&mut self, min: u32, max: u32) -> u32 {
        min + (self.next_u64() % (max - min) as u64) as u32
    }
}
