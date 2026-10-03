use super::support::{apply_merge, choose_particle, snapshot_particle};
use super::{DeterministicRng, Particle, Representative};

fn particle(id: u32, assignment: &[u8], latent: &[f32], depth: u32, value: f32) -> Particle {
    Particle {
        id,
        parent_particle_id: id.checked_sub(1),
        ancestry_id: u64::from(id) + 100,
        assignment: assignment.to_vec(),
        latent: latent.to_vec(),
        rng: DeterministicRng::new(u64::from(id) + 7),
        depth,
        last_event: depth.checked_sub(1).map(u64::from),
        value,
        allocations_since_spawn: u64::from(depth),
        alive: true,
        retired_by_merge: false,
    }
}

fn representative(state: &Particle, event: Option<u64>, initial: Option<u32>) -> Representative {
    Representative {
        particle_id: state.id,
        event_index: event,
        initial_id: initial,
        value: state.value,
        particle: state.clone(),
    }
}

#[test]
fn candidate_win_retires_and_marks_the_previous_representative() {
    let previous_particle = particle(0, &[0, 1], &[0.25, 0.5], 1, 0.4);
    let mut candidate = particle(1, &[0, 1], &[0.75, 0.5], 2, 0.9);
    let previous = representative(&previous_particle, Some(3), None);
    let mut particles = vec![previous_particle, candidate.clone()];

    let retired = apply_merge(&mut particles, &mut candidate, &previous, true);

    assert_eq!(retired, Some(0));
    assert!(!particles[0].alive);
    assert!(particles[0].retired_by_merge);
    assert!(particles[1].alive);
    assert!(!particles[1].retired_by_merge);
}

#[test]
fn candidate_loss_retires_candidate_and_keeps_previous_state() {
    let previous_particle = particle(0, &[0, 1], &[0.25], 1, 0.9);
    let mut candidate = particle(1, &[0, 1], &[0.75], 2, 0.4);
    let previous = representative(&previous_particle, Some(3), None);
    let mut particles = vec![previous_particle.clone(), candidate.clone()];

    let retired = apply_merge(&mut particles, &mut candidate, &previous, false);

    assert_eq!(retired, Some(1));
    assert!(particles[0].alive);
    assert!(!particles[0].retired_by_merge);
    assert_eq!(particles[0].latent, previous_particle.latent);
    assert!(!particles[1].alive);
    assert!(particles[1].retired_by_merge);
}

#[test]
fn same_particle_merge_records_distinct_states_without_retiring_an_id() {
    let previous_particle = particle(0, &[0, 1], &[0.25, 0.5], 1, 0.9);
    let mut candidate = particle(0, &[0, 1], &[0.75, 0.5], 2, 0.4);
    let previous = representative(&previous_particle, Some(3), None);
    let loser = snapshot_particle(&candidate, Some(4), None);
    let kept = snapshot_particle(
        &previous.particle,
        previous.event_index,
        previous.initial_id,
    );
    let mut particles = vec![candidate.clone()];

    let retired = apply_merge(&mut particles, &mut candidate, &previous, false);

    assert_eq!(retired, None);
    assert_eq!(loser.particle_id, kept.particle_id);
    assert_ne!(loser.depth, kept.depth);
    assert_ne!(loser.latent_state, kept.latent_state);
    assert_eq!(particles[0].depth, previous_particle.depth);
    assert_eq!(particles[0].latent, previous_particle.latent);
    assert!(!particles[0].retired_by_merge);
}

#[test]
fn particle_chooser_identifies_only_the_value_fallback() {
    let mut under_allocated = particle(0, &[0], &[0.0], 0, 0.1);
    under_allocated.allocations_since_spawn = 0;
    let mut allocated_low = particle(1, &[1], &[0.0], 1, 0.2);
    allocated_low.allocations_since_spawn = 1;
    let particles = vec![under_allocated, allocated_low];
    assert_eq!(choose_particle(&particles, 1), Some((0, false)));

    let mut allocated_high = particle(2, &[1], &[0.0], 1, 0.8);
    allocated_high.allocations_since_spawn = 1;
    let particles = vec![particles[1].clone(), allocated_high];
    assert_eq!(choose_particle(&particles, 1), Some((1, true)));
}
