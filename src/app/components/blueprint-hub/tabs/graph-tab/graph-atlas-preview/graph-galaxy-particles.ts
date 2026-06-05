import * as THREE from 'three';

import type { GalaxyRenderSettings } from './graph-galaxy-engine';
import type { GalaxyFocusMask } from './graph-galaxy-focus';
import type { GalaxyLorentzGuideView, GalaxySceneV2 } from './graph-galaxy-scene-v2';

const MAX_FLOW_PARTICLES = 1800;
const EMPTY_VEC3 = new Float32Array(0);
const EMPTY_SCALAR = new Float32Array(0);
const CAPS_SURFACE_EDGE_MIN_RADIUS = 0.34;
const CAPS_SURFACE_EDGE_MAX_RADIUS_DELTA = 0.36;
const CAPS_SHELL_RADII = [0.54, 0.98, 1.22, 1.34, 1.48, 1.68, 1.92];
const HYBRID_SURFACE_EDGE_MIN_RADIUS = 2.32 * 0.92;
const HYBRID_SURFACE_EDGE_MAX_RADIUS_DELTA = 0.42;
const TREE_FILAMENT_FLOW_LAYOUTS = new Set(['lorentzTree', 'productManifold', 'siegelFinsler']);
type FlowSource = { kind: 'edge'; index: number } | { kind: 'guide'; index: number };

export class GraphGalaxyParticles {
    readonly points: THREE.Points;
    private readonly geometry = new THREE.BufferGeometry();
    private readonly material = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: true,
        blending: THREE.NormalBlending,
        toneMapped: false,
        vertexColors: true,
        uniforms: {
            uBaseSize: { value: 7 },
        },
        vertexShader: `
            uniform float uBaseSize;
            attribute float alpha;
            attribute float flowSize;
            varying vec3 vColor;
            varying float vAlpha;

            void main() {
                vColor = color;
                vAlpha = alpha;
                vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
                float perspectiveScale = clamp(180.0 / max(110.0, -mvPosition.z), 0.85, 1.55);
                gl_PointSize = min(7.2, flowSize * uBaseSize * perspectiveScale);
                gl_Position = projectionMatrix * mvPosition;
            }
        `,
        fragmentShader: `
            varying vec3 vColor;
            varying float vAlpha;

            void main() {
                float dist = length(gl_PointCoord - vec2(0.5));
                float softDot = smoothstep(0.5, 0.12, dist);
                float core = smoothstep(0.28, 0.0, dist);
                vec3 litColor = vColor * (0.82 + core * 0.18);
                gl_FragColor = vec4(litColor, vAlpha * softDot);
            }
        `,
    });
    private readonly flowSources: FlowSource[] = [];
    private readonly seeds: number[] = [];
    private readonly speeds: number[] = [];

    constructor() {
        this.points = new THREE.Points(this.geometry, this.material);
        this.points.frustumCulled = false;
    }

    bind(data: GalaxySceneV2, settings: GalaxyRenderSettings): void {
        this.flowSources.length = 0;
        this.seeds.length = 0;
        this.speeds.length = 0;
        const edgeCount = data.edgePairs.length / 2;
        const guideIndexes = this.guideFlowIndexes(data);
        const sourceCount = edgeCount + guideIndexes.length;
        if (!settings.particleFlow || sourceCount === 0) {
            this.setEmptyAttributes();
            this.points.visible = false;
            return;
        }

        const particleCount = Math.min(sourceCount, MAX_FLOW_PARTICLES);
        const stride = sourceCount / particleCount;
        for (let i = 0; i < particleCount; i++) {
            const source = Math.min(sourceCount - 1, Math.floor(i * stride));
            const sourceRef: FlowSource = source < edgeCount
                ? { kind: 'edge', index: source }
                : { kind: 'guide', index: guideIndexes[source - edgeCount] };
            const seedKey = sourceRef.kind === 'edge' ? sourceRef.index * 17 + 3 : sourceRef.index * 23 + 101;
            const seed = this.stableUnit(seedKey);
            this.flowSources.push(sourceRef);
            this.seeds.push(seed);
            this.speeds.push(0.23 + this.stableUnit(seedKey * 31 + 11) * 0.32);
        }

        const count = this.flowSources.length;
        this.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
        this.geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
        this.geometry.setAttribute('alpha', new THREE.BufferAttribute(new Float32Array(count), 1));
        this.geometry.setAttribute('flowSize', new THREE.BufferAttribute(new Float32Array(count), 1));
        this.updateSettings(settings);
        this.points.visible = true;
    }

    updateSettings(settings: GalaxyRenderSettings): void {
        this.material.uniforms['uBaseSize'].value = 3.35 + settings.particleSize * 0.95;
        this.points.visible = settings.particleFlow && this.flowSources.length > 0;
    }

    update(
        data: GalaxySceneV2 | null,
        positions: Float32Array | null,
        settings: GalaxyRenderSettings,
        time: number,
        focus?: GalaxyFocusMask | null,
    ): void {
        if (!data || !positions || !this.points.visible) return;
        const positionAttr = this.geometry.getAttribute('position') as THREE.BufferAttribute;
        const colorAttr = this.geometry.getAttribute('color') as THREE.BufferAttribute;
        const alphaAttr = this.geometry.getAttribute('alpha') as THREE.BufferAttribute;
        const sizeAttr = this.geometry.getAttribute('flowSize') as THREE.BufferAttribute;
        const baseAlpha = settings.particleOpacity * (focus?.hasFocus ? 0.72 : 0.42);
        const flowSize = 0.62 + settings.particleSize * 0.1;
        const curved = settings.edgeMode === 'curved' || settings.edgeMode === 'tube';
        for (let i = 0; i < this.flowSources.length; i++) {
            const flowSource = this.flowSources[i];
            const t = (this.seeds[i] + time * 0.001 * this.speeds[i] * settings.particleSpeed) % 1;
            if (flowSource.kind === 'edge') {
                const edge = flowSource.index;
                const source = data.edgePairs[edge * 2];
                const target = data.edgePairs[edge * 2 + 1];
                const lift = settings.edgeMode === 'tube'
                    ? this.edgeTubeLift(data, settings, edge, source, target)
                    : curved ? this.edgeLift(data, settings, edge, source, target) : 0;
                if (settings.edgeMode === 'tube') {
                    this.writeTubeEdgePosition(positionAttr, i, data, positions, edge, source, target, lift, t);
                } else {
                    this.writeEdgePosition(positionAttr, i, data, positions, source, target, lift, t);
                }
                this.writeTargetColor(colorAttr, data, edge, i);
                alphaAttr.setX(i, focus?.hasFocus && focus.edgeLevels[edge] === 0 ? 0 : baseAlpha);
                sizeAttr.setX(i, flowSize * (settings.edgeMode === 'tube' ? 1.08 : 1));
                continue;
            }
            const guide = data.lorentzGuides[flowSource.index];
            this.writeGuidePosition(positionAttr, i, data, positions, guide, t);
            this.writeGuideColor(colorAttr, guide, i);
            alphaAttr.setX(i, baseAlpha * 0.74 * this.guideFocusAlpha(data, focus, guide));
            sizeAttr.setX(i, flowSize * THREE.MathUtils.clamp(0.72 + Math.sqrt(Math.max(0.08, guide.guideWeight || 0.7)) * 0.18, 0.82, 1.02));
        }
        positionAttr.needsUpdate = true;
        colorAttr.needsUpdate = true;
        alphaAttr.needsUpdate = true;
        sizeAttr.needsUpdate = true;
    }

    dispose(): void {
        this.geometry.dispose();
        this.material.dispose();
    }

    private setEmptyAttributes(): void {
        this.geometry.setAttribute('position', new THREE.BufferAttribute(EMPTY_VEC3, 3));
        this.geometry.setAttribute('color', new THREE.BufferAttribute(EMPTY_VEC3, 3));
        this.geometry.setAttribute('alpha', new THREE.BufferAttribute(EMPTY_SCALAR, 1));
        this.geometry.setAttribute('flowSize', new THREE.BufferAttribute(EMPTY_SCALAR, 1));
    }

    private guideFlowIndexes(data: GalaxySceneV2): number[] {
        if (!this.liveGuideFlow(data)) return [];
        const indexes: number[] = [];
        for (let index = 0; index < data.lorentzGuides.length; index++) {
            const guide = data.lorentzGuides[index];
            if ((guide.guideKind === 'membership' || guide.guideKind === 'rootLane') && guide.positions3d.length >= 6) indexes.push(index);
        }
        return indexes;
    }

    private liveGuideFlow(data: GalaxySceneV2): boolean {
        return data.layoutMode === 'lorentzTree' || data.layoutMode === 'productManifold' || data.layoutMode === 'siegelFinsler';
    }

    private edgeLift(data: GalaxySceneV2, settings: GalaxyRenderSettings, edge: number, source: number, target: number): number {
        const interGalaxy = data.edgeKinds[edge] === 1;
        const curveScale = THREE.MathUtils.clamp(settings.edgeCurveStrength, 0.25, 1.2) * (interGalaxy ? 0.92 : 0.58);
        if (this.usesTreeFilamentFlow(data)) {
            return this.treeFilamentEdgeLift(data, edge, source, target, curveScale);
        }
        return (0.08 + Math.abs(source - target) * 0.002) * curveScale + (interGalaxy ? 0.18 : 0);
    }

    private edgeTubeLift(data: GalaxySceneV2, settings: GalaxyRenderSettings, edge: number, source: number, target: number): number {
        const curveScale = THREE.MathUtils.clamp(settings.edgeCurveStrength, 0.25, 1.2);
        if (this.usesTreeFilamentFlow(data)) {
            const kindScale = data.edgeKinds[edge] === 1 ? 0.74 : data.edgeKinds[edge] === 2 ? 0.68 : 0.62;
            return this.treeFilamentEdgeLift(data, edge, source, target, curveScale * kindScale);
        }
        const confidence = THREE.MathUtils.clamp(data.edgeAlpha[edge] ?? 0.45, 0.12, 1);
        const bridgeBoost = data.edgeKinds[edge] === 1 ? 1.38 : 1;
        const span = Math.sqrt(Math.max(1, Math.abs(source - target)));
        return (0.045 + confidence * 0.13 + span * 0.004) * bridgeBoost * curveScale;
    }

    private writeEdgePosition(
        positionAttr: THREE.BufferAttribute,
        particle: number,
        data: GalaxySceneV2,
        positions: Float32Array,
        source: number,
        target: number,
        lift: number,
        t: number,
    ): void {
        if (this.capsSurfaceParticle(data, positions, source, target)) {
            const point = this.capsSurfacePoint(positions, source, target, t);
            if (point) {
                positionAttr.setXYZ(particle, point.x, point.y, point.z);
                return;
            }
        }
        positionAttr.setXYZ(particle, this.edgeX(positions, source, target, t), this.edgeY(positions, source, target, lift, t), this.edgeZ(positions, source, target, t));
    }

    private writeTubeEdgePosition(
        positionAttr: THREE.BufferAttribute,
        particle: number,
        data: GalaxySceneV2,
        positions: Float32Array,
        edge: number,
        source: number,
        target: number,
        lift: number,
        t: number,
    ): void {
        if (this.capsSurfaceParticle(data, positions, source, target)) {
            const point = this.capsSurfacePoint(positions, source, target, t);
            if (point) {
                positionAttr.setXYZ(particle, point.x, point.y, point.z);
                return;
            }
        }
        const ax = positions[source * 3], ay = positions[source * 3 + 1], az = positions[source * 3 + 2];
        const bx = positions[target * 3], by = positions[target * 3 + 1], bz = positions[target * 3 + 2];
        const dx = bx - ax;
        const dy = by - ay;
        const xy = Math.hypot(dx, dy) || 1;
        const sign = this.stableUnit(`tube-edge:${edge}`) < 0.5 ? -1 : 1;
        const sweep = Math.sin(Math.PI * t);
        const braid = Math.sin(Math.PI * 2 * t + sign * 0.72) * lift * 0.08;
        const flourish = this.tubeEdgeTerminalFlourish(data, t, lift, sign);
        const lateral = lift * 0.34 * sweep * sign + flourish;
        positionAttr.setXYZ(
            particle,
            THREE.MathUtils.lerp(ax, bx, t) + (-dy / xy) * lateral,
            THREE.MathUtils.lerp(ay, by, t) + (dx / xy) * lateral + lift * 0.38 * sweep + Math.abs(flourish) * 0.08,
            THREE.MathUtils.lerp(az, bz, t) + lift * 0.24 * sweep * sign + braid + flourish * 0.42,
        );
    }

    private tubeEdgeTerminalFlourish(data: GalaxySceneV2, t: number, lift: number, sign: number): number {
        if (!this.usesTreeFilamentFlow(data)) return 0;
        const width = data.layoutMode === 'productManifold' ? 0.3 : 0.26;
        const end = t > 1 - width ? Math.sin(Math.PI * (1 - t) / width) : 0;
        const style = data.layoutMode === 'siegelFinsler' ? 0.21 : data.layoutMode === 'lorentzTree' ? 0.18 : 0.16;
        return lift * style * sign * end;
    }

    private writeGuidePosition(
        positionAttr: THREE.BufferAttribute,
        particle: number,
        data: GalaxySceneV2,
        positions: Float32Array,
        guide: GalaxyLorentzGuideView,
        t: number,
    ): void {
        const point = guide.guideKind === 'rootLane' && this.usesTreeFilamentFlow(data)
            ? this.slantedRootLanePoint(guide, t)
            : this.reanchoredGuidePoint(data, positions, guide, t) ?? this.staticGuidePoint(guide, t);
        positionAttr.setXYZ(particle, point.x, point.y, point.z);
    }

    private reanchoredGuidePoint(
        data: GalaxySceneV2,
        positions: Float32Array,
        guide: GalaxyLorentzGuideView,
        t: number,
    ): { x: number; y: number; z: number } | null {
        if (positions !== data.positions3d && positions !== data.positions2d) return null;
        const sourceIndex = data.ids.indexOf(guide.nodeIds[0] || '');
        const targetIndex = data.ids.indexOf(guide.nodeIds[1] || '');
        if (sourceIndex < 0 || targetIndex < 0 || guide.guideKind !== 'membership') return null;
        const last = guide.positions3d.length - 3;
        const oldA = { x: guide.positions3d[0], y: guide.positions3d[1], z: guide.positions3d[2] };
        const oldB = { x: guide.positions3d[last], y: guide.positions3d[last + 1], z: guide.positions3d[last + 2] };
        const point = this.staticGuidePoint(guide, t);
        const odx = oldB.x - oldA.x, ody = oldB.y - oldA.y, odz = oldB.z - oldA.z;
        const oldLenSq = Math.max(0.000001, odx * odx + ody * ody + odz * odz);
        const newA = { x: positions[sourceIndex * 3], y: positions[sourceIndex * 3 + 1], z: positions[sourceIndex * 3 + 2] };
        const newB = { x: positions[targetIndex * 3], y: positions[targetIndex * 3 + 1], z: positions[targetIndex * 3 + 2] };
        const ndx = newB.x - newA.x, ndy = newB.y - newA.y, ndz = newB.z - newA.z;
        const offsetScale = THREE.MathUtils.clamp(Math.sqrt((ndx * ndx + ndy * ndy + ndz * ndz) / oldLenSq), 0.25, 2.4);
        const localT = THREE.MathUtils.clamp(((point.x - oldA.x) * odx + (point.y - oldA.y) * ody + (point.z - oldA.z) * odz) / oldLenSq, 0, 1);
        const oldBase = { x: oldA.x + odx * localT, y: oldA.y + ody * localT, z: oldA.z + odz * localT };
        const envelope = this.usesTreeFilamentFlow(data) ? this.treeFilamentTerminalTaper(localT) : 1;
        return {
            x: newA.x + ndx * localT + (point.x - oldBase.x) * offsetScale * envelope,
            y: newA.y + ndy * localT + (point.y - oldBase.y) * offsetScale * envelope,
            z: newA.z + ndz * localT + (point.z - oldBase.z) * offsetScale * envelope,
        };
    }

    private slantedRootLanePoint(guide: GalaxyLorentzGuideView, t: number): { x: number; y: number; z: number } {
        const point = this.staticGuidePoint(guide, t);
        const seed = this.stableUnit(`root-lane-slant:${guide.id}`);
        const slope = 0.1 + seed * 0.08;
        const depthSlope = 0.025 + seed * 0.035;
        const phase = (seed - 0.5) * 0.12;
        return {
            x: point.x,
            y: point.y + point.x * slope + phase,
            z: point.z + point.x * depthSlope,
        };
    }

    private usesTreeFilamentFlow(data: Pick<GalaxySceneV2, 'layoutMode'>): boolean {
        return TREE_FILAMENT_FLOW_LAYOUTS.has(data.layoutMode);
    }

    private normalizedEdgeSignal(data: Pick<GalaxySceneV2, 'edgeAlpha'>, edge = 0): number {
        const alpha = data.edgeAlpha[edge] ?? 0.18;
        return THREE.MathUtils.clamp((alpha - 0.052) / 0.288, 0, 1);
    }

    private treeFilamentEdgeLift(data: Pick<GalaxySceneV2, 'edgeAlpha' | 'edgeKinds'>, edge: number, source: number, target: number, curveScale: number): number {
        const signal = this.normalizedEdgeSignal(data, edge);
        const span = Math.sqrt(Math.max(1, Math.abs(source - target)));
        const spanLift = THREE.MathUtils.clamp(span * 0.022, 0.045, 0.42);
        const kindBoost = data.edgeKinds[edge] === 1 ? 1.42 : data.edgeKinds[edge] === 2 ? 1.24 : 1;
        const signalBoost = 0.82 + signal * 0.55;
        return (0.11 + spanLift + signal * 0.14) * curveScale * kindBoost * signalBoost;
    }

    private treeFilamentTerminalTaper(t: number): number {
        const start = THREE.MathUtils.smoothstep(t, 0.02, 0.16);
        const end = 1 - THREE.MathUtils.smoothstep(t, 0.58, 0.96);
        return THREE.MathUtils.clamp(start * end, 0, 1);
    }

    private staticGuidePoint(guide: GalaxyLorentzGuideView, t: number): { x: number; y: number; z: number } {
        const segments = Math.max(1, Math.floor(guide.positions3d.length / 6));
        const raw = THREE.MathUtils.clamp(t, 0, 0.999999) * segments;
        const segment = Math.min(segments - 1, Math.floor(raw));
        const local = raw - segment;
        const offset = segment * 6;
        return {
            x: THREE.MathUtils.lerp(guide.positions3d[offset], guide.positions3d[offset + 3], local),
            y: THREE.MathUtils.lerp(guide.positions3d[offset + 1], guide.positions3d[offset + 4], local),
            z: THREE.MathUtils.lerp(guide.positions3d[offset + 2], guide.positions3d[offset + 5], local),
        };
    }

    private capsSurfaceParticle(data: GalaxySceneV2, positions: Float32Array, source: number, target: number): boolean {
        if (positions !== data.positions3d) return false;
        const ax = positions[source * 3], ay = positions[source * 3 + 1], az = positions[source * 3 + 2];
        const bx = positions[target * 3], by = positions[target * 3 + 1], bz = positions[target * 3 + 2];
        const ar = Math.hypot(ax, ay, az);
        const br = Math.hypot(bx, by, bz);
        if (data.layoutMode === 'hybridSpace') return this.hybridSurfaceParticle(ar, br, ax, ay, az, bx, by, bz);
        if (data.layoutMode !== 'lorentzTree') return false;
        if (ar < CAPS_SURFACE_EDGE_MIN_RADIUS || br < CAPS_SURFACE_EDGE_MIN_RADIUS) return false;
        if (Math.abs(ar - br) > CAPS_SURFACE_EDGE_MAX_RADIUS_DELTA) return false;
        if (this.capsShellIndex(ar) !== this.capsShellIndex(br)) return false;
        const dot = (ax * bx + ay * by + az * bz) / Math.max(0.000001, ar * br);
        return dot > -0.985;
    }

    private hybridSurfaceParticle(ar: number, br: number, ax: number, ay: number, az: number, bx: number, by: number, bz: number): boolean {
        if (ar < HYBRID_SURFACE_EDGE_MIN_RADIUS || br < HYBRID_SURFACE_EDGE_MIN_RADIUS) return false;
        if (Math.abs(ar - br) > HYBRID_SURFACE_EDGE_MAX_RADIUS_DELTA) return false;
        const dot = (ax * bx + ay * by + az * bz) / Math.max(0.000001, ar * br);
        return dot > -0.985;
    }

    private capsShellIndex(radius: number): number {
        let best = 0;
        let bestDistance = Number.POSITIVE_INFINITY;
        for (let index = 0; index < CAPS_SHELL_RADII.length; index++) {
            const distance = Math.abs(radius - CAPS_SHELL_RADII[index]);
            if (distance >= bestDistance) continue;
            best = index;
            bestDistance = distance;
        }
        return best;
    }

    private capsSurfacePoint(positions: Float32Array, source: number, target: number, t: number): { x: number; y: number; z: number } | null {
        const ax = positions[source * 3], ay = positions[source * 3 + 1], az = positions[source * 3 + 2];
        const bx = positions[target * 3], by = positions[target * 3 + 1], bz = positions[target * 3 + 2];
        const ar = Math.hypot(ax, ay, az);
        const br = Math.hypot(bx, by, bz);
        if (ar <= 0.000001 || br <= 0.000001) return null;
        const anx = ax / ar, any = ay / ar, anz = az / ar;
        const bnx = bx / br, bny = by / br, bnz = bz / br;
        const radius = THREE.MathUtils.lerp(ar, br, t);
        const dot = THREE.MathUtils.clamp(anx * bnx + any * bny + anz * bnz, -1, 1);

        if (dot > 0.9995) {
            const x = THREE.MathUtils.lerp(anx, bnx, t);
            const y = THREE.MathUtils.lerp(any, bny, t);
            const z = THREE.MathUtils.lerp(anz, bnz, t);
            const len = Math.hypot(x, y, z);
            return len <= 0.000001 ? null : { x: x / len * radius, y: y / len * radius, z: z / len * radius };
        }

        if (dot < -0.985) return null;
        const theta = Math.acos(dot);
        const sinTheta = Math.sin(theta);
        if (Math.abs(sinTheta) <= 0.000001) return null;
        const sourceScale = Math.sin((1 - t) * theta) / sinTheta;
        const targetScale = Math.sin(t * theta) / sinTheta;
        return {
            x: (anx * sourceScale + bnx * targetScale) * radius,
            y: (any * sourceScale + bny * targetScale) * radius,
            z: (anz * sourceScale + bnz * targetScale) * radius,
        };
    }

    private edgeX(positions: Float32Array, source: number, target: number, t: number): number {
        return THREE.MathUtils.lerp(positions[source * 3], positions[target * 3], t);
    }

    private edgeY(positions: Float32Array, source: number, target: number, lift: number, t: number): number {
        return THREE.MathUtils.lerp(positions[source * 3 + 1], positions[target * 3 + 1], t) + lift * Math.sin(Math.PI * t);
    }

    private edgeZ(positions: Float32Array, source: number, target: number, t: number): number {
        return THREE.MathUtils.lerp(positions[source * 3 + 2], positions[target * 3 + 2], t);
    }

    private writeTargetColor(colorAttr: THREE.BufferAttribute, data: GalaxySceneV2, edge: number, particle: number): void {
        const offset = edge * 6 + 3;
        colorAttr.setXYZ(particle, data.edgeColors[offset], data.edgeColors[offset + 1], data.edgeColors[offset + 2]);
    }

    private writeGuideColor(colorAttr: THREE.BufferAttribute, guide: GalaxyLorentzGuideView, particle: number): void {
        colorAttr.setXYZ(
            particle,
            THREE.MathUtils.clamp(guide.color.r * 0.78, 0, 0.78),
            THREE.MathUtils.clamp(guide.color.g * 0.82, 0, 0.84),
            THREE.MathUtils.clamp(guide.color.b * 0.84, 0, 0.86),
        );
    }

    private guideFocusAlpha(data: GalaxySceneV2, focus: GalaxyFocusMask | null | undefined, guide: GalaxyLorentzGuideView): number {
        if (!focus?.hasFocus || focus.focusIndex < 0) return 0.78;
        const focusId = data.ids[focus.focusIndex];
        if (!guide.nodeIds.length) return 0.2;
        return guide.nodeIds.includes(focusId) ? 1.08 : 0.08;
    }

    private stableUnit(value: number | string): number {
        if (typeof value === 'string') {
            let hash = 2166136261;
            for (let index = 0; index < value.length; index++) {
                hash ^= value.charCodeAt(index);
                hash = Math.imul(hash, 16777619);
            }
            return (hash >>> 0) / 4294967295;
        }
        const raw = Math.sin((value + 1) * 12.9898) * 43758.5453;
        return raw - Math.floor(raw);
    }
}
