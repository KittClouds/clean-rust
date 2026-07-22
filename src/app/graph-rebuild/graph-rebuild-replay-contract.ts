import type {
    GraphIndexModelSelection,
    GraphIndexRunScope,
    GraphIndexStageReceipt,
} from './graph-rebuild-snapshot';

export const GRAPH_REBUILD_REPLAY_SCHEMA_VERSION = 'phoenix-graph-rebuild-replay/v1' as const;
export const GRAPH_FORCE_V1_PATH_ID = 'ts_force_reconstruction_v1' as const;
export const GRAPH_FORCE_V2_PATH_ID = 'native_verified_force_v2' as const;

export interface GraphReplayDocumentInput {
    noteId: string;
    title: string;
    text: string;
    version?: number;
    updatedAt?: number;
}

export interface GraphReplayDocumentIdentity {
    noteId: string;
    title: string;
    sha256: string;
    jsCodeUnitChars: number;
    unicodeScalarChars: number;
    nonLineBreakChars: number;
    utf8Bytes: number;
    lineBreaks: number;
    words: number;
    version: number | null;
    updatedAt: number | null;
}

export interface GraphReplayRuntimeIdentity {
    buildGitSha: string;
    buildProfile: string;
    target: string;
    storage: string;
    schemaVersion: string;
    binaryBlake3: string;
    nativeGraphContract: string;
}

export interface GraphReplayCacheState {
    documentBodyEntries: number;
    capabilityEntries: number;
    residentInteractiveRun: boolean;
    nativeRuntimeReady: boolean;
}

export interface GraphReplayQueueState {
    receiptPersistencePending: number;
    postCommitDiagnosticScheduled: boolean;
    postCommitDiagnosticToken: number;
    generationArtifactPending: number;
}

export interface GraphReplayMemoryCounters {
    measurement: 'instrumented-boundaries';
    documentBodyMaterializations: number;
    documentBodyCopies: number;
    documentUtf8Bytes: number;
    unmeasuredAllocatorEvents: number;
}

export interface GraphRebuildReplayManifest {
    schemaVersion: typeof GRAPH_REBUILD_REPLAY_SCHEMA_VERSION;
    cohortId: string;
    action: 'force' | 'delta';
    sourceMode: 'scoped-note-store';
    scope: GraphIndexRunScope;
    documents: GraphReplayDocumentIdentity[];
    aggregate: {
        documents: number;
        jsCodeUnitChars: number;
        unicodeScalarChars: number;
        nonLineBreakChars: number;
        utf8Bytes: number;
        lineBreaks: number;
        words: number;
    };
    model: GraphIndexModelSelection;
    dependencyIdentity: string;
    runtime: GraphReplayRuntimeIdentity;
    cache: GraphReplayCacheState;
    queues: GraphReplayQueueState;
    memory: GraphReplayMemoryCounters;
    pathId: string;
    fallbackCount: number;
}

export interface BuildGraphReplayManifestInput {
    scope: GraphIndexRunScope;
    action: 'force' | 'delta';
    documents: GraphReplayDocumentInput[];
    model: GraphIndexModelSelection;
    dependencyIdentity: string;
    runtime?: Partial<GraphReplayRuntimeIdentity> | null;
    cache: GraphReplayCacheState;
    queues: GraphReplayQueueState;
    pathId: string;
    fallbackCount: number;
}

export async function buildGraphReplayManifest(
    input: BuildGraphReplayManifestInput,
): Promise<GraphRebuildReplayManifest> {
    const encoder = new TextEncoder();
    const documents = await Promise.all(input.documents.map(async (document) => {
        const lineBreaks = document.text.match(/\r\n|\r|\n/g)?.length || 0;
        return {
            noteId: document.noteId,
            title: document.title,
            sha256: await sha256(document.text),
            jsCodeUnitChars: document.text.length,
            unicodeScalarChars: Array.from(document.text).length,
            nonLineBreakChars: document.text.replace(/\r\n|\r|\n/g, '').length,
            utf8Bytes: encoder.encode(document.text).byteLength,
            lineBreaks,
            words: unicodeWordCount(document.text),
            version: finiteOrNull(document.version),
            updatedAt: finiteOrNull(document.updatedAt),
        } satisfies GraphReplayDocumentIdentity;
    }));
    documents.sort((left, right) => left.noteId.localeCompare(right.noteId));
    const runtime: GraphReplayRuntimeIdentity = {
        buildGitSha: input.runtime?.buildGitSha || 'unavailable',
        buildProfile: input.runtime?.buildProfile || 'unavailable',
        target: input.runtime?.target || 'unavailable',
        storage: input.runtime?.storage || 'unavailable',
        schemaVersion: input.runtime?.schemaVersion || 'unavailable',
        binaryBlake3: input.runtime?.binaryBlake3 || 'unavailable',
        nativeGraphContract: input.runtime?.nativeGraphContract || 'unavailable',
    };
    const aggregate = {
        documents: documents.length,
        jsCodeUnitChars: sum(documents, (row) => row.jsCodeUnitChars),
        unicodeScalarChars: sum(documents, (row) => row.unicodeScalarChars),
        nonLineBreakChars: sum(documents, (row) => row.nonLineBreakChars),
        utf8Bytes: sum(documents, (row) => row.utf8Bytes),
        lineBreaks: sum(documents, (row) => row.lineBreaks),
        words: sum(documents, (row) => row.words),
    };
    const cohortId = await sha256(JSON.stringify({
        action: input.action,
        scope: input.scope,
        documents: documents.map((row) => ({ noteId: row.noteId, sha256: row.sha256 })),
        model: input.model,
        dependencyIdentity: input.dependencyIdentity,
    }));
    return {
        schemaVersion: GRAPH_REBUILD_REPLAY_SCHEMA_VERSION,
        cohortId: `sha256:${cohortId}`,
        action: input.action,
        sourceMode: 'scoped-note-store',
        scope: input.scope,
        documents,
        aggregate,
        model: input.model,
        dependencyIdentity: input.dependencyIdentity,
        runtime,
        cache: { ...input.cache },
        queues: { ...input.queues },
        memory: {
            measurement: 'instrumented-boundaries',
            documentBodyMaterializations: documents.length,
            documentBodyCopies: documents.length,
            documentUtf8Bytes: aggregate.utf8Bytes,
            unmeasuredAllocatorEvents: 1,
        },
        pathId: input.pathId,
        fallbackCount: input.fallbackCount,
    };
}

export function attachGraphReceiptSpans(
    receiptId: string,
    stages: GraphIndexStageReceipt[],
): { spanId: string; parentSpanId: null } {
    const rootSpanId = `${receiptId}:span:root`;
    const firstSpanByStageId = new Map<string, string>();
    for (const [index, stage] of stages.entries()) {
        stage.spanId ||= `${receiptId}:span:${index}:${stage.id}`;
        firstSpanByStageId.set(stage.id, firstSpanByStageId.get(stage.id) || stage.spanId);
    }
    for (const stage of stages) {
        stage.parentSpanId ||= firstSpanByStageId.get(parentStageId(stage.id)) || rootSpanId;
    }
    return { spanId: rootSpanId, parentSpanId: null };
}

function parentStageId(stageId: string): string {
    if (stageId === 'nliCandidatePlan' || stageId === 'nliAdjudicationPlan') return 'nliAdjudication';
    if (stageId.startsWith('snapshot') || stageId === 'nativeCompilerBoundary'
        || stageId === 'stagedNativeScenePacket') return 'graphBuildSnapshot';
    if (stageId === 'receiptDbOps') return 'uiCommit';
    return '';
}

async function sha256(value: string): Promise<string> {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function unicodeWordCount(text: string): number {
    return text.match(/[\p{L}\p{N}]+(?:['’_-][\p{L}\p{N}]+)*/gu)?.length || 0;
}

function finiteOrNull(value: number | undefined): number | null {
    return Number.isFinite(value) ? value! : null;
}

function sum<T>(rows: T[], read: (row: T) => number): number {
    return rows.reduce((total, row) => total + read(row), 0);
}
