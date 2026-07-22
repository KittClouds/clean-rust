import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
    assertGraphForceV2ShadowResult,
    buildGraphForceV2ShadowRequest,
    type GraphForceRebuildV2ShadowResult,
} from './graph-force-rebuild-v2';

describe('verified FORCE v2 shadow contract', () => {
    it('requires sealed native durability before crossing the bridge', () => {
        expect(() => buildGraphForceV2ShadowRequest(replay() as never, {
            id: 'snapshot-1', authorityContract: { contentHash: 'authority' },
        } as never)).toThrow('PHX_FORCE_V2_AUTHORITY_REQUIRED');
    });

    it('accepts only exact eight-section zero-kernel parity with no fallback', () => {
        const snapshot = compactSnapshot();
        const request = buildGraphForceV2ShadowRequest(replay() as never, snapshot);
        const result = {
            schemaVersion: 'phoenix-force-rebuild-v2-shadow-result/v1',
            contractVersion: 'phoenix-verified-force/v2', pathId: 'native_verified_force_v2',
            fallbackCount: 0, status: 'durable_verified', scopeId: 'global',
            snapshotId: 'snapshot-1', authorityHash: 'authority', manifestId: 'manifest-1',
            runHandle: 'run-1', analysisSource: 'durable_verified', analysisKernelMicros: 0,
            verifiedSections: Array.from({ length: 8 }, (_, index) => ({
                name: String(index), identity: String(index), rowCount: 0, rawBytes: 0, compressedBytes: 0,
            })),
            criticalResponseBytes: 1000, nativeCrossings: 1, sourceBodyReads: 1,
            sourceUtf8Bytes: 10, transportedSourceBytes: 0,
            sourceDocuments: request.documents,
            sourceVersionEnvelopeChanged: false,
            authorityPacket: snapshot,
            parentSpanId: 'root', spanId: 'child', error: null,
        } satisfies GraphForceRebuildV2ShadowResult;
        expect(assertGraphForceV2ShadowResult(result, request)).toBe(result);

        expect(() => assertGraphForceV2ShadowResult({ ...result, fallbackCount: 1 } as never, request))
            .toThrow('PHX_FORCE_V2_RESPONSE_INVALID');
        expect(() => assertGraphForceV2ShadowResult({ ...result, verifiedSections: [] }, request))
            .toThrow('PHX_FORCE_V2_PARITY_MISMATCH');

        const currentDocuments = request.documents.map((row) => ({ ...row, version: 3, updatedAt: 4 }));
        expect(assertGraphForceV2ShadowResult({
            ...result,
            sourceDocuments: currentDocuments,
            sourceVersionEnvelopeChanged: true,
        }, request).sourceVersionEnvelopeChanged).toBe(true);
        expect(assertGraphForceV2ShadowResult({
            ...result,
            sourceVersionEnvelopeChanged: true,
        }, request).sourceVersionEnvelopeChanged).toBe(true);
        expect(() => assertGraphForceV2ShadowResult({
            ...result,
            sourceDocuments: currentDocuments,
            sourceVersionEnvelopeChanged: false,
        }, request)).toThrow('PHX_FORCE_V2_SOURCE_IDENTITY_MISMATCH');
        expect(() => assertGraphForceV2ShadowResult({
            ...result,
            sourceDocuments: currentDocuments.map((row) => ({ ...row, sha256: 'b'.repeat(64) })),
            sourceVersionEnvelopeChanged: true,
        }, request)).toThrow('PHX_FORCE_V2_SOURCE_IDENTITY_MISMATCH');
        expect(() => assertGraphForceV2ShadowResult({
            ...result,
            authorityPacket: { ...snapshot, embeddingTargets: [{ id: 'legacy-target' }] } as never,
        }, request)).toThrow('PHX_FORCE_V2_COMPACT_AUTHORITY_INVALID');
    });

    it('locks the production FORCE route to required v2 methods with no legacy reconstruction seam', () => {
        const here = dirname(fileURLToPath(import.meta.url));
        const pipeline = readFileSync(join(here, 'graph-rebuild-pipeline.service.ts'), 'utf8');
        const backend = readFileSync(join(here, '..', 'services', 'phoenix-backend.service.ts'), 'utf8');
        const rust = readFileSync(join(here, '..', '..', '..', 'src-tauri', 'src', 'phoenix_rpc.rs'), 'utf8');
        const v2Start = pipeline.indexOf('async buildVerifiedForceV2(');
        const v2End = pipeline.indexOf('private async reuseAuthoritativeInteractiveGraph(', v2Start);
        const v2Body = pipeline.slice(v2Start, v2End);

        expect(pipeline).toContain('if (verifiedForceV2Required(request))');
        expect(pipeline).toContain('return this.buildVerifiedForceV2(request);');
        expect(v2Body).not.toContain('buildAndPersistSnapshot');
        expect(v2Body).not.toContain('scanDynamicBatch');
        expect(v2Body).not.toContain('GRAPH_FORCE_V1_PATH_ID');
        expect(v2Body).toContain('fallbackCount: 0');
        expect(backend).toContain('forceRebuildV2(request: unknown): Promise<unknown>;');
        expect(backend).toContain('persistForceV2Authority(request: unknown): Promise<unknown>;');
        expect(backend).not.toContain('forceRebuildV2?(request: unknown)');
        expect(backend).not.toContain('persistForceV2Authority?(request: unknown)');
        expect(rust).toContain('native_graph_contract: "phoenix-verified-force/v2".to_owned()');
    });
});

function replay() {
    return {
        action: 'force', sourceMode: 'scoped-note-store', cohortId: 'sha256:cohort',
        dependencyIdentity: 'sha256:dependencies',
        scope: { scopeId: 'global' },
        documents: [{
            noteId: 'note-1', sha256: 'a'.repeat(64), jsCodeUnitChars: 10,
            utf8Bytes: 10, version: 1, updatedAt: 2,
        }],
        model: {
            dynamicNerId: 'dynamic_ner', embeddingModelId: 'jina-v5-nano',
            embeddingDimensionLabel: '768d', nliModelId: 'modernbert-nli',
        },
    };
}

function compactSnapshot() {
    const counts = {
        notes: 1, chunks: 1, mentions: 0, anchors: 1, relationships: 0, events: 0,
        temporalEdges: 0, causalEdges: 0, memoryState: 0, coreferenceRecoveries: 0,
        nodes: 1, edges: 0, embeddingTargets: 2, admittedEmbeddingTargets: 2,
        packetObjects: 2, packetTargets: 2, packetParentLinks: 0, packetFamilies: {},
    };
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1', id: 'snapshot-1', scopeId: 'global',
        noteIds: ['note-1'], generationReceiptId: 'generation-1',
        generationDigestSha256: 'sha256-digest',
        authorityContract: {
            schemaVersion: 'phoenix-graph-snapshot-authority/v1',
            authority: 'graph_rebuild_live_contract', snapshotId: 'snapshot-1',
            scopeId: 'global', contentHash: 'authority', counts,
        },
        contentManifest: { snapshotId: 'snapshot-1', scopeId: 'global' },
        interactiveRunAuthority: {
            snapshotId: 'snapshot-1', scopeId: 'global',
            durable: {
                snapshotId: 'snapshot-1', scopeId: 'global',
                manifestId: 'manifest-1', runHandle: 'run-1',
            },
        },
        counters: {
            chunks: 1, mentions: 0, acceptedAnchors: 1, relationships: 0, events: 0,
            temporalEdges: 0, causalEdges: 0, memoryState: 0,
            documentSemanticLocalCoreferenceRecoveries: 0, nodes: 1, edges: 0,
            embeddingTargets: 2,
        },
        evidenceTargetRegistry: {
            sourceSnapshotId: 'snapshot-1', sourceScopeId: 'global', canonicalTargets: 2,
            exposedTargets: 2, chunks: 1, typedGraphObjects: 1, supportTargets: 0,
            duplicateTargets: 0, orphanTargets: 0, identityHash: 'fnv32-00000000',
        },
        chunks: [], mentions: [], entityAnchors: [], relationships: [], events: [], episodes: [],
        temporalEdges: [], causalEdges: [], memoryState: [], embeddingTargets: [], embeddingVectors: [],
        nodes: [], edges: [], projectionRefs: [], resolutionSuggestions: [],
    } as never;
}
