export type AtlasCapabilityFamily =
    | 'surface'
    | 'entity'
    | 'graph'
    | 'semantic'
    | 'reasoning'
    | 'manifold'
    | 'retrieval'
    | 'visualization';

export type AtlasCapabilityCost =
    | 'Very low'
    | 'Low'
    | 'Low-Med'
    | 'Medium'
    | 'Med-High'
    | 'High'
    | 'Very high'
    | 'Render';

export type AtlasCapabilityMutationPolicy =
    | 'read-only'
    | 'dirty-only'
    | 'force rebuild'
    | 'model warm'
    | 'native-only'
    | 'not wired';

export type AtlasCapabilityUiCoverage = 'wired' | 'partial' | 'sleeping';

export type AtlasGraphTargetId =
    | 'mention'
    | 'evidence'
    | 'surface'
    | 'kernel'
    | 'relation'
    | 'temporal'
    | 'eventIdentity'
    | 'memoryState'
    | 'causal'
    | 'semanticAtlas'
    | 'semanticCandidate'
    | 'galaxy';

export type AtlasRecipeId =
    | 'textGraph'
    | 'semanticGraph'
    | 'adjudicatedSemanticGraph'
    | 'reasoningGraph'
    | 'runNer';

export type AtlasModelLaneId =
    | 'dynamicNer'
    | 'coOccurrence'
    | 'semanticEmbedding'
    | 'nli'
    | 'manifoldProjection';

export type AtlasCapabilityId =
    | 'dynamicSurface'
    | 'dynamicChunking'
    | 'dynamicNer'
    | 'mentionGraph'
    | 'evidenceGraph'
    | 'surfaceGraph'
    | 'assertedKernel'
    | 'relationGraph'
    | 'temporalGraph'
    | 'eventIdentity'
    | 'memoryState'
    | 'causalGraph'
    | 'semanticEmbedding'
    | 'semanticAtlas'
    | 'semanticCandidate'
    | 'nliAdjudication'
    | 'hybridManifold'
    | 'hopfProjection'
    | 'lorentzForest'
    | 'productManifold'
    | 'retrievalWalk'
    | 'galaxyVisualization';

export type AtlasCapabilityLayerId =
    | 'textSurface'
    | 'entityMention'
    | 'graphCommit'
    | 'reasoningGraphs'
    | 'semanticAdjudication'
    | 'manifoldGeometry'
    | 'retrievalVisualization';

export const ATLAS_GRAPH_BUILD_RECIPE_IDS: AtlasRecipeId[] = [
    'textGraph',
    'semanticGraph',
    'adjudicatedSemanticGraph',
    'reasoningGraph',
];

export interface AtlasCapability {
    id: AtlasCapabilityId;
    label: string;
    family: AtlasCapabilityFamily;
    description: string;
    cost: AtlasCapabilityCost;
    subsystems: number;
    statusSource: string;
    backendRoute: string;
    inputs: string[];
    outputs: string[];
    dependencies: AtlasCapabilityId[];
    skips: AtlasCapabilityId[];
    mutationPolicy: AtlasCapabilityMutationPolicy;
    uiCoverage: AtlasCapabilityUiCoverage;
    runnable: boolean;
    modelLaneId?: AtlasModelLaneId;
    graphTargetId?: AtlasGraphTargetId;
    graphTargetLabel?: string;
    stageSummaryKeys?: string[];
    testRefs: string[];
    docRefs: string[];
}

export interface AtlasCapabilityLayer {
    id: AtlasCapabilityLayerId;
    label: string;
    description: string;
    capabilityIds: AtlasCapabilityId[];
}

export interface AtlasCapabilityRecipeDefinition {
    id: AtlasRecipeId;
    label: string;
    subtitle: string;
    description: string;
    actionLabel: string;
    icon: string;
    primary?: boolean;
    outputLabel: string;
    mutationPolicy: AtlasCapabilityMutationPolicy;
    cost: AtlasCapabilityCost;
    backendRoute: string;
    dependencyChain: AtlasCapabilityId[];
    requiredCapabilities: AtlasCapabilityId[];
    optionalCapabilities: AtlasCapabilityId[];
    skippedCapabilities: AtlasCapabilityId[];
    requiredLanes: AtlasModelLaneId[];
    optionalLanes: AtlasModelLaneId[];
    skippedLanes: AtlasModelLaneId[];
}

export const ATLAS_MODEL_LANE_LABELS: Record<AtlasModelLaneId, string> = {
    dynamicNer: 'Dynamic NER',
    coOccurrence: 'Co-occurrence',
    semanticEmbedding: 'Semantic Embedding',
    nli: 'NLI',
    manifoldProjection: 'Manifold Projection',
};

export const ATLAS_CAPABILITY_REGISTRY: AtlasCapability[] = [
    {
        id: 'dynamicSurface',
        label: 'Dynamic Text Surface',
        family: 'surface',
        description: 'Native surface compile over notes: normalized text, token tables, sentences, clauses, phrases, quotes, and speaker cues.',
        cost: 'Low',
        subsystems: 3,
        statusSource: 'machine.stage.surface + AtlasRichScanResult.stageSummaries.surface',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan surface route',
        inputs: ['scope notes', 'plain text'],
        outputs: ['tokens', 'sentences', 'clauses', 'surface units'],
        dependencies: [],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        stageSummaryKeys: ['surface', 'dynamicSurface'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['rust/phoenix/crates/phoenix-types/src/deterministic.rs', 'rust/phoenix/crates/phoenix-chunker/src/lib.rs'],
    },
    {
        id: 'dynamicChunking',
        label: 'Dynamic Chunking',
        family: 'surface',
        description: 'Sentence-aware chunk/lens production used by text graph commits and semantic atlas sidecars.',
        cost: 'Low',
        subsystems: 3,
        statusSource: 'AtlasRichScanResult.lensChunkCounts + runtime chunk defaults',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan chunk route',
        inputs: ['surface units', 'sentence boundaries'],
        outputs: ['lens chunks', 'chunk ids', 'leaf candidates'],
        dependencies: ['dynamicSurface'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        stageSummaryKeys: ['surface', 'chunking'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['rust/phoenix/crates/phoenix-chunker/src/sentence.rs'],
    },
    {
        id: 'dynamicNer',
        label: 'Dynamic NER',
        family: 'entity',
        description: 'BI-small dynamic NER candidate pass plus review lane hydration for selected scope text and Atlas surface suggestions.',
        cost: 'Medium',
        subsystems: 4,
        statusSource: 'NerService.providerStatuses.dynamic_ner + AtlasRichScanResult.candidateSuggestions',
        backendRoute: 'NerService.runDynamicScan / phoenix-dynamic-ner',
        inputs: ['plain text', 'surface chunks'],
        outputs: ['candidate entities', 'review suggestions'],
        dependencies: ['dynamicSurface'],
        skips: [],
        mutationPolicy: 'model warm',
        uiCoverage: 'wired',
        runnable: true,
        modelLaneId: 'dynamicNer',
        stageSummaryKeys: ['dynamicNer', 'surface'],
        testRefs: ['atlas-model-recipe.model.spec.ts', 'search-panel.component.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-dynamic-ner/src/lib.rs', 'src/app/services/ner.service.ts'],
    },
    {
        id: 'mentionGraph',
        label: 'Mention / Co-occurrence Graph',
        family: 'entity',
        description: 'Mention spans, normalized surfaces, resolver links, and co-occurrence edges used by the text graph path.',
        cost: 'Very low',
        subsystems: 2,
        statusSource: 'machine.stage.evidenceGraph + graph audit node/edge counts',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan mention route',
        inputs: ['surface chunks', 'dynamic NER candidates'],
        outputs: ['mentions', 'resolver links', 'local mention edges'],
        dependencies: ['dynamicSurface', 'dynamicChunking', 'dynamicNer'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        modelLaneId: 'coOccurrence',
        graphTargetId: 'mention',
        graphTargetLabel: 'Mention Graph',
        stageSummaryKeys: ['evidenceGraph', 'mentionGraph', 'graph-delta'],
        testRefs: ['search-panel.model.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-machine/src/lib.rs'],
    },
    {
        id: 'evidenceGraph',
        label: 'Evidence Graph',
        family: 'graph',
        description: 'Mention candidates, evidence edges, fusion decisions, and graph patch operations for committed graph deltas.',
        cost: 'Low',
        subsystems: 3,
        statusSource: 'graph audit graphEdges + AtlasRichScanResult.graphDeltaCounts',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan evidence route',
        inputs: ['mentions', 'surface chunks'],
        outputs: ['evidence edges', 'graph patch ops'],
        dependencies: ['mentionGraph'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        graphTargetId: 'evidence',
        graphTargetLabel: 'Evidence Graph',
        stageSummaryKeys: ['evidenceGraph', 'graph-delta'],
        testRefs: ['atlas-command-status.model.spec.ts', 'search-panel.model.spec.ts'],
        docRefs: ['src/app/services/graph-audit.service.ts'],
    },
    {
        id: 'surfaceGraph',
        label: 'Surface Graph',
        family: 'graph',
        description: 'Document, chunk, entity, mention, and local topology layer that feeds asserted kernel commits.',
        cost: 'Low-Med',
        subsystems: 4,
        statusSource: 'graph audit nodeKinds.leaf/chunk + committed graph counts',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan topology route',
        inputs: ['surface units', 'mentions', 'evidence edges'],
        outputs: ['document nodes', 'chunk nodes', 'mention topology'],
        dependencies: ['dynamicChunking', 'evidenceGraph'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        graphTargetId: 'surface',
        graphTargetLabel: 'Surface Graph',
        stageSummaryKeys: ['surfaceGraph', 'overgraph'],
        testRefs: ['search-panel.model.spec.ts'],
        docRefs: ['src/app/services/phoenix-ui-api.service.ts'],
    },
    {
        id: 'assertedKernel',
        label: 'Asserted Kernel',
        family: 'graph',
        description: 'Committed graph layer for durable entities, claims, states, events, and evidence-backed kernel edges.',
        cost: 'Medium',
        subsystems: 6,
        statusSource: 'machine.stage.overgraph + graph audit graphNodes/graphEdges',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan asserted-kernel route',
        inputs: ['surface graph', 'evidence graph'],
        outputs: ['committed vertices', 'kernel edges', 'audit snapshot'],
        dependencies: ['surfaceGraph', 'evidenceGraph'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        graphTargetId: 'kernel',
        graphTargetLabel: 'Asserted Kernel',
        stageSummaryKeys: ['overgraph', 'assertedKernel'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['src/app/services/phoenix-machine-control.service.ts', 'rust-native/phoenix/crates/phoenix-store-overgraph/src/graph_topology.rs'],
    },
    {
        id: 'relationGraph',
        label: 'Relation Graph',
        family: 'reasoning',
        description: 'Read-only native candidate-edge probe for entity-to-entity relation rows after Semantic Atlas and NLI adjudication.',
        cost: 'Medium',
        subsystems: 6,
        statusSource: 'AtlasRichScanResult.relationCandidateCount + relation sidecar stores',
        backendRoute: 'PhoenixBackendService.storeCommand relation:list(graph_candidate_edges)',
        inputs: ['NLI judgments', 'semantic candidates', 'sentence syntax'],
        outputs: ['candidate edge rows', 'relation probe samples'],
        dependencies: ['nliAdjudication'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        graphTargetId: 'relation',
        graphTargetLabel: 'Relation Graph',
        stageSummaryKeys: ['relations', 'relationGraph'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-store-native-core/src/scope_runtime.rs'],
    },
    {
        id: 'temporalGraph',
        label: 'Temporal Graph',
        family: 'reasoning',
        description: 'Read-only native graph edge probe for active-during temporal rows; temporal extraction/review batches are not exposed as a Search Panel run recipe yet.',
        cost: 'Med-High',
        subsystems: 7,
        statusSource: 'PhoenixBackendService.storeCommand relation:list(graph_edges edge_type=active_during)',
        backendRoute: 'PhoenixBackendService.storeCommand relation:list(graph_edges, edge_type=active_during)',
        inputs: ['graph_edges relation', 'active_during edge type'],
        outputs: ['temporal edge rows', 'probe samples'],
        dependencies: ['eventIdentity'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        graphTargetId: 'temporal',
        graphTargetLabel: 'Temporal Graph',
        stageSummaryKeys: ['temporal', 'timeBinding'],
        testRefs: ['atlas-capability.model.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-temporal-post/src/api.rs', 'rust-native/phoenix/crates/phoenix-temporal-post/src/normalize.rs'],
    },
    {
        id: 'eventIdentity',
        label: 'Event Identity',
        family: 'reasoning',
        description: 'Read-only native semantic prototype probe for event-like nodes; canonical event identity resolution is not exposed as a Search Panel run recipe yet.',
        cost: 'Med-High',
        subsystems: 7,
        statusSource: 'PhoenixBackendService.storeCommand relation:list(semantic_node_prototypes node_kind=event)',
        backendRoute: 'PhoenixBackendService.storeCommand relation:list(semantic_node_prototypes, node_kind=event)',
        inputs: ['semantic_node_prototypes relation', 'event node kind'],
        outputs: ['event prototype rows', 'probe samples'],
        dependencies: ['relationGraph'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        graphTargetId: 'eventIdentity',
        graphTargetLabel: 'Event Identity',
        stageSummaryKeys: ['eventIdentity'],
        testRefs: ['atlas-capability.model.spec.ts'],
        docRefs: ['rust/phoenix/crates/phoenix-types/src/deterministic.rs', 'rust-native/phoenix/crates/phoenix-store-native-core/src/scope_runtime.rs'],
    },
    {
        id: 'memoryState',
        label: 'Memory / State',
        family: 'reasoning',
        description: 'Read-only native memories relation probe for durable memory rows; state schema extraction and continuity mutation passes are not exposed as Search Panel recipes yet.',
        cost: 'High',
        subsystems: 8,
        statusSource: 'PhoenixBackendService.storeCommand relation:list(memories)',
        backendRoute: 'PhoenixBackendService.storeCommand relation:list(memories)',
        inputs: ['memories relation'],
        outputs: ['memory rows', 'probe samples'],
        dependencies: ['eventIdentity', 'temporalGraph'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        graphTargetId: 'memoryState',
        graphTargetLabel: 'Memory / State',
        stageSummaryKeys: ['memory', 'stateSchema'],
        testRefs: ['atlas-capability.model.spec.ts'],
        docRefs: ['rust/phoenix/crates/phoenix-types/src/deterministic.rs', 'rust-native/phoenix/crates/phoenix-state-schema-post/src/lib.rs'],
    },
    {
        id: 'causalGraph',
        label: 'Causal Graph',
        family: 'reasoning',
        description: 'Read-only native graph edge probe for causal-link rows after event identity and temporal graph passes.',
        cost: 'High',
        subsystems: 9,
        statusSource: 'PhoenixBackendService.storeCommand relation:list(graph_edges edge_type=causal_link)',
        backendRoute: 'PhoenixBackendService.storeCommand relation:list(graph_edges, edge_type=causal_link)',
        inputs: ['graph_edges relation', 'causal_link edge type'],
        outputs: ['causal edge rows', 'probe samples'],
        dependencies: ['eventIdentity', 'temporalGraph', 'memoryState'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        graphTargetId: 'causal',
        graphTargetLabel: 'Causal Graph',
        stageSummaryKeys: ['causal', 'causality'],
        testRefs: ['atlas-capability.model.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-causal-post/src/api.rs', 'rust-native/phoenix/crates/phoenix-graph-post/src/compile.rs'],
    },
    {
        id: 'semanticEmbedding',
        label: 'Semantic Embedding',
        family: 'semantic',
        description: 'Local embedding model warm/index lane for leaf, entity-context, and lens vectors.',
        cost: 'High',
        subsystems: 5,
        statusSource: 'PhoenixMachineVectorStatus + AtlasRichScanResult.embeddingCounts',
        backendRoute: 'PhoenixMachineControlService.loadSemanticModel (model warm only)',
        inputs: ['committed graph', 'surface text'],
        outputs: ['leaf vectors', 'entity vectors', 'lens vectors'],
        dependencies: ['assertedKernel'],
        skips: [],
        mutationPolicy: 'model warm',
        uiCoverage: 'wired',
        runnable: true,
        modelLaneId: 'semanticEmbedding',
        stageSummaryKeys: ['embeddings', 'semanticEmbedding'],
        testRefs: ['atlas-model-recipe.model.spec.ts', 'search-panel.component.spec.ts'],
        docRefs: ['src/app/services/phoenix-ui-api.service.ts', 'rust-native/phoenix'],
    },
    {
        id: 'semanticAtlas',
        label: 'Semantic Atlas Sidecar',
        family: 'semantic',
        description: 'Hierarchy, surface candidates, leaf/entity-context embeddings, and candidate relation output under the rich scan budget.',
        cost: 'High',
        subsystems: 8,
        statusSource: 'AtlasRichScanResult.embeddingCounts + graphDeltaCounts',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan embedding route',
        inputs: ['asserted kernel', 'embedding model'],
        outputs: ['semantic sidecar rows', 'embedding atlas vectors'],
        dependencies: ['assertedKernel', 'semanticEmbedding'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        graphTargetId: 'semanticAtlas',
        graphTargetLabel: 'Embedding Atlas',
        stageSummaryKeys: ['embeddings', 'semanticAtlas'],
        testRefs: ['atlas-command-status.model.spec.ts', 'atlas-model-recipe.model.spec.ts'],
        docRefs: ['src/app/services/phoenix-ui-api.service.ts', 'src/app/services/atlas-scan-coordinator.service.ts'],
    },
    {
        id: 'semanticCandidate',
        label: 'Semantic Candidate Graph',
        family: 'semantic',
        description: 'ANN/hybrid-space candidate semantic edges and relation candidates emitted by the Semantic Atlas dirty-only scan and ready for adjudication.',
        cost: 'Very high',
        subsystems: 10,
        statusSource: 'AtlasRichScanResult.graphDeltaCounts.candidateEdges + relationCandidateCount',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan candidate route',
        inputs: ['semantic atlas vectors', 'hybrid manifold', 'relation candidates'],
        outputs: ['candidate semantic edges', 'candidate relation edges'],
        dependencies: ['semanticAtlas'],
        skips: [],
        mutationPolicy: 'dirty-only',
        uiCoverage: 'sleeping',
        runnable: false,
        graphTargetId: 'semanticCandidate',
        graphTargetLabel: 'Semantic Candidate',
        stageSummaryKeys: ['semanticCandidate', 'candidateRelations'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['src/app/services/phoenix-ui-api.service.ts'],
    },
    {
        id: 'nliAdjudication',
        label: 'NLI Adjudication',
        family: 'semantic',
        description: 'ModernBERT NLI lane that lists native candidate-edge judgment inputs, classifies entailment/neutral/contradiction, and applies native judgments.',
        cost: 'High',
        subsystems: 5,
        statusSource: 'NliWorkerService model state + semantic:listNliJudgmentInputs',
        backendRoute: 'semantic:listNliJudgmentInputs → NliWorkerService.classifyStream → semantic:applyNliJudgments',
        inputs: ['semantic candidates', 'text pairs'],
        outputs: ['candidate-edge NLI judgments', 'entailment scores', 'contradiction flags'],
        dependencies: ['semanticCandidate'],
        skips: [],
        mutationPolicy: 'native-only',
        uiCoverage: 'partial',
        runnable: true,
        modelLaneId: 'nli',
        stageSummaryKeys: ['nli', 'adjudication'],
        testRefs: ['atlas-model-recipe.model.spec.ts'],
        docRefs: ['src/app/lib/services/nli-worker.service.ts', 'src/app/lib/nli/nli-utils.spec.ts'],
    },
    {
        id: 'hybridManifold',
        label: 'Hybrid Embedding Manifold',
        family: 'manifold',
        description: 'Canonical embedding manifold over semantic atlas vectors; owns the declared metric and neighborhood construction for candidate-only semantic topology.',
        cost: 'High',
        subsystems: 6,
        statusSource: 'PhoenixMachineManifoldStatusMap.hybrid',
        backendRoute: 'manifoldSnapshot(hybrid) / phoenix-hyperbolic',
        inputs: ['semantic atlas vectors'],
        outputs: ['embedding space contract', 'cosine top-k semantic neighborhoods', 'candidate-only topology hints'],
        dependencies: ['semanticAtlas'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'wired',
        runnable: true,
        modelLaneId: 'manifoldProjection',
        stageSummaryKeys: ['hybrid'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-hyperbolic/src/hybrid_space.rs', 'src/app/services/manifold-atlas.types.ts'],
    },
    {
        id: 'hopfProjection',
        label: 'Hopf Projection',
        family: 'manifold',
        description: 'Hopf/S3 projection lane for semantic atlas visualization and phase/fiber analysis.',
        cost: 'High',
        subsystems: 6,
        statusSource: 'PhoenixMachineManifoldStatusMap.hopf',
        backendRoute: 'manifoldSnapshot(hopf) / phoenix-hyperbolic',
        inputs: ['semantic atlas vectors'],
        outputs: ['Hopf fibers', 'phase projection'],
        dependencies: ['semanticAtlas'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'wired',
        runnable: true,
        modelLaneId: 'manifoldProjection',
        stageSummaryKeys: ['hopf'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['rust-native/phoenix/crates/phoenix-hyperbolic/src/sphere.rs', 'src/app/services/manifold-atlas.types.ts'],
    },
    {
        id: 'lorentzForest',
        label: 'Lorentz Forest',
        family: 'manifold',
        description: 'Hyperbolic forest over identity, relationship, location, event, temporal, causal, evidence, contradiction, and abstraction trees.',
        cost: 'Very high',
        subsystems: 9,
        statusSource: 'PhoenixMachineManifoldStatusMap.lorentz + LorentzForestBuildResponse',
        backendRoute: 'manifoldSnapshot(lorentz) / Lorentz forest sidecar query',
        inputs: ['semantic atlas vectors', 'graph target kinds'],
        outputs: ['Lorentz trees', 'memberships', 'hierarchical query hits'],
        dependencies: ['semanticAtlas', 'semanticCandidate'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        modelLaneId: 'manifoldProjection',
        stageSummaryKeys: ['lorentz', 'lorentzForest'],
        testRefs: ['atlas-command-status.model.spec.ts'],
        docRefs: ['src/app/services/manifold-atlas.types.ts'],
    },
    {
        id: 'productManifold',
        label: 'Product Manifold',
        family: 'manifold',
        description: 'Canonical Lorentz-Hopf product atlas with Klein skeleton, semantic shell, and context fibers.',
        cost: 'Very high',
        subsystems: 11,
        statusSource: 'PhoenixMachineManifoldStatusMap.product',
        backendRoute: 'manifoldSnapshot(product) / Lorentz-Hopf product atlas',
        inputs: ['semantic atlas vectors', 'Lorentz forest sidecar', 'Hopf fiber topology'],
        outputs: ['product points', 'Klein skeleton', 'fiber ribbons', 'directed lane hints'],
        dependencies: ['semanticAtlas', 'semanticCandidate'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'partial',
        runnable: true,
        modelLaneId: 'manifoldProjection',
        stageSummaryKeys: ['product', 'productManifold'],
        testRefs: ['graph-galaxy-product.spec.ts'],
        docRefs: ['rust/phoenix/crates/phoenix-hyperbolic/src/product_manifold.rs', 'src/app/services/manifold-atlas.types.ts'],
    },
    {
        id: 'retrievalWalk',
        label: 'Retrieval / Triverse Walk',
        family: 'retrieval',
        description: 'Query-time lexical, semantic, graph, entity, and evidence lanes over committed graph and sidecars.',
        cost: 'Low-Med',
        subsystems: 5,
        statusSource: 'RetrievalWorkbenchStateService.activeLanes',
        backendRoute: 'PhoenixUiApi.searchScoped / graph walk read path',
        inputs: ['query text', 'selected lanes'],
        outputs: ['ranked results', 'source lane labels'],
        dependencies: ['assertedKernel'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'wired',
        runnable: true,
        stageSummaryKeys: ['retrieval'],
        testRefs: ['search-panel.component.spec.ts'],
        docRefs: ['src/app/services/retrieval-workbench-state.service.ts'],
    },
    {
        id: 'galaxyVisualization',
        label: 'Galaxy Visualization',
        family: 'visualization',
        description: 'Read-only projection/render graph from the current kernel snapshot and graph lens focus.',
        cost: 'Render',
        subsystems: 4,
        statusSource: 'graph lens focus + graph audit snapshot',
        backendRoute: 'Blueprint graph tab / graph atlas preview',
        inputs: ['committed kernel snapshot', 'graph focus'],
        outputs: ['galaxy scene', 'render graph'],
        dependencies: ['assertedKernel'],
        skips: [],
        mutationPolicy: 'read-only',
        uiCoverage: 'wired',
        runnable: true,
        graphTargetId: 'galaxy',
        graphTargetLabel: 'Galaxy View',
        stageSummaryKeys: ['galaxy', 'visualization'],
        testRefs: ['search-panel.component.spec.ts'],
        docRefs: ['src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-atlas-preview.component.ts'],
    },
];

export const ATLAS_CAPABILITY_LAYERS: AtlasCapabilityLayer[] = [
    {
        id: 'textSurface',
        label: 'Text Surface',
        description: 'Sentence split, dynamic chunking, token, phrase, and clause structure.',
        capabilityIds: ['dynamicSurface', 'dynamicChunking'],
    },
    {
        id: 'entityMention',
        label: 'Entity + Mention Intelligence',
        description: 'Dynamic NER, mentions, aliases, review lanes, and co-occurrence edges.',
        capabilityIds: ['dynamicNer', 'mentionGraph'],
    },
    {
        id: 'graphCommit',
        label: 'Graph Commit',
        description: 'Mention, evidence, surface, and asserted kernel graph commits.',
        capabilityIds: ['evidenceGraph', 'surfaceGraph', 'assertedKernel'],
    },
    {
        id: 'reasoningGraphs',
        label: 'Reasoning Graphs',
        description: 'Relation, temporal, event identity, memory/state, and causal graph passes.',
        capabilityIds: ['relationGraph', 'temporalGraph', 'eventIdentity', 'memoryState', 'causalGraph'],
    },
    {
        id: 'semanticAdjudication',
        label: 'Semantic + Adjudication',
        description: 'Embedding sidecar, semantic candidates, and NLI adjudication lane.',
        capabilityIds: ['semanticEmbedding', 'semanticAtlas', 'semanticCandidate', 'nliAdjudication'],
    },
    {
        id: 'manifoldGeometry',
        label: 'Manifold / Geometry',
        description: 'Hybrid embedding manifold plus Hopf, Lorentz, and product projection/forest sidecars.',
        capabilityIds: ['hybridManifold', 'hopfProjection', 'lorentzForest', 'productManifold'],
    },
    {
        id: 'retrievalVisualization',
        label: 'Retrieval / Visualization',
        description: 'Triverse graph walk, ranking, and galaxy render graph.',
        capabilityIds: ['retrievalWalk', 'galaxyVisualization'],
    },
];

const TEXT_GRAPH_CHAIN: AtlasCapabilityId[] = [
    'dynamicSurface',
    'dynamicChunking',
    'dynamicNer',
    'mentionGraph',
    'evidenceGraph',
    'surfaceGraph',
    'assertedKernel',
];

const RUN_NER_CHAIN: AtlasCapabilityId[] = ['dynamicSurface', 'dynamicNer'];

const SEMANTIC_GRAPH_CHAIN: AtlasCapabilityId[] = [
    ...TEXT_GRAPH_CHAIN,
    'semanticEmbedding',
    'semanticAtlas',
    'semanticCandidate',
];

const MANIFOLD_CAPABILITIES: AtlasCapabilityId[] = ['hybridManifold', 'hopfProjection', 'lorentzForest', 'productManifold'];

const ADJUDICATED_SEMANTIC_CHAIN: AtlasCapabilityId[] = [
    ...SEMANTIC_GRAPH_CHAIN,
    ...MANIFOLD_CAPABILITIES,
    'nliAdjudication',
];

const REASONING_CAPABILITIES: AtlasCapabilityId[] = [
    'relationGraph',
    'temporalGraph',
    'eventIdentity',
    'memoryState',
    'causalGraph',
];

const SEMANTIC_CAPABILITIES: AtlasCapabilityId[] = [
    'semanticEmbedding',
    'semanticAtlas',
    'semanticCandidate',
    'nliAdjudication',
];

const RETRIEVAL_CAPABILITIES: AtlasCapabilityId[] = ['retrievalWalk', 'galaxyVisualization'];

const REASONING_GRAPH_CHAIN: AtlasCapabilityId[] = [
    ...ADJUDICATED_SEMANTIC_CHAIN,
    'relationGraph',
    'eventIdentity',
    'temporalGraph',
    'memoryState',
    'causalGraph',
];

export const ATLAS_CAPABILITY_RECIPES: AtlasCapabilityRecipeDefinition[] = [
    {
        id: 'textGraph',
        label: 'Text Graph',
        subtitle: 'entity anchors required',
        description: 'Build the deterministic surface, entity anchoring, mention, evidence, and committed graph path for the selected documents.',
        actionLabel: 'Build Text Graph',
        icon: 'lucideZap',
        primary: true,
        outputLabel: 'committed text graph',
        mutationPolicy: 'dirty-only',
        cost: 'Low-Med',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan text-graph route',
        dependencyChain: TEXT_GRAPH_CHAIN,
        requiredCapabilities: TEXT_GRAPH_CHAIN,
        optionalCapabilities: [],
        skippedCapabilities: [...SEMANTIC_CAPABILITIES, ...MANIFOLD_CAPABILITIES, ...REASONING_CAPABILITIES, ...RETRIEVAL_CAPABILITIES],
        requiredLanes: ['dynamicNer'],
        optionalLanes: [],
        skippedLanes: ['semanticEmbedding', 'nli', 'manifoldProjection'],
    },
    {
        id: 'semanticGraph',
        label: 'Semantic Graph',
        subtitle: 'vectors + candidate links',
        description: 'Build the selected documents through text graph, semantic embeddings, atlas rows, and semantic candidate links.',
        actionLabel: 'Build Semantic Graph',
        icon: 'lucideSparkles',
        primary: true,
        outputLabel: 'graph + vectors',
        mutationPolicy: 'dirty-only',
        cost: 'High',
        backendRoute: 'QUARANTINED: legacy atlas_rich_scan semantic-graph route',
        dependencyChain: [...SEMANTIC_GRAPH_CHAIN, ...MANIFOLD_CAPABILITIES],
        requiredCapabilities: [...SEMANTIC_GRAPH_CHAIN, ...MANIFOLD_CAPABILITIES],
        optionalCapabilities: [],
        skippedCapabilities: ['nliAdjudication', ...REASONING_CAPABILITIES],
        requiredLanes: ['dynamicNer', 'semanticEmbedding', 'manifoldProjection'],
        optionalLanes: [],
        skippedLanes: ['nli'],
    },
    {
        id: 'adjudicatedSemanticGraph',
        label: 'Adjudicated Semantic Graph',
        subtitle: 'embedding + NLI',
        description: 'Build semantic graph candidates, then apply native NLI judgments to candidate edges.',
        actionLabel: 'Build Adjudicated Graph',
        icon: 'lucideMicrochip',
        outputLabel: 'judged candidate graph',
        mutationPolicy: 'dirty-only',
        cost: 'Very high',
        backendRoute: 'QUARANTINED: depends on the legacy atlas_rich_scan semantic-graph route',
        dependencyChain: ADJUDICATED_SEMANTIC_CHAIN,
        requiredCapabilities: ADJUDICATED_SEMANTIC_CHAIN,
        optionalCapabilities: [],
        skippedCapabilities: REASONING_CAPABILITIES,
        requiredLanes: ['dynamicNer', 'semanticEmbedding', 'manifoldProjection', 'nli'],
        optionalLanes: [],
        skippedLanes: [],
    },
    {
        id: 'reasoningGraph',
        label: 'Reasoning Graph',
        subtitle: 'semantic + NLI first',
        description: 'Run the semantic/adjudication contract, then expose the native relation, event, temporal, memory, and causal reasoning probes.',
        actionLabel: 'Build Reasoning Graph',
        icon: 'lucideLayers',
        outputLabel: 'reasoning graph probes',
        mutationPolicy: 'native-only',
        cost: 'Very high',
        backendRoute: 'QUARANTINED: depends on the legacy atlas_rich_scan semantic-graph route',
        dependencyChain: REASONING_GRAPH_CHAIN,
        requiredCapabilities: REASONING_GRAPH_CHAIN,
        optionalCapabilities: [],
        skippedCapabilities: [],
        requiredLanes: ['dynamicNer', 'semanticEmbedding', 'manifoldProjection', 'nli'],
        optionalLanes: [],
        skippedLanes: [],
    },
    {
        id: 'runNer',
        label: 'Run NER',
        subtitle: 'selected scope',
        description: 'Scan the selected Atlas scope for dynamic entity candidates while keeping graph mutation off.',
        actionLabel: 'Run NER',
        icon: 'lucideCpu',
        outputLabel: 'candidate entities',
        mutationPolicy: 'model warm',
        cost: 'Medium',
        backendRoute: 'NerService.runDynamicScan',
        dependencyChain: RUN_NER_CHAIN,
        requiredCapabilities: RUN_NER_CHAIN,
        optionalCapabilities: [],
        skippedCapabilities: [...TEXT_GRAPH_CHAIN.filter((id) => !RUN_NER_CHAIN.includes(id)), ...SEMANTIC_CAPABILITIES, ...MANIFOLD_CAPABILITIES, ...REASONING_CAPABILITIES, ...RETRIEVAL_CAPABILITIES],
        requiredLanes: ['dynamicNer'],
        optionalLanes: [],
        skippedLanes: ['semanticEmbedding', 'nli', 'manifoldProjection'],
    },
];

export function atlasCapabilityById(id: AtlasCapabilityId): AtlasCapability {
    return ATLAS_CAPABILITY_REGISTRY.find((capability) => capability.id === id) || ATLAS_CAPABILITY_REGISTRY[0];
}

export function atlasRecipeDefinitionById(id: AtlasRecipeId): AtlasCapabilityRecipeDefinition {
    return ATLAS_CAPABILITY_RECIPES.find((recipe) => recipe.id === id) || ATLAS_CAPABILITY_RECIPES[0];
}

export function capabilityLabel(id: AtlasCapabilityId): string {
    return atlasCapabilityById(id).label;
}

export function capabilityListLabel(ids: AtlasCapabilityId[]): string {
    return ids.length ? ids.map(capabilityLabel).join(' → ') : 'none';
}

export function laneLabelFromRegistry(id: AtlasModelLaneId): string {
    return ATLAS_MODEL_LANE_LABELS[id];
}
