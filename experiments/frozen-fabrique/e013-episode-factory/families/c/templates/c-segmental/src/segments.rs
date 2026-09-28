#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Segment {
    pub start: i64,
    pub end: i64,
}

impl Segment {
    pub fn new(start: i64, end: i64) -> Option<Self> {
        (start <= end).then_some(Self { start, end })
    }

    pub fn overlaps(self, other: Self) -> bool {
        self.start < other.end && other.start < self.end
    }

    pub fn intersection(self, other: Self) -> Option<Self> {
        let start = self.start.max(other.start);
        let end = self.end.min(other.end);
        (start < end).then_some(Self { start, end })
    }
}

pub fn merge_sorted(segments: &mut Vec<Segment>) {
    segments.sort_unstable_by_key(|item| (item.start, item.end));
    let mut write = 0;
    for read in 0..segments.len() {
        let item = segments[read];
        if write > 0 && segments[write - 1].end >= item.start {
            segments[write - 1].end = segments[write - 1].end.max(item.end);
        } else {
            segments[write] = item;
            write += 1;
        }
    }
    segments.truncate(write);
}
