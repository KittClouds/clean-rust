import { describe, expect, it } from 'vitest';

import {
    ATLAS_CAPABILITY_LAYERS,
    ATLAS_CAPABILITY_RECIPES,
    ATLAS_CAPABILITY_REGISTRY,
    ATLAS_MODEL_LANE_LABELS,
    type AtlasGraphTargetId,
} from './atlas-capability.model';

describe('atlas capability registry', () => {
    it('keeps every graph target visible in the central capability registry', () => {
        const graphTargets = new Set(
            ATLAS_CAPABILITY_REGISTRY
                .map((capability) => capability.graphTargetId)
                .filter((id): id is AtlasGraphTargetId => !!id),
        );

        expect([...graphTargets].sort()).toEqual([
            'causal',
            'eventIdentity',
            'evidence',
            'galaxy',
            'kernel',
            'memoryState',
            'mention',
            'relation',
            'semanticAtlas',
            'semanticCandidate',
            'surface',
            'temporal',
        ].sort());
    });

    it('groups all capabilities into layered pipeline sections exactly once', () => {
        const layerIds = ATLAS_CAPABILITY_LAYERS.flatMap((layer) => layer.capabilityIds);
        const registryIds = ATLAS_CAPABILITY_REGISTRY.map((capability) => capability.id);

        expect(new Set(layerIds).size).toBe(layerIds.length);
        expect(layerIds.sort()).toEqual(registryIds.sort());
    });

    it('documents native reasoning graph probes as read-only partial coverage', () => {
        const reasoning = ATLAS_CAPABILITY_REGISTRY.filter((capability) => capability.family === 'reasoning');

        expect(reasoning.map((capability) => capability.id)).toEqual([
            'relationGraph',
            'temporalGraph',
            'eventIdentity',
            'memoryState',
            'causalGraph',
        ]);
        expect(reasoning.every((capability) => capability.runnable)).toBe(true);
        expect(reasoning.every((capability) => capability.mutationPolicy === 'read-only')).toBe(true);
        expect(reasoning.every((capability) => capability.uiCoverage === 'partial')).toBe(true);
    });

    it('requires every recipe to expose dependencies, skips, outputs, cost, and mutation policy', () => {
        for (const recipe of ATLAS_CAPABILITY_RECIPES) {
            expect(recipe.outputLabel.length).toBeGreaterThan(0);
            expect(recipe.backendRoute.length).toBeGreaterThan(0);
            expect(recipe.cost.length).toBeGreaterThan(0);
            expect(recipe.mutationPolicy.length).toBeGreaterThan(0);
            expect(recipe.dependencyChain.length + recipe.optionalCapabilities.length + recipe.skippedCapabilities.length).toBeGreaterThan(0);
        }
    });

    it('keeps graph recipes as dependency-complete contracts instead of independent toggles', () => {
        const byId = new Map(ATLAS_CAPABILITY_RECIPES.map((recipe) => [recipe.id, recipe]));

        expect(byId.get('textGraph')?.requiredCapabilities).toEqual(expect.arrayContaining([
            'dynamicNer',
            'assertedKernel',
        ]));
        expect(byId.get('semanticGraph')?.requiredCapabilities).toEqual(expect.arrayContaining([
            'dynamicNer',
            'semanticEmbedding',
            'semanticAtlas',
            'semanticCandidate',
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
        ]));
        expect(byId.get('semanticGraph')?.optionalCapabilities).toEqual([]);
        expect(byId.get('adjudicatedSemanticGraph')?.requiredCapabilities).toEqual(expect.arrayContaining([
            'semanticCandidate',
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
            'nliAdjudication',
        ]));
        expect(byId.get('reasoningGraph')?.requiredCapabilities).toEqual(expect.arrayContaining([
            'dynamicNer',
            'semanticEmbedding',
            'hybridManifold',
            'hopfProjection',
            'lorentzForest',
            'nliAdjudication',
            'relationGraph',
            'temporalGraph',
            'memoryState',
            'causalGraph',
        ]));
        expect(byId.get('reasoningGraph')?.skippedCapabilities).toEqual([]);
    });

    it('keeps model lane labels in the same registry used by recipe plans', () => {
        expect(Object.keys(ATLAS_MODEL_LANE_LABELS).sort()).toEqual([
            'coOccurrence',
            'dynamicNer',
            'manifoldProjection',
            'nli',
            'semanticEmbedding',
        ].sort());
    });

    it('treats only Hybrid as the embedding manifold authority', () => {
        const byId = new Map(ATLAS_CAPABILITY_REGISTRY.map((capability) => [capability.id, capability]));

        expect(byId.get('hybridManifold')).toEqual(expect.objectContaining({
            label: 'Hybrid Embedding Manifold',
            inputs: ['semantic atlas vectors'],
            outputs: expect.arrayContaining([
                'embedding space contract',
                'cosine top-k semantic neighborhoods',
                'candidate-only topology hints',
            ]),
            mutationPolicy: 'read-only',
        }));
        expect(byId.get('hopfProjection')?.description).toContain('projection lane');
        expect(byId.get('lorentzForest')?.description).toContain('forest');
        expect(byId.get('productManifold')?.description).toContain('product atlas');
    });
});
