//! Frozen cross-language certificates from the MQL5 auction golden suite.

use northstar_auction_contract::{AuctionResolution, CensorReason};
use serde::Serialize;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum Direction {
    FromBelow,
    FromAbove,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct DirectionCertificate {
    pub direction: Direction,
    pub ledger_hash: u64,
    pub terminal_hash: u64,
    pub event_id_hash: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct GoldenScenario {
    pub ordinal: u8,
    pub name: &'static str,
    pub event_kinds: &'static str,
    pub resolution: AuctionResolution,
    pub censor_reason: CensorReason,
    pub from_below: DirectionCertificate,
    pub from_above: DirectionCertificate,
}

macro_rules! direction {
    ($direction:ident, $ledger:literal, $terminal:literal, $ids:literal) => {
        DirectionCertificate {
            direction: Direction::$direction,
            ledger_hash: $ledger,
            terminal_hash: $terminal,
            event_id_hash: $ids,
        }
    };
}

macro_rules! scenario {
    ($ordinal:literal, $name:literal, $kinds:literal, $resolution:ident, $censor:ident,
     [$ul:literal, $ut:literal, $ui:literal], [$dl:literal, $dt:literal, $di:literal]) => {
        GoldenScenario {
            ordinal: $ordinal,
            name: $name,
            event_kinds: $kinds,
            resolution: AuctionResolution::$resolution,
            censor_reason: CensorReason::$censor,
            from_below: direction!(FromBelow, $ul, $ut, $ui),
            from_above: direction!(FromAbove, $dl, $dt, $di),
        }
    };
}

pub const GOLDEN_SCENARIOS: &[GoldenScenario; 16] = &[
    scenario!(
        0,
        "APPROACH_NO_CONTACT",
        "APPROACH>CENSOR",
        None,
        TestEnd,
        [
            7083069907504036072,
            7240623425234628329,
            5920646751861704652
        ],
        [
            5100406292250002032,
            2271471525806773903,
            1704758368957475857
        ]
    ),
    scenario!(
        1,
        "CONTACT_REJECTION",
        "APPROACH>CONTACT>REJECTION>DEPARTURE",
        RejectToOrigin,
        None,
        [
            17234920380482589903,
            4255550726003280340,
            10305093563953195233
        ],
        [
            9181384818587435743,
            15840599953404591754,
            701918442754072255
        ]
    ),
    scenario!(
        2,
        "PENETRATION_REJECTION",
        "APPROACH>CONTACT>PENETRATION>REJECTION>DEPARTURE",
        RejectToOrigin,
        None,
        [
            7998763031280463331,
            3981949413412508721,
            7358647779410966262
        ],
        [
            5150527400566364082,
            17921681375142322637,
            4532736161092647748
        ]
    ),
    scenario!(
        3,
        "BREAK_NO_ACCEPTANCE",
        "APPROACH>CONTACT>PENETRATION>BREAK>CENSOR",
        None,
        TestEnd,
        [
            8999996696812602008,
            382921348341376874,
            13378246171143484416
        ],
        [
            1296034520943644563,
            9700630133129727326,
            7911324944616231131
        ]
    ),
    scenario!(
        4,
        "BREAK_RECLAIM",
        "APPROACH>CONTACT>PENETRATION>BREAK>RECLAIM",
        ReclaimAfterBreak,
        None,
        [
            3869186426537818021,
            8274381957972330142,
            18328460970932262857
        ],
        [
            6371835978745044890,
            2952186044566286158,
            11455660104188826580
        ]
    ),
    scenario!(
        5,
        "BREAK_ACCEPTANCE",
        "APPROACH>CONTACT>PENETRATION>BREAK>PROVISIONAL_ACCEPTANCE>ACCEPTANCE>DEPARTURE>CENSOR",
        AcceptThroughNode,
        None,
        [
            15570506635571705216,
            5543345434357033219,
            15004074108227539876
        ],
        [
            15119495069442673042,
            18064756836351036067,
            4496185398138898066
        ]
    ),
    scenario!(
        6,
        "ACCEPTED_RETEST",
        "APPROACH>CONTACT>PENETRATION>BREAK>PROVISIONAL_ACCEPTANCE>ACCEPTANCE>DEPARTURE>APPROACH>RETURN_TO_SOURCE>CONTACT>RETEST>CENSOR",
        None,
        TestEnd,
        [
            1028031337811295880,
            564393878215883356,
            11873359204263253046
        ],
        [
            9239068977316485758,
            7927687496521948414,
            2731330480194682687
        ]
    ),
    scenario!(
        7,
        "RETEST_HOLD",
        "APPROACH>CONTACT>PENETRATION>BREAK>PROVISIONAL_ACCEPTANCE>ACCEPTANCE>DEPARTURE>APPROACH>RETURN_TO_SOURCE>CONTACT>RETEST>HOLD",
        AcceptAndHoldRetest,
        None,
        [
            5384248241672369382,
            2528108811141936918,
            16146631415087033190
        ],
        [
            395324507031466781,
            2490223198596302268,
            16078501192377845712
        ]
    ),
    scenario!(
        8,
        "RETEST_FAILURE",
        "APPROACH>CONTACT>PENETRATION>BREAK>PROVISIONAL_ACCEPTANCE>ACCEPTANCE>DEPARTURE>APPROACH>RETURN_TO_SOURCE>CONTACT>RETEST>PENETRATION>RETEST_FAILURE>RECLAIM",
        AcceptAndFailRetest,
        None,
        [
            16325750041606752666,
            10631684843213046911,
            7101004766598655624
        ],
        [
            9898959940002425269,
            18327088783697664053,
            4292310943116116109
        ]
    ),
    scenario!(
        9,
        "RETURN_SOURCE",
        "APPROACH>CONTACT>PENETRATION>BREAK>PROVISIONAL_ACCEPTANCE>ACCEPTANCE>DEPARTURE>RETURN_TO_SOURCE",
        AcceptThroughNode,
        None,
        [9201460165761740647, 1577608385086293592, 948256575516084411],
        [
            5499461254795119433,
            17585471472416223388,
            3805214455603787998
        ]
    ),
    scenario!(
        10,
        "TRANSIT_ADJACENT",
        "APPROACH>CONTACT>PENETRATION>BREAK>PROVISIONAL_ACCEPTANCE>ACCEPTANCE>DEPARTURE>TRANSIT",
        AcceptThroughNode,
        None,
        [
            12632819863046688287,
            15809581704739409810,
            16873771406178285682
        ],
        [
            5901797956137671279,
            8300214946437105210,
            3861559939113912715
        ]
    ),
    scenario!(
        11,
        "TIMEOUT",
        "APPROACH>EXPIRE",
        Timeout,
        None,
        [
            15569827033252705233,
            12181638427695920177,
            685309674440241029
        ],
        [
            7581232223658989445,
            8350398994520137743,
            14952053851128413588
        ]
    ),
    scenario!(
        12,
        "NODE_RETIREMENT",
        "APPROACH>EXPIRE",
        NodeRetired,
        None,
        [
            15882738534277105299,
            5331655575585107249,
            11694692260249422848
        ],
        [
            7027864189427090271,
            3198328650767607631,
            9598442023567218660
        ]
    ),
    scenario!(
        13,
        "TEST_END_CENSOR",
        "APPROACH>CENSOR",
        None,
        TestEnd,
        [
            7083069907504036072,
            7240623425234628329,
            5920646751861704652
        ],
        [
            5100406292250002032,
            2271471525806773903,
            1704758368957475857
        ]
    ),
    scenario!(
        14,
        "SHUTDOWN_CENSOR",
        "APPROACH>CENSOR",
        None,
        Shutdown,
        [
            6792784554728606836,
            7187534605912059705,
            5920646751861704652
        ],
        [
            5394745968431901060,
            13823697150968723111,
            1704758368957475857
        ]
    ),
    scenario!(
        15,
        "DATA_GAP_CENSOR",
        "APPROACH>CENSOR",
        None,
        DataGap,
        [
            6958003235467834460,
            7534294185060981541,
            5920646751861704652
        ],
        [
            5582755161909489398,
            1977800765980420691,
            1704758368957475857
        ]
    ),
];

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct FixtureReport {
    pub contract: &'static str,
    pub status: &'static str,
    pub scenarios: usize,
    pub directional_certificates: usize,
}

pub fn verify_fixtures() -> Result<FixtureReport, &'static str> {
    for (ordinal, scenario) in GOLDEN_SCENARIOS.iter().enumerate() {
        if usize::from(scenario.ordinal) != ordinal {
            return Err("scenario ordinal drift");
        }
        if scenario.name.is_empty() || scenario.event_kinds.is_empty() {
            return Err("empty scenario identity");
        }
        if scenario.from_below.direction != Direction::FromBelow
            || scenario.from_above.direction != Direction::FromAbove
        {
            return Err("direction certificate drift");
        }
        if [scenario.from_below, scenario.from_above]
            .iter()
            .any(|certificate| {
                certificate.ledger_hash == 0
                    || certificate.terminal_hash == 0
                    || certificate.event_id_hash == 0
            })
        {
            return Err("zero golden hash");
        }
    }
    Ok(FixtureReport {
        contract: "NORTHSTAR_MQL5_GOLDEN_FIXTURES_V1",
        status: "PASS",
        scenarios: GOLDEN_SCENARIOS.len(),
        directional_certificates: GOLDEN_SCENARIOS.len() * 2,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_mql5_certificates_are_frozen() {
        let report = verify_fixtures().unwrap();
        assert_eq!(report.scenarios, 16);
        assert_eq!(report.directional_certificates, 32);
    }

    #[test]
    fn censor_scenarios_preserve_event_ids_but_change_terminal_semantics() {
        let test_end = GOLDEN_SCENARIOS[13];
        let shutdown = GOLDEN_SCENARIOS[14];
        let data_gap = GOLDEN_SCENARIOS[15];
        assert_eq!(
            test_end.from_below.event_id_hash,
            shutdown.from_below.event_id_hash
        );
        assert_eq!(
            shutdown.from_below.event_id_hash,
            data_gap.from_below.event_id_hash
        );
        assert_ne!(
            test_end.from_below.terminal_hash,
            shutdown.from_below.terminal_hash
        );
        assert_ne!(
            shutdown.from_below.terminal_hash,
            data_gap.from_below.terminal_hash
        );
    }
}
