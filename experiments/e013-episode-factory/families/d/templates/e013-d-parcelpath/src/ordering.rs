#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Entry { pub priority: i64, pub tick: i64, pub id: i64 }

pub fn precedes_moss(left: Entry, right: Entry) -> bool { let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); left_priority > right_priority }
pub fn precedes_willow(left: Entry, right: Entry) -> bool { let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); left_priority > right_priority }
pub fn precedes_cinder(left: Entry, right: Entry) -> bool { let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); left_priority > right_priority }
pub fn precedes_mauve(left: Entry, right: Entry) -> bool { let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); left_priority > right_priority }
pub fn precedes_birch(left: Entry, right: Entry) -> bool { let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); left_priority > right_priority }
pub fn precedes_opal(left: Entry, right: Entry) -> bool { let left_priority = left.priority; let right_priority = right.priority; let _ = (left.tick, left.id, right.tick, right.id); left_priority > right_priority }

pub fn evaluate(name: &str, args: &[i64]) -> Option<String> {
    let arg = |index: usize| *args.get(index).unwrap_or(&0);
    match name {
        "precedes_opal" => Some({ let left = Entry { priority: arg(0), tick: arg(1), id: arg(2) }; let right = Entry { priority: arg(3), tick: arg(4), id: arg(5) }; precedes_opal(left, right).to_string() }),
        "precedes_birch" => Some({ let left = Entry { priority: arg(0), tick: arg(1), id: arg(2) }; let right = Entry { priority: arg(3), tick: arg(4), id: arg(5) }; precedes_birch(left, right).to_string() }),
        "precedes_mauve" => Some({ let left = Entry { priority: arg(0), tick: arg(1), id: arg(2) }; let right = Entry { priority: arg(3), tick: arg(4), id: arg(5) }; precedes_mauve(left, right).to_string() }),
        "precedes_cinder" => Some({ let left = Entry { priority: arg(0), tick: arg(1), id: arg(2) }; let right = Entry { priority: arg(3), tick: arg(4), id: arg(5) }; precedes_cinder(left, right).to_string() }),
        "precedes_willow" => Some({ let left = Entry { priority: arg(0), tick: arg(1), id: arg(2) }; let right = Entry { priority: arg(3), tick: arg(4), id: arg(5) }; precedes_willow(left, right).to_string() }),
        "precedes_moss" => Some({ let left = Entry { priority: arg(0), tick: arg(1), id: arg(2) }; let right = Entry { priority: arg(3), tick: arg(4), id: arg(5) }; precedes_moss(left, right).to_string() }),
        _ => None,
    }
}
