use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct EventLensChunkConsumer;

impl LensChunkConsumer for EventLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Event
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens(
            "phoenix-event-identity-post/event",
            self.lens(),
            chunks,
            context,
        )
    }
}
