const WORKGROUP_WIDTH: u32 = 128u;
const MAX_CANDIDATES: u32 = 512u;
const INVALID_ID: u32 = 0xffffffffu;
const NEGATIVE_INFINITY: f32 = -3.402823466e+38;

struct TopKRecord {
    candidate_id: u32,
    score: f32,
}

struct Params {
    corpus_rows: u32,
    dimensions: u32,
    queries: u32,
    top_k: u32,
    dispatch_width: u32,
    minimum_similarity: f32,
    pad_0: u32,
    pad_1: u32,
}

@group(0) @binding(0) var<storage, read> corpus: array<f32>;
@group(0) @binding(1) var<storage, read> lexical_ranks: array<u32>;
@group(0) @binding(2) var<storage, read> query_vectors: array<f32>;
@group(0) @binding(3) var<storage, read> candidate_offsets: array<u32>;
@group(0) @binding(4) var<storage, read> candidate_ids: array<u32>;
@group(0) @binding(5) var<storage, read_write> output_records: array<TopKRecord>;
@group(0) @binding(6) var<storage, read_write> output_counts: array<u32>;
@group(0) @binding(7) var<storage, read> params: Params;

var<workgroup> shared_scores: array<f32, 512>;
var<workgroup> shared_ids: array<u32, 512>;
var<workgroup> shared_ranks: array<u32, 512>;

fn ranks_before(
    score: f32,
    candidate_id: u32,
    lexical_rank: u32,
    other_score: f32,
    other_id: u32,
    other_rank: u32,
) -> bool {
    return score > other_score
        || (score == other_score && lexical_rank < other_rank)
        || (score == other_score && lexical_rank == other_rank && candidate_id < other_id);
}

@compute @workgroup_size(128)
fn exact_cosine_top_k(
    @builtin(workgroup_id) workgroup: vec3<u32>,
    @builtin(local_invocation_id) local: vec3<u32>,
) {
    let query_index = workgroup.x + workgroup.y * params.dispatch_width;
    if (query_index >= params.queries) {
        return;
    }
    let candidate_start = candidate_offsets[query_index];
    let candidate_count = candidate_offsets[query_index + 1u] - candidate_start;

    var slot = local.x;
    while (slot < MAX_CANDIDATES) {
        shared_scores[slot] = NEGATIVE_INFINITY;
        shared_ids[slot] = INVALID_ID;
        shared_ranks[slot] = INVALID_ID;
        if (slot < candidate_count) {
            let candidate_id = candidate_ids[candidate_start + slot];
            let query_base = query_index * params.dimensions;
            let candidate_base = candidate_id * params.dimensions;
            var score = 0.0;
            var dimension = 0u;
            while (dimension < params.dimensions) {
                score = score + query_vectors[query_base + dimension]
                    * corpus[candidate_base + dimension];
                dimension = dimension + 1u;
            }
            score = clamp(score, -1.0, 1.0);
            if (score >= params.minimum_similarity) {
                shared_scores[slot] = score;
                shared_ids[slot] = candidate_id;
                shared_ranks[slot] = lexical_ranks[candidate_id];
            }
        }
        slot = slot + WORKGROUP_WIDTH;
    }
    workgroupBarrier();

    if (local.x == 0u) {
        let output_base = query_index * params.top_k;
        var rank = 0u;
        while (rank < params.top_k) {
            output_records[output_base + rank].candidate_id = INVALID_ID;
            output_records[output_base + rank].score = NEGATIVE_INFINITY;
            rank = rank + 1u;
        }
        var selected = 0u;
        while (selected < params.top_k) {
            var best_slot = INVALID_ID;
            var best_score = NEGATIVE_INFINITY;
            var best_id = INVALID_ID;
            var best_rank = INVALID_ID;
            var scan = 0u;
            while (scan < candidate_count) {
                let score = shared_scores[scan];
                let candidate_id = shared_ids[scan];
                let lexical_rank = shared_ranks[scan];
                if (candidate_id != INVALID_ID && ranks_before(
                    score,
                    candidate_id,
                    lexical_rank,
                    best_score,
                    best_id,
                    best_rank,
                )) {
                    best_slot = scan;
                    best_score = score;
                    best_id = candidate_id;
                    best_rank = lexical_rank;
                }
                scan = scan + 1u;
            }
            if (best_slot == INVALID_ID) {
                break;
            }
            output_records[output_base + selected].candidate_id = best_id;
            output_records[output_base + selected].score = best_score;
            shared_scores[best_slot] = NEGATIVE_INFINITY;
            shared_ids[best_slot] = INVALID_ID;
            shared_ranks[best_slot] = INVALID_ID;
            selected = selected + 1u;
        }
        output_counts[query_index] = selected;
    }
}
