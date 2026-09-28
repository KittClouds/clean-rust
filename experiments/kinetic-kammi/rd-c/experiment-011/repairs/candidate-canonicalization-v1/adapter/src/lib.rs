use hashbrown::{HashMap, HashSet};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ActionMapping {
    pub canonical_action_id: u16,
    pub original_action_id: u16,
    pub patch_sha256: String,
}

pub fn canonicalize_frame(mut frame: Value) -> Result<(Value, Vec<ActionMapping>), String> {
    let options = frame
        .get_mut("action_options")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| "frame.action_options must be an array".to_owned())?;
    if options.is_empty() || options.len() > u16::MAX as usize {
        return Err("action option count is outside the supported range".to_owned());
    }

    let mut seen_patch_hashes = HashSet::with_capacity(options.len());
    let mut seen_action_ids = HashSet::with_capacity(options.len());
    let mut keyed = Vec::with_capacity(options.len());
    for option in std::mem::take(options) {
        let patch = option
            .get("patch_sha256")
            .and_then(Value::as_str)
            .ok_or_else(|| "action option is missing patch_sha256".to_owned())?
            .to_owned();
        if patch.len() != 64 || !patch.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("patch_sha256 must be a 64-character hexadecimal digest".to_owned());
        }
        if !seen_patch_hashes.insert(patch.clone()) {
            return Err("duplicate patch_sha256 makes canonical choice ambiguous".to_owned());
        }

        let action = option
            .get("action")
            .and_then(Value::as_object)
            .ok_or_else(|| "action option is missing its action object".to_owned())?;
        let raw_id = action
            .get("id")
            .and_then(Value::as_u64)
            .ok_or_else(|| "action.id must be an unsigned integer".to_owned())?;
        let original_id =
            u16::try_from(raw_id).map_err(|_| "action.id exceeds the v1 wire range".to_owned())?;
        if !seen_action_ids.insert(original_id) {
            return Err("duplicate original action IDs are not legal".to_owned());
        }
        keyed.push((patch, original_id, option));
    }

    keyed.sort_unstable_by(|left, right| left.0.cmp(&right.0));
    let options = frame
        .get_mut("action_options")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| "frame.action_options changed during normalization".to_owned())?;
    options.reserve(keyed.len());

    let mut receipt = Vec::with_capacity(keyed.len());
    for (index, (patch_sha256, original_action_id, mut option)) in keyed.into_iter().enumerate() {
        let canonical_action_id =
            u16::try_from(index + 1).map_err(|_| "canonical action ID overflow".to_owned())?;
        let action = option
            .get_mut("action")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| "action option lost its action object".to_owned())?;
        action.insert("id".to_owned(), Value::from(canonical_action_id));
        options.push(option);
        receipt.push(ActionMapping {
            canonical_action_id,
            original_action_id,
            patch_sha256,
        });
    }
    Ok((frame, receipt))
}

pub fn restore_original_action_id(
    choice: Option<u16>,
    receipt: &[ActionMapping],
) -> Result<Option<u16>, String> {
    let Some(choice) = choice else {
        return Ok(None);
    };
    let mut by_canonical_id = HashMap::with_capacity(receipt.len());
    for row in receipt {
        if by_canonical_id
            .insert(row.canonical_action_id, row.original_action_id)
            .is_some()
        {
            return Err("receipt contains duplicate canonical action IDs".to_owned());
        }
    }
    by_canonical_id
        .get(&choice)
        .copied()
        .map(Some)
        .ok_or_else(|| "observer selected an ID absent from the canonical receipt".to_owned())
}

#[cfg(test)]
mod tests {
    use super::{ActionMapping, canonicalize_frame, restore_original_action_id};
    use serde_json::{Value, json};

    fn sample_frame(order: [usize; 4], ids: [u16; 4]) -> Value {
        let source = [
            ("c".repeat(64), "third"),
            ("a".repeat(64), "first"),
            ("d".repeat(64), "fourth"),
            ("b".repeat(64), "second"),
        ];
        let action_options = order
            .into_iter()
            .map(|index| {
                json!({
                    "action": {"id": ids[index], "schema_id": 1},
                    "summary": source[index].1,
                    "diff_excerpt": format!("change-{}", source[index].1),
                    "patch_sha256": source[index].0
                })
            })
            .collect::<Vec<_>>();
        json!({
            "schema_id": "rdc-real-coding-observation.v1",
            "task_id": "synthetic-task",
            "action_options": action_options
        })
    }

    #[test]
    fn canonical_frame_is_invariant_to_order_and_wire_ids() {
        let baseline = sample_frame([0, 1, 2, 3], [11, 37, 68, 94]);
        let (expected, _) = canonicalize_frame(baseline).expect("valid frame");
        let permutations = [
            [3, 2, 1, 0],
            [1, 3, 0, 2],
            [2, 0, 3, 1],
            [0, 2, 1, 3],
            [3, 0, 2, 1],
            [1, 0, 3, 2],
        ];
        for (run, order) in permutations.into_iter().enumerate() {
            let ids = [
                20_001 + (run * 4) as u16,
                30_003 + (run * 4) as u16,
                40_007 + (run * 4) as u16,
                50_009 + (run * 4) as u16,
            ];
            let actual = sample_frame(order, ids);
            let (actual, _) = canonicalize_frame(actual).expect("permuted frame");
            assert_eq!(actual, expected);
        }
    }

    #[test]
    fn receipt_restores_the_original_authority_id_by_stable_patch() {
        let frame = sample_frame([3, 0, 1, 2], [11, 37, 68, 94]);
        let (_, receipt) = canonicalize_frame(frame).expect("valid frame");
        let second_patch = "b".repeat(64);
        let row = receipt
            .iter()
            .find(|item| item.patch_sha256 == second_patch)
            .expect("second patch exists");
        assert_eq!(row.canonical_action_id, 2);
        assert_eq!(
            restore_original_action_id(Some(2), &receipt).unwrap(),
            Some(94)
        );
        assert_eq!(restore_original_action_id(None, &receipt).unwrap(), None);
    }

    #[test]
    fn duplicate_patch_digest_is_rejected() {
        let mut frame = sample_frame([0, 1, 2, 3], [11, 37, 68, 94]);
        let duplicate = frame["action_options"][0]["patch_sha256"].clone();
        frame["action_options"][1]["patch_sha256"] = duplicate;
        assert!(
            canonicalize_frame(frame)
                .unwrap_err()
                .contains("duplicate patch_sha256")
        );
    }

    #[test]
    fn unknown_canonical_choice_is_rejected() {
        let receipt = vec![ActionMapping {
            canonical_action_id: 1,
            original_action_id: 17,
            patch_sha256: "a".repeat(64),
        }];
        assert!(restore_original_action_id(Some(2), &receipt).is_err());
    }
}
