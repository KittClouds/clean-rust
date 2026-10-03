use crate::spec::FamilySpec;

/// Returns a pure solve(input) body. Candidate code may inspect only its argument.
pub fn body(family: &FamilySpec, variant: u8) -> Option<String> {
    let (first, second, mutants) = match family.id {
        "c.token-cursor" => (token_a(), token_b(), vec![token_ascii(), token_char_offsets(), token_space_only(), token_drop_last()]),
        "c.interval-index" => (interval_a(), interval_b(), vec![interval_left_closed(), interval_right_closed(), interval_sort_output(), interval_empty_match()]),
        "c.graph-witness" => (graph_a(), graph_b(), vec![graph_dfs(), graph_reverse_ties(), graph_endpoints_only(), graph_false_source()]),
        "c.delta-codec" => (delta_a(), delta_b(), vec![delta_absolute(), delta_unsigned(), delta_single_byte(), delta_reverse()]),
        "c.parser-precedence" => (parser_a(), parser_b(), vec![parser_left_to_right(), parser_reverse_precedence(), parser_first_digit(), parser_drop_last_term()]),
        "c.window-fold" => (window_a(), window_b(), vec![window_partial(), window_chunks(), window_drop_final(), window_total_repeated()]),
        "c.binary-frame" => (frame_a(), frame_b(), vec![frame_big_endian(), frame_allow_trailing(), frame_tag_zero_only(), frame_off_by_one()]),
        "c.dependency-eval" => (dependency_a(), dependency_b(), vec![dependency_direct_only(), dependency_duplicates(), dependency_reverse_sort(), dependency_drop_largest()]),
        _ => return None,
    };
    match variant {
        0 => Some(first),
        1 => Some(second),
        2..=5 => mutants.get((variant - 2) as usize).cloned(),
        _ => None,
    }
}

pub fn all_bodies(family: &FamilySpec) -> Vec<String> {
    (0..6).filter_map(|variant| body(family, variant)).collect()
}

pub fn is_pure_body(source: &str) -> bool {
    [
        "std::env", "env::var", "std::fs", "File::open", "read_to_string", "read_to_end",
        "std::process", "std::net", "std::thread", "unsafe", "include_bytes!", "include_str!",
        "option_env!", "env!", "Command::new", "TcpStream", "UdpSocket",
    ]
    .iter()
    .all(|forbidden| !source.contains(forbidden))
}

fn token_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let mut spans = Vec::new();
let mut start = None;
for (offset, ch) in text.char_indices() {
    if ch.is_whitespace() {
        if let Some(begin) = start.take() { spans.push(format!("{begin}:{offset}")); }
    } else if start.is_none() { start = Some(offset); }
}
if let Some(begin) = start { spans.push(format!("{begin}:{}", text.len())); }
spans.join(",").into_bytes()
"#.trim().to_string() }

fn token_b() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let mut spans = Vec::new();
let mut cursor = 0usize;
for token in text.split_whitespace() {
    let Some(relative) = text[cursor..].find(token) else { return Vec::new(); };
    let begin = cursor + relative;
    let end = begin + token.len();
    spans.push(format!("{begin}:{end}"));
    cursor = end;
}
spans.join(",").into_bytes()
"#.trim().to_string() }

fn token_ascii() -> String { token_a().replace("ch.is_whitespace()", "ch.is_ascii_whitespace()") }
fn token_char_offsets() -> String { token_a().replace("text.len()", "text.chars().count()") }
fn token_space_only() -> String { token_a().replace("ch.is_whitespace()", "ch == ' '") }
fn token_drop_last() -> String { token_a().replace("if let Some(begin) = start { spans.push(format!(\"{begin}:{}\", text.len())); }", "") }

fn interval_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let Some((items, query)) = text.split_once('|') else { return Vec::new(); };
let Some((query_start, query_end)) = parse_pair(query) else { return Vec::new(); };
let mut hits = Vec::new();
for (index, field) in items.split(';').filter(|field| !field.is_empty()).enumerate() {
    let Some((start, end)) = parse_pair(field) else { return Vec::new(); };
    if start < end && start < query_end && query_start < end { hits.push(index.to_string()); }
}
hits.join(",").into_bytes()
fn parse_pair(field: &str) -> Option<(i64, i64)> {
    let (left, right) = field.split_once(',')?;
    Some((left.parse().ok()?, right.parse().ok()?))
}
"#.trim().to_string() }

fn interval_b() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let Some((items, query)) = text.split_once('|') else { return Vec::new(); };
let Some((query_start, query_end)) = parse_pair(query) else { return Vec::new(); };
let parsed: Option<Vec<(usize, i64, i64)>> = items.split(';').filter(|field| !field.is_empty()).enumerate().map(|(index, field)| {
    let (start, end) = parse_pair(field)?;
    Some((index, start, end))
}).collect();
let Some(parsed) = parsed else { return Vec::new(); };
parsed.into_iter().filter(|(_, start, end)| *start < *end && *start < query_end && query_start < *end)
    .map(|(index, _, _)| index.to_string()).collect::<Vec<_>>().join(",").into_bytes()
fn parse_pair(field: &str) -> Option<(i64, i64)> {
    let (left, right) = field.split_once(',')?;
    Some((left.parse().ok()?, right.parse().ok()?))
}
"#.trim().to_string() }

fn interval_left_closed() -> String { interval_a().replace("start < query_end", "start <= query_end") }
fn interval_right_closed() -> String { interval_a().replace("query_start < end", "query_start <= end") }
fn interval_sort_output() -> String { interval_a().replace("hits.push(index.to_string())", "hits.push(start.to_string())") }
fn interval_empty_match() -> String { interval_a().replace("start < end && ", "") }

fn graph_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let Some((header, edge_text)) = text.split_once('|') else { return Vec::new(); };
let fields: Vec<_> = header.split(';').collect();
if fields.len() != 3 { return Vec::new(); }
let (Ok(count), Ok(source), Ok(target)) = (fields[0].parse::<usize>(), fields[1].parse::<usize>(), fields[2].parse::<usize>()) else { return Vec::new(); };
if source >= count || target >= count { return Vec::new(); }
let mut graph = vec![Vec::new(); count];
for edge in edge_text.split(';').filter(|edge| !edge.is_empty()) {
    let Some((left, right)) = edge.split_once(',') else { return Vec::new(); };
    let (Ok(from), Ok(to)) = (left.parse::<usize>(), right.parse::<usize>()) else { return Vec::new(); };
    if from >= count || to >= count { return Vec::new(); }
    graph[from].push(to);
}
for neighbors in &mut graph { neighbors.sort_unstable(); }
let mut parent = vec![usize::MAX; count];
let mut queue = std::collections::VecDeque::new();
parent[source] = source;
queue.push_back(source);
while let Some(node) = queue.pop_front() {
    if node == target { break; }
    for &next in &graph[node] {
        if parent[next] == usize::MAX { parent[next] = node; queue.push_back(next); }
    }
}
if parent[target] == usize::MAX { return Vec::new(); }
let mut path = vec![target];
while *path.last().unwrap() != source { path.push(parent[*path.last().unwrap()]); }
path.reverse();
path.iter().map(usize::to_string).collect::<Vec<_>>().join(",").into_bytes()
"#.trim().to_string() }

fn graph_b() -> String {
    graph_a()
        .replace("let mut queue = std::collections::VecDeque::new();", "let mut queue = Vec::with_capacity(count);\nlet mut head = 0usize;")
        .replace("queue.push_back(source);", "queue.push(source);")
        .replace("while let Some(node) = queue.pop_front() {", "while head < queue.len() {\n    let node = queue[head];\n    head += 1;")
        .replace("queue.push_back(next);", "queue.push(next);")
}
fn graph_dfs() -> String {
    graph_a()
        .replace("let mut queue = std::collections::VecDeque::new();", "let mut queue = Vec::new();")
        .replace("queue.push_back(source);", "queue.push(source);")
        .replace("while let Some(node) = queue.pop_front() {", "while let Some(node) = queue.pop() {")
        .replace("queue.push_back(next);", "queue.push(next);")
}
fn graph_reverse_ties() -> String { graph_a().replace("neighbors.sort_unstable();", "neighbors.sort_unstable_by(|left, right| right.cmp(left));") }
fn graph_endpoints_only() -> String {
    graph_a().replace(
        "path.iter().map(usize::to_string)",
        "path.iter().enumerate().filter(|(index, _)| *index == 0 || *index + 1 == path.len()).map(|(_, node)| node.to_string())",
    )
}
fn graph_false_source() -> String { graph_a().replace("if parent[target] == usize::MAX { return Vec::new(); }", "if parent[target] == usize::MAX { return source.to_string().into_bytes(); }") }

fn delta_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let mut previous = 0i64;
let mut output = Vec::new();
for field in text.split(',').filter(|field| !field.is_empty()) {
    let Ok(value) = field.parse::<i64>() else { return Vec::new(); };
    let delta = value.wrapping_sub(previous);
    let mut encoded = ((delta as u64) << 1) ^ ((delta >> 63) as u64);
    while encoded >= 0x80 { output.push((encoded as u8) | 0x80); encoded >>= 7; }
    output.push(encoded as u8);
    previous = value;
}
output
"#.trim().to_string() }

fn delta_b() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let values: Option<Vec<i64>> = text.split(',').filter(|field| !field.is_empty()).map(|field| field.parse().ok()).collect();
let Some(values) = values else { return Vec::new(); };
let mut output = Vec::new();
let mut previous = 0i64;
for value in values {
    let difference = value.wrapping_sub(previous);
    let sign = (difference >> 63) as u64;
    let mut word = ((difference as u64) << 1) ^ sign;
    loop {
        let low = (word & 0x7f) as u8;
        word >>= 7;
        output.push(low | if word == 0 { 0 } else { 0x80 });
        if word == 0 { break; }
    }
    previous = value;
}
output
"#.trim().to_string() }

fn delta_absolute() -> String { delta_a().replace("let delta = value.wrapping_sub(previous);", "let delta = value;") }
fn delta_unsigned() -> String { delta_a().replace("((delta as u64) << 1) ^ ((delta >> 63) as u64)", "delta as u64") }
fn delta_single_byte() -> String { delta_a().replace("while encoded >= 0x80 { output.push((encoded as u8) | 0x80); encoded >>= 7; }", "") }
fn delta_reverse() -> String { delta_a().replace("for field in text.split(',').filter(|field| !field.is_empty()) {", "for field in text.split(',').filter(|field| !field.is_empty()).rev() {") }

fn parser_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let mut total = 0i64;
for term in text.split('+') {
    let mut product = 1i64;
    for factor in term.split('*') {
        let Ok(value) = factor.parse::<i64>() else { return Vec::new(); };
        let Some(next) = product.checked_mul(value) else { return Vec::new(); };
        product = next;
    }
    let Some(next) = total.checked_add(product) else { return Vec::new(); };
    total = next;
}
total.to_string().into_bytes()
"#.trim().to_string() }

fn parser_b() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let mut sum = 0i64;
let mut product = 1i64;
let mut number = 0i64;
let mut has_digit = false;
for byte in text.bytes().chain(std::iter::once(b'+')) {
    if byte.is_ascii_digit() {
        let Some(next) = number.checked_mul(10).and_then(|value| value.checked_add(i64::from(byte - b'0'))) else { return Vec::new(); };
        number = next;
        has_digit = true;
    } else if byte == b'*' || byte == b'+' {
        if !has_digit { return Vec::new(); }
        let Some(next) = product.checked_mul(number) else { return Vec::new(); };
        product = next;
        number = 0;
        has_digit = false;
        if byte == b'+' { let Some(next_sum) = sum.checked_add(product) else { return Vec::new(); }; sum = next_sum; product = 1; }
    } else { return Vec::new(); }
}
sum.to_string().into_bytes()
"#.trim().to_string() }

fn parser_left_to_right() -> String {
    parser_a()
        .replace("for term in text.split('+') {", "let normalized = text.replace('*', \"+\");\nfor term in normalized.split('+') {")
        .replace("for factor in term.split('*') {", "for factor in term.split('+') {")
}
fn parser_reverse_precedence() -> String {
    parser_a()
        .replace("let mut total = 0i64;", "let normalized = text.replace('+', \"*\");\nlet mut total = 0i64;")
        .replace("for term in text.split('+') {", "for term in normalized.split('*') {")
        .replace("for factor in term.split('*') {", "for factor in term.split('+') {")
}
fn parser_first_digit() -> String {
    parser_a().replace(
        "factor.parse::<i64>()",
        "factor.as_bytes().first().copied().and_then(|byte| byte.checked_sub(b'0')).map(i64::from).unwrap_or(0)",
    )
}
fn parser_drop_last_term() -> String {
    parser_a().replace(
        "for term in text.split('+') {",
        "for term in text.split('+').take(text.matches('+').count()) {",
    )
}

fn window_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let Some((width_text, values_text)) = text.split_once('|') else { return Vec::new(); };
let Ok(width) = width_text.parse::<usize>() else { return Vec::new(); };
if width == 0 { return Vec::new(); }
let values: Option<Vec<i64>> = values_text.split(',').filter(|field| !field.is_empty()).map(|field| field.parse().ok()).collect();
let Some(values) = values else { return Vec::new(); };
if values.len() < width { return Vec::new(); }
let mut sum: i64 = values[..width].iter().sum();
let mut output = vec![sum.to_string()];
for index in width..values.len() { sum += values[index] - values[index - width]; output.push(sum.to_string()); }
output.join(",").into_bytes()
"#.trim().to_string() }

fn window_b() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let Some((width_text, values_text)) = text.split_once('|') else { return Vec::new(); };
let Ok(width) = width_text.parse::<usize>() else { return Vec::new(); };
if width == 0 { return Vec::new(); }
let values: Option<Vec<i64>> = values_text.split(',').filter(|field| !field.is_empty()).map(|field| field.parse().ok()).collect();
let Some(values) = values else { return Vec::new(); };
values.windows(width).map(|window| window.iter().sum::<i64>().to_string()).collect::<Vec<_>>().join(",").into_bytes()
"#.trim().to_string() }

fn window_partial() -> String { window_a().replace("if values.len() < width { return Vec::new(); }", "if values.is_empty() { return Vec::new(); }\nlet width = width.min(values.len());") }
fn window_chunks() -> String {
    window_a().replace(
        "for index in width..values.len() { sum += values[index] - values[index - width]; output.push(sum.to_string()); }",
        "for chunk in values[width..].chunks(width) { sum = chunk.iter().sum(); output.push(sum.to_string()); }",
    )
}
fn window_drop_final() -> String { window_a().replace("for index in width..values.len() {", "for index in width..values.len().saturating_sub(1) {") }
fn window_total_repeated() -> String { window_a().replace("sum += values[index] - values[index - width];", "sum += values[index];") }

fn frame_a() -> String { r#"
if input.len() < 3 { return Vec::new(); }
let length = u16::from_le_bytes([input[1], input[2]]) as usize;
if input.len() != 3 + length { return Vec::new(); }
input[3..].to_vec()
"#.trim().to_string() }

fn frame_b() -> String { r#"
let Some(header) = input.get(..3) else { return Vec::new(); };
let length = usize::from(u16::from_le_bytes([header[1], header[2]]));
let Some(payload) = input.get(3..3 + length) else { return Vec::new(); };
if payload.len() + 3 != input.len() { return Vec::new(); }
payload.to_vec()
"#.trim().to_string() }

fn frame_big_endian() -> String { frame_a().replace("u16::from_le_bytes", "u16::from_be_bytes") }
fn frame_allow_trailing() -> String { frame_a().replace("if input.len() != 3 + length { return Vec::new(); }", "if input.len() < 3 + length { return Vec::new(); }") }
fn frame_tag_zero_only() -> String { frame_a().replace("let length = u16::from_le_bytes", "if input[0] != 0 { return Vec::new(); }\nlet length = u16::from_le_bytes") }
fn frame_off_by_one() -> String { frame_a().replace("let length = u16::from_le_bytes([input[1], input[2]]) as usize;", "let length = u16::from_le_bytes([input[1], input[2]]) as usize + 1;") }

fn dependency_a() -> String { r#"
let Ok(text) = std::str::from_utf8(input) else { return Vec::new(); };
let Some((target_text, graph_text)) = text.split_once('|') else { return Vec::new(); };
let Ok(target) = target_text.parse::<usize>() else { return Vec::new(); };
let mut graph = std::collections::HashMap::<usize, Vec<usize>>::new();
for item in graph_text.split(';').filter(|item| !item.is_empty()) {
    let Some((node_text, deps_text)) = item.split_once(':') else { return Vec::new(); };
    let Ok(node) = node_text.parse::<usize>() else { return Vec::new(); };
    let mut deps = Vec::new();
    for dep in deps_text.split(',').filter(|dep| !dep.is_empty()) { let Ok(id) = dep.parse::<usize>() else { return Vec::new(); }; deps.push(id); }
    graph.insert(node, deps);
}
let mut seen = std::collections::HashSet::new();
let mut stack = graph.get(&target).cloned().unwrap_or_default();
while let Some(node) = stack.pop() {
    if node != target && seen.insert(node) { if let Some(deps) = graph.get(&node) { stack.extend(deps.iter().copied()); } }
}
let mut output: Vec<_> = seen.into_iter().collect();
output.sort_unstable();
output.iter().map(usize::to_string).collect::<Vec<_>>().join(",").into_bytes()
"#.trim().to_string() }

fn dependency_b() -> String {
    dependency_a()
        .replace("let mut stack = graph.get(&target).cloned().unwrap_or_default();\nwhile let Some(node) = stack.pop() {", "let mut stack = std::collections::VecDeque::from(graph.get(&target).cloned().unwrap_or_default());\nwhile let Some(node) = stack.pop_front() {")
}
fn dependency_direct_only() -> String { dependency_a().replace("if let Some(deps) = graph.get(&node) { stack.extend(deps.iter().copied()); }", "") }
fn dependency_duplicates() -> String { dependency_a().replace("if node != target && seen.insert(node) {", "if node != target { seen.insert(node);") }
fn dependency_reverse_sort() -> String { dependency_a().replace("output.sort_unstable();", "output.sort_unstable_by(|left, right| right.cmp(left));") }
fn dependency_drop_largest() -> String {
    dependency_a().replace(
        "output.iter().map(usize::to_string)",
        "output.iter().filter(|id| **id != *output.iter().max().unwrap_or(&usize::MAX)).map(usize::to_string)",
    )
}

