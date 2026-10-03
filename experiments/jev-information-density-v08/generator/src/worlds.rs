use anyhow::{Result, ensure};
use jev_decision_world_v01::{
    Mechanism, ObservationChannel, Variable, VariableKind, VariableRole, WorldTemplate,
};

#[derive(Clone, Copy)]
pub struct Concept {
    pub id: &'static str,
    pub name: &'static str,
    pub definition: &'static str,
}

#[derive(Clone, Copy)]
pub struct FamilySpec {
    pub slug: &'static str,
    pub setting: &'static str,
    pub concepts: [Concept; 4],
}

const fn c(id: &'static str, name: &'static str, definition: &'static str) -> Concept {
    Concept {
        id,
        name,
        definition,
    }
}

const FAMILIES: [FamilySpec; 24] = [
    FamilySpec {
        slug: "payment_settlement",
        setting: "card-payment ledger",
        concepts: [
            c(
                "duplicate_charge",
                "Duplicate charge",
                "One intended purchase produced multiple posted debits.",
            ),
            c(
                "merchant_reversal",
                "Merchant reversal",
                "The merchant reversed or voided the original authorization.",
            ),
            c(
                "currency_conversion",
                "Currency conversion issue",
                "A conversion or settlement rule changed the displayed amount.",
            ),
            c(
                "expected_split",
                "Expected split settlement",
                "The entries are legitimate parts of a split or delayed settlement.",
            ),
        ],
    },
    FamilySpec {
        slug: "fulfillment_delay",
        setting: "shipment-tracking record",
        concepts: [
            c(
                "carrier_delay",
                "Carrier delay",
                "The parcel is delayed while moving through the carrier network.",
            ),
            c(
                "inventory_shortage",
                "Inventory shortage",
                "The order is waiting because the requested item is not available.",
            ),
            c(
                "address_hold",
                "Address verification hold",
                "Delivery is paused until the destination details are verified.",
            ),
            c(
                "normal_transit",
                "Normal transit",
                "The shipment is progressing within its expected delivery window.",
            ),
        ],
    },
    FamilySpec {
        slug: "machine_diagnostics",
        setting: "production-machine service log",
        concepts: [
            c(
                "bearing_wear",
                "Bearing wear",
                "Mechanical wear is increasing friction in a rotating assembly.",
            ),
            c(
                "sensor_drift",
                "Sensor drift",
                "A measurement sensor is reporting a gradually biased value.",
            ),
            c(
                "power_instability",
                "Power instability",
                "Irregular electrical supply is disrupting machine operation.",
            ),
            c(
                "scheduled_service",
                "Scheduled service",
                "A planned maintenance procedure explains the observed pause.",
            ),
        ],
    },
    FamilySpec {
        slug: "document_triage",
        setting: "incoming-document queue",
        concepts: [
            c(
                "invoice_dispute",
                "Invoice discrepancy",
                "A billed amount conflicts with the supporting order or receipt.",
            ),
            c(
                "contract_renewal",
                "Contract renewal",
                "The document requests continuation or amendment of an existing agreement.",
            ),
            c(
                "privacy_request",
                "Privacy request",
                "The sender requests access, correction, deletion, or export of personal data.",
            ),
            c(
                "routine_notice",
                "Routine notice",
                "The document provides information without requesting an exceptional action.",
            ),
        ],
    },
    FamilySpec {
        slug: "network_operations",
        setting: "service-network incident record",
        concepts: [
            c(
                "name_resolution_failure",
                "Name-resolution failure",
                "Clients cannot resolve a service name to a reachable endpoint.",
            ),
            c(
                "route_misconfiguration",
                "Route misconfiguration",
                "An incorrect routing rule sends traffic along an invalid path.",
            ),
            c(
                "capacity_outage",
                "Capacity outage",
                "Available service capacity is insufficient for the current demand.",
            ),
            c(
                "planned_network_change",
                "Planned network change",
                "An authorized network change explains the temporary disruption.",
            ),
        ],
    },
    FamilySpec {
        slug: "warehouse_accuracy",
        setting: "warehouse inventory record",
        concepts: [
            c(
                "pick_error",
                "Pick error",
                "The picked item or quantity differs from the order instruction.",
            ),
            c(
                "cycle_count_mismatch",
                "Cycle-count mismatch",
                "The recorded stock count differs from the physical count.",
            ),
            c(
                "replenishment_delay",
                "Replenishment delay",
                "Expected stock has not yet arrived from the replenishment source.",
            ),
            c(
                "valid_backorder",
                "Valid backorder",
                "The order is intentionally waiting for a known future stock receipt.",
            ),
        ],
    },
    FamilySpec {
        slug: "energy_control",
        setting: "distributed-energy control log",
        concepts: [
            c(
                "inverter_fault",
                "Inverter fault",
                "An inverter fault prevents expected conversion or delivery of power.",
            ),
            c(
                "grid_curtailment",
                "Grid curtailment",
                "An external grid instruction limits the amount of power delivered.",
            ),
            c(
                "load_spike",
                "Unexpected load spike",
                "Demand rose sharply beyond the expected operating profile.",
            ),
            c(
                "normal_dispatch",
                "Normal dispatch",
                "The controller is following the expected operating schedule.",
            ),
        ],
    },
    FamilySpec {
        slug: "lab_quality",
        setting: "laboratory quality-control record",
        concepts: [
            c(
                "sample_contamination",
                "Sample contamination",
                "Material from outside the intended sample affected the result.",
            ),
            c(
                "instrument_calibration",
                "Calibration error",
                "The instrument calibration is outside its accepted reference range.",
            ),
            c(
                "sample_mixup",
                "Sample mix-up",
                "The result is associated with a different sample than the intended one.",
            ),
            c(
                "expected_variation",
                "Expected variation",
                "The measurement falls within the established variation range.",
            ),
        ],
    },
    FamilySpec {
        slug: "fleet_dispatch",
        setting: "fleet-dispatch event log",
        concepts: [
            c(
                "vehicle_breakdown",
                "Vehicle breakdown",
                "A vehicle fault prevents the assigned trip from proceeding.",
            ),
            c(
                "route_congestion",
                "Route congestion",
                "Traffic conditions are delaying an otherwise valid route.",
            ),
            c(
                "missed_pickup",
                "Missed pickup",
                "The scheduled pickup did not occur at the assigned time or location.",
            ),
            c(
                "planned_reassignment",
                "Planned reassignment",
                "Dispatch deliberately moved the work to another vehicle or route.",
            ),
        ],
    },
    FamilySpec {
        slug: "compliance_screening",
        setting: "compliance-screening case",
        concepts: [
            c(
                "sanctions_match",
                "Potential sanctions match",
                "Identifying details may match a restricted-party record.",
            ),
            c(
                "name_false_positive",
                "Name-match false positive",
                "A superficial name match is contradicted by identifying details.",
            ),
            c(
                "missing_documentation",
                "Missing documentation",
                "Required evidence is absent or has not been supplied.",
            ),
            c(
                "cleared_case",
                "Cleared case",
                "Available checks do not support a compliance concern.",
            ),
        ],
    },
    FamilySpec {
        slug: "data_pipeline",
        setting: "data-pipeline run record",
        concepts: [
            c(
                "schema_drift",
                "Schema drift",
                "An upstream field or type changed incompatibly with the consumer.",
            ),
            c(
                "late_source_data",
                "Late source data",
                "An expected input arrived after the processing deadline.",
            ),
            c(
                "duplicate_ingestion",
                "Duplicate ingestion",
                "The same source records were processed more than once.",
            ),
            c(
                "expected_backfill",
                "Expected backfill",
                "A planned historical load explains the additional processing.",
            ),
        ],
    },
    FamilySpec {
        slug: "manufacturing_inspection",
        setting: "manufacturing inspection report",
        concepts: [
            c(
                "material_defect",
                "Material defect",
                "The inspected item has a physical defect in its material or finish.",
            ),
            c(
                "process_deviation",
                "Process deviation",
                "Production departed from a required process setting or sequence.",
            ),
            c(
                "measurement_artifact",
                "Measurement artifact",
                "The reported deviation is caused by the measurement procedure.",
            ),
            c(
                "conforming_batch",
                "Conforming batch",
                "The inspected output meets the declared acceptance criteria.",
            ),
        ],
    },
    FamilySpec {
        slug: "calendar_scheduling",
        setting: "shared-resource schedule",
        concepts: [
            c(
                "resource_conflict",
                "Resource conflict",
                "Two valid requests require the same unavailable resource.",
            ),
            c(
                "dependency_delay",
                "Dependency delay",
                "The task is waiting for a prerequisite to complete.",
            ),
            c(
                "stale_calendar",
                "Stale calendar state",
                "The displayed schedule does not reflect the latest accepted update.",
            ),
            c(
                "valid_reschedule",
                "Valid reschedule",
                "The timing changed through an accepted rescheduling action.",
            ),
        ],
    },
    FamilySpec {
        slug: "identity_proofing",
        setting: "identity-verification case",
        concepts: [
            c(
                "synthetic_identity",
                "Synthetic identity",
                "The identity record combines details that do not belong to one person.",
            ),
            c(
                "legitimate_name_variance",
                "Legitimate name variance",
                "A documented name variation explains the apparent mismatch.",
            ),
            c(
                "stale_source_record",
                "Stale source record",
                "An authoritative source has not yet reflected a recent update.",
            ),
            c(
                "credential_recovery",
                "Credential recovery",
                "The user is completing an expected account-recovery process.",
            ),
        ],
    },
    FamilySpec {
        slug: "procurement_review",
        setting: "procurement matching record",
        concepts: [
            c(
                "duplicate_invoice",
                "Duplicate invoice",
                "The same supplier obligation appears to have been billed twice.",
            ),
            c(
                "receiving_mismatch",
                "Receiving mismatch",
                "The recorded delivery differs from the purchase or receipt record.",
            ),
            c(
                "price_variance",
                "Price variance",
                "The invoiced price differs from the accepted purchase terms.",
            ),
            c(
                "valid_split_order",
                "Valid split order",
                "The supplier used multiple entries allowed by the order terms.",
            ),
        ],
    },
    FamilySpec {
        slug: "building_climate",
        setting: "building climate-control log",
        concepts: [
            c(
                "sensor_failure",
                "Sensor failure",
                "A faulty sensor is reporting an implausible environmental reading.",
            ),
            c(
                "actuator_stuck",
                "Actuator stuck",
                "A valve or damper is not following its control command.",
            ),
            c(
                "external_weather_shift",
                "External weather shift",
                "A change in outdoor conditions altered the expected load.",
            ),
            c(
                "scheduled_setback",
                "Scheduled setback",
                "The controller applied a planned unoccupied-period setting.",
            ),
        ],
    },
    FamilySpec {
        slug: "transit_connection",
        setting: "passenger itinerary record",
        concepts: [
            c(
                "missed_connection",
                "Missed connection",
                "The first leg arrived too late for the next scheduled departure.",
            ),
            c(
                "schedule_revision",
                "Schedule revision",
                "An operator changed the published service time or route.",
            ),
            c(
                "boarding_hold",
                "Boarding hold",
                "Boarding is delayed while a required operational check is completed.",
            ),
            c(
                "expected_transfer",
                "Expected transfer",
                "The itinerary includes a planned transfer within its normal allowance.",
            ),
        ],
    },
    FamilySpec {
        slug: "marketplace_review",
        setting: "marketplace transaction record",
        concepts: [
            c(
                "account_takeover",
                "Account takeover",
                "An unauthorized party appears to be controlling a valid account.",
            ),
            c(
                "seller_collusion",
                "Seller collusion",
                "Related sellers appear to coordinate activity to distort outcomes.",
            ),
            c(
                "shipping_dispute",
                "Shipping dispute",
                "The buyer and seller provide conflicting delivery evidence.",
            ),
            c(
                "legitimate_refund",
                "Legitimate refund",
                "The refund follows a documented and authorized return.",
            ),
        ],
    },
    FamilySpec {
        slug: "cloud_capacity",
        setting: "cloud-service deployment record",
        concepts: [
            c(
                "capacity_saturation",
                "Capacity saturation",
                "Demand has reached the available compute or storage limit.",
            ),
            c(
                "quota_exhaustion",
                "Quota exhaustion",
                "A configured account or project quota blocks the requested operation.",
            ),
            c(
                "release_regression",
                "Release regression",
                "A recent software release introduced the observed service failure.",
            ),
            c(
                "normal_deployment",
                "Normal deployment",
                "The service change is part of an expected deployment process.",
            ),
        ],
    },
    FamilySpec {
        slug: "irrigation_control",
        setting: "irrigation-control record",
        concepts: [
            c(
                "valve_failure",
                "Valve failure",
                "A valve failed to open, close, or regulate the commanded flow.",
            ),
            c(
                "sensor_miscalibration",
                "Sensor miscalibration",
                "A moisture or flow sensor reports a biased measurement.",
            ),
            c(
                "water_supply_limit",
                "Water-supply limit",
                "An external supply restriction limits the available flow.",
            ),
            c(
                "scheduled_watering",
                "Scheduled watering",
                "The observed flow matches a planned irrigation cycle.",
            ),
        ],
    },
    FamilySpec {
        slug: "access_review",
        setting: "workforce access-review log",
        concepts: [
            c(
                "token_replay",
                "Token replay",
                "A valid access token appears to have been reused from an unauthorized context.",
            ),
            c(
                "expired_credential",
                "Expired credential",
                "The presented credential is no longer valid under its lifetime policy.",
            ),
            c(
                "role_misassignment",
                "Role misassignment",
                "The account has permissions inconsistent with its approved role.",
            ),
            c(
                "expected_automation",
                "Expected automation",
                "A registered service account performed its scheduled operation.",
            ),
        ],
    },
    FamilySpec {
        slug: "quality_returns",
        setting: "product-return inspection record",
        concepts: [
            c(
                "assembly_defect",
                "Assembly defect",
                "The product was assembled with a missing or incorrectly fitted component.",
            ),
            c(
                "transit_damage",
                "Transit damage",
                "The item was damaged while being handled or transported.",
            ),
            c(
                "user_configuration",
                "User configuration issue",
                "The product is functioning but is configured contrary to the instructions.",
            ),
            c(
                "no_fault_found",
                "No fault found",
                "Inspection did not reproduce a product defect or handling issue.",
            ),
        ],
    },
    FamilySpec {
        slug: "research_instrument",
        setting: "research-instrument run log",
        concepts: [
            c(
                "reagent_degradation",
                "Reagent degradation",
                "A reagent lost activity before or during the measurement run.",
            ),
            c(
                "thermal_instability",
                "Thermal instability",
                "Temperature variation affected the instrument or specimen.",
            ),
            c(
                "protocol_deviation",
                "Protocol deviation",
                "The run departed from a specified experimental procedure.",
            ),
            c(
                "expected_noise",
                "Expected measurement noise",
                "The observed variation is consistent with the known noise range.",
            ),
        ],
    },
    FamilySpec {
        slug: "service_routing",
        setting: "customer-service request queue",
        concepts: [
            c(
                "account_access",
                "Account access request",
                "The customer needs help signing in or restoring account access.",
            ),
            c(
                "billing_correction",
                "Billing correction",
                "The customer is asking to correct a charge or account balance.",
            ),
            c(
                "technical_fault",
                "Technical fault",
                "A product or service is not operating as expected.",
            ),
            c(
                "information_request",
                "Information request",
                "The customer seeks information without reporting a fault or dispute.",
            ),
        ],
    },
];

#[derive(Clone, Copy, Debug)]
pub enum Topology {
    DirectCauses,
    MediatedChain,
    EvidenceCollider,
    CompetingPathways,
}

impl Topology {
    pub fn all() -> [Self; 4] {
        [
            Self::DirectCauses,
            Self::MediatedChain,
            Self::EvidenceCollider,
            Self::CompetingPathways,
        ]
    }

    pub fn id(self) -> &'static str {
        match self {
            Self::DirectCauses => "direct_causes",
            Self::MediatedChain => "mediated_chain",
            Self::EvidenceCollider => "evidence_collider",
            Self::CompetingPathways => "competing_pathways",
        }
    }
}

pub fn family_count() -> usize {
    FAMILIES.len()
}

pub fn family(index: usize) -> &'static FamilySpec {
    &FAMILIES[index % FAMILIES.len()]
}

pub fn build_template(
    family_index: usize,
    topology: Topology,
    parameterization: usize,
) -> Result<WorldTemplate> {
    let spec = family(family_index);
    let root_domain: Vec<String> = spec
        .concepts
        .iter()
        .map(|concept| concept.id.to_string())
        .collect();
    let mut variables = vec![
        variable(
            "root_cause",
            VariableRole::Latent,
            VariableKind::Categorical,
            root_domain.clone(),
            false,
        ),
        variable(
            "severity",
            VariableRole::DecisionRelevant,
            VariableKind::Ordinal,
            (1..=5).map(|value| value.to_string()).collect(),
            true,
        ),
    ];
    let mut mechanisms = Vec::new();
    let prior = root_prior(family_index, parameterization);
    mechanisms.push(Mechanism {
        target: "root_cause".to_string(),
        parents: vec![],
        table: prior,
    });
    mechanisms.push(severity_mechanism(family_index, parameterization));

    let factor_names = match topology {
        Topology::DirectCauses => Vec::new(),
        Topology::MediatedChain => vec!["mediator"],
        Topology::EvidenceCollider => vec!["background_factor"],
        Topology::CompetingPathways => vec!["path_a", "path_b"],
    };
    for name in &factor_names {
        variables.push(variable(
            name,
            VariableRole::Latent,
            VariableKind::Boolean,
            vec!["false".to_string(), "true".to_string()],
            false,
        ));
    }
    for name in &factor_names {
        if *name == "background_factor" {
            let high = 0.25 + 0.1 * (parameterization % 3) as f64;
            mechanisms.push(Mechanism {
                target: (*name).to_string(),
                parents: vec![],
                table: vec![1.0 - high, high],
            });
        } else {
            let p = (0..root_domain.len())
                .map(|cause| {
                    factor_probability(family_index, parameterization, cause, name_index(name))
                })
                .collect::<Vec<_>>();
            mechanisms.push(bernoulli_mechanism(
                (*name).to_string(),
                vec!["root_cause".to_string()],
                &variables,
                |parents| p[parents[0]],
            ));
        }
    }

    for signal in 0..4 {
        let signal_name = format!("signal_{signal}");
        variables.push(variable(
            &signal_name,
            VariableRole::Observable,
            VariableKind::Boolean,
            vec!["false".to_string(), "true".to_string()],
            false,
        ));
        let parents = signal_parents(topology, signal);
        let mechanism =
            bernoulli_mechanism(signal_name.clone(), parents.clone(), &variables, |values| {
                signal_probability(family_index, parameterization, signal, &parents, values)
            });
        mechanisms.push(mechanism);
    }

    let observation_channels = (0..4)
        .map(|signal| {
            let false_positive =
                0.015 + 0.015 * ((family_index + signal + parameterization) % 4) as f64;
            let false_negative =
                0.025 + 0.02 * ((family_index * 2 + signal + parameterization) % 4) as f64;
            ObservationChannel {
                id: format!("signal_{signal}_sensor"),
                source_variable: format!("signal_{signal}"),
                observed_domain: vec!["false".to_string(), "true".to_string()],
                likelihood_table: vec![
                    1.0 - false_positive,
                    false_positive,
                    false_negative,
                    1.0 - false_negative,
                ],
                default_visibility_probability: 1.0,
            }
        })
        .collect();

    let template = WorldTemplate {
        family_id: "system_diagnosis".to_string(),
        template_id: format!(
            "jev-v08-{}-{}-p{}",
            spec.slug,
            topology.id(),
            parameterization
        ),
        version: 8,
        variables,
        mechanisms,
        constraints: Vec::new(),
        observation_channels,
        derived_variables: Vec::new(),
    };
    ensure!(
        template.variables.len() <= 10,
        "v0.8 world exceeds exact-enumeration cap"
    );
    Ok(template)
}

fn variable(
    id: &str,
    role: VariableRole,
    kind: VariableKind,
    domain: Vec<String>,
    ordered: bool,
) -> Variable {
    Variable {
        id: id.to_string(),
        role,
        kind,
        domain,
        ordered,
    }
}

fn root_prior(family_index: usize, parameterization: usize) -> Vec<f64> {
    let preferred = (family_index + parameterization * 3) % 4;
    let mut weights: Vec<f64> = (0..4)
        .map(|value| {
            let distance = (value + 4 - preferred) % 4;
            [1.0, 0.68, 0.43, 0.31][distance]
        })
        .collect();
    let divisor: f64 = weights.iter().sum();
    for value in &mut weights {
        *value /= divisor;
    }
    weights
}

fn severity_mechanism(family_index: usize, parameterization: usize) -> Mechanism {
    let mut table = Vec::with_capacity(20);
    for cause in 0..4 {
        let center = 1 + ((family_index + cause * 2 + parameterization) % 5);
        let temperature = 0.8 + (parameterization % 4) as f64 * 0.25;
        let mut row: Vec<f64> = (1..=5)
            .map(|score| {
                let distance = (score as i32 - center as i32).unsigned_abs() as f64;
                (-distance / temperature).exp()
            })
            .collect();
        let sum: f64 = row.iter().sum();
        for probability in &mut row {
            *probability /= sum;
        }
        table.extend(row);
    }
    Mechanism {
        target: "severity".to_string(),
        parents: vec!["root_cause".to_string()],
        table,
    }
}

fn signal_parents(topology: Topology, signal: usize) -> Vec<String> {
    match topology {
        Topology::DirectCauses => vec!["root_cause".to_string()],
        Topology::MediatedChain if signal == 0 => vec!["root_cause".to_string()],
        Topology::MediatedChain => vec!["mediator".to_string()],
        Topology::EvidenceCollider if signal < 3 => vec!["root_cause".to_string()],
        Topology::EvidenceCollider => {
            vec!["root_cause".to_string(), "background_factor".to_string()]
        }
        Topology::CompetingPathways if signal < 2 => vec!["path_a".to_string()],
        Topology::CompetingPathways if signal == 2 => vec!["path_b".to_string()],
        Topology::CompetingPathways => vec!["path_a".to_string(), "path_b".to_string()],
    }
}

fn bernoulli_mechanism<F>(
    target: String,
    parents: Vec<String>,
    variables: &[Variable],
    mut p_true: F,
) -> Mechanism
where
    F: FnMut(&[usize]) -> f64,
{
    let mut count = 1_usize;
    let mut widths = Vec::with_capacity(parents.len());
    for parent in &parents {
        let width = variables
            .iter()
            .find(|variable| variable.id == *parent)
            .expect("parent variable")
            .domain
            .len();
        widths.push(width);
        count *= width;
    }
    let mut table = Vec::with_capacity(count * 2);
    let mut values = vec![0usize; parents.len()];
    for row in 0..count {
        let mut remainder = row;
        for index in (0..parents.len()).rev() {
            values[index] = remainder % widths[index];
            remainder /= widths[index];
        }
        let p = p_true(&values).clamp(0.02, 0.98);
        table.extend([1.0 - p, p]);
    }
    Mechanism {
        target,
        parents,
        table,
    }
}

fn factor_probability(family: usize, parameter: usize, cause: usize, factor: usize) -> f64 {
    let phase = (family + cause * 3 + factor * 2 + parameter) % 4;
    [0.12, 0.31, 0.66, 0.87][phase]
}

fn name_index(name: &str) -> usize {
    match name {
        "mediator" => 1,
        "path_a" => 2,
        "path_b" => 3,
        _ => 0,
    }
}

fn signal_probability(
    family: usize,
    parameter: usize,
    signal: usize,
    parents: &[String],
    values: &[usize],
) -> f64 {
    let strength = [0.58, 0.72, 0.84, 0.94][parameter % 4];
    let root_index = parents.iter().position(|parent| parent == "root_cause");
    let root_affinity = root_index.map(|index| {
        let phase = (values[index] * 3 + signal * 2 + family) % 4;
        [0.82, 0.61, 0.34, 0.16][phase]
    });
    let factor_positions: Vec<usize> = parents
        .iter()
        .enumerate()
        .filter_map(|(index, parent)| (parent != "root_cause").then_some(index))
        .collect();
    match (root_affinity, factor_positions.as_slice()) {
        (Some(root), []) => 0.06 + root * strength,
        (Some(root), [factor]) => {
            let factor_signal = if values[*factor] == 1 { 0.78 } else { 0.14 };
            0.06 + (0.62 * root + 0.38 * factor_signal) * strength
        }
        (None, [factor]) => {
            if values[*factor] == 1 {
                0.79
            } else {
                0.13
            }
        }
        (None, [left, right]) => {
            let active = (values[*left] + values[*right]) as f64;
            0.08 + active * 0.34
        }
        _ => 0.35,
    }
}

pub fn signal_phrase(spec: &FamilySpec, signal: usize, observed_true: bool) -> String {
    const CUES: [&str; 4] = [
        "an unexpected repeat in the record",
        "a mismatch between recorded status fields",
        "an unusual timing pattern",
        "an independent monitoring alert",
    ];
    if observed_true {
        format!("The {} shows {}.", spec.setting, CUES[signal % CUES.len()])
    } else {
        format!(
            "No {} is visible in the {}.",
            CUES[signal % CUES.len()],
            spec.setting
        )
    }
}

pub fn definition(spec: &FamilySpec, candidate: usize, variant: usize) -> String {
    let base = spec.concepts[candidate].definition;
    match variant % 4 {
        0 => base.to_string(),
        1 => format!("Interpret this pattern as follows: {base}"),
        2 => format!("Category description: {base}"),
        _ => format!("Operational meaning: {base}"),
    }
}
