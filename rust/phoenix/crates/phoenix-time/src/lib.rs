use std::cmp::Ordering;

use compact_str::CompactString;
use phoenix_types::{BiTemporalWindow, TimeAnchorRecord};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default)]
pub struct TemporalBinding {
    pub anchor: Option<TimeAnchorRecord>,
    pub recorded_window: BiTemporalWindow,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum TemporalRelation {
    Before,
    After,
    Overlaps,
    Contains,
    During,
    Equal,
    #[default]
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemporalConfidence {
    pub confidence_millis: u32,
    pub margin_millis: u32,
}

pub struct TimeKernel;

impl TimeKernel {
    pub fn bind_label(label: &str, recorded_at: Option<i64>) -> TemporalBinding {
        TemporalBinding {
            anchor: Some(TimeAnchorRecord {
                time_id: None,
                label: CompactString::from(label),
                interval: Self::recorded_window(recorded_at),
            }),
            recorded_window: Self::recorded_window(recorded_at),
        }
    }

    #[inline]
    pub fn window(
        valid_from: Option<i64>,
        valid_to: Option<i64>,
        recorded_at: Option<i64>,
    ) -> BiTemporalWindow {
        BiTemporalWindow {
            valid_from,
            valid_to,
            recorded_from: recorded_at,
            recorded_to: None,
        }
    }

    #[inline]
    pub fn recorded_window(recorded_at: Option<i64>) -> BiTemporalWindow {
        Self::window(None, None, recorded_at)
    }

    pub fn relation(left: &BiTemporalWindow, right: &BiTemporalWindow) -> TemporalRelation {
        let Some((left_start, left_end)) = valid_bounds(left) else {
            return TemporalRelation::Indeterminate;
        };
        let Some((right_start, right_end)) = valid_bounds(right) else {
            return TemporalRelation::Indeterminate;
        };
        if left_start == right_start && left_end == right_end {
            return TemporalRelation::Equal;
        }
        if left_end < right_start {
            return TemporalRelation::Before;
        }
        if right_end < left_start {
            return TemporalRelation::After;
        }
        if left_start <= right_start && left_end >= right_end {
            return TemporalRelation::Contains;
        }
        if right_start <= left_start && right_end >= left_end {
            return TemporalRelation::During;
        }
        TemporalRelation::Overlaps
    }

    #[inline]
    pub fn overlaps(left: &BiTemporalWindow, right: &BiTemporalWindow) -> bool {
        matches!(
            Self::relation(left, right),
            TemporalRelation::Overlaps
                | TemporalRelation::Contains
                | TemporalRelation::During
                | TemporalRelation::Equal
        )
    }

    pub fn order_key(window: &BiTemporalWindow) -> (i64, i64, i64) {
        (
            window.valid_from.unwrap_or(i64::MAX),
            window.valid_to.unwrap_or(i64::MAX),
            window.recorded_from.unwrap_or(i64::MAX),
        )
    }

    pub fn compare_start(left: &BiTemporalWindow, right: &BiTemporalWindow) -> Ordering {
        Self::order_key(left).cmp(&Self::order_key(right))
    }

    pub fn merge_windows<I>(windows: I, recorded_fallback: Option<i64>) -> BiTemporalWindow
    where
        I: Iterator<Item = BiTemporalWindow>,
    {
        let mut min_valid = None::<i64>;
        let mut max_valid = None::<i64>;
        let mut min_recorded = None::<i64>;
        let mut max_recorded = None::<i64>;
        for window in windows {
            min_valid = min_opt(min_valid, window.valid_from);
            max_valid = max_opt(max_valid, window.valid_to);
            min_recorded = min_opt(min_recorded, window.recorded_from);
            max_recorded = max_opt(max_recorded, window.recorded_to);
        }
        BiTemporalWindow {
            valid_from: min_valid,
            valid_to: max_valid,
            recorded_from: min_recorded.or(recorded_fallback),
            recorded_to: max_recorded,
        }
    }

    pub fn confidence(strength: u32, runner_up: u32) -> TemporalConfidence {
        TemporalConfidence {
            confidence_millis: strength.min(1000),
            margin_millis: strength.saturating_sub(runner_up).min(1000),
        }
    }
}

fn valid_bounds(window: &BiTemporalWindow) -> Option<(i64, i64)> {
    let start = window.valid_from?;
    Some((start, window.valid_to.unwrap_or(start)))
}

fn min_opt(current: Option<i64>, next: Option<i64>) -> Option<i64> {
    match (current, next) {
        (Some(left), Some(right)) => Some(left.min(right)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

fn max_opt(current: Option<i64>, next: Option<i64>) -> Option<i64> {
    match (current, next) {
        (Some(left), Some(right)) => Some(left.max(right)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn temporal_relation_detects_overlap_and_order() {
        let first = TimeKernel::window(Some(10), Some(20), Some(1));
        let second = TimeKernel::window(Some(15), Some(30), Some(1));
        let third = TimeKernel::window(Some(40), Some(50), Some(1));

        assert_eq!(
            TimeKernel::relation(&first, &second),
            TemporalRelation::Overlaps
        );
        assert_eq!(
            TimeKernel::relation(&first, &third),
            TemporalRelation::Before
        );
        assert!(TimeKernel::overlaps(&first, &second));
    }

    #[test]
    fn merge_windows_keeps_valid_and_recorded_bounds() {
        let windows = [
            TimeKernel::window(Some(20), Some(25), Some(7)),
            TimeKernel::window(Some(10), Some(30), Some(3)),
        ];
        let merged = TimeKernel::merge_windows(windows.into_iter(), Some(99));

        assert_eq!(merged.valid_from, Some(10));
        assert_eq!(merged.valid_to, Some(30));
        assert_eq!(merged.recorded_from, Some(3));
    }
}
