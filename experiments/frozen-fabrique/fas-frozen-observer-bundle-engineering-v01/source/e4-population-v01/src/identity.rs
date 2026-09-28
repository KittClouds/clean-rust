use hashbrown::HashSet;
use sha2::{Digest, Sha256};

use crate::schema::{CollisionSkip, RenderChoice, SemanticQuartet};

pub const POPULATION_NAMESPACE: &str = "FAS-E4-0-POP-V01";
pub const WORLD_RENDER_SEED: u64 = 2_026_092_605;
pub const SELECTED_PREFIX: usize = 18_667;
pub const SUPPORT_TARGET: u64 = 250;
pub const ROW_BYTES: u64 = 8_192;
pub const E1_ROOT_SHA256: &str = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03";
pub const E1_INPUT_SHA256: &str =
    "9f0076daa147bac37aa80d4f9a55f9225289910ceb8acc41998354c5a166917a";
pub const E1_ROW_MANIFEST_SHA256: &str =
    "ebfdf0064430ecae7a9ae2edd139f47c0c61291aa6c30c8ccb97daa195f835bc";
pub const E1_TERM_INVENTORY_SHA256: &str =
    "43b793068ad759a7ec77bd0027e7113a0145a35b1daacb8ea1cefa551803c672";
pub const HELDOUT_TEMPLATE_SHA256: &str =
    "e3b8a70b90b06fc4185d2e379cbfc7cf3724238d9505590add1cf8bba2e9b068";
pub const E1_GENERATOR_SOURCE_SHA256: &str =
    "fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1";
pub const PRIMARY_CHOICE_DOMAIN: &[u8] = b"FAS-E4-0-SEEN-CHOICE-v01\0";
pub const HELDOUT_CHOICE_DOMAIN: &[u8] = b"FAS-E4-0-HELDOUT-CHOICE-v01\0";
pub const QUARTET_ID_DOMAIN: &[u8] = b"FAS-E4-0-QUARTET-ID-v01\0";
const CHOICE_COUNT: usize = 8 * 8 * 6;

pub fn sha256(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    hex(&sha256(bytes))
}

pub fn hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

pub fn quartet_id_digest(counter: u64, semantic: SemanticQuartet) -> [u8; 32] {
    let mut digest = Sha256::new();
    digest.update(QUARTET_ID_DOMAIN);
    digest.update(POPULATION_NAMESPACE.as_bytes());
    digest.update([0]);
    digest.update(WORLD_RENDER_SEED.to_le_bytes());
    digest.update(counter.to_le_bytes());
    digest.update(semantic.schedule_ordinal.to_le_bytes());
    digest.update([
        semantic.track_code,
        semantic.context_split,
        semantic.entity_split,
        semantic.family_id,
        semantic.relation_id,
        semantic.state_id,
        semantic.context_pair_id,
        semantic.entity_pair_id,
    ]);
    digest.finalize().into()
}

pub fn row_id(quartet_digest: &[u8; 32], surface_code: u8, variant_code: u8) -> String {
    format!(
        "{}:{surface_code:02x}:{variant_code:02x}",
        hex(quartet_digest)
    )
}

pub fn choice_permutation(domain: &[u8], ordinal: u64) -> (usize, usize) {
    let mut digest = Sha256::new();
    digest.update(domain);
    digest.update(POPULATION_NAMESPACE.as_bytes());
    digest.update([0]);
    digest.update(WORLD_RENDER_SEED.to_le_bytes());
    digest.update(ordinal.to_le_bytes());
    let digest = digest.finalize();
    let start_raw = u32::from_le_bytes(digest[..4].try_into().expect("fixed digest slice"));
    let step_raw = u32::from_le_bytes(digest[4..8].try_into().expect("fixed digest slice"));
    let start = start_raw as usize % CHOICE_COUNT;
    let mut step = step_raw as usize % CHOICE_COUNT;
    while gcd(step, CHOICE_COUNT) != 1 {
        step = (step + 1) % CHOICE_COUNT;
    }
    (start, step)
}

pub fn choice_at(domain: &[u8], ordinal: u64, counter: u64) -> RenderChoice {
    let (start, step) = choice_permutation(domain, ordinal);
    let choice = (start + counter as usize * step) % CHOICE_COUNT;
    let observation_id = ((choice % 48) / 6) as u8;
    RenderChoice {
        query_id: (choice / 48) as u8,
        observation_id,
        candidate_order_id: (choice % 6) as u8,
    }
}

pub fn candidate_choices(ordinal: u64, counter: u64) -> (RenderChoice, RenderChoice) {
    (
        choice_at(PRIMARY_CHOICE_DOMAIN, ordinal, counter),
        choice_at(HELDOUT_CHOICE_DOMAIN, ordinal, counter),
    )
}

pub fn candidate_observation_id(choice: RenderChoice, variant_code: usize) -> u8 {
    if variant_code == 3 {
        (choice.observation_id + 4) % 8
    } else {
        choice.observation_id
    }
}

pub fn candidate_order(order_id: u8) -> [u8; 3] {
    const ORDERS: [[u8; 3]; 6] = [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ];
    ORDERS[order_id as usize]
}

fn candidate_row_ids(digest: &[u8; 32]) -> [String; 8] {
    std::array::from_fn(|index| {
        let surface = u8::from(index >= 4);
        row_id(digest, surface, (index % 4) as u8)
    })
}

fn gcd(mut left: usize, mut right: usize) -> usize {
    while right != 0 {
        (left, right) = (right, left % right);
    }
    left
}

#[derive(Default)]
pub struct FreshnessIndex {
    pub rendered_input_hashes: HashSet<[u8; 32]>,
    pub quartet_ids: HashSet<String>,
    pub row_ids: HashSet<String>,
}

impl FreshnessIndex {
    pub fn with_capacity(input_hashes: usize, quartets: usize, rows: usize) -> Self {
        Self {
            rendered_input_hashes: HashSet::with_capacity(input_hashes),
            quartet_ids: HashSet::with_capacity(quartets),
            row_ids: HashSet::with_capacity(rows),
        }
    }

    pub fn insert_input_hash(&mut self, hash: [u8; 32]) {
        self.rendered_input_hashes.insert(hash);
    }

    pub fn insert_quartet_id(&mut self, id: String) {
        self.quartet_ids.insert(id);
    }

    pub fn insert_row_id(&mut self, id: String) {
        self.row_ids.insert(id);
    }

    pub fn contains_rendered_input(&self, bytes: &[u8]) -> bool {
        self.rendered_input_hashes.contains(&sha256(bytes))
    }

    fn commit(&mut self, quartet_id: String, row_ids: [String; 8], input_hashes: [[u8; 32]; 8]) {
        self.quartet_ids.insert(quartet_id);
        self.row_ids.extend(row_ids);
        self.rendered_input_hashes.extend(input_hashes);
    }
}

#[derive(Clone, Debug)]
pub struct AcceptedRender {
    pub quartet_id: String,
    pub quartet_digest: [u8; 32],
    pub candidate_counter: u64,
    pub primary_choice: RenderChoice,
    pub heldout_choice: RenderChoice,
    pub rendered_input_hashes: [[u8; 32]; 8],
    pub skipped: Vec<CollisionSkip>,
}

pub fn choose_collision_free<F>(
    used: &mut FreshnessIndex,
    semantic: SemanticQuartet,
    mut render_inputs: F,
) -> Result<AcceptedRender, String>
where
    F: FnMut(u64, RenderChoice, RenderChoice) -> Result<[String; 8], String>,
{
    let mut skipped = Vec::new();
    for counter in 0..CHOICE_COUNT as u64 {
        let (primary_choice, heldout_choice) =
            candidate_choices(semantic.schedule_ordinal, counter);
        let inputs = render_inputs(counter, primary_choice, heldout_choice)?;
        let hashes: [[u8; 32]; 8] = std::array::from_fn(|i| sha256(inputs[i].as_bytes()));
        let digest = quartet_id_digest(counter, semantic);
        let quartet_id = hex(&digest);
        let row_ids = candidate_row_ids(&digest);
        let collision_classes = collision_classes(used, &quartet_id, &row_ids, &hashes);
        if collision_classes.is_empty() {
            used.commit(quartet_id.clone(), row_ids, hashes);
            return Ok(AcceptedRender {
                quartet_id,
                quartet_digest: digest,
                candidate_counter: counter,
                primary_choice,
                heldout_choice,
                rendered_input_hashes: hashes,
                skipped,
            });
        }
        skipped.push(CollisionSkip {
            schedule_ordinal: semantic.schedule_ordinal,
            candidate_counter: counter,
            collision_classes,
        });
    }
    Err(format!(
        "all 384 paired render choices collided for schedule ordinal {}",
        semantic.schedule_ordinal
    ))
}

fn collision_classes(
    used: &FreshnessIndex,
    quartet_id: &str,
    row_ids: &[String; 8],
    input_hashes: &[[u8; 32]; 8],
) -> Vec<String> {
    let mut classes = Vec::with_capacity(3);
    if used.quartet_ids.contains(quartet_id) {
        classes.push("quartet_id".to_owned());
    }
    let repeated_row = (0..row_ids.len()).any(|i| row_ids[i + 1..].contains(&row_ids[i]));
    if row_ids.iter().any(|id| used.row_ids.contains(id)) || repeated_row {
        classes.push("row_id".to_owned());
    }
    let repeated_input =
        (0..input_hashes.len()).any(|i| input_hashes[i + 1..].contains(&input_hashes[i]));
    if input_hashes
        .iter()
        .any(|hash| used.rendered_input_hashes.contains(hash))
        || repeated_input
    {
        classes.push("rendered_input_sha256".to_owned());
    }
    classes
}

pub fn supported_collision_classes() -> [&'static str; 3] {
    ["quartet_id", "row_id", "rendered_input_sha256"]
}

#[cfg(test)]
mod tests {
    use super::{
        FreshnessIndex, candidate_choices, candidate_observation_id, candidate_order, choice_at,
        choice_permutation, choose_collision_free, quartet_id_digest, row_id,
        supported_collision_classes,
    };
    use crate::schema::SemanticQuartet;

    fn semantic(ordinal: u64) -> SemanticQuartet {
        SemanticQuartet {
            schedule_ordinal: ordinal,
            track_code: 0,
            context_split: 0,
            entity_split: 1,
            family_id: 3,
            relation_id: 1,
            state_id: 2,
            context_pair_id: 7,
            entity_pair_id: 9,
        }
    }

    fn fixture_inputs(counter: u64) -> [String; 8] {
        std::array::from_fn(|index| format!("fixture:{counter}:{index}"))
    }

    #[test]
    fn namespace_identity_and_row_serialization_are_fixed_width() {
        let digest = quartet_id_digest(0, semantic(12));
        assert_eq!(row_id(&digest, 0, 0).len(), 70);
        assert!(row_id(&digest, 0, 0).ends_with(":00:00"));
        assert_ne!(row_id(&digest, 0, 0), row_id(&digest, 1, 0));
        assert_eq!(candidate_order(0), [0, 1, 2]);
        assert_eq!(candidate_order(5), [2, 1, 0]);
    }

    #[test]
    fn choice_permutations_cover_all_384_candidates() {
        for ordinal in [0, 1, 17, 18_666, u64::MAX] {
            for (domain, _choice_fn) in [
                (b"FAS-E4-0-SEEN-CHOICE-v01\0".as_slice(), 0_u8),
                (b"FAS-E4-0-HELDOUT-CHOICE-v01\0".as_slice(), 1_u8),
            ] {
                let (start, step) = choice_permutation(domain, ordinal);
                let mut choices = (0..384)
                    .map(|counter| (start + counter * step) % 384)
                    .collect::<Vec<_>>();
                choices.sort_unstable();
                assert_eq!(choices, (0..384).collect::<Vec<_>>());
                let choice = choice_at(domain, ordinal, 4);
                assert!(choice.query_id < 8 && choice.observation_id < 8);
            }
        }
        let (primary, heldout) = candidate_choices(3, 9);
        assert_ne!(primary, heldout);
        assert_eq!(
            candidate_observation_id(primary, 3),
            (primary.observation_id + 4) % 8
        );
    }

    #[test]
    fn retries_each_freshness_key_without_partial_commit() {
        let expected_classes = supported_collision_classes();
        for class in expected_classes {
            let mut used = FreshnessIndex::default();
            let sem = semantic(5);
            let first = super::candidate_choices(sem.schedule_ordinal, 0);
            let digest = quartet_id_digest(0, sem);
            match class {
                "quartet_id" => {
                    used.insert_quartet_id(super::hex(&digest));
                }
                "row_id" => {
                    used.insert_row_id(row_id(&digest, 0, 2));
                }
                "rendered_input_sha256" => {
                    used.insert_input_hash(super::sha256(b"fixture:0:6"));
                }
                _ => unreachable!(),
            }
            assert_ne!(first.0.query_id, 255);
            let accepted =
                choose_collision_free(&mut used, sem, |counter, _, _| Ok(fixture_inputs(counter)))
                    .unwrap();
            assert_eq!(accepted.candidate_counter, 1, "collision class: {class}");
            assert_eq!(accepted.skipped.len(), 1);
            assert!(
                accepted.skipped[0]
                    .collision_classes
                    .contains(&class.to_owned())
            );
            assert_eq!(
                used.quartet_ids.len(),
                1 + usize::from(class == "quartet_id")
            );
            assert_eq!(used.row_ids.len(), 8 + usize::from(class == "row_id"));
            assert_eq!(
                used.rendered_input_hashes.len(),
                8 + usize::from(class == "rendered_input_sha256")
            );
        }
    }

    #[test]
    fn deterministic_replay_and_collision_exhaustion_are_exact() {
        let sem = semantic(42);
        let mut left = FreshnessIndex::default();
        let mut right = FreshnessIndex::default();
        let a = choose_collision_free(&mut left, sem, |counter, _, _| Ok(fixture_inputs(counter)))
            .unwrap();
        let b = choose_collision_free(&mut right, sem, |counter, _, _| Ok(fixture_inputs(counter)))
            .unwrap();
        assert_eq!(a.quartet_id, b.quartet_id);
        assert_eq!(a.candidate_counter, b.candidate_counter);
        assert_eq!(a.rendered_input_hashes, b.rendered_input_hashes);

        let mut exhausted = FreshnessIndex::default();
        for counter in 0..384 {
            for input in fixture_inputs(counter) {
                exhausted.insert_input_hash(super::sha256(input.as_bytes()));
            }
        }
        let before = exhausted.rendered_input_hashes.len();
        let error = choose_collision_free(&mut exhausted, sem, |counter, _, _| {
            Ok(fixture_inputs(counter))
        })
        .expect_err("all candidate renderings are preoccupied");
        assert!(error.contains("all 384"));
        assert_eq!(exhausted.quartet_ids.len(), 0);
        assert_eq!(exhausted.row_ids.len(), 0);
        assert_eq!(exhausted.rendered_input_hashes.len(), before);
    }
}
