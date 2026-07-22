#[derive(Default)]
pub(super) struct TemporalCues {
    pub persistence: bool,
    pub termination: bool,
    pub transition: bool,
    pub recurrence: bool,
    pub persistence_cue: Option<String>,
    pub termination_cue: Option<String>,
    pub transition_cue: Option<String>,
    pub before_cue: Option<&'static str>,
    pub after_cue: Option<&'static str>,
    pub sequence_cue: Option<&'static str>,
    pub overlap_cue: Option<&'static str>,
}

impl TemporalCues {
    pub fn has_temporal_evidence(&self) -> bool {
        self.persistence
            || self.termination
            || self.transition
            || self.recurrence
            || self.before_cue.is_some()
            || self.after_cue.is_some()
            || self.sequence_cue.is_some()
            || self.overlap_cue.is_some()
    }

    pub fn reasons(&self) -> Vec<String> {
        let mut out = Vec::with_capacity(3);
        if let Some(cue) = &self.persistence_cue {
            out.push(format!("persistence_cue:{cue}"));
        }
        if let Some(cue) = &self.termination_cue {
            out.push(format!("termination_cue:{cue}"));
        }
        if let Some(cue) = &self.transition_cue {
            out.push(format!("transition_cue:{cue}"));
        }
        out
    }
}

pub(super) fn temporal_cues(text: &str) -> TemporalCues {
    let lower = text.to_ascii_lowercase();
    let persistence_cue = first_cue(
        &lower,
        &[
            "still",
            "remained",
            "continued",
            "kept",
            "stayed",
            "persisted",
        ],
    );
    let termination_cue = first_cue(
        &lower,
        &[
            "no longer",
            "stopped",
            "ceased",
            "ended",
            "left",
            "lost",
            "released",
            "closed",
        ],
    );
    let transition_cue = first_cue(
        &lower,
        &[
            "then",
            "later",
            "eventually",
            "became",
            "turned",
            "started",
            "began",
        ],
    );
    TemporalCues {
        persistence: persistence_cue.is_some(),
        termination: termination_cue.is_some(),
        transition: transition_cue.is_some(),
        recurrence: contains_cue(
            &lower,
            &["again", "once more", "repeated", "often", "usually"],
        )
        .is_some(),
        persistence_cue,
        termination_cue,
        transition_cue,
        before_cue: contains_cue(&lower, &["before"]),
        after_cue: contains_cue(&lower, &["after"]),
        sequence_cue: contains_cue(
            &lower,
            &["then", "later", "next", "subsequently", "eventually"],
        ),
        overlap_cue: contains_cue(&lower, &["while", "meanwhile", "during", "simultaneously"]),
    }
}

fn first_cue(text: &str, cues: &[&str]) -> Option<String> {
    cues.iter()
        .find(|cue| text.contains(**cue))
        .map(|cue| (*cue).to_owned())
}

fn contains_cue(text: &str, cues: &[&'static str]) -> Option<&'static str> {
    cues.iter().copied().find(|cue| text.contains(cue))
}

pub(super) fn normalize(value: &str) -> String {
    let value = value.trim_matches(|ch: char| !ch.is_alphanumeric());
    let mut out = String::with_capacity(value.len());
    let mut separated = true;
    for ch in value.chars() {
        if ch.is_alphanumeric() {
            out.extend(ch.to_lowercase());
            separated = false;
        } else if !separated && !out.is_empty() {
            out.push('-');
            separated = true;
        }
    }
    if out.ends_with('-') {
        out.pop();
    }
    out
}
