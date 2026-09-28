#[path = "families/binary_frame.rs"]
pub mod binary_frame;
#[path = "families/delta_codec.rs"]
pub mod delta_codec;
#[path = "families/dependency_eval.rs"]
pub mod dependency_eval;
#[path = "families/graph_witness.rs"]
pub mod graph_witness;
#[path = "families/interval_index.rs"]
pub mod interval_index;
#[path = "families/parser_precedence.rs"]
pub mod parser_precedence;
#[path = "families/token_cursor.rs"]
pub mod token_cursor;
#[path = "families/window_fold.rs"]
pub mod window_fold;
pub mod segments;

pub const REPOSITORY_ID: &str = "e013-c-segmental";

pub fn dispatch(family_id: &str, input: &[u8]) -> Option<Vec<u8>> {
    let output = match family_id {
        "c.token-cursor" => token_cursor::solve(input),
        "c.interval-index" => interval_index::solve(input),
        "c.graph-witness" => graph_witness::solve(input),
        "c.delta-codec" => delta_codec::solve(input),
        "c.parser-precedence" => parser_precedence::solve(input),
        "c.window-fold" => window_fold::solve(input),
        "c.binary-frame" => binary_frame::solve(input),
        "c.dependency-eval" => dependency_eval::solve(input),
        _ => return None,
    };
    Some(output)
}
#![forbid(unsafe_code)]
