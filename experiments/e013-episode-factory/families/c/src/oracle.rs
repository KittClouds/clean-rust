use std::collections::BinaryHeap;
use std::cmp::Reverse;

use crate::spec::FamilySpec;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Case {
    pub input: Vec<u8>,
    pub expected: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct FixtureSet {
    pub visible: Vec<Case>,
    pub hidden: Vec<Case>,
    pub hidden_canary: String,
}

pub fn fixtures(family: &FamilySpec, seed: u64) -> Option<FixtureSet> {
    let nonce = ((mix64(seed) % 997) + 1) as i64;
    let visible = match family.id {
        "c.token-cursor" => vec![case("alpha ", token_oracle("alpha "))],
        "c.interval-index" => vec![case(
            "0,8;1,9;2,10|5,6",
            interval_oracle("0,8;1,9;2,10|5,6"),
        )],
        "c.graph-witness" => vec![case(
            "2;0;1|0,1",
            graph_oracle("2;0;1|0,1"),
        )],
        "c.delta-codec" => vec![case("0", delta_oracle(&[0]))],
        "c.parser-precedence" => vec![case("1+0*1", parser_oracle("1+0*1")?)],
        "c.window-fold" => vec![case("1|1", window_oracle("1|1")?)],
        "c.binary-frame" => vec![case(&[0, 0, 0], frame_oracle(&[0, 0, 0]))],
        "c.dependency-eval" => vec![case("0|0:", dependency_oracle("0|0:"))],
        _ => return None,
    };

    let hidden = match family.id {
        "c.token-cursor" => {
            let input = format!("\u{2003}é{nonce}\t漢字 beta");
            vec![case(input.as_bytes(), token_oracle(&input))]
        }
        "c.interval-index" => vec![
            case("0,5;1,2;2,10|5,7", interval_oracle("0,5;1,2;2,10|5,7")),
            case("7,8;3,7|5,7", interval_oracle("7,8;3,7|5,7")),
            case("5,5;1,9|4,6", interval_oracle("5,5;1,9|4,6")),
            case("8,12;0,10;4,9|2,3", interval_oracle("8,12;0,10;4,9|2,3")),
        ],
        "c.graph-witness" => vec![
            case(
                "6;0;5|0,3;3,5;0,1;1,5;0,2;2,4;4,5",
                graph_oracle("6;0;5|0,3;3,5;0,1;1,5;0,2;2,4;4,5"),
            ),
            case("3;0;2|0,1", graph_oracle("3;0;2|0,1")),
        ],
        "c.delta-codec" => {
            let values = [nonce, nonce, -2, 300 + nonce, -130];
            let input = values.iter().map(i64::to_string).collect::<Vec<_>>().join(",");
            vec![case(input.as_bytes(), delta_oracle(&values))]
        }
        "c.parser-precedence" => {
            let input = format!("12+3*4+{nonce}*6");
            vec![case(input.as_bytes(), parser_oracle(&input)?) ]
        }
        "c.window-fold" => vec![
            case("3|1,2,3,4,5", window_oracle("3|1,2,3,4,5")?),
            case("4|2,7", window_oracle("4|2,7")?),
        ],
        "c.binary-frame" => {
            let payload = [0x10, nonce as u8, 0x30, 0x40];
            let mut valid = vec![0x21, payload.len() as u8, 0];
            valid.extend_from_slice(&payload);
            let valid_expected = frame_oracle(&valid);
            let mut trailing = valid.clone();
            trailing.push(0x99);
            let mut wrong_tag = vec![0x01, 1, 0, 0x7f];
            let mut off_by_one = vec![0x21, 4, 0, 1, 2, 3, 4];
            vec![
                case(&valid, valid_expected),
                case(&trailing, frame_oracle(&trailing)),
                case(&wrong_tag, frame_oracle(&wrong_tag)),
                case(&off_by_one, frame_oracle(&off_by_one)),
            ]
        }
        "c.dependency-eval" => vec![case(
            "0|0:1,2;1:3;2:3,4;3:5;4:5;5:",
            dependency_oracle("0|0:1,2;1:3;2:3,4;3:5;4:5;5:"),
        )],
        _ => return None,
    };
    let hidden_canary = format!("E013-C-HIDDEN-{:016x}", mix64(seed ^ 0xC013_5EA1_D15C_A11E));
    Some(FixtureSet { visible, hidden, hidden_canary })
}

pub fn encode_cases(cases: &[Case], canary: Option<&str>) -> Vec<u8> {
    let mut output = Vec::with_capacity(cases.len() * 96 + canary.map_or(0, str::len) + 2);
    if let Some(marker) = canary {
        output.extend_from_slice(b"# ");
        output.extend_from_slice(marker.as_bytes());
        output.push(b'\n');
    }
    for case in cases {
        encode_hex(&case.input, &mut output);
        output.push(b'\t');
        encode_hex(&case.expected, &mut output);
        output.push(b'\n');
    }
    output
}

fn case(input: impl AsRef<[u8]>, expected: Vec<u8>) -> Case {
    Case { input: input.as_ref().to_vec(), expected }
}

fn encode_hex(input: &[u8], output: &mut Vec<u8>) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    output.reserve(input.len() * 2);
    for byte in input {
        output.push(HEX[(byte >> 4) as usize]);
        output.push(HEX[(byte & 15) as usize]);
    }
}

fn token_oracle(input: &str) -> Vec<u8> {
    let mut ranges = Vec::new();
    let mut start = None;
    for (offset, ch) in input.char_indices() {
        if ch.is_whitespace() {
            if let Some(begin) = start.take() { ranges.push((begin, offset)); }
        } else if start.is_none() { start = Some(offset); }
    }
    if let Some(begin) = start { ranges.push((begin, input.len())); }
    ranges.iter().map(|(start, end)| format!("{start}:{end}")).collect::<Vec<_>>().join(",").into_bytes()
}

fn interval_oracle(input: &str) -> Vec<u8> {
    let Some((items, query)) = input.split_once('|') else { return Vec::new(); };
    let Some((q0, q1)) = pair_i64(query) else { return Vec::new(); };
    let mut result = Vec::new();
    for (index, item) in items.split(';').filter(|item| !item.is_empty()).enumerate() {
        let Some((start, end)) = pair_i64(item) else { return Vec::new(); };
        if start < end && q0 < end && start < q1 { result.push(index.to_string()); }
    }
    result.join(",").into_bytes()
}

fn pair_i64(input: &str) -> Option<(i64, i64)> {
    let (left, right) = input.split_once(',')?;
    Some((left.parse().ok()?, right.parse().ok()?))
}

fn graph_oracle(input: &str) -> Vec<u8> {
    let Some((header, edge_text)) = input.split_once('|') else { return Vec::new(); };
    let fields: Vec<_> = header.split(';').collect();
    if fields.len() != 3 { return Vec::new(); }
    let (Ok(count), Ok(source), Ok(target)) = (
        fields[0].parse::<usize>(),
        fields[1].parse::<usize>(),
        fields[2].parse::<usize>(),
    ) else { return Vec::new(); };
    if count == 0 || source >= count || target >= count { return Vec::new(); }
    let mut graph = vec![Vec::new(); count];
    for field in edge_text.split(';').filter(|field| !field.is_empty()) {
        let Some((left, right)) = field.split_once(',') else { return Vec::new(); };
        let (Ok(from), Ok(to)) = (left.parse::<usize>(), right.parse::<usize>()) else { return Vec::new(); };
        if from >= count || to >= count { return Vec::new(); }
        graph[from].push(to);
    }
    let mut heap = BinaryHeap::new();
    let mut best: Vec<Option<Vec<usize>>> = vec![None; count];
    best[source] = Some(vec![source]);
    heap.push(Reverse((1usize, vec![source])));
    while let Some(Reverse((_, path))) = heap.pop() {
        let Some(&node) = path.last() else { continue; };
        if best[node].as_ref() != Some(&path) { continue; }
        if node == target { return path.iter().map(usize::to_string).collect::<Vec<_>>().join(",").into_bytes(); }
        for &next in &graph[node] {
            if path.contains(&next) { continue; }
            let mut candidate = path.clone();
            candidate.push(next);
            if best[next].as_ref().map_or(true, |old| (candidate.len(), &candidate) < (old.len(), old)) {
                best[next] = Some(candidate.clone());
                heap.push(Reverse((candidate.len(), candidate)));
            }
        }
    }
    Vec::new()
}

fn delta_oracle(values: &[i64]) -> Vec<u8> {
    let mut previous = 0i64;
    let mut bytes = Vec::new();
    for &value in values {
        let delta = value.wrapping_sub(previous);
        let magnitude = if delta < 0 { ((delta.unsigned_abs()) << 1).wrapping_sub(1) } else { (delta as u64) << 1 };
        let mut rest = magnitude;
        while rest > 0x7f {
            bytes.push((rest as u8 & 0x7f) | 0x80);
            rest >>= 7;
        }
        bytes.push(rest as u8);
        previous = value;
    }
    bytes
}

fn parser_oracle(input: &str) -> Option<Vec<u8>> {
    let mut sum = 0i64;
    let mut term = 0i64;
    let mut number = 0i64;
    let mut saw_digit = false;
    let mut saw_any = false;
    for byte in input.bytes().chain(std::iter::once(b'+')) {
        match byte {
            b'0'..=b'9' => {
                number = number.checked_mul(10)?.checked_add(i64::from(byte - b'0'))?;
                saw_digit = true;
                saw_any = true;
            }
            b'*' | b'+' => {
                if !saw_digit { return None; }
                term = if term == 0 { number } else { term.checked_mul(number)? };
                number = 0;
                saw_digit = false;
                if byte == b'+' { sum = sum.checked_add(term)?; term = 0; }
            }
            _ => return None,
        }
    }
    if !saw_any { return None; }
    Some(sum.to_string().into_bytes())
}

fn window_oracle(input: &str) -> Option<Vec<u8>> {
    let (width_text, values_text) = input.split_once('|')?;
    let width = width_text.parse::<usize>().ok()?;
    if width == 0 { return Some(Vec::new()); }
    let values: Option<Vec<i64>> = values_text.split(',').filter(|item| !item.is_empty()).map(|item| item.parse().ok()).collect();
    let values = values?;
    if values.len() < width { return Some(Vec::new()); }
    let totals = values.windows(width).map(|window| window.iter().sum::<i64>().to_string()).collect::<Vec<_>>();
    Some(totals.join(",").into_bytes())
}

fn frame_oracle(input: &[u8]) -> Vec<u8> {
    if input.len() < 3 { return Vec::new(); }
    let length = usize::from(u16::from_le_bytes([input[1], input[2]]));
    if input.len() != 3 + length { return Vec::new(); }
    input[3..].to_vec()
}

fn dependency_oracle(input: &str) -> Vec<u8> {
    let Some((target_text, graph_text)) = input.split_once('|') else { return Vec::new(); };
    let Ok(target) = target_text.parse::<usize>() else { return Vec::new(); };
    let mut graph = std::collections::BTreeMap::<usize, Vec<usize>>::new();
    for item in graph_text.split(';').filter(|item| !item.is_empty()) {
        let Some((node_text, deps_text)) = item.split_once(':') else { return Vec::new(); };
        let Ok(node) = node_text.parse::<usize>() else { return Vec::new(); };
        let mut deps = Vec::new();
        for dep in deps_text.split(',').filter(|dep| !dep.is_empty()) {
            let Ok(value) = dep.parse::<usize>() else { return Vec::new(); };
            deps.push(value);
        }
        graph.insert(node, deps);
    }
    let mut stack = vec![target];
    let mut seen = std::collections::BTreeSet::new();
    while let Some(node) = stack.pop() {
        if let Some(deps) = graph.get(&node) {
            for &dependency in deps {
                if dependency != target && seen.insert(dependency) { stack.push(dependency); }
            }
        }
    }
    seen.iter().map(usize::to_string).collect::<Vec<_>>().join(",").into_bytes()
}

fn mix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

