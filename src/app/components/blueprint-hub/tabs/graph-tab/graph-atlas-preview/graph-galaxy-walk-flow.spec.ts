import { buildGalaxyWalkBranches, galaxyWalkHierarchyRank } from './graph-galaxy-walk-flow';

describe('graph galaxy walk flow', () => {
    it('fans from every document into every root and every downstream branch', () => {
        const scene = walkScene();

        const branches = buildGalaxyWalkBranches(scene);

        expect(new Set(branches.map((branch) => scene.ids[branch.root]))).toEqual(new Set(['doc-a', 'doc-b']));
        expect(branches).toHaveLength(7);
        expect(branches.filter((branch) => branch.root === 0 && branch.depth === 0).map((branch) => scene.ids[branch.target])).toEqual([
            'root-a',
            'root-a-secondary',
        ]);
        expect(branches.filter((branch) => branch.source === 3).map((branch) => scene.ids[branch.target])).toEqual([
            'fact-a',
            'entity-a',
        ]);
        expect(branches.filter((branch) => branch.source === 3).every((branch) => branch.depth === 2)).toBe(true);
    });

    it('orients reversed hierarchy edges down from document to leaf', () => {
        const scene = walkScene();
        scene.edgePairs = new Uint32Array([
            1, 0,
            3, 1,
            4, 3,
            5, 4,
        ]);
        scene.edgeTypes = ['target-parent', 'target-parent', 'chunk-anchor', 'anchor-entity'];
        scene.edgeKinds = new Uint8Array([2, 2, 2, 2]);
        scene.edgeAlpha = new Float32Array([1, 1, 1, 1]);

        const branches = buildGalaxyWalkBranches(scene);

        expect(branches.map((branch) => [scene.ids[branch.source], scene.ids[branch.target], branch.depth])).toEqual([
            ['doc-a', 'root-a', 0],
            ['root-a', 'chunk-a', 1],
            ['chunk-a', 'fact-a', 2],
            ['fact-a', 'entity-a', 3],
        ]);
    });

    it('is deterministic, breadth-first, and does not cross into another document root', () => {
        const scene = walkScene();

        const first = buildGalaxyWalkBranches(scene);
        const second = buildGalaxyWalkBranches(scene);

        expect(second).toEqual(first);
        expect(first.map((branch) => branch.depth)).toEqual([...first.map((branch) => branch.depth)].sort((a, b) => a - b));
        expect(first.every((branch) => {
            const target = scene.ids[branch.target];
            return target === scene.ids[branch.root] || !target.startsWith('doc-');
        })).toBe(true);
    });

    it('preserves every first-level root before a branch limit trims deep leaves', () => {
        const scene = walkScene();

        const branches = buildGalaxyWalkBranches(scene, 3);

        expect(branches.map((branch) => scene.ids[branch.target])).toEqual(['root-a', 'root-b', 'root-a-secondary']);
    });

    it('ranks the general document hierarchy without story-only assumptions', () => {
        expect(galaxyWalkHierarchyRank('doc', 'document')).toBeLessThan(galaxyWalkHierarchyRank('root', 'section'));
        expect(galaxyWalkHierarchyRank('root', 'section')).toBeLessThan(galaxyWalkHierarchyRank('chunk', 'leaf_chunk'));
        expect(galaxyWalkHierarchyRank('chunk', 'leaf_chunk')).toBeLessThan(galaxyWalkHierarchyRank('claim', 'claim'));
        expect(galaxyWalkHierarchyRank('claim', 'claim')).toBeLessThan(galaxyWalkHierarchyRank('entity', 'concept'));
    });
});

function walkScene() {
    return {
        ids: ['doc-a', 'root-a', 'root-a-secondary', 'chunk-a', 'fact-a', 'entity-a', 'doc-b', 'root-b', 'chunk-b'],
        kinds: ['note', 'structureRoot', 'section', 'leaf_chunk', 'claim', 'concept', 'document', 'section', 'paragraph_group'],
        edgePairs: new Uint32Array([
            0, 1,
            0, 2,
            1, 3,
            3, 4,
            3, 5,
            6, 7,
            7, 8,
            5, 6,
        ]),
        edgeTypes: ['target-parent', 'target-parent', 'target-parent', 'chunk-anchor', 'chunk-entity', 'target-parent', 'target-parent', 'related-to'],
        edgeKinds: new Uint8Array([2, 2, 2, 2, 2, 2, 2, 0]),
        edgeAlpha: new Float32Array([1, 0.98, 0.95, 0.9, 0.85, 1, 0.95, 0.8]),
        hierarchyHints: [],
    };
}
