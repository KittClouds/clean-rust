use serde::{Deserialize, Serialize};

use super::DocumentSemanticArgument;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentSemanticFrame {
    pub frame: String,
    pub family: String,
    pub target: String,
    pub lexical_unit: String,
    pub definition: String,
    pub source: String,
    pub confidence_millis: u16,
    pub expected_roles: Vec<String>,
    pub matched_roles: Vec<String>,
    pub missing_roles: Vec<String>,
    pub reasons: Vec<String>,
    pub failure_reasons: Vec<String>,
}

#[derive(Clone, Copy, Debug)]
struct FrameDefinition {
    frame: &'static str,
    family: &'static str,
    definition: &'static str,
    expected_roles: &'static [&'static str],
    ambiguous: bool,
}

const ACTOR_THEME: &[&str] = &["actor", "theme"];
const ACTOR_THEME_RECIPIENT: &[&str] = &["actor", "theme", "recipient"];
const ACTOR_THEME_DESTINATION: &[&str] = &["actor", "theme", "destination"];
const ACTOR_GOAL: &[&str] = &["actor", "destination"];
const COMMUNICATION_ROLES: &[&str] = &["actor", "theme", "recipient"];
const CAUSATION_ROLES: &[&str] = &["cause", "theme"];
const PERCEPTION_ROLES: &[&str] = &["experiencer", "theme"];
const DECISION_ROLES: &[&str] = &["actor", "theme"];
const STATE_ROLES: &[&str] = &["bearer", "theme"];
const IDENTITY_ROLES: &[&str] = &["bearer", "theme"];

pub(super) fn classify_frame(
    predicate: &str,
    relation_type: &str,
    arguments: &[DocumentSemanticArgument],
) -> DocumentSemanticFrame {
    let target = predicate.to_ascii_lowercase();
    let (definition, source, mut reasons) = lexical_frame_definition(target.as_str())
        .map(|definition| {
            (
                definition,
                "lexical_table",
                vec!["lexical_unit_match".to_owned()],
            )
        })
        .or_else(|| {
            relation_type_frame_definition(relation_type).map(|definition| {
                (
                    definition,
                    "relation_type_rule",
                    vec![
                        "lexical_unit_unmatched".to_owned(),
                        "relation_type_fallback".to_owned(),
                    ],
                )
            })
        })
        .or_else(|| {
            role_pattern_frame_definition(arguments).map(|definition| {
                (
                    definition,
                    "role_pattern_rule",
                    vec![
                        "lexical_unit_unmatched".to_owned(),
                        "role_pattern_fallback".to_owned(),
                    ],
                )
            })
        })
        .unwrap_or((
            FrameDefinition {
                frame: "unclassified",
                family: "unknown",
                definition:
                    "No stable frame could be assigned from lexical, relation, or role cues.",
                expected_roles: &[],
                ambiguous: false,
            },
            "unknown",
            vec!["lexical_unit_unmatched".to_owned()],
        ));

    if definition.ambiguous {
        reasons.push("ambiguous_lexical_unit".to_owned());
    }

    let mut matched_roles = Vec::with_capacity(definition.expected_roles.len());
    for expected in definition.expected_roles {
        if arguments
            .iter()
            .any(|argument| argument.semantic_role == *expected)
        {
            matched_roles.push((*expected).to_owned());
        }
    }
    let missing_roles = definition
        .expected_roles
        .iter()
        .filter(|role| !matched_roles.iter().any(|matched| matched == **role))
        .map(|role| (*role).to_owned())
        .collect::<Vec<_>>();
    let mut failure_reasons = missing_roles
        .iter()
        .take(4)
        .map(|role| format!("missing_role:{role}"))
        .collect::<Vec<_>>();
    if definition.frame == "unclassified" {
        failure_reasons.push("no_frame_definition".to_owned());
    }
    let confidence_millis = frame_confidence_millis(
        source,
        definition.ambiguous,
        matched_roles.len(),
        missing_roles.len(),
    );
    if confidence_millis < 600 {
        failure_reasons.push("low_frame_confidence".to_owned());
    }

    DocumentSemanticFrame {
        frame: definition.frame.to_owned(),
        family: definition.family.to_owned(),
        target,
        lexical_unit: format!("{}.v", predicate_lemma(predicate)),
        definition: definition.definition.to_owned(),
        source: source.to_owned(),
        confidence_millis,
        expected_roles: definition
            .expected_roles
            .iter()
            .map(|role| (*role).to_owned())
            .collect(),
        matched_roles,
        missing_roles,
        reasons,
        failure_reasons,
    }
}

fn lexical_frame_definition(predicate: &str) -> Option<FrameDefinition> {
    let lemma = predicate_lemma(predicate);
    Some(match lemma.as_str() {
        "give" | "send" | "pass" | "offer" | "hand" | "deliver" | "receive" | "take" => {
            FrameDefinition {
                frame: "transfer_possession",
                family: "transfer",
                definition: "An actor transfers or receives a theme across a possession boundary.",
                expected_roles: ACTOR_THEME_RECIPIENT,
                ambiguous: matches!(lemma.as_str(), "pass" | "take"),
            }
        }
        "move" | "go" | "arrive" | "return" | "walk" | "run" | "leave" | "enter" | "travel" => {
            FrameDefinition {
                frame: "motion",
                family: "motion",
                definition: "An actor or theme changes location along a path or toward a goal.",
                expected_roles: ACTOR_GOAL,
                ambiguous: false,
            }
        }
        "bring" | "carry" => FrameDefinition {
            frame: "caused_motion",
            family: "motion",
            definition: "An actor causes a theme to move toward a destination or recipient.",
            expected_roles: ACTOR_THEME_DESTINATION,
            ambiguous: true,
        },
        "say" | "tell" | "ask" | "warn" | "answer" | "reply" | "speak" | "call" | "explain"
        | "report" | "claim" | "announce" | "show" => FrameDefinition {
            frame: "communication",
            family: "communication",
            definition: "A speaker conveys a message or signal to an addressee or audience.",
            expected_roles: COMMUNICATION_ROLES,
            ambiguous: matches!(lemma.as_str(), "show" | "call"),
        },
        "cause" | "make" | "force" | "allow" | "lead" | "trigger" | "prevent" | "change" => {
            FrameDefinition {
                frame: "causation",
                family: "causation",
                definition: "A cause or actor brings about, blocks, or changes an effect.",
                expected_roles: CAUSATION_ROLES,
                ambiguous: matches!(lemma.as_str(), "make" | "change"),
            }
        }
        "see" | "look" | "watch" | "notice" | "hear" | "feel" => FrameDefinition {
            frame: "perception",
            family: "perception",
            definition: "An experiencer perceives or notices a stimulus.",
            expected_roles: PERCEPTION_ROLES,
            ambiguous: matches!(lemma.as_str(), "feel"),
        },
        "decide" | "choose" | "plan" | "agree" | "approve" | "reject" | "order" => {
            FrameDefinition {
                frame: "decision",
                family: "decision",
                definition:
                    "An actor selects, commits to, approves, or rejects a course of action.",
                expected_roles: DECISION_ROLES,
                ambiguous: matches!(lemma.as_str(), "order"),
            }
        }
        "create" | "build" | "grow" | "write" | "produce" | "form" => FrameDefinition {
            frame: "creation",
            family: "creation",
            definition: "An actor brings a theme, artifact, or state into existence.",
            expected_roles: ACTOR_THEME,
            ambiguous: false,
        },
        "fight" | "attack" | "kill" | "threaten" | "blame" | "prosecute" => FrameDefinition {
            frame: "conflict",
            family: "conflict",
            definition: "Participants oppose, harm, accuse, or pursue one another.",
            expected_roles: ACTOR_THEME,
            ambiguous: matches!(lemma.as_str(), "blame"),
        },
        "have" | "own" | "hold" | "keep" | "wear" => FrameDefinition {
            frame: "possession",
            family: "possession",
            definition: "A bearer or possessor holds, owns, keeps, or wears a theme.",
            expected_roles: STATE_ROLES,
            ambiguous: matches!(lemma.as_str(), "hold" | "keep"),
        },
        "be" | "seem" | "become" | "remain" | "stay" => FrameDefinition {
            frame: "state",
            family: "state",
            definition: "A bearer exists in or changes into a state or attribute.",
            expected_roles: STATE_ROLES,
            ambiguous: matches!(lemma.as_str(), "stay"),
        },
        "mean" | "represent" | "name" => FrameDefinition {
            frame: "identity",
            family: "identity",
            definition: "A bearer is identified, named, represented, or defined as a theme.",
            expected_roles: IDENTITY_ROLES,
            ambiguous: false,
        },
        "know" | "think" | "believe" | "remember" | "understand" | "realize" => FrameDefinition {
            frame: "cognition",
            family: "cognition",
            definition: "An experiencer holds or changes a mental state about a theme.",
            expected_roles: PERCEPTION_ROLES,
            ambiguous: false,
        },
        _ => return None,
    })
}

fn relation_type_frame_definition(relation_type: &str) -> Option<FrameDefinition> {
    if relation_type.contains("movement") {
        Some(FrameDefinition {
            frame: "motion",
            family: "motion",
            definition: "An actor or theme changes location along a path or toward a goal.",
            expected_roles: ACTOR_GOAL,
            ambiguous: false,
        })
    } else if relation_type.contains("communication") {
        Some(FrameDefinition {
            frame: "communication",
            family: "communication",
            definition: "A speaker conveys a message or signal to an addressee or audience.",
            expected_roles: COMMUNICATION_ROLES,
            ambiguous: false,
        })
    } else if relation_type.contains("creation") {
        Some(FrameDefinition {
            frame: "creation",
            family: "creation",
            definition: "An actor brings a theme, artifact, or state into existence.",
            expected_roles: ACTOR_THEME,
            ambiguous: false,
        })
    } else if relation_type.contains("conflict") {
        Some(FrameDefinition {
            frame: "conflict",
            family: "conflict",
            definition: "Participants oppose, harm, accuse, or pursue one another.",
            expected_roles: ACTOR_THEME,
            ambiguous: false,
        })
    } else if relation_type.contains("identity") {
        Some(FrameDefinition {
            frame: "identity",
            family: "identity",
            definition: "A bearer is identified, named, represented, or defined as a theme.",
            expected_roles: IDENTITY_ROLES,
            ambiguous: false,
        })
    } else if relation_type.contains("state") || relation_type.contains("attribute") {
        Some(FrameDefinition {
            frame: "state",
            family: "state",
            definition: "A bearer exists in or changes into a state or attribute.",
            expected_roles: STATE_ROLES,
            ambiguous: false,
        })
    } else {
        None
    }
}

fn role_pattern_frame_definition(
    arguments: &[DocumentSemanticArgument],
) -> Option<FrameDefinition> {
    let has = |role: &str| {
        arguments
            .iter()
            .any(|argument| argument.semantic_role == role)
    };
    if has("recipient") && has("theme") {
        Some(FrameDefinition {
            frame: "transfer_possession",
            family: "transfer",
            definition: "An actor transfers or receives a theme across a possession boundary.",
            expected_roles: ACTOR_THEME_RECIPIENT,
            ambiguous: false,
        })
    } else if has("destination") || has("source") || has("location") {
        Some(FrameDefinition {
            frame: "motion",
            family: "motion",
            definition: "An actor or theme changes location along a path or toward a goal.",
            expected_roles: ACTOR_GOAL,
            ambiguous: false,
        })
    } else if has("cause") {
        Some(FrameDefinition {
            frame: "causation",
            family: "causation",
            definition: "A cause or actor brings about, blocks, or changes an effect.",
            expected_roles: CAUSATION_ROLES,
            ambiguous: false,
        })
    } else {
        None
    }
}

fn frame_confidence_millis(
    source: &str,
    ambiguous: bool,
    matched_roles: usize,
    missing_roles: usize,
) -> u16 {
    let mut score = match source {
        "lexical_table" => 790,
        "relation_type_rule" => 650,
        "role_pattern_rule" => 610,
        _ => 280,
    };
    score += matched_roles.min(3) as i32 * 45;
    score -= missing_roles.min(4) as i32 * 35;
    if ambiguous {
        score -= 65;
    }
    score.clamp(120, 960) as u16
}

fn predicate_lemma(predicate: &str) -> String {
    let lower = predicate.to_ascii_lowercase();
    match lower.as_str() {
        "gave" | "given" | "giving" => "give".to_owned(),
        "sent" => "send".to_owned(),
        "took" | "taken" | "taking" => "take".to_owned(),
        "went" | "gone" => "go".to_owned(),
        "came" | "come" => "come".to_owned(),
        "left" | "leaving" => "leave".to_owned(),
        "arriving" => "arrive".to_owned(),
        "moved" | "moving" => "move".to_owned(),
        "said" => "say".to_owned(),
        "told" => "tell".to_owned(),
        "made" | "making" => "make".to_owned(),
        "changed" | "changing" => "change".to_owned(),
        "saw" | "seen" => "see".to_owned(),
        "felt" => "feel".to_owned(),
        "approved" => "approve".to_owned(),
        "rejected" => "reject".to_owned(),
        "decided" => "decide".to_owned(),
        "planned" => "plan".to_owned(),
        "built" => "build".to_owned(),
        "created" | "creating" => "create".to_owned(),
        "caused" | "causing" => "cause".to_owned(),
        "attacked" => "attack".to_owned(),
        "killed" => "kill".to_owned(),
        "threatened" => "threaten".to_owned(),
        "blamed" => "blame".to_owned(),
        "fought" => "fight".to_owned(),
        "had" | "has" => "have".to_owned(),
        "was" | "were" | "is" | "are" | "been" | "being" => "be".to_owned(),
        "meant" => "mean".to_owned(),
        "knew" | "known" => "know".to_owned(),
        _ if lower.ends_with("ing") && lower.len() > 5 => lower[..lower.len() - 3].to_owned(),
        _ if lower.ends_with("ed") && lower.len() > 4 => lower[..lower.len() - 2].to_owned(),
        _ if lower.ends_with('s') && lower.len() > 3 => lower[..lower.len() - 1].to_owned(),
        _ => lower,
    }
}
