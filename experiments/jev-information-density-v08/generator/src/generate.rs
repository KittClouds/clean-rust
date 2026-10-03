use anyhow::{Context, Result, ensure};
use jev_decision_world_v01 as v01;
use serde::Serialize;
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::Path;

use crate::metadata::{GroupRecord, group_records};
use crate::project::{FamilyIds, canonical_episode};
use crate::worlds::{self, Topology, build_template};

const GENERATOR_ID: &str = "jev-information-density-v08-generator";

#[derive(Serialize)]
struct Receipt {
    protocol: &'static str,
    generator_id: &'static str,
    generator_version: &'static str,
    seed: u64,
    root_world_count: usize,
    canonical_episode_count: usize,
    atomic_group_count: usize,
    family_bundle_count: usize,
    family_world_count: usize,
    topology_counts: Vec<(String, usize)>,
    renderer_counts: Vec<(String, usize)>,
    operation_counts: Vec<(String, usize)>,
    world_model_assignments: Vec<WorldModelAssignment>,
    episodes_per_root: usize,
    groups_per_episode: usize,
    expected_groups_per_root: usize,
    exact_inference: bool,
    model_contact_authorized: bool,
    phoenix_in_scope: bool,
}

#[derive(Serialize)]
struct WorldModelAssignment {
    family_slug: &'static str,
    topology: &'static str,
    parameterization: usize,
}

#[derive(Clone)]
struct FamilyIdStrings {
    world: String,
    ontology: String,
    schema: String,
    candidate_set: String,
    definition: String,
    intervention: String,
    bundle: String,
}

impl FamilyIdStrings {
    fn borrow(&self) -> FamilyIds<'_> {
        FamilyIds {
            world: &self.world,
            ontology: &self.ontology,
            schema: &self.schema,
            candidate_set: &self.candidate_set,
            definition: &self.definition,
            intervention: &self.intervention,
        }
    }
}

pub fn run(roots: usize, seed: u64, output: &Path) -> Result<()> {
    if output.exists() {
        ensure!(
            output.is_dir(),
            "output path exists and is not a directory: {}",
            output.display()
        );
        ensure!(
            fs::read_dir(output)?.next().is_none(),
            "refusing to overwrite non-empty output directory: {}",
            output.display()
        );
    } else {
        fs::create_dir_all(output)?;
    }
    let canonical_path = output.join("new-universe-canonical.jsonl");
    let records_path = output.join("group-records.jsonl");
    let canonical_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&canonical_path)
        .with_context(|| format!("create {}", canonical_path.display()))?;
    let records_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&records_path)
        .with_context(|| format!("create {}", records_path.display()))?;
    let mut canonical_writer = BufWriter::with_capacity(1 << 20, canonical_file);
    let mut records_writer = BufWriter::with_capacity(1 << 20, records_file);
    let mut episode_count = 0_usize;
    let mut group_count = 0_usize;
    let mut topology_counts = [0_usize; 4];
    let mut renderer_counts = [0_usize; 6];
    let mut operation_counts = [0_usize; 4];
    let family_count = worlds::family_count();
    let topology_variants = Topology::all();
    let world_model_assignments: Vec<WorldModelAssignment> = (0..family_count)
        .map(|family_index| {
            let (topology, parameterization) = model_assignment(family_index);
            WorldModelAssignment {
                family_slug: worlds::family(family_index).slug,
                topology: topology.id(),
                parameterization,
            }
        })
        .collect();
    let base_config = v01::GenerationConfig {
        seed,
        count: 1,
        visibility_probability: 1.0,
    };

    for root_index in 0..roots {
        let family_index = root_index % family_count;
        let local_index = root_index / family_count;
        // The world mechanism is fixed within each observable domain family.
        // Varying it invisibly per root creates identical model inputs with
        // incompatible exact posteriors. Sampled truths/evidence still vary.
        let (topology, parameterization) = model_assignment(family_index);
        let topology_index = topology_variants
            .iter()
            .position(|candidate| candidate.id() == topology.id())
            .context("world topology assignment is not in the topology catalog")?;
        let hierarchy = (local_index / (topology_variants.len() * 2) + family_index) % 4;
        let definition_variant = (local_index / (topology_variants.len() * 3) + family_index) % 4;
        let spec = worlds::family(family_index);
        let template = build_template(family_index, topology, parameterization)?;
        let family_ids = family_id_strings(spec.slug, topology.id(), hierarchy, definition_variant);
        let root_id = format!("jev-v08-root-{root_index:08}");
        let base_episode_id = format!("jev-v08-{root_index:08}-base");

        let base = v01::generate_episode(&template, root_index, &base_config)
            .with_context(|| format!("generate base world {root_index}"))?;
        let mut surface = v01::surface_perturbation(&base, &template, v01::RenderFormat::Json)
            .with_context(|| format!("surface sibling {root_index}"))?;
        let original_prose = base
            .renderings
            .iter()
            .find(|rendering| rendering.format == v01::RenderFormat::Prose)
            .context("base world has no prose rendering")?
            .clone();
        surface.renderings.push(original_prose);
        let removable_fact = base
            .evidence_state
            .facts
            .iter()
            .find(|fact| matches!(fact.visibility, v01::Visibility::Visible))
            .context("fully observed world has no visible fact")?
            .fact_id
            .clone();
        let evidence_child = v01::observation_perturbation(&base, &template, &removable_fact)
            .with_context(|| format!("evidence sibling {root_index}"))?;
        let cause_index = template
            .variable_index("root_cause")
            .context("root cause variable absent")?;
        let alternate_cause = (base.sampled_world[cause_index] + 1) % 4;
        let world_child = v01::world_perturbation(&base, &template, "root_cause", alternate_cause)
            .with_context(|| format!("world sibling {root_index}"))?;

        let base_renderer = local_index % 6;
        let siblings = [
            (
                &base,
                "base",
                base_episode_id.clone(),
                None,
                base_renderer,
                0_usize,
            ),
            (
                &surface,
                "surface_invariance",
                format!("jev-v08-{root_index:08}-surface"),
                Some(base_episode_id.as_str()),
                (base_renderer + 1) % 6,
                1,
            ),
            (
                &evidence_child,
                "observation_intervention",
                format!("jev-v08-{root_index:08}-hide"),
                Some(base_episode_id.as_str()),
                (base_renderer + 3) % 6,
                2,
            ),
            (
                &world_child,
                "world_intervention",
                format!("jev-v08-{root_index:08}-do"),
                Some(base_episode_id.as_str()),
                (base_renderer + 5) % 6,
                3,
            ),
        ];
        topology_counts[topology_index] += 1;
        for (source, operation, episode_id, parent_id, renderer, operation_index) in siblings {
            let canonical = canonical_episode(
                source,
                &template,
                spec,
                family_ids.borrow(),
                hierarchy,
                definition_variant,
                renderer,
                &root_id,
                &episode_id,
                parent_id,
            )
            .with_context(|| format!("project {} to canonical episode", episode_id))?;
            serde_json::to_writer(&mut canonical_writer, &canonical)?;
            canonical_writer.write_all(b"\n")?;
            let groups: Vec<GroupRecord> = group_records(
                &canonical,
                &root_id,
                &family_ids.bundle,
                family_ids.borrow(),
                &template.template_id,
                topology.id(),
                hierarchy,
                operation,
            )?;
            ensure!(
                groups.len() == 4,
                "episode {} emitted {} trainable groups, expected 4",
                episode_id,
                groups.len()
            );
            for group in groups {
                serde_json::to_writer(&mut records_writer, &group)?;
                records_writer.write_all(b"\n")?;
                group_count += 1;
            }
            renderer_counts[renderer % 6] += 1;
            operation_counts[operation_index] += 1;
            episode_count += 1;
        }
    }
    canonical_writer.flush()?;
    records_writer.flush()?;
    let topologies = topology_variants
        .iter()
        .enumerate()
        .map(|(i, topology)| (topology.id().to_string(), topology_counts[i]))
        .collect();
    let renderers = [
        "prose",
        "json",
        "table",
        "event_stream",
        "key_value",
        "dialogue",
    ]
    .iter()
    .enumerate()
    .map(|(i, name)| (name.to_string(), renderer_counts[i]))
    .collect();
    let operations = [
        "base",
        "surface_invariance",
        "observation_intervention",
        "world_intervention",
    ]
    .iter()
    .enumerate()
    .map(|(i, name)| (name.to_string(), operation_counts[i]))
    .collect();
    let receipt = Receipt {
        protocol: "jev-decision-data-information-density/v0.8",
        generator_id: GENERATOR_ID,
        generator_version: "0.8.0",
        seed,
        root_world_count: roots,
        canonical_episode_count: episode_count,
        atomic_group_count: group_count,
        family_bundle_count: family_count,
        family_world_count: family_count,
        topology_counts: topologies,
        renderer_counts: renderers,
        operation_counts: operations,
        world_model_assignments,
        episodes_per_root: 4,
        groups_per_episode: 4,
        expected_groups_per_root: 16,
        exact_inference: true,
        model_contact_authorized: false,
        phoenix_in_scope: false,
    };
    let receipt_path = output.join("generation-receipt.json");
    let mut receipt_writer = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&receipt_path)?,
    );
    serde_json::to_writer_pretty(&mut receipt_writer, &receipt)?;
    receipt_writer.write_all(b"\n")?;
    receipt_writer.flush()?;
    ensure!(
        group_count == roots * 16,
        "group total does not match generator contract"
    );
    Ok(())
}

fn model_assignment(family_index: usize) -> (Topology, usize) {
    let topologies = Topology::all();
    (
        topologies[family_index % topologies.len()],
        (family_index / topologies.len()) % 4,
    )
}

fn family_id_strings(
    slug: &str,
    topology: &str,
    hierarchy: usize,
    definition_variant: usize,
) -> FamilyIdStrings {
    FamilyIdStrings {
        world: format!("jev-v08-world-family:{slug}:{topology}"),
        ontology: format!("jev-v08-ontology-family:{slug}:h{hierarchy}"),
        schema: format!("jev-v08-schema-composition:{slug}:h{hierarchy}:card4"),
        candidate_set: format!(
            "jev-v08-candidate-construction:{slug}:closed-open-independent-ordinal"
        ),
        definition: format!("jev-v08-definition-family:{slug}:v{definition_variant}"),
        intervention: format!("jev-v08-intervention-family:{slug}:surface-hide-do"),
        bundle: format!("jev-v08-bundle:{slug}"),
    }
}

#[cfg(test)]
mod tests {
    use super::model_assignment;
    use crate::worlds::{self, Topology};
    use std::collections::HashSet;

    #[test]
    fn every_observable_family_has_a_fixed_world_model() {
        let mut pairs = HashSet::new();
        for family_index in 0..worlds::family_count() {
            let (topology, parameterization) = model_assignment(family_index);
            for local_index in [0, 1, 17, 1_000] {
                let root_index = local_index * worlds::family_count() + family_index;
                let root_family_index = root_index % worlds::family_count();
                let (root_topology, root_parameterization) = model_assignment(root_family_index);
                assert_eq!(root_topology.id(), topology.id());
                assert_eq!(root_parameterization, parameterization);
            }
            pairs.insert((topology.id(), parameterization));
        }
        assert_eq!(Topology::all().len(), 4);
        assert_eq!(
            pairs.len(),
            16,
            "catalog should cover all topology/parameter pairs"
        );
    }
}
