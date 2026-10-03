#[derive(Clone, Copy, Debug)]
pub struct CandidateSpec {
    pub suffix: &'static str,
    pub name: &'static str,
    pub description: &'static str,
}

#[derive(Clone, Copy, Debug)]
pub struct FamilySpec {
    pub slug: &'static str,
    pub domain: &'static str,
    pub asset: &'static str,
    pub metric: &'static str,
    pub candidates: [CandidateSpec; 4],
}

const fn candidate(
    suffix: &'static str,
    name: &'static str,
    description: &'static str,
) -> CandidateSpec {
    CandidateSpec {
        suffix,
        name,
        description,
    }
}

pub fn all_families() -> Vec<FamilySpec> {
    vec![
        FamilySpec {
            slug: "power_quality",
            domain: "power quality",
            asset: "electrical circuit",
            metric: "voltage",
            candidates: [
                candidate(
                    "overvoltage",
                    "Overvoltage",
                    "The voltage is above the expected operating range.",
                ),
                candidate(
                    "undervoltage",
                    "Undervoltage",
                    "The voltage is below the expected operating range.",
                ),
                candidate(
                    "frequency_drift",
                    "Frequency drift",
                    "The supply frequency is outside its normal band.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "pressure_control",
            domain: "pressure control",
            asset: "pressure line",
            metric: "pressure",
            candidates: [
                candidate(
                    "overpressure",
                    "Overpressure",
                    "The pressure exceeds the expected operating range.",
                ),
                candidate(
                    "underpressure",
                    "Underpressure",
                    "The pressure falls below the expected operating range.",
                ),
                candidate(
                    "flow_instability",
                    "Flow instability",
                    "The measured flow varies outside its normal pattern.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The pressure measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "thermal_control",
            domain: "thermal control",
            asset: "thermal unit",
            metric: "temperature",
            candidates: [
                candidate(
                    "overheating",
                    "Overheating",
                    "The temperature exceeds the expected operating range.",
                ),
                candidate(
                    "underheating",
                    "Underheating",
                    "The temperature falls below the expected operating range.",
                ),
                candidate(
                    "thermal_cycling",
                    "Thermal cycling",
                    "The temperature repeatedly moves between operating bands.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The temperature measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "flow_management",
            domain: "flow management",
            asset: "process conduit",
            metric: "flow rate",
            candidates: [
                candidate(
                    "excess_flow",
                    "Excess flow",
                    "The flow rate exceeds the expected operating range.",
                ),
                candidate(
                    "insufficient_flow",
                    "Insufficient flow",
                    "The flow rate falls below the expected operating range.",
                ),
                candidate(
                    "flow_pulsation",
                    "Flow pulsation",
                    "The flow varies in a repeated unstable pattern.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The flow measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "inventory_control",
            domain: "inventory control",
            asset: "stock location",
            metric: "inventory level",
            candidates: [
                candidate(
                    "overstock",
                    "Overstock",
                    "The available inventory exceeds the planned range.",
                ),
                candidate(
                    "stockout",
                    "Stockout",
                    "The available inventory falls below the required range.",
                ),
                candidate(
                    "count_drift",
                    "Count drift",
                    "Recorded inventory differs from the physical count.",
                ),
                candidate(
                    "location_mismatch",
                    "Location mismatch",
                    "Inventory is recorded at an unexpected location.",
                ),
            ],
        },
        FamilySpec {
            slug: "dosage_safety",
            domain: "dosage safety",
            asset: "dispensing device",
            metric: "measured dose",
            candidates: [
                candidate(
                    "overdose",
                    "Overdose",
                    "The measured dose exceeds the prescribed amount.",
                ),
                candidate(
                    "underdose",
                    "Underdose",
                    "The measured dose falls below the prescribed amount.",
                ),
                candidate(
                    "delivery_interruption",
                    "Delivery interruption",
                    "The device stopped before completing delivery.",
                ),
                candidate(
                    "measurement_bias",
                    "Measurement bias",
                    "The dose measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "load_management",
            domain: "load management",
            asset: "support assembly",
            metric: "applied load",
            candidates: [
                candidate(
                    "overload",
                    "Overload",
                    "The applied load exceeds the rated operating range.",
                ),
                candidate(
                    "underload",
                    "Underload",
                    "The applied load falls below the expected operating range.",
                ),
                candidate(
                    "load_oscillation",
                    "Load oscillation",
                    "The applied load varies in a repeated unstable pattern.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The load measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "rotational_speed",
            domain: "rotational speed",
            asset: "rotating assembly",
            metric: "rotation speed",
            candidates: [
                candidate(
                    "overspeed",
                    "Overspeed",
                    "The rotation speed exceeds the expected operating range.",
                ),
                candidate(
                    "underspeed",
                    "Underspeed",
                    "The rotation speed falls below the expected operating range.",
                ),
                candidate(
                    "speed_instability",
                    "Speed instability",
                    "The rotation speed varies outside its normal pattern.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The speed measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "torque_control",
            domain: "torque control",
            asset: "drive assembly",
            metric: "drive torque",
            candidates: [
                candidate(
                    "over_torque",
                    "Excess torque",
                    "The drive torque exceeds the expected operating range.",
                ),
                candidate(
                    "under_torque",
                    "Low torque",
                    "The drive torque falls below the expected operating range.",
                ),
                candidate(
                    "torque_ripple",
                    "Torque ripple",
                    "The drive torque has a repeated oscillating component.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The torque measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "humidity_control",
            domain: "humidity control",
            asset: "air handling unit",
            metric: "humidity level",
            candidates: [
                candidate(
                    "excess_humidity",
                    "Excess humidity",
                    "The humidity exceeds the expected operating range.",
                ),
                candidate(
                    "low_humidity",
                    "Low humidity",
                    "The humidity falls below the expected operating range.",
                ),
                candidate(
                    "condensation_cycle",
                    "Condensation cycle",
                    "Moisture repeatedly condenses and clears.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The humidity measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "chemical_concentration",
            domain: "chemical concentration",
            asset: "mixing vessel",
            metric: "concentration",
            candidates: [
                candidate(
                    "high_concentration",
                    "High concentration",
                    "The concentration exceeds the target range.",
                ),
                candidate(
                    "low_concentration",
                    "Low concentration",
                    "The concentration falls below the target range.",
                ),
                candidate(
                    "mixing_gradient",
                    "Mixing gradient",
                    "Concentration differs across the sampled locations.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The concentration measurement has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "liquid_level",
            domain: "liquid level control",
            asset: "storage vessel",
            metric: "liquid level",
            candidates: [
                candidate(
                    "overfill",
                    "Overfill",
                    "The liquid level exceeds the vessel's target range.",
                ),
                candidate(
                    "underfill",
                    "Underfill",
                    "The liquid level falls below the vessel's target range.",
                ),
                candidate(
                    "level_oscillation",
                    "Level oscillation",
                    "The level repeatedly moves between operating bands.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The level measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "salinity_control",
            domain: "salinity control",
            asset: "water sample",
            metric: "salinity",
            candidates: [
                candidate(
                    "high_salinity",
                    "High salinity",
                    "The salinity exceeds the expected operating range.",
                ),
                candidate(
                    "low_salinity",
                    "Low salinity",
                    "The salinity falls below the expected operating range.",
                ),
                candidate(
                    "mineral_imbalance",
                    "Mineral imbalance",
                    "The mineral mixture differs from its expected profile.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The salinity measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "exposure_control",
            domain: "exposure control",
            asset: "imaging station",
            metric: "exposure level",
            candidates: [
                candidate(
                    "overexposure",
                    "Overexposure",
                    "The exposure level exceeds the target range.",
                ),
                candidate(
                    "underexposure",
                    "Underexposure",
                    "The exposure level falls below the target range.",
                ),
                candidate(
                    "contrast_drift",
                    "Contrast drift",
                    "Image contrast differs from the expected profile.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The exposure measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "vibration_monitoring",
            domain: "vibration monitoring",
            asset: "rotating platform",
            metric: "vibration amplitude",
            candidates: [
                candidate(
                    "excess_vibration",
                    "Excess vibration",
                    "The vibration amplitude exceeds the expected range.",
                ),
                candidate(
                    "low_vibration",
                    "Low vibration",
                    "The vibration amplitude falls below the expected range.",
                ),
                candidate(
                    "resonance",
                    "Resonance",
                    "The platform has a frequency-specific oscillation.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The vibration measurement channel has a persistent offset.",
                ),
            ],
        },
        FamilySpec {
            slug: "respiratory_monitoring",
            domain: "respiratory monitoring",
            asset: "breathing monitor",
            metric: "breathing rate",
            candidates: [
                candidate(
                    "rapid_breathing",
                    "Rapid breathing",
                    "The breathing rate exceeds the expected range.",
                ),
                candidate(
                    "slow_breathing",
                    "Slow breathing",
                    "The breathing rate falls below the expected range.",
                ),
                candidate(
                    "irregular_breathing",
                    "Irregular breathing",
                    "Breaths occur with inconsistent timing.",
                ),
                candidate(
                    "sensor_bias",
                    "Sensor bias",
                    "The breathing-rate channel has a persistent offset.",
                ),
            ],
        },
    ]
}

pub const TRAIN_FAMILY_COUNT: usize = 12;
pub const TRAIN_PAIRS_PER_FAMILY: usize = 1_000;
pub const EVAL_PAIRS_PER_FAMILY: usize = 500;
