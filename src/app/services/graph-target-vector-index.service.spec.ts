import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';

import { assertGraphEvidenceTargetRegistry } from '../graph-rebuild/graph-evidence-target-registry';
import { assertGraphEncoderVectorIndex } from '../graph-rebuild/graph-encoder-vector-index';
import { buildGraphRebuildSnapshot } from '../graph-rebuild/graph-rebuild-builder';
import {
    attachInteractiveAtlasPacketForSnapshotTargets,
    graphRebuildSnapshotContentBlobDocuments,
    graphRebuildSnapshotToScopedDocument,
    scopedDocumentToGraphRebuildContentBlob,
    scopedDocumentToGraphRebuildSnapshot,
} from '../graph-rebuild/graph-rebuild.service';
import {
    assertGraphSnapshotAuthority,
    hydrateGraphSnapshotContent,
    sealGraphSnapshotAuthority,
    type GraphSnapshotHydrationBlob,
} from '../graph-rebuild/graph-snapshot-authority';
import type { GraphRebuildContentBlobField } from '../graph-rebuild/graph-rebuild-snapshot';
import { GraphTargetVectorIndexService } from './graph-target-vector-index.service';

describe('GraphTargetVectorIndexService', () => {
    it('uses transferable real encoder output to build and seal the candidate index', async () => {
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'note:real-encoder',
            noteIds: ['note-1'],
            entities: [],
            occurrences: [],
            chunks: [{
                id: 'note-1:block:0',
                noteId: 'note-1',
                start: 0,
                end: 48,
                ordinal: 0,
                source: 'note-block',
            }],
            noteTexts: { 'note-1': 'A quiet threshold waits beyond the last known route.' },
            builtAt: 20,
        });
        expect(attachInteractiveAtlasPacketForSnapshotTargets(snapshot)).toBe(true);
        const beforeAuthority = sealGraphSnapshotAuthority(snapshot);
        const exposed = assertGraphEvidenceTargetRegistry(snapshot).exposedTargets;
        const encoder = {
            initialize: vi.fn(async () => undefined),
            embedFlat: vi.fn(async (texts: string[]) => {
                const values = new Float32Array(texts.length * 768);
                for (let row = 0; row < texts.length; row += 1) values[row * 768] = 1;
                return { values, rows: texts.length, dims: 768, batchIndex: 1, totalBatches: 1 };
            }),
        };
        const service = new GraphTargetVectorIndexService(encoder as any);

        const index = await service.build(snapshot, {
            modelId: 'jina-v5-nano-retrieval',
            modelVersion: 'test-jina-v5',
            batchSize: 4,
            generation: 20,
        });

        expect(encoder.initialize).toHaveBeenCalledWith('jina-v5-nano-retrieval');
        expect(encoder.embedFlat).toHaveBeenCalledTimes(1);
        expect(index.targetIds).toEqual(exposed.map((target) => target.id));
        expect(index.contract.executionProvider).toBe('transformers-worker');
        expect(snapshot.encoderVectorIndex).toEqual(index.contract);
        expect(service.get(snapshot.id)).toBe(index);
        expect(() => assertGraphEncoderVectorIndex(snapshot)).not.toThrow();
        expect(assertGraphSnapshotAuthority(snapshot).contentHash).not.toBe(beforeAuthority.contentHash);

        const query = await service.search(snapshot.id, 'quiet threshold', {
            limit: 1,
            maxCandidates: 1,
            minimumSimilarity: -1,
        });
        expect(query?.neighbors).toHaveLength(1);
        expect(query?.evaluatedCandidates).toBeLessThanOrEqual(1);
        expect(encoder.embedFlat).toHaveBeenCalledTimes(2);

        const persisted = scopedDocumentToGraphRebuildSnapshot(graphRebuildSnapshotToScopedDocument(snapshot))!;
        const blobs = Object.fromEntries(graphRebuildSnapshotContentBlobDocuments(snapshot).map((document) => {
            const blob = scopedDocumentToGraphRebuildContentBlob(document)!;
            return [blob.field, blob];
        })) as Partial<Record<GraphRebuildContentBlobField, GraphSnapshotHydrationBlob>>;
        const hydrated = hydrateGraphSnapshotContent(persisted, blobs);
        expect(assertGraphSnapshotAuthority(hydrated).contentHash).toBe(snapshot.authorityContract?.contentHash);
        expect(hydrated.encoderVectorIndex).toEqual(snapshot.encoderVectorIndex);
    });
});
