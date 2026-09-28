use serde_json::{Deserializer, Value};

pub fn first_item_offset(input: &str) -> usize {
    let de = Deserializer::from_str(input);
    let mut stream = de.into_iter::<Value>();
    let _ = stream.next();
    let base = stream.byte_offset();
    // E012 candidate slot.
    base
}
