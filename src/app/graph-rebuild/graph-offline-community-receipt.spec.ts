import '@angular/compiler';
import { Injector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import { buildGraphRebuildSnapshot } from './graph-rebuild-builder';
import { sealGraphSnapshotAuthority } from './graph-snapshot-authority';
import {
    GraphRebuildService,
    attachInteractiveAtlasPacketForSnapshotTargets,
} from './graph-rebuild.service';

describe('offline community live shadow receipt', () => {
    it('accepts an explicit CPU selection with zero fallback', async () => {
        const { service, backend, snapshot, destroy } = fixture();
        backend.storeCommand.mockResolvedValue(response(snapshot.id, 0));

        await expect(service.prepareAssertedQueryArtifact(snapshot)).resolves.toMatchObject({
            kind: 'asserted-query',
            status: 'ready',
        });
        expect(service.offlineCommunityReceipt()?.executionPathId)
            .toBe('community_cpu_deterministic_v1');
        expect(service.offlineCommunityReceipt()?.fallbackCount).toBe(0);
        destroy();
    });

    it('rejects any compatibility fallback telemetry', async () => {
        const { service, backend, snapshot, destroy } = fixture();
        backend.storeCommand.mockResolvedValue(response(snapshot.id, 1));

        await expect(service.prepareAssertedQueryArtifact(snapshot))
            .rejects.toThrow('offline community shadow receipt failed authority validation');
        destroy();
    });
});

function fixture() {
    const snapshot = buildGraphRebuildSnapshot({
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: [],
        entities: [],
        occurrences: [],
        chunks: [],
        noteTexts: {},
        builtAt: 42,
    });
    attachInteractiveAtlasPacketForSnapshotTargets(snapshot);
    sealGraphSnapshotAuthority(snapshot);
    const backend = {
        target: 'native',
        storeCommand: vi.fn(),
    };
    const injector = createEnvironmentInjector([
        { provide: PhoenixStoreService, useValue: {} },
        { provide: PhoenixBackendService, useValue: backend },
    ], Injector.create({ providers: [] }));
    const service = runInInjectionContext(injector, () => new GraphRebuildService());
    return {
        service,
        backend,
        snapshot,
        destroy: () => injector.destroy(),
    };
}

function response(snapshotId: string, fallbackCount: number) {
    return {
        schemaVersion: 'phoenix-graph-generation-asserted-query/v1',
        manifest: {
            schemaVersion: 'phoenix-asserted-discovery-view/v1',
            artifactDigest: 'a'.repeat(64),
            payloadDigest: 'b'.repeat(64),
            generation: 42,
            sourceSnapshotId: snapshotId,
            sourceSnapshotDigest: 'c'.repeat(64),
            nodeCount: 0,
            edgeCount: 0,
            excludedCandidateEdges: 0,
            admittedCandidateEdges: 0,
            binaryBytes: 4096,
        },
        communityShadow: {
            manifest: {
                artifactDigest: 'd'.repeat(64),
                payloadDigest: 'e'.repeat(64),
                generation: 42,
                binaryBytes: 4096,
            },
            receipt: {
                schemaVersion: 'phoenix-offline-community-artifact-shadow/v1',
                executionPathId: 'community_cpu_deterministic_v1',
                selectionReason: 'below_structural_gpu_crossover',
                generation: 42,
                sourceArtifactDigest: 'a'.repeat(64),
                artifactDigest: 'd'.repeat(64),
                payloadDigest: 'e'.repeat(64),
                nodes: 0,
                coreNodes: 0,
                selectedEdges: 0,
                fallbackCount,
                residentUploads: 0,
                runtimeReused: false,
                runtimeInitMicros: 0,
                wallMicros: 100,
                gpuPrepareMicros: 0,
                gpuExecuteMicros: 0,
                gpuReadbackMicros: 0,
                cpuPipelineMicros: 80,
                cpuLeidenMicros: 0,
                cpuMetricsMicros: 0,
                sealMicros: 0,
                residentBytes: 0,
                readbackBytes: 0,
                adapter: null,
                productionPublished: false,
            },
        },
    };
}
