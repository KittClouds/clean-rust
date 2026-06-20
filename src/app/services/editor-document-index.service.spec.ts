import '@angular/compiler';
import {
    Injector,
    createEnvironmentInjector,
    runInInjectionContext,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    EditorDocumentIndexService,
    editorDocumentIndexReadRequest,
} from './editor-document-index.service';
import { EditorService } from './editor.service';
import { PhoenixBackendService } from './phoenix-backend.service';
import type { PhoenixDocumentIndexReadResponse } from './phoenix-document-index.model';

describe('EditorDocumentIndexService', () => {
    let injector: EnvironmentInjector;
    let editorMock: { captureSnapshot: ReturnType<typeof vi.fn> };
    let phoenixMock: { readDocumentIndex: ReturnType<typeof vi.fn> };
    let service: EditorDocumentIndexService;

    beforeEach(() => {
        editorMock = {
            captureSnapshot: vi.fn(() => ({
                json: {},
                markdown: '# Live\n\nCurrent paragraph.',
                timings: { jsonMs: 1, markdownMs: 2, totalMs: 3 },
            })),
        };
        phoenixMock = {
            readDocumentIndex: vi.fn(async () => indexResponse()),
        };
        injector = createEnvironmentInjector(
            [
                { provide: EditorService, useValue: editorMock },
                { provide: PhoenixBackendService, useValue: phoenixMock },
            ],
            Injector.create({ providers: [] }),
        );
        service = runInInjectionContext(injector, () => new EditorDocumentIndexService());
    });

    afterEach(() => injector.destroy());

    it('reads the live editor snapshot through the bounded native index path', async () => {
        const response = await service.readCurrentNote(
            {
                id: 'note-1',
                title: 'Saved title',
                markdownContent: '# Saved\n\nOld paragraph.',
            },
            {
                maxUnits: 8,
                maxRoutes: 3,
                maxRouteTargets: 2,
                maxFamilyRoutes: 4,
                maxFamilyTargets: 2,
                maxLabelChars: 24,
            },
        );

        expect(response.source).toBe('tauri-editor-mmap');
        expect(editorMock.captureSnapshot).toHaveBeenCalledWith('api');
        expect(phoenixMock.readDocumentIndex).toHaveBeenCalledWith({
            documentId: 'note-1',
            noteId: 'note-1',
            title: 'Saved title',
            text: '# Live\n\nCurrent paragraph.',
            maxUnits: 8,
            maxRoutes: 3,
            maxRouteTargets: 2,
            maxFamilyRoutes: 4,
            maxFamilyTargets: 2,
            maxLabelChars: 24,
        });
    });

    it('falls back to persisted note markdown when no editor snapshot is available', async () => {
        editorMock.captureSnapshot.mockReturnValue(null);

        await service.readCurrentNote({
            id: 'note-2',
            title: null,
            markdownContent: '# Persisted\n\nOnly copy.',
        });

        expect(phoenixMock.readDocumentIndex).toHaveBeenCalledWith({
            documentId: 'note-2',
            noteId: 'note-2',
            title: 'note-2',
            text: '# Persisted\n\nOnly copy.',
        });
    });
});

describe('editorDocumentIndexReadRequest', () => {
    it('keeps caps caller-owned and does not invent text when the note has none', () => {
        expect(
            editorDocumentIndexReadRequest({ id: 'empty-note' }, null, {
                maxUnits: 1,
                maxRoutes: 1,
            }),
        ).toEqual({
            documentId: 'empty-note',
            noteId: 'empty-note',
            title: 'empty-note',
            text: '',
            maxUnits: 1,
            maxRoutes: 1,
        });
    });
});

function indexResponse(): PhoenixDocumentIndexReadResponse {
    return {
        schemaVersion: 'phoenix-document-index-read/v1',
        source: 'tauri-editor-mmap',
        reference: {
            schemaVersion: 1,
            documentId: 'note-1',
            noteId: 'note-1',
            contentHash: 'hash',
            byteLen: 128,
            unitCount: 2,
        },
        receipt: {
            bounded: true,
            mmap: true,
            cacheReused: true,
            textBytes: 25,
            shardBytes: 128,
            unitCount: 2,
            unitsReturned: 2,
            unitsTruncated: 0,
            routeCount: 1,
            routesReturned: 1,
            routesTruncated: 0,
            familyRouteCount: 1,
            familyRoutesReturned: 1,
            familyRoutesTruncated: 0,
            familyTargetCount: 1,
            familyTargetsReturned: 1,
            familyTargetsTruncated: 0,
            maxUnits: 8,
            maxRoutes: 3,
            maxRouteTargets: 2,
            maxFamilyRoutes: 4,
            maxFamilyTargets: 2,
            maxLabelChars: 24,
            buildMs: 0,
            persistMs: 0,
            mmapMs: 0,
            readMs: 0,
        },
        units: [],
        outlineRoutes: [],
        families: [
            {
                family: 'entityState',
                routeCount: 1,
                routesReturned: 1,
                routesTruncated: 0,
                targetCount: 1,
                targetsReturned: 1,
                targetsTruncated: 0,
                routes: [
                    {
                        paragraphIndex: 1,
                        start: 0,
                        end: 12,
                        targets: [{ kind: 'entityMention', start: 0, end: 4, label: 'Live' }],
                    },
                ],
            },
            {
                family: 'timeline',
                routeCount: 0,
                routesReturned: 0,
                routesTruncated: 0,
                targetCount: 0,
                targetsReturned: 0,
                targetsTruncated: 0,
                routes: [],
            },
            {
                family: 'tension',
                routeCount: 0,
                routesReturned: 0,
                routesTruncated: 0,
                targetCount: 0,
                targetsReturned: 0,
                targetsTruncated: 0,
                routes: [],
            },
        ],
    };
}
