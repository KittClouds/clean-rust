use crate::types::{
    Mechanism, ObservationChannel, Variable, VariableKind, VariableRole, WorldTemplate,
};

const FALSE: &str = "false";
const TRUE: &str = "true";

pub fn all_templates() -> Vec<WorldTemplate> {
    vec![system_diagnosis(), support_routing(), network_incident()]
}

pub fn template_by_id(id: &str) -> Option<WorldTemplate> {
    all_templates()
        .into_iter()
        .find(|template| template.template_id == id)
}

fn system_diagnosis() -> WorldTemplate {
    let root = categorical(
        "root_cause",
        VariableRole::Latent,
        &[
            "credential_compromise",
            "maintenance",
            "hardware_failure",
            "benign_activity",
        ],
        false,
    );
    let severity = categorical(
        "severity",
        VariableRole::DecisionRelevant,
        &["1", "2", "3", "4", "5"],
        true,
    );
    let nuisance = categorical(
        "device_color",
        VariableRole::Nuisance,
        &["black", "silver", "blue"],
        false,
    );
    let evidence = [
        binary("unseen_device", VariableRole::Observable),
        binary("change_ticket", VariableRole::Observable),
        binary("auth_failure_burst", VariableRole::Observable),
        binary("service_degradation", VariableRole::Observable),
    ];
    let variables = std::iter::once(root)
        .chain(std::iter::once(severity))
        .chain(std::iter::once(nuisance))
        .chain(evidence)
        .collect();
    let mechanisms = vec![
        prior("root_cause", &[0.15, 0.25, 0.25, 0.35]),
        conditional(
            "severity",
            "root_cause",
            &[
                &[0.42, 0.30, 0.18, 0.08, 0.02],
                &[0.05, 0.18, 0.37, 0.30, 0.10],
                &[0.08, 0.27, 0.38, 0.22, 0.05],
                &[0.40, 0.34, 0.18, 0.06, 0.02],
            ],
        ),
        prior("device_color", &[0.52, 0.33, 0.15]),
        conditional_bernoulli("unseen_device", "root_cause", &[0.85, 0.15, 0.05, 0.20]),
        conditional_bernoulli("change_ticket", "root_cause", &[0.10, 0.90, 0.15, 0.20]),
        conditional_bernoulli(
            "auth_failure_burst",
            "root_cause",
            &[0.75, 0.20, 0.10, 0.15],
        ),
        conditional_bernoulli(
            "service_degradation",
            "root_cause",
            &[0.25, 0.45, 0.75, 0.05],
        ),
    ];
    WorldTemplate {
        family_id: "system_diagnosis".to_string(),
        template_id: "system_diagnosis_v1".to_string(),
        version: 1,
        variables,
        mechanisms,
        constraints: Vec::new(),
        observation_channels: standard_binary_channels(&[
            "unseen_device",
            "change_ticket",
            "auth_failure_burst",
            "service_degradation",
        ]),
        derived_variables: Vec::new(),
    }
}

fn support_routing() -> WorldTemplate {
    let route = categorical(
        "route",
        VariableRole::Latent,
        &["account_access", "billing", "security", "technical"],
        false,
    );
    let severity = categorical(
        "severity",
        VariableRole::DecisionRelevant,
        &["1", "2", "3", "4", "5"],
        true,
    );
    let region = categorical(
        "customer_region",
        VariableRole::Nuisance,
        &["americas", "emea", "apac"],
        false,
    );
    let evidence = [
        binary("account_locked", VariableRole::Observable),
        binary("payment_issue", VariableRole::Observable),
        binary("security_alert", VariableRole::Observable),
        binary("product_failure", VariableRole::Observable),
    ];
    let variables = std::iter::once(route)
        .chain(std::iter::once(severity))
        .chain(std::iter::once(region))
        .chain(evidence)
        .collect();
    let mechanisms = vec![
        prior("route", &[0.30, 0.25, 0.15, 0.30]),
        conditional(
            "severity",
            "route",
            &[
                &[0.30, 0.35, 0.22, 0.10, 0.03],
                &[0.45, 0.30, 0.16, 0.07, 0.02],
                &[0.05, 0.12, 0.25, 0.36, 0.22],
                &[0.16, 0.25, 0.32, 0.20, 0.07],
            ],
        ),
        prior("customer_region", &[0.45, 0.35, 0.20]),
        conditional_bernoulli("account_locked", "route", &[0.82, 0.08, 0.18, 0.20]),
        conditional_bernoulli("payment_issue", "route", &[0.12, 0.86, 0.10, 0.08]),
        conditional_bernoulli("security_alert", "route", &[0.10, 0.06, 0.88, 0.12]),
        conditional_bernoulli("product_failure", "route", &[0.12, 0.15, 0.10, 0.84]),
    ];
    WorldTemplate {
        family_id: "support_routing".to_string(),
        template_id: "support_routing_v1".to_string(),
        version: 1,
        variables,
        mechanisms,
        constraints: Vec::new(),
        observation_channels: standard_binary_channels(&[
            "account_locked",
            "payment_issue",
            "security_alert",
            "product_failure",
        ]),
        derived_variables: Vec::new(),
    }
}

fn network_incident() -> WorldTemplate {
    let incident = categorical(
        "incident_type",
        VariableRole::Latent,
        &["compromise", "misconfiguration", "outage", "benign"],
        false,
    );
    let impact = categorical(
        "impact",
        VariableRole::DecisionRelevant,
        &["1", "2", "3", "4", "5"],
        true,
    );
    let region = categorical(
        "server_region",
        VariableRole::Nuisance,
        &["east", "central", "west"],
        false,
    );
    let evidence = [
        binary("unseen_device", VariableRole::Observable),
        binary("auth_burst", VariableRole::Observable),
        binary("service_degradation", VariableRole::Observable),
        binary("maintenance_window", VariableRole::Observable),
    ];
    let variables = std::iter::once(incident)
        .chain(std::iter::once(impact))
        .chain(std::iter::once(region))
        .chain(evidence)
        .collect();
    let mechanisms = vec![
        prior("incident_type", &[0.20, 0.25, 0.30, 0.25]),
        conditional(
            "impact",
            "incident_type",
            &[
                &[0.04, 0.12, 0.24, 0.36, 0.24],
                &[0.18, 0.35, 0.30, 0.13, 0.04],
                &[0.05, 0.20, 0.35, 0.28, 0.12],
                &[0.56, 0.28, 0.11, 0.04, 0.01],
            ],
        ),
        prior("server_region", &[0.40, 0.35, 0.25]),
        conditional_bernoulli("unseen_device", "incident_type", &[0.80, 0.20, 0.10, 0.12]),
        conditional_bernoulli("auth_burst", "incident_type", &[0.82, 0.18, 0.12, 0.10]),
        conditional_bernoulli(
            "service_degradation",
            "incident_type",
            &[0.30, 0.55, 0.90, 0.08],
        ),
        conditional_bernoulli(
            "maintenance_window",
            "incident_type",
            &[0.08, 0.65, 0.15, 0.12],
        ),
    ];
    WorldTemplate {
        family_id: "network_incident".to_string(),
        template_id: "network_incident_v1".to_string(),
        version: 1,
        variables,
        mechanisms,
        constraints: Vec::new(),
        observation_channels: standard_binary_channels(&[
            "unseen_device",
            "auth_burst",
            "service_degradation",
            "maintenance_window",
        ]),
        derived_variables: Vec::new(),
    }
}

fn binary(id: &str, role: VariableRole) -> Variable {
    categorical(id, role, &[FALSE, TRUE], false)
}

fn categorical(id: &str, role: VariableRole, domain: &[&str], ordered: bool) -> Variable {
    Variable {
        id: id.to_string(),
        role,
        kind: if domain == [FALSE, TRUE] {
            VariableKind::Boolean
        } else if ordered {
            VariableKind::Ordinal
        } else {
            VariableKind::Categorical
        },
        domain: domain.iter().map(|value| (*value).to_string()).collect(),
        ordered,
    }
}

fn prior(target: &str, probabilities: &[f64]) -> Mechanism {
    Mechanism {
        target: target.to_string(),
        parents: Vec::new(),
        table: probabilities.to_vec(),
    }
}

fn conditional(target: &str, parent: &str, rows: &[&[f64]]) -> Mechanism {
    Mechanism {
        target: target.to_string(),
        parents: vec![parent.to_string()],
        table: rows.iter().flat_map(|row| row.iter().copied()).collect(),
    }
}

fn conditional_bernoulli(target: &str, parent: &str, p_true: &[f64]) -> Mechanism {
    Mechanism {
        target: target.to_string(),
        parents: vec![parent.to_string()],
        table: p_true
            .iter()
            .flat_map(|probability| [1.0 - probability, *probability])
            .collect(),
    }
}

fn standard_binary_channels(ids: &[&str]) -> Vec<ObservationChannel> {
    ids.iter()
        .map(|id| ObservationChannel {
            id: format!("{id}_sensor"),
            source_variable: (*id).to_string(),
            observed_domain: vec![FALSE.to_string(), TRUE.to_string()],
            likelihood_table: vec![0.97, 0.03, 0.05, 0.95],
            default_visibility_probability: 0.80,
        })
        .collect()
}
