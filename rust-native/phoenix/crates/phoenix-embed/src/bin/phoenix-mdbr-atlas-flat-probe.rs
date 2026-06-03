use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use phoenix_embed::{
    default_ort_dylib_path, workspace_root, OrtExecutionProviderPreference, OrtTextEmbedConfig,
    OrtTextEmbedder, TextEmbeddingBatch, TextEmbeddingInputPrefix, TextEmbeddingPooling,
    TextEmbeddingProfile,
};

const STOP_WORDS: &[&str] = &[
    "Chapter",
    "Table",
    "Contents",
    "The",
    "A",
    "An",
    "It",
    "He",
    "She",
    "They",
    "We",
    "I",
    "Of",
    "And",
    "But",
    "May",
    "That",
    "This",
    "These",
    "Those",
    "There",
    "Then",
    "When",
    "What",
    "Where",
    "Why",
    "How",
    "Who",
    "Whom",
    "Which",
    "With",
    "Without",
    "Within",
    "For",
    "From",
    "Into",
    "Onto",
    "Over",
    "Under",
    "After",
    "Before",
    "While",
    "Until",
    "His",
    "Her",
    "Their",
    "Your",
    "Our",
    "My",
    "Mine",
    "Yours",
    "Hers",
    "Theirs",
    "Its",
    "You",
    "Me",
    "Him",
    "Them",
    "Could",
    "Would",
    "Should",
    "Can",
    "Will",
    "Won",
    "Don",
    "Didn",
    "Wasn",
    "Isn",
    "Just",
    "Not",
    "Even",
    "Still",
    "Soon",
    "Better",
    "Thankfully",
    "Unfortunately",
    "Frankly",
    "Eventually",
    "According",
    "Unlike",
    "Owing",
    "Add",
    "Have",
    "Had",
    "Has",
    "Like",
    "Only",
    "Did",
    "One",
    "Since",
    "Having",
    "Good",
    "Probably",
    "Well",
    "Also",
    "Clearly",
    "Every",
    "Many",
    "Most",
    "None",
    "No",
    "Yes",
    "Yep",
    "Mmmm",
    "Eh",
    "Ah",
    "Maybe",
    "However",
    "All",
    "Although",
    "Instead",
    "Too",
    "Are",
    "Now",
    "More",
    "Less",
    "Once",
    "Outside",
    "Inside",
    "Again",
];

#[derive(Clone, Debug)]
struct Config {
    input_path: PathBuf,
    model_root: PathBuf,
    max_leaf_chars: usize,
    max_entities: usize,
    entity_context_chars: usize,
    batch_size: usize,
    leaf_top_k: usize,
    entity_top_k: usize,
    entity_leaf_top_k: usize,
    min_leaf_cosine: f32,
    min_entity_cosine: f32,
    min_entity_leaf_cosine: f32,
}

#[derive(Clone, Debug)]
struct Leaf {
    id: usize,
    chapter: String,
    text: String,
}

#[derive(Clone, Debug)]
struct EdgeScore {
    score: f32,
}

#[derive(Clone, Debug)]
struct NamedEdgeScore {
    source: String,
    target: String,
    score: f32,
}

#[derive(Clone, Debug)]
struct CoMentionEdge {
    source: String,
    target: String,
    shared_leaves: usize,
    score: f32,
}

#[derive(Clone, Debug)]
struct CandidateRelationEdge {
    score: f32,
}

#[derive(Clone, Debug)]
struct EntityVector {
    entity: String,
    mentions: Vec<usize>,
    vector: Vec<f32>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = parse_config();
    if env::var_os("ORT_DYLIB_PATH").is_none() {
        if let Some(path) = default_ort_dylib_path(&workspace_root()) {
            unsafe { env::set_var("ORT_DYLIB_PATH", path) };
        }
    }

    let total_started = Instant::now();
    let markdown = fs::read_to_string(&config.input_path)?;
    let leaves = chunk_markdown(&markdown, config.max_leaf_chars);
    let candidate_entities = extract_entities(&markdown)
        .into_iter()
        .take(160)
        .collect::<Vec<_>>();
    let mention_map = build_mention_map(&leaves, &candidate_entities);
    let entities = rank_entities(&candidate_entities, &mention_map)
        .into_iter()
        .take(config.max_entities)
        .collect::<Vec<_>>();
    let trimmed_mention_map = entities
        .iter()
        .map(|entity| {
            (
                entity.clone(),
                mention_map.get(entity).cloned().unwrap_or_default(),
            )
        })
        .collect::<HashMap<_, _>>();
    let entity_cards = entities
        .iter()
        .map(|entity| {
            build_entity_card(
                entity,
                &leaves,
                trimmed_mention_map
                    .get(entity)
                    .map(Vec::as_slice)
                    .unwrap_or(&[]),
                config.entity_context_chars,
            )
        })
        .collect::<Vec<_>>();

    let load_started = Instant::now();
    let embedder = OrtTextEmbedder::load(&OrtTextEmbedConfig {
        model_root: config.model_root.clone(),
        batch_size: config.batch_size,
        max_length: 512,
        profile: TextEmbeddingProfile::Native384,
        prefix_passage: false,
        pooling: TextEmbeddingPooling::Mean,
        input_prefix: TextEmbeddingInputPrefix::None,
        execution_provider: OrtExecutionProviderPreference::from_env(),
    })?;
    let model_load_ms = elapsed_ms(load_started);

    let leaf_texts = leaves
        .iter()
        .map(|leaf| leaf.text.as_str())
        .collect::<Vec<_>>();
    let leaf_started = Instant::now();
    let leaf_vectors = embedder.embed_slices_flat(&leaf_texts)?;
    let leaf_embed_ms = elapsed_ms(leaf_started);

    let entity_texts = entity_cards.iter().map(String::as_str).collect::<Vec<_>>();
    let entity_started = Instant::now();
    let entity_context_vectors = embedder.embed_slices_flat(&entity_texts)?;
    let entity_embed_ms = elapsed_ms(entity_started);

    let graph_started = Instant::now();
    let chapter_count = leaves
        .iter()
        .map(|leaf| leaf.chapter.as_str())
        .collect::<HashSet<_>>()
        .len();
    let leaf_edges = build_top_k_edges(&leaf_vectors, config.leaf_top_k, config.min_leaf_cosine);
    let entity_vectors = build_fused_entity_vectors(
        &leaf_vectors,
        &entity_context_vectors,
        &entities,
        &trimmed_mention_map,
    );
    let entity_edges = build_named_entity_edges(
        &entity_vectors,
        config.entity_top_k,
        config.min_entity_cosine,
    );
    let entity_leaf_edges = build_entity_leaf_edges(
        &entity_vectors,
        &leaf_vectors,
        config.entity_leaf_top_k,
        config.min_entity_leaf_cosine,
        &trimmed_mention_map,
    );
    let co_mention_edges = build_co_mention_edges(&trimmed_mention_map, 2);
    let candidate_relation_edges = build_candidate_relation_edges(&entity_edges, &co_mention_edges);
    let graph_build_ms = elapsed_ms(graph_started);

    let mention_edges = trimmed_mention_map.values().map(Vec::len).sum::<usize>();
    let hierarchy_edges = chapter_count + leaves.len();
    let sequence_edges = chapter_count.saturating_sub(1) + leaves.len().saturating_sub(1);
    let total_edges = hierarchy_edges
        + sequence_edges
        + mention_edges
        + leaf_edges.len()
        + entity_edges.len()
        + entity_leaf_edges.len()
        + co_mention_edges.len()
        + candidate_relation_edges.len();

    println!("ENGINE rust_mdbr_atlas_flat_probe");
    println!("DOC {}", config.input_path.display());
    println!("MODEL_ROOT {}", config.model_root.display());
    println!("POOLING mean");
    println!(
        "ORT_EP {}",
        OrtExecutionProviderPreference::from_env().label()
    );
    println!("DIMS {}", leaf_vectors.dims());
    println!(
        "CONFIG max_leaf_chars={} max_entities={} entity_context_chars={} batch_size={} leaf_top_k={} entity_top_k={} entity_leaf_top_k={}",
        config.max_leaf_chars,
        config.max_entities,
        config.entity_context_chars,
        config.batch_size,
        config.leaf_top_k,
        config.entity_top_k,
        config.entity_leaf_top_k
    );
    println!(
        "SPEED total_ms={:.3} model_load_ms={:.3} leaf_embed_ms={:.3} entity_embed_ms={:.3} total_embed_ms={:.3} ms_per_embedding={:.3} graph_build_ms={:.3}",
        elapsed_ms(total_started),
        model_load_ms,
        leaf_embed_ms,
        entity_embed_ms,
        leaf_embed_ms + entity_embed_ms,
        (leaf_embed_ms + entity_embed_ms) / (leaf_vectors.rows() + entity_context_vectors.rows()).max(1) as f64,
        graph_build_ms
    );
    println!(
        "GRAPH document_nodes=1 chapter_nodes={} leaf_nodes={} entity_nodes={} total_nodes={} hierarchy_edges={} sequence_edges={} mention_edges={} leaf_knn_edges={} entity_balanced_edges={} entity_leaf_semantic_edges={} co_mention_edges={} candidate_relation_edges={} total_edges={}",
        chapter_count,
        leaves.len(),
        entity_vectors.len(),
        1 + chapter_count + leaves.len() + entity_vectors.len(),
        hierarchy_edges,
        sequence_edges,
        mention_edges,
        leaf_edges.len(),
        entity_edges.len(),
        entity_leaf_edges.len(),
        co_mention_edges.len(),
        candidate_relation_edges.len(),
        total_edges
    );
    println!(
        "QUALITY avg_leaf_knn_score={:.3} avg_entity_similarity={:.3} avg_entity_leaf_score={:.3} entity_grounding_ratio={:.3}",
        average_edge_score(&leaf_edges),
        average_named_edge_score(&entity_edges),
        average_edge_score(&entity_leaf_edges),
        entity_vectors.iter().filter(|entity| !entity.mentions.is_empty()).count() as f32
            / entity_vectors.len().max(1) as f32
    );
    if let Some(edge) = candidate_relation_edges.first() {
        println!("TOP_CANDIDATE_RELATION score={:.3}", edge.score);
    }

    Ok(())
}

fn parse_config() -> Config {
    let root = workspace_root();
    let mut config = Config {
        input_path: root.join("docs").join("shortrun.md"),
        model_root: root
            .join("node_modules")
            .join("@huggingface")
            .join("transformers")
            .join(".cache")
            .join("MongoDB")
            .join("mdbr-leaf-mt"),
        max_leaf_chars: env_usize("MAX_LEAF_CHARS", 2200),
        max_entities: env_usize("MAX_ENTITIES", 70),
        entity_context_chars: env_usize("ENTITY_CONTEXT_CHARS", 950),
        batch_size: env_usize("BATCH_SIZE", 8),
        leaf_top_k: env_usize("LEAF_TOP_K", 4),
        entity_top_k: env_usize("ENTITY_TOP_K", 3),
        entity_leaf_top_k: env_usize("ENTITY_LEAF_TOP_K", 3),
        min_leaf_cosine: env_f32("MIN_LEAF_COSINE", 0.25),
        min_entity_cosine: env_f32("MIN_ENTITY_COSINE", 0.32),
        min_entity_leaf_cosine: env_f32("MIN_ENTITY_LEAF_COSINE", 0.28),
    };
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--model-root" => {
                if let Some(value) = args.next() {
                    config.model_root = PathBuf::from(value);
                }
            }
            "--max-entities" => {
                if let Some(value) = args.next().and_then(|value| value.parse::<usize>().ok()) {
                    config.max_entities = value;
                }
            }
            "--batch-size" => {
                if let Some(value) = args.next().and_then(|value| value.parse::<usize>().ok()) {
                    config.batch_size = value.max(1);
                }
            }
            value if !value.starts_with('-') => config.input_path = PathBuf::from(value),
            _ => {}
        }
    }
    config
}

fn env_usize(key: &str, default: usize) -> usize {
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(default)
}

fn env_f32(key: &str, default: f32) -> f32 {
    env::var(key)
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .unwrap_or(default)
}

fn chunk_markdown(text: &str, max_chars: usize) -> Vec<Leaf> {
    let mut sections = Vec::<(String, String)>::new();
    let mut heading = "Front Matter".to_owned();
    let mut body = String::new();
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("## Chapter ") && trimmed.contains(':') {
            if !body.trim().is_empty() {
                sections.push((heading, normalize_ws(&body)));
                body.clear();
            }
            heading = trimmed.trim_start_matches("## ").trim().to_owned();
        } else {
            body.push_str(line);
            body.push('\n');
        }
    }
    if !body.trim().is_empty() {
        sections.push((heading, normalize_ws(&body)));
    }

    let mut leaves = Vec::new();
    for (chapter, body) in sections {
        for segment in split_text(&body, max_chars) {
            if segment.trim().is_empty() {
                continue;
            }
            leaves.push(Leaf {
                id: leaves.len(),
                chapter: chapter.clone(),
                text: format!("{chapter}\n{segment}"),
            });
        }
    }
    leaves
}

fn normalize_ws(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn split_text(text: &str, max_chars: usize) -> Vec<String> {
    if text.len() <= max_chars {
        return vec![text.to_owned()];
    }
    let mut sentences = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        current.push(ch);
        if matches!(ch, '.' | '!' | '?') {
            sentences.push(std::mem::take(&mut current));
        }
    }
    if !current.trim().is_empty() {
        sentences.push(current);
    }

    let mut out = Vec::new();
    let mut chunk = String::new();
    for sentence in sentences {
        if chunk.len() + sentence.len() > max_chars && !chunk.trim().is_empty() {
            out.push(chunk.trim().to_owned());
            chunk.clear();
        }
        if sentence.len() > max_chars {
            out.extend(split_long_at_char_boundaries(&sentence, max_chars));
        } else {
            chunk.push_str(&sentence);
        }
    }
    if !chunk.trim().is_empty() {
        out.push(chunk.trim().to_owned());
    }
    out
}

fn split_long_at_char_boundaries(text: &str, max_chars: usize) -> Vec<String> {
    let mut out = Vec::new();
    let mut start = 0;
    while start < text.len() {
        let mut end = (start + max_chars).min(text.len());
        while end > start && !text.is_char_boundary(end) {
            end -= 1;
        }
        out.push(text[start..end].trim().to_owned());
        start = end;
    }
    out
}

fn extract_entities(text: &str) -> Vec<String> {
    let mut counts = HashMap::<String, usize>::new();
    let mut phrase = Vec::<String>::new();
    for raw in text.split_whitespace() {
        let token = clean_token(raw);
        if is_entity_token(&token) {
            phrase.push(token);
            continue;
        }
        flush_entity_phrase(&mut phrase, &mut counts);
    }
    flush_entity_phrase(&mut phrase, &mut counts);
    let mut entities = counts
        .into_iter()
        .filter(|(entity, count)| *count >= 2 && !is_stop(entity))
        .collect::<Vec<_>>();
    entities.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    entities.into_iter().map(|(entity, _)| entity).collect()
}

fn clean_token(raw: &str) -> String {
    raw.trim_matches(|ch: char| !ch.is_alphanumeric() && ch != '\'' && ch != '-')
        .trim_matches('-')
        .to_owned()
}

fn is_entity_token(token: &str) -> bool {
    if token.len() < 2 || token.contains('\'') {
        return false;
    }
    let mut chars = token.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (first.is_uppercase() || is_roman(token))
        && chars.all(|ch| ch.is_alphabetic() || ch == '-' || ch.is_ascii_digit())
}

fn is_roman(token: &str) -> bool {
    !token.is_empty() && token.chars().all(|ch| matches!(ch, 'I' | 'V' | 'X'))
}

fn flush_entity_phrase(phrase: &mut Vec<String>, counts: &mut HashMap<String, usize>) {
    if phrase.is_empty() {
        return;
    }
    let value = canonical_entity(&phrase.join(" "));
    if value.len() >= 3 && !is_stop(&value) {
        *counts.entry(value).or_default() += 1;
    }
    phrase.clear();
}

fn canonical_entity(value: &str) -> String {
    value
        .strip_prefix("The ")
        .or_else(|| value.strip_prefix("A "))
        .or_else(|| value.strip_prefix("An "))
        .unwrap_or(value)
        .trim()
        .to_owned()
}

fn is_stop(value: &str) -> bool {
    STOP_WORDS.contains(&value)
}

fn build_mention_map(leaves: &[Leaf], entities: &[String]) -> HashMap<String, Vec<usize>> {
    let mut map = entities
        .iter()
        .map(|entity| (entity.clone(), Vec::new()))
        .collect::<HashMap<_, _>>();
    for leaf in leaves {
        let lower = leaf.text.to_ascii_lowercase();
        for entity in entities {
            if contains_phrase(&lower, &entity.to_ascii_lowercase()) {
                if let Some(ids) = map.get_mut(entity) {
                    ids.push(leaf.id);
                }
            }
        }
    }
    map.retain(|_, ids| !ids.is_empty());
    map
}

fn contains_phrase(text: &str, phrase: &str) -> bool {
    let Some(index) = text.find(phrase) else {
        return false;
    };
    let before = if index == 0 {
        ' '
    } else {
        text[..index].chars().next_back().unwrap_or(' ')
    };
    let after_index = index + phrase.len();
    let after = text[after_index..].chars().next().unwrap_or(' ');
    !before.is_ascii_alphanumeric()
        && before != '_'
        && !after.is_ascii_alphanumeric()
        && after != '_'
}

fn rank_entities(entities: &[String], mention_map: &HashMap<String, Vec<usize>>) -> Vec<String> {
    let mut ranked = entities
        .iter()
        .filter(|entity| mention_map.get(*entity).map(Vec::len).unwrap_or_default() > 0)
        .cloned()
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| {
        entity_score(right, mention_map)
            .cmp(&entity_score(left, mention_map))
            .then_with(|| left.cmp(right))
    });
    ranked
}

fn entity_score(entity: &str, mention_map: &HashMap<String, Vec<usize>>) -> i32 {
    let mentions = mention_map.get(entity).map(Vec::len).unwrap_or_default() as i32;
    let multiword = if entity.contains(' ') { 7 } else { 0 };
    let proper = if entity
        .split_whitespace()
        .all(|part| part.chars().next().is_some_and(char::is_uppercase))
    {
        3
    } else {
        0
    };
    let noisy = if matches!(
        entity,
        "Blue"
            | "Black"
            | "White"
            | "Red"
            | "Green"
            | "Old"
            | "New"
            | "Little"
            | "Golden"
            | "Poor"
            | "Private"
            | "Security"
            | "Dad"
            | "Mom"
    ) {
        -8
    } else {
        0
    };
    mentions + multiword + proper + noisy
}

fn build_entity_card(
    entity: &str,
    leaves: &[Leaf],
    leaf_ids: &[usize],
    max_chars: usize,
) -> String {
    let snippets = leaf_ids
        .iter()
        .take(8)
        .filter_map(|leaf_id| leaves.get(*leaf_id))
        .map(|leaf| snippet_around(&leaf.text, entity, 180))
        .filter(|snippet| !snippet.is_empty())
        .collect::<Vec<_>>();
    let mut chapters = leaf_ids
        .iter()
        .filter_map(|leaf_id| leaves.get(*leaf_id).map(|leaf| leaf.chapter.clone()))
        .collect::<Vec<_>>();
    chapters.sort();
    chapters.dedup();
    chapters.truncate(6);
    let mut card = format!("Entity: {entity}\nMentions: {}\n", leaf_ids.len());
    if !chapters.is_empty() {
        card.push_str(&format!("Chapters: {}\n", chapters.join("; ")));
    }
    card.push_str("Context:\n");
    for snippet in snippets {
        card.push_str("- ");
        card.push_str(&snippet);
        card.push('\n');
    }
    truncate_at_char_boundary(&card, max_chars)
}

fn snippet_around(text: &str, entity: &str, radius: usize) -> String {
    let lower = text.to_ascii_lowercase();
    let entity_lower = entity.to_ascii_lowercase();
    let Some(index) = lower.find(&entity_lower) else {
        return truncate_at_char_boundary(text, radius * 2)
            .trim()
            .to_owned();
    };
    let start = index.saturating_sub(radius);
    let end = (index + entity.len() + radius).min(text.len());
    normalize_ws(&text[floor_char_boundary(text, start)..floor_char_boundary(text, end)])
}

fn truncate_at_char_boundary(text: &str, max_len: usize) -> String {
    if text.len() <= max_len {
        return text.to_owned();
    }
    text[..floor_char_boundary(text, max_len)].to_owned()
}

fn floor_char_boundary(text: &str, mut index: usize) -> usize {
    index = index.min(text.len());
    while index > 0 && !text.is_char_boundary(index) {
        index -= 1;
    }
    index
}

fn build_top_k_edges(vectors: &TextEmbeddingBatch, top_k: usize, min_score: f32) -> Vec<EdgeScore> {
    let mut seen = HashSet::<(usize, usize)>::new();
    let mut edges = Vec::new();
    for i in 0..vectors.rows() {
        let Some(left) = vectors.row(i) else {
            continue;
        };
        let mut scores = Vec::new();
        for j in 0..vectors.rows() {
            if i == j {
                continue;
            }
            let Some(right) = vectors.row(j) else {
                continue;
            };
            let score = cosine(left, right);
            if score >= min_score {
                scores.push((j, score));
            }
        }
        scores.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for (target, score) in scores.into_iter().take(top_k) {
            let low = i.min(target);
            let high = i.max(target);
            if seen.insert((low, high)) {
                edges.push(EdgeScore { score });
            }
        }
    }
    edges.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    edges
}

fn build_fused_entity_vectors(
    leaf_vectors: &TextEmbeddingBatch,
    entity_context_vectors: &TextEmbeddingBatch,
    entities: &[String],
    mention_map: &HashMap<String, Vec<usize>>,
) -> Vec<EntityVector> {
    let dims = leaf_vectors.dims();
    let mut global = vec![0.0; dims];
    for row in 0..leaf_vectors.rows() {
        if let Some(vector) = leaf_vectors.row(row) {
            for dim in 0..dims {
                global[dim] += vector[dim];
            }
        }
    }
    normalize_in_place(&mut global);

    let mut out = Vec::new();
    for (index, entity) in entities.iter().enumerate() {
        let mentions = mention_map.get(entity).cloned().unwrap_or_default();
        if mentions.is_empty() {
            continue;
        }
        let mut centroid = vec![0.0; dims];
        for leaf_id in &mentions {
            if let Some(vector) = leaf_vectors.row(*leaf_id) {
                for dim in 0..dims {
                    centroid[dim] += vector[dim];
                }
            }
        }
        for dim in 0..dims {
            centroid[dim] = centroid[dim] / mentions.len() as f32 - global[dim] * 0.72;
        }
        normalize_in_place(&mut centroid);
        let context_weight = if mentions.len() <= 2 {
            0.82
        } else if mentions.len() >= 20 {
            0.76
        } else {
            0.66
        };
        let centroid_weight = 1.0 - context_weight;
        let Some(context) = entity_context_vectors.row(index) else {
            continue;
        };
        let mut vector = vec![0.0; dims];
        for dim in 0..dims {
            vector[dim] = context[dim] * context_weight + centroid[dim] * centroid_weight;
        }
        normalize_in_place(&mut vector);
        out.push(EntityVector {
            entity: entity.clone(),
            mentions,
            vector,
        });
    }
    out
}

fn build_named_entity_edges(
    entity_vectors: &[EntityVector],
    top_k: usize,
    min_score: f32,
) -> Vec<NamedEdgeScore> {
    let mut seen = HashSet::<(usize, usize)>::new();
    let mut edges = Vec::new();
    for i in 0..entity_vectors.len() {
        let mut scores = Vec::new();
        for j in 0..entity_vectors.len() {
            if i == j {
                continue;
            }
            let score = cosine(&entity_vectors[i].vector, &entity_vectors[j].vector);
            if score >= min_score {
                scores.push((j, score));
            }
        }
        scores.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for (target, score) in scores.into_iter().take(top_k) {
            let low = i.min(target);
            let high = i.max(target);
            if seen.insert((low, high)) {
                edges.push(NamedEdgeScore {
                    source: entity_vectors[low].entity.clone(),
                    target: entity_vectors[high].entity.clone(),
                    score,
                });
            }
        }
    }
    edges.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    edges
}

fn build_entity_leaf_edges(
    entity_vectors: &[EntityVector],
    leaf_vectors: &TextEmbeddingBatch,
    top_k: usize,
    min_score: f32,
    mention_map: &HashMap<String, Vec<usize>>,
) -> Vec<EdgeScore> {
    let mut edges = Vec::new();
    for entity_vector in entity_vectors {
        let mentioned = mention_map
            .get(&entity_vector.entity)
            .map(|ids| ids.iter().copied().collect::<HashSet<_>>())
            .unwrap_or_default();
        let mut scores = Vec::new();
        for leaf_id in 0..leaf_vectors.rows() {
            if mentioned.contains(&leaf_id) {
                continue;
            }
            let Some(leaf_vector) = leaf_vectors.row(leaf_id) else {
                continue;
            };
            let score = cosine(&entity_vector.vector, leaf_vector);
            if score >= min_score {
                scores.push((leaf_id, score));
            }
        }
        scores.sort_by(|left, right| {
            right
                .1
                .partial_cmp(&left.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for (_leaf_id, score) in scores.into_iter().take(top_k) {
            edges.push(EdgeScore { score });
        }
    }
    edges.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    edges
}

fn build_co_mention_edges(
    mention_map: &HashMap<String, Vec<usize>>,
    min_shared_leaves: usize,
) -> Vec<CoMentionEdge> {
    let entries = mention_map
        .iter()
        .map(|(entity, ids)| (entity.clone(), ids.iter().copied().collect::<HashSet<_>>()))
        .collect::<Vec<_>>();
    let mut edges = Vec::new();
    for i in 0..entries.len() {
        for j in (i + 1)..entries.len() {
            let (left, left_ids) = &entries[i];
            let (right, right_ids) = &entries[j];
            let shared = left_ids.iter().filter(|id| right_ids.contains(id)).count();
            if shared >= min_shared_leaves {
                let denom = ((left_ids.len() * right_ids.len()) as f32).sqrt().max(1.0);
                edges.push(CoMentionEdge {
                    source: left.clone(),
                    target: right.clone(),
                    shared_leaves: shared,
                    score: shared as f32 / denom,
                });
            }
        }
    }
    edges.sort_by(|left, right| {
        right.shared_leaves.cmp(&left.shared_leaves).then_with(|| {
            right
                .score
                .partial_cmp(&left.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
    });
    edges.truncate(220);
    edges
}

fn build_candidate_relation_edges(
    entity_edges: &[NamedEdgeScore],
    co_mention_edges: &[CoMentionEdge],
) -> Vec<CandidateRelationEdge> {
    let mut by_pair = HashMap::<String, (f32, f32, usize)>::new();
    for edge in entity_edges {
        by_pair.insert(pair_key(&edge.source, &edge.target), (edge.score, 0.0, 0));
    }
    for edge in co_mention_edges {
        let entry = by_pair
            .entry(pair_key(&edge.source, &edge.target))
            .or_insert((0.0, 0.0, 0));
        entry.1 = entry.1.max(edge.score.min(1.0));
        entry.2 = entry.2.max(edge.shared_leaves);
    }
    let mut edges = by_pair
        .into_values()
        .filter_map(|(semantic, co_mention, shared_leaves)| {
            let score = semantic * 0.62 + co_mention * 0.38;
            (score >= 0.30 && (semantic >= 0.32 || shared_leaves >= 2))
                .then_some(CandidateRelationEdge { score })
        })
        .collect::<Vec<_>>();
    edges.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    edges.truncate(180);
    edges
}

fn pair_key(left: &str, right: &str) -> String {
    if left <= right {
        format!("{left}\0{right}")
    } else {
        format!("{right}\0{left}")
    }
}

fn cosine(left: &[f32], right: &[f32]) -> f32 {
    left.iter().zip(right.iter()).map(|(a, b)| a * b).sum()
}

fn normalize_in_place(values: &mut [f32]) {
    let norm = values
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt()
        .max(1e-12);
    for value in values {
        *value /= norm;
    }
}

fn average_edge_score(edges: &[EdgeScore]) -> f32 {
    if edges.is_empty() {
        return 0.0;
    }
    edges.iter().map(|edge| edge.score).sum::<f32>() / edges.len() as f32
}

fn average_named_edge_score(edges: &[NamedEdgeScore]) -> f32 {
    if edges.is_empty() {
        return 0.0;
    }
    edges.iter().map(|edge| edge.score).sum::<f32>() / edges.len() as f32
}

fn elapsed_ms(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1000.0
}
