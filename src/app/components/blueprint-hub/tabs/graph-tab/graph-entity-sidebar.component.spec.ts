// @vitest-environment jsdom
import '@angular/compiler';
import {
    Injector,
    SimpleChange,
    computed,
    createEnvironmentInjector,
    runInInjectionContext,
    signal,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RegisteredEntity } from '../../../../lib/registry';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import { entityColorStore } from '../../../../lib/store/entityColorStore';
import { buildGraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-builder';
import { buildAdaptiveGraphRebuildChunks } from '../../../../graph-rebuild/graph-rebuild-meaning-frames';
import { GraphRebuildService } from '../../../../graph-rebuild/graph-rebuild.service';
import { AtlasControlContractService } from '../../../../services/atlas-control-contract.service';
import { PhoenixProjectionService } from '../../../../services/phoenix-projection.service';
import { NliWorkerService } from '../../../../lib/services/nli-worker.service';
import { GraphEntitySidebarComponent } from './graph-entity-sidebar.component';

describe('GraphEntitySidebarComponent discourse focus', () => {
    let injector: EnvironmentInjector;
    let component: GraphEntitySidebarComponent;
    let restorePersistedSnapshot: ReturnType<typeof vi.fn>;
    let graphSnapshot: ReturnType<typeof signal<any>>;

    beforeEach(() => {
        restorePersistedSnapshot = vi.fn(async () => undefined);
        graphSnapshot = signal<any>(null);
        injector = createEnvironmentInjector([
            {
                provide: GraphRebuildService,
                useValue: {
                    snapshot: graphSnapshot,
                    isBuilding: computed(() => false),
                    loadPersistedSnapshot: vi.fn(async () => graphSnapshot()),
                    restorePersistedSnapshot,
                    attachReviewAdjudicationCertificate: vi.fn(),
                },
            },
            { provide: PhoenixProjectionService, useValue: { entityCount: computed(() => 2) } },
            {
                provide: NliWorkerService,
                useValue: {
                    isInitialized: signal(false),
                    modelId: signal(null),
                    isProcessing: signal(false),
                    progress: signal(null),
                },
            },
            AtlasControlContractService,
        ], Injector.create({ providers: [] }) as unknown as EnvironmentInjector);
        component = runInInjectionContext(injector, () => new GraphEntitySidebarComponent());
        component.entities = entities();
        component.ngOnChanges({
            entities: new SimpleChange([], component.entities, true),
        });
    });

    afterEach(() => {
        component?.ngOnDestroy();
        injector?.destroy();
        vi.clearAllMocks();
    });

    it('keeps discourse button focus out of the shared entity search', () => {
        component.sidebarView.set('discourse');

        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));
        const visibleEntityRows = component.rows().filter((row) => row.type === 'entity').length;

        component.highlightDiscourseQuery('discourse overlay');

        expect(component.sidebarView()).toBe('discourse');
        expect(component.entitySearch()).toBe('');
        expect(component.focusedDiscourseQuery()).toBe('discourse overlay');
        expect(component.rows().filter((row) => row.type === 'entity').length).toBe(visibleEntityRows);
        expect(emittedSearches).toEqual([]);
    });

    it('still emits explicit entity searches for atlas filtering', () => {
        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));

        component.updateEntitySearch('Kai');

        expect(component.entitySearch()).toBe('Kai');
        expect(emittedSearches).toEqual(['Kai']);
    });

    it('updates an entity family color directly from its header control', () => {
        const original = entityColorStore.getRawHsl('CHARACTER');
        const stopPropagation = vi.fn();

        component.updateKindColor('CHARACTER', '#12b8a6', { stopPropagation } as unknown as Event);

        expect(stopPropagation).toHaveBeenCalledOnce();
        expect(component.getHexColor('CHARACTER')).toBe('#12b8a6');

        entityColorStore.setColor('CHARACTER', original);
    });

    it('selects discourse workbench rows without mutating atlas search', () => {
        component.sidebarView.set('discourse');
        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));

        component.selectDiscourseRecord('gaps:row-1');

        expect(component.selectedDiscourseRecordId()).toBe('gaps:row-1');
        expect(component.entitySearch()).toBe('');
        expect(emittedSearches).toEqual([]);
    });

    it('uses the explicit discourse focus action to update atlas search', () => {
        component.sidebarView.set('discourse');
        const emittedSearches: string[] = [];
        component.searchTextChange.subscribe((value) => emittedSearches.push(value));

        component.focusDiscourseRecord({
            id: 'gaps:row-1',
            focusQuery: 'Kai Hazel bridge',
        } as any);

        expect(component.focusedDiscourseQuery()).toBe('Kai Hazel bridge');
        expect(emittedSearches).toEqual(['Kai Hazel bridge']);
    });

    it('exposes the Phase 5 operating-room tabs and count filters', () => {
        const tabIds = component.operatingRoomTabs().map((tab) => tab.id);
        const entityCount = component.operatingRoom().countsById['entities-total'];

        expect(tabIds).toEqual(['entities', 'structure', 'facts', 'review', 'discourse', 'metrics']);
        expect(entityCount.value).toBe(3);

        component.selectOperatingCount(entityCount);

        expect(component.sidebarView()).toBe('entities');
        expect(component.selectedOperatingCount()?.id).toBe('entities-total');
        expect(component.activeOperatingRecords().length).toBe(3);
        expect(component.selectedOperatingRecord()?.facts.some((fact) => fact.label === 'Lineage')).toBe(true);
    });

    it('keeps compact persisted Atlas room counts from run counters', () => {
        component.diagnosticsSnapshot.set(compactRunSnapshot());
        graphSnapshot.set(component.diagnosticsSnapshot());

        const tabs = Object.fromEntries(component.operatingRoomTabs().map((tab) => [tab.id, tab.count]));
        const counts = component.operatingRoom().countsById;

        expect(tabs).toMatchObject({
            entities: 3,
            structure: 3953,
            facts: 741,
            review: 1192,
            discourse: 234,
            metrics: 11,
        });
        expect(counts['structure-total'].value).toBe(3953);
        expect(counts['facts-relations'].value).toBe(741);
        expect(counts['review-gaps'].value).toBe(1192);
        expect(counts['discourse-packets'].value).toBe(234);
    });

    it('opens the evaluation workspace when Metrics is selected', () => {
        const rooms: string[] = [];
        component.operatingRoomChange.subscribe((room) => rooms.push(room));

        component.setSidebarView('metrics');

        expect(component.sidebarView()).toBe('metrics');
        expect(rooms).toEqual(['metrics']);
        expect(component.evaluationDashboard()).toMatchObject({ verdict: 'No data', score: null });
    });

    it('surfaces weighted document profiles as inspectable Structure records', () => {
        const text = '# Methods\n\nThe method compares samples.\n\n# Results\n\nEvidence supports the result.';
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'profile-note',
            noteIds: ['profile-note'],
            entities: [],
            occurrences: [],
            chunks: buildAdaptiveGraphRebuildChunks('profile-note', text),
            noteTexts: { 'profile-note': text },
            builtAt: 30,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });
        component.diagnosticsSnapshot.set(snapshot);
        graphSnapshot.set(snapshot);
        const profileCount = component.operatingRoom().countsById['structure-profiles'];

        component.selectOperatingCount(profileCount);

        expect(profileCount.value).toBe(1);
        expect(component.sidebarView()).toBe('structure');
        expect(component.selectedOperatingRecord()?.kind).toBe('document-profile:weighted');
        expect(component.selectedOperatingRecord()?.facts.some((fact) => fact.label === 'Ontology policy')).toBe(true);
    });

    it('persists document review actions with a reversible receipt', async () => {
        const text = [
            '# Review Note',
            'Policy means Amara moved from Red Mesa to Halcyon because the report changed the plan.',
            '- Use the recovered record as evidence.',
            '"Should this become an anchor?" Amara asked.',
        ].join('\n\n');
        const snapshot = buildGraphRebuildSnapshot({
            scopeKind: 'note',
            scopeId: 'review-note',
            noteIds: ['review-note'],
            entities: [],
            occurrences: [],
            chunks: buildAdaptiveGraphRebuildChunks('review-note', text),
            noteTexts: { 'review-note': text },
            builtAt: 40,
            postProcessMode: 'core',
            embeddingStagePolicy: { entityLinkerEnabled: false },
        });
        component.diagnosticsSnapshot.set(snapshot);
        graphSnapshot.set(snapshot);
        const record = component.discourseWorkbench()?.records.find((candidate) =>
            candidate.kind === 'document-review:graph_fact_candidate'
            && candidate.actionKinds.includes('accept_fact')
        );
        expect(record).toBeTruthy();

        await component.stageDiscourseRecordDecision(record!, 'accepted');

        expect(restorePersistedSnapshot).toHaveBeenCalledOnce();
        const persisted = restorePersistedSnapshot.mock.calls[0][0];
        const persistedRow = persisted.documentReviewSummary.rows.find(
            (candidate: any) => candidate.objectId === record!.sourceIds[0],
        );
        expect(persistedRow.state).toBe('accepted');
        expect(persisted.documentReviewSummary.receipts.at(-1)).toMatchObject({
            actionKind: 'accept_fact',
            reversible: true,
            mutationAllowed: false,
        });
        expect(persisted.documentCompilerSummary.sourceReviewBuiltAt).toBeGreaterThan(40);
    });
});

function entities(): RegisteredEntity[] {
    return [
        { id: 'kai', label: 'Kai', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'hazel', label: 'Hazel', kind: 'CHARACTER', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
        { id: 'mesa', label: 'Red Mesa', kind: 'LOCATION', aliases: [], attributes: {}, createdAt: 1, updatedAt: 1 },
    ] as RegisteredEntity[];
}

function compactRunSnapshot(): GraphRebuildSnapshot {
    return {
        schemaVersion: 'phoenix-graph-rebuild/v1',
        id: 'compact-run',
        source: 'phoenix-graph-rebuild',
        scopeKind: 'global',
        scopeId: 'global',
        noteIds: ['note-1'],
        builtAt: 1,
        chunks: [],
        mentions: [],
        entityAnchors: [],
        relationships: [],
        events: [],
        episodes: [],
        temporalEdges: [],
        causalEdges: [],
        memoryState: [],
        embeddingTargets: [],
        embeddingVectors: [],
        projectionRefs: [],
        nodes: [],
        edges: [],
        atlasPacket: {
            schemaVersion: 'phoenix-atlas-packet/v1',
            snapshotId: 'compact-run',
            scopeKind: 'global',
            scopeId: 'global',
            builtAt: 1,
            sourceContract: {
                authority: 'rust-atlas-packet',
                identityAuthority: 'registry',
                vectorContract: 'missing',
                tsGraphBuilderRole: 'visuals_only',
            },
            objects: [],
            manifoldTargets: [],
            counters: {
                objects: 0,
                manifoldTargets: 0,
                registryEntities: 3,
                evidenceAnchors: 903,
                modelVectors: 0,
                families: [],
            },
        },
        counters: {
            entities: 3,
            aliases: 0,
            candidates: 0,
            mentions: 903,
            acceptedAnchors: 903,
            chunks: 42,
            relationshipCandidates: 0,
            relationships: 700,
            acceptedRelationships: 38,
            reviewRelationships: 0,
            rejectedRelationships: 0,
            events: 20,
            episodes: 0,
            temporalEdges: 12,
            causalEdges: 9,
            memoryState: 0,
            embeddingTargets: 1325,
            embeddingVectors: 0,
            projectionRefs: 0,
            nodes: 332,
            edges: 126,
            documentSidecarUnits: 3953,
            documentReviewRows: 1192,
            documentReviewActionableRows: 1192,
            discourseSpineTargets: 234,
            dropReasons: {},
        },
    } as unknown as GraphRebuildSnapshot;
}
