use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct WorldProjectionLensChunkConsumer;

impl LensChunkConsumer for WorldProjectionLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Worldbuilding
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens(
            "phoenix-graph-post/world-projection",
            self.lens(),
            chunks,
            context,
        )
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct EvidenceProjectionLensChunkConsumer;

impl LensChunkConsumer for EvidenceProjectionLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Evidence
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens(
            "phoenix-graph-post/evidence-projection",
            self.lens(),
            chunks,
            context,
        )
    }
}
