use phoenix_chunker_native::{
    build_graph_delta_for_lens, ChunkLens, GraphBuildContext, GraphDelta, LensChunk,
    LensChunkConsumer,
};

#[derive(Clone, Copy, Debug, Default)]
pub struct WorldbuildingLensChunkConsumer;

impl LensChunkConsumer for WorldbuildingLensChunkConsumer {
    fn lens(&self) -> ChunkLens {
        ChunkLens::Worldbuilding
    }

    fn consume(&self, chunks: &[LensChunk], context: GraphBuildContext) -> GraphDelta {
        build_graph_delta_for_lens(
            "phoenix-memory-post/worldbuilding",
            self.lens(),
            chunks,
            context,
        )
    }
}
