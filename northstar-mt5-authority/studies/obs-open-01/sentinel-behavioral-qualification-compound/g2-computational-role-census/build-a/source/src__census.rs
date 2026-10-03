use crate::graph::{carry_ledger, collision_registry, dependency_graph, qualify, typed_findings};
use crate::model::{DependencyGraph, ElementRole};
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Serialize)]
pub struct CensusProducts {
    pub elements: Vec<ElementRole>,
    pub graph: DependencyGraph,
    pub carry_ledger: Value,
    pub collisions: Value,
    pub qualification: Value,
    pub typed_findings: Value,
}

pub fn execute() -> Result<CensusProducts, String> {
    let mut elements = crate::registry::element_census();
    for element in &mut elements {
        element.multi_role_collision = crate::graph::axis_count(&element.roles) > 1;
    }
    let graph = dependency_graph(&elements)?;
    let qualification = qualify(&elements, &graph)?;
    let collisions = collision_registry(&elements);
    let carry_ledger = carry_ledger(&elements);
    let typed_findings = typed_findings(&elements, &graph);
    Ok(CensusProducts {
        elements,
        graph,
        carry_ledger,
        collisions,
        qualification,
        typed_findings,
    })
}
