use crate::identity::{candidate_observation_id, candidate_order};
use crate::schema::{RenderChoice, SemanticQuartet};
use fas_frozen_observer_bundle_panel_v04::generate::{
    OBSERVATION_TEMPLATES, QUERY_TEMPLATES, STATES,
};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::path::Path;

pub const PRIMARY_SURFACE_ID: &str = "PRIMARY_SEEN";
pub const HELDOUT_SURFACE_ID: &str = "HELDOUT_TEMPLATE";
pub const PRIMARY_TRUTH_PARTITION: &str = "PRIMARY_TERMINAL";
pub const ESCROW_TRUTH_PARTITION: &str = "TEMPLATE_ESCROW";
pub const VARIANT_IDS: [&str; 4] = ["A", "C", "E", "P"];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemplateSurface {
    pub observation_templates: Vec<String>,
    pub query_templates: Vec<String>,
}

#[derive(Deserialize)]
struct TemplateManifest {
    observation_templates: Vec<TemplateEntry>,
    query_templates: Vec<TemplateEntry>,
}

#[derive(Deserialize)]
struct TemplateEntry {
    id: usize,
    text: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RenderedSurface {
    pub inputs: [String; 4],
    pub context_term_ids: [u8; 4],
    pub entity_term_ids: [u8; 4],
    pub candidate_identity_order: [u8; 3],
    pub exact_target: u8,
}

pub fn primary_surface() -> TemplateSurface {
    TemplateSurface {
        observation_templates: OBSERVATION_TEMPLATES
            .iter()
            .map(|s| (*s).to_owned())
            .collect(),
        query_templates: QUERY_TEMPLATES.iter().map(|s| (*s).to_owned()).collect(),
    }
}

pub fn load_heldout_surface(path: &Path) -> Result<(TemplateSurface, String, u64), String> {
    let bytes = std::fs::read(path).map_err(|error| format!("read template manifest: {error}"))?;
    let digest = Sha256::digest(&bytes);
    let hash = digest
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    if hash != crate::identity::HELDOUT_TEMPLATE_SHA256 {
        return Err(
            "held-out template manifest SHA-256 differs from the reviewed v02 identity".into(),
        );
    }
    let manifest: TemplateManifest = serde_json::from_slice(&bytes)
        .map_err(|error| format!("decode held-out template manifest: {error}"))?;
    let observations = ordered_templates(manifest.observation_templates)?;
    let queries = ordered_templates(manifest.query_templates)?;
    Ok((
        TemplateSurface {
            observation_templates: observations,
            query_templates: queries,
        },
        hash,
        bytes.len() as u64,
    ))
}

fn ordered_templates(entries: Vec<TemplateEntry>) -> Result<Vec<String>, String> {
    if entries.len() != 8
        || entries
            .iter()
            .enumerate()
            .any(|(index, entry)| entry.id != index)
    {
        return Err("template manifest must contain exactly ordered IDs 0 through 7".into());
    }
    Ok(entries.into_iter().map(|entry| entry.text).collect())
}

pub fn render_surface(
    templates: &TemplateSurface,
    terms: &TermInventoryView<'_>,
    semantic: SemanticQuartet,
    choice: RenderChoice,
) -> Result<RenderedSurface, String> {
    if choice.observation_id >= 8 || choice.query_id >= 8 || choice.candidate_order_id >= 6 {
        return Err("render choice falls outside the frozen 8x8x6 choice surface".into());
    }
    if templates.observation_templates.len() != 8 || templates.query_templates.len() != 8 {
        return Err(
            "each rendering surface must have eight observation and eight query templates".into(),
        );
    }
    let context_base_id = semantic.context_split * 16 + semantic.context_pair_id;
    let context_partner_id = semantic.context_split * 16 + (semantic.context_pair_id + 7) % 16;
    let entity_base_id = semantic.entity_split * 16 + semantic.entity_pair_id;
    let entity_partner_id = semantic.entity_split * 16 + (semantic.entity_pair_id + 7) % 16;
    let context_ids = [
        context_base_id,
        context_partner_id,
        context_base_id,
        context_base_id,
    ];
    let entity_ids = [
        entity_base_id,
        entity_base_id,
        entity_partner_id,
        entity_base_id,
    ];
    let order = candidate_order(choice.candidate_order_id);
    let exact_target = order
        .iter()
        .position(|candidate_identity| *candidate_identity == semantic.state_id)
        .ok_or_else(|| "candidate order does not contain the frozen target identity".to_owned())?
        as u8;
    let options = order
        .map(|candidate_id| STATES[candidate_id as usize])
        .join(", ");
    let render_one = |variant_index: usize| -> Result<String, String> {
        let observation_id = candidate_observation_id(choice, variant_index) as usize;
        let context = terms
            .context_terms
            .get(context_ids[variant_index] as usize)
            .ok_or_else(|| "context term ID falls outside the sealed E1 inventory".to_owned())?;
        let entity = terms
            .entity_terms
            .get(entity_ids[variant_index] as usize)
            .ok_or_else(|| "entity term ID falls outside the sealed E1 inventory".to_owned())?;
        let relation = fas_frozen_observer_bundle_panel_v04::generate::RELATIONS
            .get(semantic.relation_id as usize)
            .ok_or_else(|| "relation ID falls outside the E1 vocabulary".to_owned())?;
        let state = STATES
            .get(semantic.state_id as usize)
            .ok_or_else(|| "state ID falls outside the E1 vocabulary".to_owned())?;
        let observation = render_template(
            &templates.observation_templates[observation_id],
            context,
            entity,
            relation,
            state,
        );
        let query = render_query_template(
            &templates.query_templates[choice.query_id as usize],
            context,
            entity,
            relation,
        );
        Ok(format!("{observation}\n{query}\nOptions: {options}"))
    };
    let inputs = [
        render_one(0)?,
        render_one(1)?,
        render_one(2)?,
        render_one(3)?,
    ];
    Ok(RenderedSurface {
        inputs,
        context_term_ids: context_ids,
        entity_term_ids: entity_ids,
        candidate_identity_order: order,
        exact_target,
    })
}

pub struct TermInventoryView<'a> {
    pub context_terms: &'a [String],
    pub entity_terms: &'a [String],
}

fn render_template(
    template: &str,
    context: &str,
    entity: &str,
    relation: &str,
    state: &str,
) -> String {
    template
        .replace("{context}", context)
        .replace("{entity}", entity)
        .replace("{relation}", relation)
        .replace("{state}", state)
}

fn render_query_template(template: &str, context: &str, entity: &str, relation: &str) -> String {
    template
        .replace("{context}", context)
        .replace("{entity}", entity)
        .replace("{relation}", relation)
}

#[cfg(test)]
mod tests {
    use super::{
        HELDOUT_SURFACE_ID, PRIMARY_SURFACE_ID, TemplateSurface, TermInventoryView, render_surface,
    };
    use crate::schema::{RenderChoice, SemanticQuartet};
    use fas_frozen_observer_bundle_panel_v04::generate::{OBSERVATION_TEMPLATES, QUERY_TEMPLATES};

    fn terms() -> (Vec<String>, Vec<String>) {
        (
            (0..32).map(|id| format!("ctx{id}")).collect(),
            (0..32).map(|id| format!("ent{id}")).collect(),
        )
    }

    #[test]
    fn primary_renderer_preserves_quartet_variant_semantics_and_input_shape() {
        let (contexts, entities) = terms();
        let term_view = TermInventoryView {
            context_terms: &contexts,
            entity_terms: &entities,
        };
        let surface = TemplateSurface {
            observation_templates: OBSERVATION_TEMPLATES
                .iter()
                .map(|s| (*s).to_owned())
                .collect(),
            query_templates: QUERY_TEMPLATES.iter().map(|s| (*s).to_owned()).collect(),
        };
        let semantic = SemanticQuartet {
            schedule_ordinal: 5,
            track_code: 0,
            context_split: 1,
            entity_split: 0,
            family_id: 2,
            relation_id: 1,
            state_id: 2,
            context_pair_id: 3,
            entity_pair_id: 6,
        };
        let rendered = render_surface(
            &surface,
            &term_view,
            semantic,
            RenderChoice {
                observation_id: 1,
                query_id: 2,
                candidate_order_id: 4,
            },
        )
        .unwrap();
        assert_eq!(rendered.inputs.len(), 4);
        assert_eq!(rendered.context_term_ids, [19, 26, 19, 19]);
        assert_eq!(rendered.entity_term_ids, [6, 6, 13, 6]);
        assert_eq!(rendered.candidate_identity_order, [2, 0, 1]);
        assert_eq!(rendered.exact_target, 0);
        assert!(rendered.inputs[0].contains("Options: tovira, brinok, saldem"));
        assert!(
            rendered.inputs[3].starts_with(
                &surface.observation_templates[5]
                    .replace("{context}", "ctx19")
                    .replace("{entity}", "ent6")
                    .replace("{relation}", "vethaku")
                    .replace("{state}", "tovira")
            )
        );
        assert_eq!(PRIMARY_SURFACE_ID, "PRIMARY_SEEN");
        assert_eq!(HELDOUT_SURFACE_ID, "HELDOUT_TEMPLATE");
    }
}
