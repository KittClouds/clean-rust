use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct EntityLensChunkConsumer;

impl LensChunkConsumer for EntityLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Entity
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens("phoenix-er-post/entity", self.lens(), chunks, context)
    }
}
