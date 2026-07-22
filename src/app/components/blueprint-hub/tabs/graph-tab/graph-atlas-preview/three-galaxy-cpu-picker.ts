import * as THREE from 'three';

import type { GraphCanvasHit } from './graph-canvas-interaction';
import type { GalaxyRenderSettings } from './graph-galaxy-engine';
import { galaxyNodePickShapeBoost } from './graph-galaxy-objects';
import type { GalaxyInteractionRect } from './graph-galaxy-interaction.model';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';
import type { GraphRendererMode, GraphRendererPointer } from './graph-renderer-port';

const PICK_CELL_SIZE = 32;

export class ThreeGalaxyCpuPicker {
    private readonly projected = new THREE.Vector3();
    private readonly projectedRadius = new THREE.Vector3();
    private dirty = true;
    private width = 0;
    private height = 0;
    private columns = 0;
    private rows = 0;
    private nodeScreen = new Float32Array(0);
    private nodeBins: number[][] = [];
    private edgeBins: number[][] = [];
    private edgeSeen = new Uint32Array(0);
    private edgeEpoch = 0;
    private readonly candidates: number[] = [];

    invalidate(): void {
        this.dirty = true;
    }

    pickNode(
        data: GalaxySceneV2,
        positions: Float32Array,
        camera: THREE.Camera,
        pointer: GraphRendererPointer,
        settings: GalaxyRenderSettings,
    ): number {
        if (pointer.width <= 0 || pointer.height <= 0) return -1;
        this.ensureIndex(data, positions, camera, pointer);
        let best = -1;
        let bestScore = Number.POSITIVE_INFINITY;
        const glowBoost = settings.glow * 4;
        const shapeBoost = galaxyNodePickShapeBoost(settings.nodeShape);
        const densityPenalty = data.ids.length > 160 ? 4 : 0;
        for (const index of this.pickCandidates(this.nodeBins, pointer.x, pointer.y)) {
            const offset = index * 3;
            const dx = this.nodeScreen[offset] - pointer.x;
            const dy = this.nodeScreen[offset + 1] - pointer.y;
            const radius = THREE.MathUtils.clamp(
                11 + data.radii[index] * 1.9 + glowBoost + shapeBoost - densityPenalty,
                10,
                34,
            );
            const score = (dx * dx + dy * dy) / (radius * radius);
            if (score <= 1 && score < bestScore) {
                bestScore = score;
                best = index;
            }
        }
        return best;
    }

    pickEdge(
        data: GalaxySceneV2,
        positions: Float32Array,
        camera: THREE.Camera,
        pointer: GraphRendererPointer,
    ): number {
        if (pointer.width <= 0 || pointer.height <= 0) return -1;
        this.ensureIndex(data, positions, camera, pointer);
        let best = -1;
        let bestDistance = 9 * 9;
        this.edgeEpoch = (this.edgeEpoch + 1) >>> 0 || 1;
        for (const index of this.pickCandidates(this.edgeBins, pointer.x, pointer.y)) {
            if (this.edgeSeen[index] === this.edgeEpoch) continue;
            this.edgeSeen[index] = this.edgeEpoch;
            const sourceOffset = data.edgePairs[index * 2] * 3;
            const targetOffset = data.edgePairs[index * 2 + 1] * 3;
            const distance = pointSegmentDistanceSquared(
                pointer.x,
                pointer.y,
                this.nodeScreen[sourceOffset],
                this.nodeScreen[sourceOffset + 1],
                this.nodeScreen[targetOffset],
                this.nodeScreen[targetOffset + 1],
            );
            if (distance < bestDistance) {
                best = index;
                bestDistance = distance;
            }
        }
        return best;
    }

    nodesInRect(
        data: GalaxySceneV2,
        positions: Float32Array,
        camera: THREE.Camera,
        rect: GalaxyInteractionRect,
    ): string[] {
        const ids: string[] = [];
        for (let index = 0; index < data.ids.length; index++) {
            const offset = index * 3;
            this.projected.set(positions[offset], positions[offset + 1], positions[offset + 2]).project(camera);
            if (this.projected.z < -1 || this.projected.z > 1) continue;
            const x = (this.projected.x * 0.5 + 0.5) * rect.width;
            const y = (-this.projected.y * 0.5 + 0.5) * rect.height;
            if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
                ids.push(data.ids[index]);
            }
        }
        return ids;
    }

    pickGroup(
        data: GalaxySceneV2,
        camera: THREE.Camera,
        pointer: GraphRendererPointer,
        mode: GraphRendererMode,
    ): GraphCanvasHit | null {
        if (pointer.width <= 0 || pointer.height <= 0) return null;
        let best = -1;
        let bestScore = Number.POSITIVE_INFINITY;
        for (let index = 0; index < data.groups.length; index++) {
            const group = data.groups[index];
            const center = mode === '2d'
                ? { x: group.center.x, y: group.center.y, z: 0 }
                : group.center;
            this.projected.set(center.x, center.y, center.z).project(camera);
            this.projectedRadius.set(center.x + group.radius, center.y, center.z).project(camera);
            if (this.projected.z < -1 || this.projected.z > 1) continue;
            const x = (this.projected.x * 0.5 + 0.5) * pointer.width;
            const y = (-this.projected.y * 0.5 + 0.5) * pointer.height;
            const radius = Math.max(
                18,
                Math.abs(this.projectedRadius.x - this.projected.x) * pointer.width * 0.5,
            );
            const score = Math.hypot(pointer.x - x, pointer.y - y) / radius;
            if (score <= 1 && score < bestScore) {
                best = index;
                bestScore = score;
            }
        }
        const group = data.groups[best];
        return group
            ? { kind: 'cluster', id: group.id, label: group.label, nodeIds: group.nodeIds }
            : null;
    }

    private ensureIndex(
        data: GalaxySceneV2,
        positions: Float32Array,
        camera: THREE.Camera,
        pointer: GraphRendererPointer,
    ): void {
        const width = Math.max(1, Math.floor(pointer.width));
        const height = Math.max(1, Math.floor(pointer.height));
        if (!this.dirty && this.width === width && this.height === height) return;
        this.width = width;
        this.height = height;
        this.columns = Math.max(1, Math.ceil(width / PICK_CELL_SIZE));
        this.rows = Math.max(1, Math.ceil(height / PICK_CELL_SIZE));
        const binCount = this.columns * this.rows;
        this.nodeBins = resetBins(this.nodeBins, binCount);
        this.edgeBins = resetBins(this.edgeBins, binCount);
        if (this.nodeScreen.length !== data.ids.length * 3) {
            this.nodeScreen = new Float32Array(data.ids.length * 3);
        }
        if (this.edgeSeen.length !== data.edgeIds.length) {
            this.edgeSeen = new Uint32Array(data.edgeIds.length);
            this.edgeEpoch = 0;
        }
        for (let index = 0; index < data.ids.length; index++) {
            const offset = index * 3;
            this.projected.set(positions[offset], positions[offset + 1], positions[offset + 2]).project(camera);
            const x = (this.projected.x * 0.5 + 0.5) * width;
            const y = (-this.projected.y * 0.5 + 0.5) * height;
            this.nodeScreen[offset] = x;
            this.nodeScreen[offset + 1] = y;
            this.nodeScreen[offset + 2] = this.projected.z;
            if (this.projected.z < -1 || this.projected.z > 1) continue;
            const bin = this.pickBin(x, y);
            if (bin >= 0) this.nodeBins[bin].push(index);
        }
        for (let edge = 0; edge < data.edgeIds.length; edge++) {
            const sourceOffset = data.edgePairs[edge * 2] * 3;
            const targetOffset = data.edgePairs[edge * 2 + 1] * 3;
            if (
                this.nodeScreen[sourceOffset + 2] < -1
                || this.nodeScreen[sourceOffset + 2] > 1
                || this.nodeScreen[targetOffset + 2] < -1
                || this.nodeScreen[targetOffset + 2] > 1
            ) {
                continue;
            }
            const ax = this.nodeScreen[sourceOffset];
            const ay = this.nodeScreen[sourceOffset + 1];
            const bx = this.nodeScreen[targetOffset];
            const by = this.nodeScreen[targetOffset + 1];
            const steps = Math.max(
                1,
                Math.ceil(Math.max(Math.abs(bx - ax), Math.abs(by - ay)) / (PICK_CELL_SIZE * 0.5)),
            );
            let previousBin = -1;
            for (let step = 0; step <= steps; step++) {
                const t = step / steps;
                const bin = this.pickBin(THREE.MathUtils.lerp(ax, bx, t), THREE.MathUtils.lerp(ay, by, t));
                if (bin < 0 || bin === previousBin) continue;
                this.edgeBins[bin].push(edge);
                previousBin = bin;
            }
        }
        this.dirty = false;
    }

    private pickCandidates(bins: number[][], x: number, y: number): readonly number[] {
        this.candidates.length = 0;
        const centerX = Math.floor(x / PICK_CELL_SIZE);
        const centerY = Math.floor(y / PICK_CELL_SIZE);
        for (let row = Math.max(0, centerY - 1); row <= Math.min(this.rows - 1, centerY + 1); row++) {
            for (let column = Math.max(0, centerX - 1); column <= Math.min(this.columns - 1, centerX + 1); column++) {
                this.candidates.push(...bins[column + row * this.columns]);
            }
        }
        return this.candidates;
    }

    private pickBin(x: number, y: number): number {
        const column = Math.floor(x / PICK_CELL_SIZE);
        const row = Math.floor(y / PICK_CELL_SIZE);
        if (column < 0 || column >= this.columns || row < 0 || row >= this.rows) return -1;
        return column + row * this.columns;
    }
}

function resetBins(bins: number[][], count: number): number[][] {
    if (bins.length !== count) return Array.from({ length: count }, () => []);
    for (const bin of bins) bin.length = 0;
    return bins;
}

function pointSegmentDistanceSquared(
    px: number,
    py: number,
    ax: number,
    ay: number,
    bx: number,
    by: number,
): number {
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    if (lengthSquared <= 0.000001) return (px - ax) ** 2 + (py - ay) ** 2;
    const t = THREE.MathUtils.clamp(((px - ax) * dx + (py - ay) * dy) / lengthSquared, 0, 1);
    const x = ax + t * dx;
    const y = ay + t * dy;
    return (px - x) ** 2 + (py - y) ** 2;
}
