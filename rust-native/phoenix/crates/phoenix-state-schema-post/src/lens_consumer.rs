use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct AttributeLensChunkConsumer;

impl LensChunkConsumer for AttributeLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Attribute
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens(
            "phoenix-state-schema-post/attribute",
            self.lens(),
            chunks,
            context,
        )
    }
}
