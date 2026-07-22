import * as THREE from 'three';

import {
    isTransitLayoutMode,
    mergeGalaxySettings,
    type GalaxyNodeDragMode,
    type GalaxyRenderSettings,
} from './graph-galaxy-engine';
import { galaxyIncidentEdges, type GalaxySceneV2 } from './graph-galaxy-scene-v2';

const EPSILON = 0.0008;
const MAX_XZ = 3.15;
const MAX_Y = 2.55;
const HYBRID_DEFAULT_BOUNDARY_RADIUS = 2.32;
const CAPS_DEFAULT_BOUNDARY_RADIUS = 2.18;
const HYBRID_SHELL_LOCK_RATIO = 0.92;
const HYBRID_MIN_RADIUS = 0.000001;
const HOPF_DEFAULT_BOUNDARY_RADIUS = 1.95;
const HOPF_BOUNDARY_PADDING = 1.04;
const HOPF_ANCHOR_RAIL_PULL = 0.08;
const HOPF_FIBER_RAIL_PULL = 0.16;
const TRANSIT_DEFAULT_BOUNDARY_RADIUS = 2.32;
const TRANSIT_BOUNDARY_PADDING = 1.1;
export const GALAXY_INTERACTIVE_FORCE_NODE_LIMIT = 384;
export const GALAXY_INTERACTIVE_FORCE_NEIGHBOR_LIMIT = 128;

export class GraphGalaxyForceController {
    private base3d = new Float32Array(0);
    private base2d = new Float32Array(0);
    private hybridShellLocked = new Uint8Array(0);
    private hybridShellRadius3d = new Float32Array(0);
    private hybridShellRadius2d = new Float32Array(0);
    private hierarchyShellRadii = new Float32Array(0);
    private hopfRailStrength = new Float32Array(0);
    private vx = new Float32Array(0);
    private vy = new Float32Array(0);
    private vz = new Float32Array(0);
    private fixed = new Uint8Array(0);
    private readonly dragDelta = new THREE.Vector3();
    private readonly neighbors: number[][] = [];
    private scene: GalaxySceneV2 | null = null;
    private settings: GalaxyRenderSettings = mergeGalaxySettings();
    private mode: '3d' | '2d' = '3d';
    private activeIndex = -1;
    private alpha = 0;
    private relaxing = false;
    private forceActive = false;
    private largeGraph = false;
    private hybridBoundaryRadius3d = HYBRID_DEFAULT_BOUNDARY_RADIUS;
    private hybridBoundaryRadius2d = HYBRID_DEFAULT_BOUNDARY_RADIUS;
    private hopfBoundaryRadius3d = HOPF_DEFAULT_BOUNDARY_RADIUS;
    private hopfBoundaryRadius2d = HOPF_DEFAULT_BOUNDARY_RADIUS;
    private transitBoundaryRadius3d = TRANSIT_DEFAULT_BOUNDARY_RADIUS;
    private transitBoundaryRadius2d = TRANSIT_DEFAULT_BOUNDARY_RADIUS;

    bind(scene: GalaxySceneV2): void {
        this.scene = scene;
        this.largeGraph = scene.ids.length > GALAXY_INTERACTIVE_FORCE_NODE_LIMIT;
        this.base3d = scene.positions3d.slice();
        this.base2d = scene.positions2d.slice();
        this.hybridShellLocked = new Uint8Array(scene.ids.length);
        this.hybridShellRadius3d = new Float32Array(scene.ids.length);
        this.hybridShellRadius2d = new Float32Array(scene.ids.length);
        this.hierarchyShellRadii = scene.hierarchyShellRadii?.slice() ?? new Float32Array(scene.ids.length);
        this.hopfRailStrength = new Float32Array(scene.ids.length);
        this.vx = new Float32Array(scene.ids.length);
        this.vy = new Float32Array(scene.ids.length);
        this.vz = new Float32Array(scene.ids.length);
        this.fixed = new Uint8Array(scene.ids.length);
        this.rebuildHybridConstraints(scene);
        this.rebuildHopfConstraints(scene);
        this.rebuildTransitConstraints(scene);
        this.constrainManifoldScene(scene);
        this.neighbors.length = this.largeGraph ? 0 : scene.ids.length;
        if (!this.largeGraph) {
            for (let i = 0; i < scene.ids.length; i++) this.neighbors[i] = [];
            for (let i = 0; i < scene.edgePairs.length; i += 2) {
                const a = scene.edgePairs[i];
                const b = scene.edgePairs[i + 1];
                if (a < this.neighbors.length && b < this.neighbors.length) {
                    this.neighbors[a].push(b);
                    this.neighbors[b].push(a);
                }
            }
        }
        this.activeIndex = -1;
        this.alpha = 0;
        this.relaxing = false;
        this.forceActive = false;
    }

    setSettings(settings: Partial<GalaxyRenderSettings> | null | undefined): void {
        const previous = this.settings;
        this.settings = mergeGalaxySettings(settings ?? undefined);
        const layoutChanged = previous.edgeLength !== this.settings.edgeLength || previous.nodeDistance !== this.settings.nodeDistance;
        if (!layoutChanged || !this.scene || this.scene.ids.length < 2) return;
        if (this.largeGraph) {
            this.forceActive = false;
            this.relaxing = false;
            this.alpha = 0;
            return;
        }
        if (isTransitLayoutMode(this.scene.layoutMode)) {
            this.applyTransitVolume(this.scene);
            this.forceActive = false;
            this.relaxing = false;
            this.alpha = 0;
            return;
        }
        if (this.scene.layoutMode !== 'single') return;
        this.forceActive = true;
        this.relaxing = false;
        this.alpha = Math.max(this.alpha, this.scene.edgePairs.length ? 0.62 : 0.36);
    }

    setMode(mode: '3d' | '2d'): void {
        this.mode = mode;
    }

    cancel(): void {
        this.activeIndex = -1;
        this.alpha = 0;
        this.relaxing = false;
        this.forceActive = false;
        this.vx.fill(0);
        this.vy.fill(0);
        this.vz.fill(0);
    }

    begin(nodeId: string): boolean {
        const indexed = this.scene?.runtimeIndex?.nodeById.get(nodeId);
        const index = indexed ?? (this.largeGraph ? -1 : this.scene?.ids.indexOf(nodeId) ?? -1);
        if (this.largeGraph && this.scene?.layoutMode !== 'single') return false;
        this.activeIndex = index;
        if (index >= 0) {
            this.vx[index] = 0;
            this.vy[index] = 0;
            this.vz[index] = 0;
        }
        return index >= 0;
    }

    writeActivePosition(out: THREE.Vector3): boolean {
        const scene = this.scene;
        if (!scene || this.activeIndex < 0) return false;
        const live = this.livePositions(scene);
        const offset = this.activeIndex * 3;
        out.set(live[offset], live[offset + 1], live[offset + 2]);
        return true;
    }

    dragTo(target: THREE.Vector3, mode: GalaxyNodeDragMode): boolean {
        const scene = this.scene;
        if (!scene || this.activeIndex < 0 || mode === 'camera') return false;
        const dragMode = this.effectiveDragMode(scene, mode);
        if (dragMode === 'stretch' && mode === 'force') return this.drag(this.dragDelta.set(
            target.x - this.livePositions(scene)[this.activeIndex * 3],
            target.y - this.livePositions(scene)[this.activeIndex * 3 + 1],
            this.mode === '2d' ? 0 : target.z - this.livePositions(scene)[this.activeIndex * 3 + 2],
        ), dragMode);
        const live = this.livePositions(scene);
        const offset = this.activeIndex * 3;
        this.dragDelta.set(
            target.x - live[offset],
            target.y - live[offset + 1],
            this.mode === '2d' ? 0 : target.z - live[offset + 2],
        );

        if (dragMode === 'force') {
            this.setPosition(live, this.activeIndex, target.x, target.y, this.mode === '2d' ? 0 : target.z);
            this.zeroVelocity(this.activeIndex);
            this.alpha = Math.max(this.alpha, 0.66);
            this.forceActive = true;
            this.relaxing = false;
            this.constrainAndSync(scene, live);
            return true;
        }

        return this.drag(this.dragDelta, dragMode);
    }

    drag(delta: THREE.Vector3, mode: GalaxyNodeDragMode): boolean {
        const scene = this.scene;
        if (!scene || this.activeIndex < 0 || mode === 'camera') return false;
        this.relaxing = false;
        this.forceActive = false;
        this.alpha = 0;
        this.move(scene.positions3d, this.activeIndex, delta.x, delta.y, delta.z);
        this.move(scene.positions2d, this.activeIndex, delta.x, delta.y, 0);
        const pull = mode === 'pin' ? 0.18 : 0.14;
        for (const neighbor of this.localNeighbors(scene, this.activeIndex)) {
            if (this.fixed[neighbor]) continue;
            this.move(scene.positions3d, neighbor, delta.x * pull, delta.y * pull, delta.z * pull);
            this.move(scene.positions2d, neighbor, delta.x * pull, delta.y * pull, 0);
        }
        this.constrainManifoldScene(scene);
        return true;
    }

    end(mode: GalaxyNodeDragMode): boolean {
        if (this.activeIndex < 0) return false;
        const scene = this.scene;
        const dragMode = scene ? this.effectiveDragMode(scene, mode) : mode;
        if (dragMode === 'pin') this.fixed[this.activeIndex] = 1;
        else if (dragMode === 'stretch') this.relaxing = !this.largeGraph;
        else if (dragMode === 'force') {
            this.forceActive = true;
            this.alpha = Math.max(this.alpha, 0.38);
        }
        this.activeIndex = -1;
        return this.active();
    }

    tick(): boolean {
        const scene = this.scene;
        if (!scene) return false;
        if (this.largeGraph) return false;
        if (this.forceActive && this.alpha > EPSILON) {
            this.tickForce(scene);
            return true;
        }
        if (this.relaxing) return this.tickElastic(scene);
        return false;
    }

    active(): boolean {
        return this.activeIndex >= 0 || this.relaxing || this.alpha > EPSILON;
    }

    private effectiveDragMode(scene: GalaxySceneV2, mode: GalaxyNodeDragMode): GalaxyNodeDragMode {
        return mode === 'force' && (scene.layoutMode !== 'single' || this.largeGraph) ? 'stretch' : mode;
    }

    private tickForce(scene: GalaxySceneV2): void {
        if (scene.layoutMode !== 'single' || this.largeGraph) {
            this.forceActive = false;
            this.alpha = 0;
            return;
        }
        const live = this.livePositions(scene);
        const base = this.mode === '2d' ? this.base2d : this.base3d;
        const count = scene.ids.length;
        const alpha = this.alpha;
        const targetLength = 0.34 + this.settings.edgeLength * 0.84;
        const repel = 0.0038 * this.settings.nodeDistance;
        const shellStrength = count > 48 && this.mode === '3d' ? 0.02 : 0.006;

        for (let i = 0; i < scene.edgePairs.length; i += 2) {
            this.applySpring(live, scene.edgePairs[i], scene.edgePairs[i + 1], targetLength, 0.021 * alpha);
        }

        for (let a = 0; a < count; a++) {
            for (let b = a + 1; b < count; b++) {
                this.applyRepulsion(live, scene.radii, a, b, repel * alpha);
            }
        }

        for (let i = 0; i < count; i++) {
            if (this.isLocked(i)) continue;
            const offset = i * 3;
            this.vx[i] += (base[offset] - live[offset]) * shellStrength * alpha;
            this.vy[i] += (base[offset + 1] - live[offset + 1]) * shellStrength * alpha;
            if (this.mode === '3d') this.vz[i] += (base[offset + 2] - live[offset + 2]) * shellStrength * alpha;
        }

        let kinetic = 0;
        for (let i = 0; i < count; i++) {
            if (this.isLocked(i)) {
                this.zeroVelocity(i);
                continue;
            }
            const offset = i * 3;
            live[offset] = clamp(live[offset] + this.vx[i] * alpha, -MAX_XZ, MAX_XZ);
            live[offset + 1] = clamp(live[offset + 1] + this.vy[i] * alpha, -MAX_Y, MAX_Y);
            if (this.mode === '3d') live[offset + 2] = clamp(live[offset + 2] + this.vz[i] * alpha, -MAX_XZ, MAX_XZ);
            else live[offset + 2] = 0;
            kinetic = Math.max(kinetic, Math.abs(this.vx[i]) + Math.abs(this.vy[i]) + Math.abs(this.vz[i]));
            this.vx[i] *= 0.82;
            this.vy[i] *= 0.82;
            this.vz[i] *= 0.82;
        }

        this.constrainAndSync(scene, live);
        this.alpha *= 0.92;
        if (this.alpha <= EPSILON || kinetic <= EPSILON) {
            this.alpha = 0;
            this.forceActive = false;
        }
    }

    private tickElastic(scene: GalaxySceneV2): boolean {
        if (this.largeGraph) return false;
        const live = this.livePositions(scene);
        const base = this.mode === '2d' ? this.base2d : this.base3d;
        let maxDelta = 0;
        for (let index = 0; index < scene.ids.length; index++) {
            if (this.fixed[index]) continue;
            const offset = index * 3;
            for (let axis = 0; axis < 3; axis++) {
                if (this.mode === '2d' && axis === 2) continue;
                const next = live[offset + axis] + (base[offset + axis] - live[offset + axis]) * 0.18;
                maxDelta = Math.max(maxDelta, Math.abs(next - live[offset + axis]));
                live[offset + axis] = next;
            }
        }
        this.constrainAndSync(scene, live);
        this.relaxing = maxDelta > EPSILON;
        return this.relaxing;
    }

    private applySpring(live: Float32Array, a: number, b: number, target: number, strength: number): void {
        if (a === b) return;
        const ao = a * 3;
        const bo = b * 3;
        const dx = live[bo] - live[ao];
        const dy = live[bo + 1] - live[ao + 1];
        const dz = this.mode === '2d' ? 0 : live[bo + 2] - live[ao + 2];
        const distSq = dx * dx + dy * dy + dz * dz + 0.000001;
        const dist = Math.sqrt(distSq);
        const force = (dist - target) * strength / dist;
        this.addForce(a, dx * force, dy * force, dz * force);
        this.addForce(b, -dx * force, -dy * force, -dz * force);
    }

    private applyRepulsion(live: Float32Array, radii: Float32Array, a: number, b: number, strength: number): void {
        const ao = a * 3;
        const bo = b * 3;
        let dx = live[bo] - live[ao];
        let dy = live[bo + 1] - live[ao + 1];
        let dz = this.mode === '2d' ? 0 : live[bo + 2] - live[ao + 2];
        let distSq = dx * dx + dy * dy + dz * dz;
        if (distSq < 0.000001) {
            dx = ((a * 17 + b * 13) % 19 - 9) * 0.001;
            dy = ((a * 11 + b * 7) % 17 - 8) * 0.001;
            dz = this.mode === '2d' ? 0 : ((a * 5 + b * 3) % 13 - 6) * 0.001;
            distSq = dx * dx + dy * dy + dz * dz;
        }
        const dist = Math.sqrt(distSq);
        const minDist = 0.045 + (radii[a] + radii[b]) * 0.014;
        const push = (strength / distSq) + (dist < minDist ? (minDist - dist) * 0.065 : 0);
        const fx = (dx / dist) * push;
        const fy = (dy / dist) * push;
        const fz = (dz / dist) * push;
        this.addForce(a, -fx, -fy, -fz);
        this.addForce(b, fx, fy, fz);
    }

    private addForce(index: number, x: number, y: number, z: number): void {
        if (this.isLocked(index)) return;
        this.vx[index] += x;
        this.vy[index] += y;
        this.vz[index] += z;
    }

    private isLocked(index: number): boolean {
        return this.fixed[index] === 1 || index === this.activeIndex;
    }

    private zeroVelocity(index: number): void {
        this.vx[index] = 0;
        this.vy[index] = 0;
        this.vz[index] = 0;
    }

    private localNeighbors(scene: GalaxySceneV2, index: number): number[] {
        if (!this.largeGraph) return this.neighbors[index] ?? [];
        const neighbors: number[] = [];
        const seen = new Set<number>();
        for (const edge of galaxyIncidentEdges(scene, index)) {
            const source = scene.edgePairs[edge * 2];
            const target = scene.edgePairs[edge * 2 + 1];
            const neighbor = source === index ? target : target === index ? source : -1;
            if (neighbor < 0 || seen.has(neighbor)) continue;
            seen.add(neighbor);
            neighbors.push(neighbor);
            if (neighbors.length >= GALAXY_INTERACTIVE_FORCE_NEIGHBOR_LIMIT) break;
        }
        return neighbors;
    }

    private livePositions(scene: GalaxySceneV2): Float32Array {
        return this.mode === '2d' ? scene.positions2d : scene.positions3d;
    }

    private move(buffer: Float32Array, index: number, x: number, y: number, z: number): void {
        const offset = index * 3;
        buffer[offset] += x;
        buffer[offset + 1] += y;
        buffer[offset + 2] += z;
    }

    private setPosition(buffer: Float32Array, index: number, x: number, y: number, z: number): void {
        const offset = index * 3;
        buffer[offset] = clamp(x, -MAX_XZ, MAX_XZ);
        buffer[offset + 1] = clamp(y, -MAX_Y, MAX_Y);
        buffer[offset + 2] = this.mode === '2d' ? 0 : clamp(z, -MAX_XZ, MAX_XZ);
    }

    private rebuildHybridConstraints(scene: GalaxySceneV2): void {
        const shellConstrained = scene.layoutMode === 'hybridSpace' || scene.layoutMode === 'lorentzTree';
        const defaultRadius = scene.layoutMode === 'lorentzTree' ? CAPS_DEFAULT_BOUNDARY_RADIUS : HYBRID_DEFAULT_BOUNDARY_RADIUS;
        this.hybridBoundaryRadius3d = defaultRadius;
        this.hybridBoundaryRadius2d = defaultRadius;
        if (!shellConstrained) return;

        for (let i = 0; i < scene.ids.length; i++) {
            const radius3d = pointRadius(this.base3d, i, true);
            const radius2d = pointRadius(this.base2d, i, false);
            if (Number.isFinite(radius3d)) this.hybridBoundaryRadius3d = Math.max(this.hybridBoundaryRadius3d, radius3d);
            if (Number.isFinite(radius2d)) this.hybridBoundaryRadius2d = Math.max(this.hybridBoundaryRadius2d, radius2d);
            this.hybridShellRadius3d[i] = radius3d;
            this.hybridShellRadius2d[i] = radius2d;
        }

        const shellCutoff = this.hybridBoundaryRadius3d * HYBRID_SHELL_LOCK_RATIO;
        for (let i = 0; i < scene.ids.length; i++) {
            const contractRadius = this.hierarchyShellRadii[i] || 0;
            if (scene.layoutMode === 'lorentzTree' && contractRadius > 0) {
                this.hybridShellRadius3d[i] = contractRadius;
                this.hybridShellRadius2d[i] = contractRadius;
                this.hybridShellLocked[i] = 1;
                continue;
            }
            this.hybridShellLocked[i] = this.hybridShellRadius3d[i] >= shellCutoff ? 1 : 0;
        }
    }

    private constrainAndSync(scene: GalaxySceneV2, live: Float32Array): void {
        this.constrainManifoldBuffer(scene, live);
        this.syncTwinBuffers(scene, live);
        this.constrainManifoldScene(scene);
    }

    private constrainManifoldScene(scene: GalaxySceneV2): void {
        this.constrainManifoldBuffer(scene, scene.positions3d);
        this.constrainManifoldBuffer(scene, scene.positions2d);
    }

    private constrainManifoldBuffer(scene: GalaxySceneV2, buffer: Float32Array): void {
        this.constrainHybridBuffer(scene, buffer);
        this.constrainHopfBuffer(scene, buffer);
        this.constrainTransitBuffer(scene, buffer);
    }

    private constrainHybridBuffer(scene: GalaxySceneV2, buffer: Float32Array): void {
        if (scene.layoutMode !== 'hybridSpace' && scene.layoutMode !== 'lorentzTree') return;
        const is3d = buffer === scene.positions3d && this.mode !== '2d';
        const boundaryRadius = is3d ? this.hybridBoundaryRadius3d : this.hybridBoundaryRadius2d;
        const shellRadii = is3d ? this.hybridShellRadius3d : this.hybridShellRadius2d;
        for (let i = 0; i < scene.ids.length; i++) {
            const offset = i * 3;
            const x = buffer[offset];
            const y = buffer[offset + 1];
            const z = is3d ? buffer[offset + 2] : 0;
            const radius = Math.hypot(x, y, z);
            const shellLocked = this.hybridShellLocked[i] === 1;
            const shellRadius = shellRadii[i] || boundaryRadius;
            const targetRadius = shellLocked
                ? clamp(shellRadius, HYBRID_MIN_RADIUS, boundaryRadius)
                : Math.min(radius, boundaryRadius);

            if (radius <= HYBRID_MIN_RADIUS) {
                if (shellLocked) this.writeBaseDirection(buffer, i, is3d, targetRadius);
                if (!is3d) buffer[offset + 2] = 0;
                continue;
            }
            if (!shellLocked && radius <= boundaryRadius + EPSILON) {
                if (!is3d) buffer[offset + 2] = 0;
                continue;
            }

            const scale = targetRadius / radius;
            buffer[offset] = x * scale;
            buffer[offset + 1] = y * scale;
            buffer[offset + 2] = is3d ? z * scale : 0;
            this.zeroVelocity(i);
        }
    }

    private rebuildHopfConstraints(scene: GalaxySceneV2): void {
        this.hopfBoundaryRadius3d = HOPF_DEFAULT_BOUNDARY_RADIUS;
        this.hopfBoundaryRadius2d = HOPF_DEFAULT_BOUNDARY_RADIUS;
        this.hopfRailStrength.fill(0);
        if (scene.layoutMode !== 'hopfProjection') return;
        for (let i = 0; i < scene.ids.length; i++) {
            const radius3d = pointRadius(this.base3d, i, true);
            const radius2d = pointRadius(this.base2d, i, false);
            if (Number.isFinite(radius3d)) this.hopfBoundaryRadius3d = Math.max(this.hopfBoundaryRadius3d, radius3d * HOPF_BOUNDARY_PADDING);
            if (Number.isFinite(radius2d)) this.hopfBoundaryRadius2d = Math.max(this.hopfBoundaryRadius2d, radius2d * HOPF_BOUNDARY_PADDING);
            const role = scene.hopfRoles?.[i] || 0;
            this.hopfRailStrength[i] = role === 1 ? HOPF_ANCHOR_RAIL_PULL : role === 2 ? HOPF_FIBER_RAIL_PULL : 0;
        }
    }

    private constrainHopfBuffer(scene: GalaxySceneV2, buffer: Float32Array): void {
        if (scene.layoutMode !== 'hopfProjection') return;
        const is3d = buffer === scene.positions3d && this.mode !== '2d';
        const base = is3d ? this.base3d : this.base2d;
        const boundaryRadius = is3d ? this.hopfBoundaryRadius3d : this.hopfBoundaryRadius2d;
        for (let i = 0; i < scene.ids.length; i++) {
            const offset = i * 3;
            let x = buffer[offset];
            let y = buffer[offset + 1];
            let z = is3d ? buffer[offset + 2] : 0;
            const radius = Math.hypot(x, y, z);
            if (!is3d) buffer[offset + 2] = 0;
            if (radius > boundaryRadius + EPSILON && radius > HYBRID_MIN_RADIUS) {
                const scale = Math.max(HYBRID_MIN_RADIUS, boundaryRadius - EPSILON) / radius;
                x *= scale;
                y *= scale;
                z = is3d ? z * scale : 0;
                this.zeroVelocity(i);
            }
            const rail = i === this.activeIndex ? 0 : this.hopfRailStrength[i];
            if (rail > 0) {
                x += (base[offset] - x) * rail;
                y += (base[offset + 1] - y) * rail;
                z = is3d ? z + (base[offset + 2] - z) * rail : 0;
                this.vx[i] *= 1 - rail;
                this.vy[i] *= 1 - rail;
                this.vz[i] *= 1 - rail;
            }
            buffer[offset] = x;
            buffer[offset + 1] = y;
            buffer[offset + 2] = is3d ? z : 0;
        }
    }

    private rebuildTransitConstraints(scene: GalaxySceneV2): void {
        this.transitBoundaryRadius3d = TRANSIT_DEFAULT_BOUNDARY_RADIUS;
        this.transitBoundaryRadius2d = TRANSIT_DEFAULT_BOUNDARY_RADIUS;
        if (!isTransitLayoutMode(scene.layoutMode)) return;
        const expansion = transitManifoldExpansionScale(this.settings);
        for (let i = 0; i < scene.ids.length; i++) {
            const radius3d = pointRadius(this.base3d, i, true);
            const radius2d = pointRadius(this.base2d, i, false);
            if (Number.isFinite(radius3d)) this.transitBoundaryRadius3d = Math.max(this.transitBoundaryRadius3d, radius3d * expansion * TRANSIT_BOUNDARY_PADDING);
            if (Number.isFinite(radius2d)) this.transitBoundaryRadius2d = Math.max(this.transitBoundaryRadius2d, radius2d * expansion * TRANSIT_BOUNDARY_PADDING);
        }
    }

    private applyTransitVolume(scene: GalaxySceneV2): void {
        if (!isTransitLayoutMode(scene.layoutMode)) return;
        const expansion = transitManifoldExpansionScale(this.settings);
        this.scaleFromBase(this.base3d, scene.positions3d, expansion, true);
        this.scaleFromBase(this.base2d, scene.positions2d, expansion, false);
        this.rebuildTransitConstraints(scene);
        this.vx.fill(0);
        this.vy.fill(0);
        this.vz.fill(0);
    }

    private scaleFromBase(base: Float32Array, target: Float32Array, scale: number, is3d: boolean): void {
        for (let offset = 0; offset < target.length; offset += 3) {
            target[offset] = base[offset] * scale;
            target[offset + 1] = base[offset + 1] * scale;
            target[offset + 2] = is3d ? base[offset + 2] * scale : 0;
        }
    }

    private constrainTransitBuffer(scene: GalaxySceneV2, buffer: Float32Array): void {
        if (!isTransitLayoutMode(scene.layoutMode)) return;
        const is3d = buffer === scene.positions3d && this.mode !== '2d';
        const boundaryRadius = is3d ? this.transitBoundaryRadius3d : this.transitBoundaryRadius2d;
        for (let i = 0; i < scene.ids.length; i++) {
            const offset = i * 3;
            const x = buffer[offset];
            const y = buffer[offset + 1];
            const z = is3d ? buffer[offset + 2] : 0;
            const radius = Math.hypot(x, y, z);
            if (!is3d) buffer[offset + 2] = 0;
            if (radius <= boundaryRadius + EPSILON || radius <= HYBRID_MIN_RADIUS) continue;

            const scale = Math.max(HYBRID_MIN_RADIUS, boundaryRadius - EPSILON) / radius;
            buffer[offset] = x * scale;
            buffer[offset + 1] = y * scale;
            buffer[offset + 2] = is3d ? z * scale : 0;
            this.zeroVelocity(i);
        }
    }

    private writeBaseDirection(buffer: Float32Array, index: number, is3d: boolean, radius: number): void {
        const base = is3d ? this.base3d : this.base2d;
        const offset = index * 3;
        const bx = base[offset];
        const by = base[offset + 1];
        const bz = is3d ? base[offset + 2] : 0;
        const baseRadius = Math.hypot(bx, by, bz);
        if (baseRadius <= HYBRID_MIN_RADIUS) return;
        const scale = radius / baseRadius;
        buffer[offset] = bx * scale;
        buffer[offset + 1] = by * scale;
        buffer[offset + 2] = is3d ? bz * scale : 0;
        this.zeroVelocity(index);
    }

    private syncTwinBuffers(scene: GalaxySceneV2, live: Float32Array): void {
        if (live === scene.positions2d) this.copy2dTo3d(scene);
        else this.copy3dTo2d(scene);
    }

    private copy2dTo3d(scene: GalaxySceneV2): void {
        for (let i = 0; i < scene.ids.length; i++) {
            scene.positions3d[i * 3] = scene.positions2d[i * 3];
            scene.positions3d[i * 3 + 1] = scene.positions2d[i * 3 + 1];
        }
    }

    private copy3dTo2d(scene: GalaxySceneV2): void {
        for (let i = 0; i < scene.ids.length; i++) {
            scene.positions2d[i * 3] = scene.positions3d[i * 3];
            scene.positions2d[i * 3 + 1] = scene.positions3d[i * 3 + 1];
        }
    }
}

export function transitManifoldExpansionScale(settings: Pick<GalaxyRenderSettings, 'edgeLength' | 'nodeDistance'>): number {
    const distance = clamp(settings.nodeDistance, 0.15, 3.2);
    const edgeLength = clamp(settings.edgeLength, 0.15, 3.4);
    return clamp(1 + (distance - 1) * 0.28 + (edgeLength - 1) * 0.16, 0.68, 1.82);
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

function pointRadius(buffer: Float32Array, index: number, includeZ: boolean): number {
    const offset = index * 3;
    return Math.hypot(buffer[offset], buffer[offset + 1], includeZ ? buffer[offset + 2] : 0);
}
