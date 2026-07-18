import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));

describe('Galaxy V2 authority failure shields', () => {
    it('keeps retired base64 scene decoders out of the production graph lane', () => {
        expect(existsSync(join(here, 'graph-native-scene-packet.ts'))).toBe(false);
        expect(existsSync(join(here, '../../../../../services/phoenix-graph-scene-packet.decode.ts'))).toBe(false);

        const packetSource = readFileSync(join(here, 'graph-galaxy-scene-packet-v2.ts'), 'utf8');
        expect(packetSource).not.toContain('atob(');
        expect(packetSource).not.toContain('btoa(');
    });

    it('returns transferred binary pages from the scene worker instead of a whole scene object', () => {
        const source = readFileSync(join(here, 'graph-galaxy-scene.worker.ts'), 'utf8');

        expect(source).toContain('packGalaxyScenePacketV2');
        expect(source).toContain('galaxyScenePacketV2TransferList(packet)');
        expect(source).not.toMatch(/postMessage\(\{\s*id:\s*data\.id,\s*scene/);
    });

    it('keeps runtime adjacency packed instead of allocating one array per node', () => {
        const source = readFileSync(join(here, 'graph-galaxy-scene-v2.ts'), 'utf8');

        expect(source).toContain('incidentOffsets: Uint32Array');
        expect(source).toContain('incidentEdges: Uint32Array');
        expect(source).not.toContain('incidentEdges: number[][]');
        expect(source).not.toContain('Array.from({ length: scene.ids.length }, () => [] as number[])');
    });

    it('keeps ordinary resident edges on the GPU endpoint-fetch surface', () => {
        const source = readFileSync(join(here, 'three-galaxy-renderer.ts'), 'utf8');

        expect(source).toContain('new GalaxyGpuEdgeSurface');
        expect(source).toContain('this.edges.updateNodePositions(positions)');
        expect(source).toContain('new ThreeGalaxyCpuPicker');
        expect(source).not.toContain('private ensureScreenPickIndex(');
        expect(source).not.toContain('private updateEdgeColors(');
    });

    it('keeps the compatibility adapter until the renderer consumes packed pages directly', () => {
        const compiler = readFileSync(join(here, 'graph-galaxy-scene-compiler.ts'), 'utf8');
        const canvas = readFileSync(join(here, 'graph-galaxy-canvas.component.ts'), 'utf8');
        const port = readFileSync(join(here, 'graph-renderer-port.ts'), 'utf8');

        expect(compiler).toContain('pending.resolve(unpackGalaxyScenePacketV2(');
        expect(canvas).toContain('private scene: GalaxySceneV2 | null');
        expect(canvas).toContain('this.renderer.installScene(scene, settings, mode, selectedIds)');
        expect(port).toContain('setScene(scene: GalaxySceneV2): void');
    });
});
