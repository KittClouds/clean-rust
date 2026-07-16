use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct CausalLensChunkConsumer;

impl LensChunkConsumer for CausalLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Causal
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens("phoenix-causal-post/causal", self.lens(), chunks, context)
    }
}
