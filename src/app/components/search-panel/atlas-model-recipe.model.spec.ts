import { describe, expect, it } from 'vitest';

import {
    buildAtlasModelLaneViews,
    buildAtlasRecipeLifecycle,
    getAtlasModelRecipePlan,
    laneListLabel,
} from './atlas-model-recipe.model';

describe('atlas model recipe model', () => {
    it('requires entity anchors for Text Graph without semantic or NLI lanes', () => {
        const plan = getAtlasModelRecipePlan('textGraph');

        expect(plan.requiredLanes).toEqual(['dynamicNer']);
        expect(plan.optionalLanes).toEqual([]);
        expect(plan.skippedLanes).toContain('semanticEmbedding');
        expect(plan.skippedLanes).toContain('nli');
        expect(plan.dependencyChain).toEqual(expect.arrayContaining([
            'dynamicSurface',
            'dynamicNer',
            'assertedKernel',
        ]));
        expect(plan.outputLabel).toMatch(/graph/i);
    });

    it('marks Semantic Graph as NER plus embedding backed while leaving NLI out', () => {
        const plan = getAtlasModelRecipePlan('semanticGraph');

        expect(plan.requiredLanes).toEqual(['dynamicNer', 'semanticEmbedding', 'manifoldProjection']);
        expect(plan.optionalLanes).toEqual([]);
        expect(plan.skippedLanes).toEqual(['nli']);
        expect(plan.actionLabel).toBe('Build Semantic Graph');
        expect(plan.dependencyChain).toContain('dynamicNer');
        expect(plan.dependencyChain).toContain('semanticCandidate');
        expect(plan.dependencyChain).toEqual(expect.arrayContaining([
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
        ]));
        expect(plan.mutationPolicy).toBe('dirty-only');
    });

    it('requires NER, embeddings, and NLI before reasoning graph probes', () => {
        const plan = getAtlasModelRecipePlan('reasoningGraph');

        expect(plan.requiredLanes).toEqual(['dynamicNer', 'semanticEmbedding', 'manifoldProjection', 'nli']);
        expect(plan.dependencyChain).toEqual(expect.arrayContaining([
            'semanticCandidate',
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
            'nliAdjudication',
            'relationGraph',
            'temporalGraph',
            'memoryState',
            'causalGraph',
        ]));
        expect(plan.skippedCapabilities).toEqual([]);
    });

    it('normalizes model lane status into readable command-center lanes', () => {
        const lanes = buildAtlasModelLaneViews({
            dynamicNerStatus: 'warming',
            coOccurrenceReady: true,
            coOccurrenceLoading: false,
            vectorStatus: 'loading',
            semanticReady: false,
            semanticDetail: 'MDBR Leaf MT 384d',
            nliInitialized: false,
            nliProcessing: true,
            nliModelId: null,
            manifoldStatuses: { hybrid: 'ready', hopf: 'stale', lorentz: 'idle' },
        });

        expect(lanes.map((lane) => [lane.id, lane.status])).toEqual([
            ['dynamicNer', 'warming'],
            ['coOccurrence', 'ready'],
            ['semanticEmbedding', 'warming'],
            ['nli', 'running'],
            ['manifoldProjection', 'idle'],
        ]);
    });

    it('renders deterministic lifecycle step states', () => {
        const steps = buildAtlasRecipeLifecycle('run', ['scope', 'warm'], null);

        expect(steps.map((step) => [step.id, step.status])).toEqual([
            ['scope', 'ready'],
            ['warm', 'ready'],
            ['run', 'running'],
            ['refresh', 'idle'],
        ]);
    });

    it('formats lane lists without bare identifiers', () => {
        expect(laneListLabel(['dynamicNer', 'semanticEmbedding'])).toBe('Dynamic NER / Semantic Embedding');
        expect(laneListLabel([])).toBe('none');
    });
});

