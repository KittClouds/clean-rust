import type {
    GraphIndexLayerKind,
    GraphIndexLayerReceipt,
    GraphIndexLayerStatus,
    GraphIndexProjectionMode,
    GraphIndexProjectionReceipt,
    GraphIndexRunReceipt,
    GraphIndexStageReceipt,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';

interface LayerInput {
    receipt: GraphIndexRunReceipt;
    snapshot: GraphRebuildSnapshot | null;
}

interface LayerDraft {
    id: string;
    label: string;
    kind: GraphIndexLayerKind;
    owner: string;
    source: string;
    consumes: string[];
    produces: string[];
    stageIds: string[];
    projectionModes?: GraphIndexProjectionMode[];
    authority?: string;
    contentHash?: string;
    counters: Record<string, number>;
    message: string;
}

const INPUT_STAGE_IDS = [
    'interactiveIdentityReuse',
    'dynamicNer',
    'deltaPostprocessPlan',
    'signalCandidatePlan',
    'nliCandidatePlan',
    'nliAdjudication',
    'nliRelationshipRows',
    'nliTemporalRows',
    'nliEventIdentityRows',
    'nliMemoryStateRows',
    'nliCausalRows',
];

const DIAGNOSTIC_STAGE_IDS = [
    'interactiveIdentityReuse',
    'entityLinkerPlan',
    'edgeTypeJudgmentPlan',
    'semanticRerankPlan',
    'semanticAdjudicationDag',
    'semanticEvalLedger',
    'memoryGraphRagBridge',
    'discourseSpine',
    'discourseBridgeCandidates',
    'discourseBridgeAdjudication',
    'discourseEvalLedger',
    'discoursePromotionSurface',
    'discourseCompilerOverlay',
    'calendarRegistryBridge',
    'stagedNativeScenePacket',
    'interactivePostCommitEnrichment',
];

export function buildGraphIndexLayerReceipts(input: LayerInput): GraphIndexLayerReceipt[] {
    const stageById = new Map(input.receipt.stageReceipts.map((stage) => [stage.id, stage]));
    const projectionModes = input.receipt.projectionReceipts.map((row) => row.mode);
    const snapshot = input.snapshot;
    const contract = input.receipt.authorityContract || snapshot?.authorityContract;
    const packetContract = snapshot?.atlasPacket?.sourceContract;
    const timing = snapshot?.buildTimings;
    const layers: LayerDraft[] = [
        {
            id: 'input-signals',
            label: 'Input Signals',
            kind: 'input',
            owner: 'GraphRebuildPipelineService',
            source: 'scope documents, registry entities, NER/NLI rows',
            consumes: ['scope.noteIds', 'registeredEntities', 'noteText'],
            produces: ['stagedOccurrences', 'relationshipHints', 'candidatePlan'],
            stageIds: presentStageIds(stageById, INPUT_STAGE_IDS),
            counters: {
                documents: input.receipt.scope.noteIds.length,
                committedEntities: input.receipt.counters.nodes || 0,
                candidateTargets: counter(stageById, 'signalTargetCoverage', 'candidateTargets'),
                nliOutputs: stageOutput(stageById, 'nliAdjudication'),
            },
            message: 'Explains which source signals entered the graph build before snapshot authority sealed them.',
        },
        {
            id: 'snapshot-truth',
            label: 'Snapshot Truth',
            kind: 'truth',
            owner: 'GraphRebuildService',
            source: 'graph rebuild snapshot rows',
            consumes: ['sourceEvidence', 'chunks', 'relationshipHints'],
            produces: ['chunks', 'mentions', 'anchors', 'nodes', 'edges', 'embeddingTargets'],
            stageIds: presentStageIds(stageById, ['interactiveIdentityReuse', 'graphBuildSnapshot', 'signalTargetCoverage', 'snapshotCpu']),
            counters: {
                chunks: input.receipt.counters.chunks || 0,
                mentions: input.receipt.counters.mentions || 0,
                anchors: input.receipt.counters.acceptedAnchors || 0,
                nodes: input.receipt.counters.nodes || 0,
                edges: input.receipt.counters.edges || 0,
                embeddingTargets: input.receipt.counters.embeddingTargets || 0,
            },
            message: 'Explains the committed graph truth rows and target fanout produced by the live snapshot build.',
        },
        {
            id: 'native-atlas-packet',
            label: 'Native Atlas Packet',
            kind: 'native',
            owner: packetContract?.authority || 'rust-atlas-packet',
            source: packetContract?.tsGraphBuilderRole || 'native-atlas-packet-authority',
            consumes: ['snapshotRows', 'admittedEmbeddingTargets', 'graphCompilerSidecar'],
            produces: ['atlasPacket.objects', 'atlasPacket.manifoldTargets'],
            stageIds: presentStageIds(stageById, ['interactiveIdentityReuse', 'nativeCompilerBoundary', 'stagedNativeScenePacket']),
            authority: packetContract?.authority,
            counters: {
                packetObjects: snapshot?.atlasPacket?.objects.length || 0,
                packetTargets: snapshot?.atlasPacket?.manifoldTargets.length || 0,
                packetFamilies: snapshot?.atlasPacket?.counters.families.length || 0,
                nativeCompilerSkipped: timing?.nativeCompilerSkipped || 0,
                nativeAtlasSeedRawBytes: timing?.nativeAtlasSeedRawBytes || 0,
                nativeAtlasSeedCompressedBytes: timing?.nativeAtlasSeedCompressedBytes || 0,
            },
            message: 'Explains the Rust-owned packet boundary that all graph lenses render from.',
        },
        {
            id: 'authority-seal',
            label: 'Authority Seal',
            kind: 'authority',
            owner: contract?.authority || 'graph_rebuild_live_contract',
            source: 'graph-snapshot-authority',
            consumes: ['snapshotRows', 'atlasPacket', 'embeddingTargets'],
            produces: ['authorityContract.contentHash', 'authorityContract.counts'],
            stageIds: presentStageIds(stageById, ['interactiveIdentityReuse', 'snapshotAuthorityContract']),
            authority: contract?.authority,
            contentHash: contract?.contentHash,
            counters: {
                authorityParity: counter(stageById, 'snapshotAuthorityContract', 'authorityParity'),
                packetObjects: contract?.counts.packetObjects || 0,
                packetTargets: contract?.counts.packetTargets || 0,
                packetParentLinks: contract?.counts.packetParentLinks || 0,
            },
            message: 'Explains the fail-closed content hash and count parity for the live graph contract.',
        },
        {
            id: 'persistence-payload',
            label: 'Persistence Payload',
            kind: 'persistence',
            owner: 'Phoenix scoped document store',
            source: 'snapshot content manifest and run receipt document',
            consumes: ['authorityContract', 'contentBlobs', 'runReceipt'],
            produces: ['primarySnapshotDocument', 'contentBlobDocuments', 'receiptDocument'],
            stageIds: presentStageIds(stageById, ['interactiveIdentityReuse', 'snapshotDbOps', 'snapshotPayloadProfile', 'receiptDbOps']),
            counters: {
                snapshotPayloadChars: timing?.snapshotPayloadChars || 0,
                snapshotStoreDocuments: timing?.snapshotStoreDocuments || 0,
                primaryWriteSkipped: timing?.snapshotPrimaryWriteSkipped || 0,
                primaryIdentityReused: timing?.snapshotPrimaryIdentityReused || 0,
                contentBlobsWritten: timing?.snapshotWrittenContentBlobs || 0,
                contentBlobsReused: timing?.snapshotReusedContentBlobs || 0,
                receiptPayloadChars: counter(stageById, 'receiptDbOps', 'receiptPayloadChars'),
            },
            message: 'Explains what was persisted, reused, or deliberately skipped for durability.',
        },
        {
            id: 'projection-lenses',
            label: 'Projection Lenses',
            kind: 'projection',
            owner: 'GraphRebuildPipelineService',
            source: 'snapshot-owned read-model topology',
            consumes: ['atlasPacket', 'embeddingTargets', 'authorityHash'],
            produces: ['hybridProjection', 'hopfProjection', 'lorentzProjection', 'productProjection', 'siegelBackbone'],
            stageIds: [],
            projectionModes,
            contentHash: contract?.contentHash,
            counters: projectionCounters(input.receipt.projectionReceipts),
            message: 'Explains which manifold lenses synced from the sealed snapshot instead of alternate graph authorities.',
        },
        {
            id: 'diagnostic-ledgers',
            label: 'Diagnostic Ledgers',
            kind: 'diagnostic',
            owner: 'Graph rebuild diagnostics',
            source: input.receipt.durabilityMode === 'interactive' ? 'post-commit scheduled diagnostics' : 'durable diagnostic stages',
            consumes: ['sealedSnapshot', 'semanticCandidates', 'discourseCandidates'],
            produces: ['semanticReceipts', 'discourseReceipts', 'calendarReceipts', 'postCommitWork'],
            stageIds: presentStageIds(stageById, DIAGNOSTIC_STAGE_IDS),
            counters: {
                semanticReceipts: counter(stageById, 'semanticRerankPlan', 'receipts')
                    + counter(stageById, 'semanticAdjudicationDag', 'receipts'),
                discourseReceipts: counter(stageById, 'discourseSpine', 'receipts')
                    + counter(stageById, 'discourseBridgeAdjudication', 'receipts')
                    + counter(stageById, 'discourseEvalLedger', 'rows'),
                calendarReceipts: counter(stageById, 'calendarRegistryBridge', 'receipts'),
                scheduledAfterUiCommit: counter(stageById, 'interactivePostCommitEnrichment', 'scheduledAfterUiCommit'),
            },
            message: 'Explains which read-only diagnostic ledgers ran now and which were deferred beyond the UI path.',
        },
        {
            id: 'transport-boundary',
            label: 'Transport Boundary',
            kind: 'transport',
            owner: 'Phoenix transport audit',
            source: 'TauRPC and scoped-store calls',
            consumes: ['pipelineRequests', 'snapshotPersistence', 'receiptPersistence'],
            produces: ['transportCounters', 'payloadByteCounters'],
            stageIds: presentStageIds(stageById, ['transportOps']),
            counters: {
                calls: counter(stageById, 'transportOps', 'transportCalls'),
                requestBytes: counter(stageById, 'transportOps', 'transportRequestBytes'),
                responseBytes: counter(stageById, 'transportOps', 'transportResponseBytes'),
                storeCalls: counter(stageById, 'transportOps', 'storeCommandCalls'),
                walCalls: counter(stageById, 'transportOps', 'applyWalBatchCalls'),
            },
            message: 'Explains bridge traffic and payload volume without needing DevTools spelunking.',
        },
        {
            id: 'ui-commit',
            label: 'UI Commit',
            kind: 'ui',
            owner: 'Angular graph tab',
            source: 'lastSnapshot and lastReceipt signals',
            consumes: ['runReceipt', 'graphSnapshot'],
            produces: ['visibleGraphState', 'receiptPanelState'],
            stageIds: presentStageIds(stageById, ['uiCommit']),
            counters: {
                signalCommitMs: counter(stageById, 'uiCommit', 'signalCommitMs'),
                uiFrameMs: counter(stageById, 'uiCommit', 'uiFrameMs'),
            },
            message: 'Explains when the sealed graph and receipt reached the UI.',
        },
    ];
    return layers.map((layer) => completeLayer(layer, stageById, input.receipt.projectionReceipts));
}

function completeLayer(
    layer: LayerDraft,
    stageById: Map<string, GraphIndexStageReceipt>,
    projections: GraphIndexProjectionReceipt[],
): GraphIndexLayerReceipt {
    return {
        ...layer,
        status: layer.projectionModes ? projectionStatus(projections) : stageStatus(layer.stageIds, stageById),
        counters: compactCounters(layer.counters),
    };
}

function stageStatus(ids: string[], stageById: Map<string, GraphIndexStageReceipt>): GraphIndexLayerStatus {
    if (!ids.length) return 'skipped';
    const stages = ids.map((id) => stageById.get(id)).filter(Boolean) as GraphIndexStageReceipt[];
    if (stages.some((stage) => stage.status === 'failed')) return 'failed';
    if (stages.every((stage) => stage.status === 'completed')) return 'complete';
    if (stages.some((stage) => stage.status === 'completed')) return 'partial';
    return 'skipped';
}

function projectionStatus(projections: GraphIndexProjectionReceipt[]): GraphIndexLayerStatus {
    if (!projections.length) return 'skipped';
    if (projections.some((projection) => projection.status === 'error')) return 'failed';
    if (projections.every((projection) => projection.status === 'synced')) return 'complete';
    if (projections.some((projection) => projection.status === 'synced')) return 'partial';
    return 'skipped';
}

function presentStageIds(
    stageById: Map<string, GraphIndexStageReceipt>,
    ids: string[],
): string[] {
    return ids.filter((id) => stageById.has(id));
}

function stageOutput(stageById: Map<string, GraphIndexStageReceipt>, stageId: string): number {
    return stageById.get(stageId)?.outputCount || 0;
}

function counter(stageById: Map<string, GraphIndexStageReceipt>, stageId: string, key: string): number {
    return stageById.get(stageId)?.counters[key] || 0;
}

function projectionCounters(projections: GraphIndexProjectionReceipt[]): Record<string, number> {
    const synced = projections.filter((projection) => projection.status === 'synced');
    return compactCounters({
        projections: projections.length,
        syncedProjections: synced.length,
        targetCount: synced.reduce((sum, projection) => Math.max(sum, projection.targetCount), 0),
        vectorCount: synced.reduce((sum, projection) => Math.max(sum, projection.vectorCount), 0),
    });
}

function compactCounters(counters: Record<string, number>): Record<string, number> {
    const out: Record<string, number> = {};
    for (const [key, value] of Object.entries(counters)) {
        if (Number.isFinite(value)) out[key] = value;
    }
    return out;
}
