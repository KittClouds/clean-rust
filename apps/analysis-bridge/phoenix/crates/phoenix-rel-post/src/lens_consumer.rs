use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct RelationshipLensChunkConsumer;

impl LensChunkConsumer for RelationshipLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Relationship
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens(
            "phoenix-rel-post/relationship",
            self.lens(),
            chunks,
            context,
        )
    }
}
