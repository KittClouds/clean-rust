import * as THREE from 'three/webgpu';

import type { GalaxyRenderSettings } from '../graph-galaxy-engine';
import type {
    GalaxyHopfRibbonView,
    GalaxyLorentzGuideView,
} from '../graph-galaxy-scene-v2';
import type { GalaxyScenePacketV2GuideDetails } from '../graph-galaxy-scene-packet-v2';

const MAX_FIBER_LINES = 128;
const MAX_ROUTE_LINES = 260;
const MAX_FIBER_TUBES = 18;
const MAX_ROUTE_TUBES = 18;

type GuideFamily = 'fibers' | 'routes';

export interface GalaxyRendererV3GuideSurface {
    root: THREE.Group;
    fibers: THREE.Group;
    routes: THREE.Group;
    fiberGuideCount: number;
    routeGuideCount: number;
}

export function buildGalaxyRendererV3GuideSurface(
    details: GalaxyScenePacketV2GuideDetails,
): GalaxyRendererV3GuideSurface {
    const root = namedGroup('v3-guides');
    const fibers = namedGroup('v3-guide-fibers');
    const routes = namedGroup('v3-guide-routes');
    const fiberGuides = boundedFiberGuides(details.hopfRibbons);
    const routeGuides = boundedRouteGuides(details.lorentzGuides);

    const fiberLines = buildLineBatch(fiberGuides, 'fibers');
    if (fiberLines) fibers.add(fiberLines);
    addTubes(fibers, fiberGuides.filter(isFiberTube).slice(0, MAX_FIBER_TUBES), 'fibers');

    const routeLines = buildLineBatch(routeGuides, 'routes');
    if (routeLines) routes.add(routeLines);
    addTubes(routes, routeGuides.filter(isRouteTube).slice(0, MAX_ROUTE_TUBES), 'routes');

    root.add(fibers, routes);
    return {
        root,
        fibers,
        routes,
        fiberGuideCount: fiberGuides.length,
        routeGuideCount: routeGuides.length,
    };
}

export function syncGalaxyRendererV3GuidePresentation(
    surface: GalaxyRendererV3GuideSurface | null,
    settings: GalaxyRenderSettings,
): void {
    if (!surface) return;
    surface.fibers.visible = settings.hopfSpaceVisible !== false
        && settings.guideFibersVisible !== false;
    surface.routes.visible = settings.lorentzSpaceVisible !== false
        && settings.guideRoutesVisible !== false;
    syncFamilyOpacity(surface.fibers, settings.hopfSpaceIntensity, settings.glow);
    syncFamilyOpacity(surface.routes, settings.lorentzSpaceIntensity, settings.glow);
}

function boundedFiberGuides(guides: readonly GalaxyHopfRibbonView[]): GalaxyHopfRibbonView[] {
    return [...guides]
        .sort((left, right) => fiberRank(left) - fiberRank(right)
            || right.importance - left.importance
            || left.id.localeCompare(right.id))
        .slice(0, MAX_FIBER_LINES);
}

function boundedRouteGuides(guides: readonly GalaxyLorentzGuideView[]): GalaxyLorentzGuideView[] {
    return [...guides]
        .sort((left, right) => routeRank(left) - routeRank(right)
            || right.importance - left.importance
            || left.id.localeCompare(right.id))
        .slice(0, MAX_ROUTE_LINES);
}

function buildLineBatch(
    guides: readonly (GalaxyHopfRibbonView | GalaxyLorentzGuideView)[],
    family: GuideFamily,
): THREE.LineSegments | null {
    const floatCount = guides.reduce((total, guide) => total + usableFloatCount(guide.positions3d), 0);
    if (!floatCount) return null;
    const positions = new Float32Array(floatCount);
    const colors = new Float32Array(floatCount);
    let cursor = 0;
    for (const guide of guides) {
        const length = usableFloatCount(guide.positions3d);
        positions.set(guide.positions3d.subarray(0, length), cursor);
        const tint = guide.sourceColor ?? guide.color;
        const gain = clamp(0.62 + Math.sqrt(Math.max(0.04, guide.guideWeight)) * 0.3, 0.68, 1);
        for (let offset = 0; offset < length; offset += 3) {
            colors[cursor + offset] = clamp(tint.r * gain, 0, 1);
            colors[cursor + offset + 1] = clamp(tint.g * gain, 0, 1);
            colors[cursor + offset + 2] = clamp(tint.b * gain, 0, 1);
        }
        cursor += length;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const material = guideMaterial(family, 'line', true);
    const lines = new THREE.LineSegments(geometry, material);
    lines.frustumCulled = false;
    lines.renderOrder = 1;
    lines.userData['guideFamily'] = family;
    lines.userData['guideLayer'] = 'line';
    lines.userData['pickable'] = false;
    return lines;
}

function addTubes(
    target: THREE.Group,
    guides: readonly (GalaxyHopfRibbonView | GalaxyLorentzGuideView)[],
    family: GuideFamily,
): void {
    for (const guide of guides) {
        const points = guidePath(guide);
        if (points.length < 4) continue;
        const closed = family === 'fibers'
            && (guide as GalaxyHopfRibbonView).guideKind !== 'crossFiberBraid';
        const curve = new THREE.CatmullRomCurve3(points, closed, 'centripetal', closed ? 0.45 : 0.35);
        const tint = guide.sourceColor ?? guide.color;
        for (const layer of ['glow', 'core'] as const) {
            const geometry = new THREE.TubeGeometry(
                curve,
                family === 'fibers' ? 72 : 52,
                tubeRadius(family, layer, guide.guideWeight),
                4,
                closed,
            );
            const material = guideMaterial(family, layer, false, tint);
            const mesh = new THREE.Mesh(geometry, material);
            mesh.frustumCulled = false;
            mesh.renderOrder = layer === 'glow' ? 0 : 1;
            mesh.userData['guideFamily'] = family;
            mesh.userData['guideLayer'] = layer;
            mesh.userData['pickable'] = false;
            target.add(mesh);
        }
    }
}

function guidePath(
    guide: GalaxyHopfRibbonView | GalaxyLorentzGuideView,
): THREE.Vector3[] {
    const segmentCount = Math.floor(guide.positions3d.length / 6);
    if (segmentCount < 2) return [];
    const stride = Math.max(1, Math.floor(segmentCount / 64));
    const points: THREE.Vector3[] = [];
    for (let segment = 0; segment < segmentCount; segment += stride) {
        const offset = segment * 6;
        points.push(new THREE.Vector3(
            guide.positions3d[offset],
            guide.positions3d[offset + 1],
            guide.positions3d[offset + 2],
        ));
    }
    const last = guide.positions3d.length - 3;
    const tail = new THREE.Vector3(
        guide.positions3d[last],
        guide.positions3d[last + 1],
        guide.positions3d[last + 2],
    );
    if (!points.at(-1)?.equals(tail)) points.push(tail);
    return points;
}

function guideMaterial(
    family: GuideFamily,
    layer: 'line' | 'glow' | 'core',
    vertexColors: boolean,
    tint = { r: 1, g: 1, b: 1 },
): THREE.LineBasicMaterial | THREE.MeshBasicMaterial {
    const baseOpacity = family === 'fibers'
        ? layer === 'core' ? 0.2 : layer === 'glow' ? 0.045 : 0.13
        : layer === 'core' ? 0.16 : layer === 'glow' ? 0.034 : 0.11;
    const common = {
        color: new THREE.Color(tint.r, tint.g, tint.b),
        vertexColors,
        transparent: true,
        opacity: baseOpacity,
        depthWrite: false,
        depthTest: true,
        blending: layer === 'glow' ? THREE.AdditiveBlending : THREE.NormalBlending,
        toneMapped: false,
    };
    const material = layer === 'line'
        ? new THREE.LineBasicMaterial(common)
        : new THREE.MeshBasicMaterial(common);
    material.userData['baseOpacity'] = baseOpacity;
    material.userData['guideLayer'] = layer;
    return material;
}

function syncFamilyOpacity(group: THREE.Group, intensity: number, glow: number): void {
    const strength = clamp(intensity, 0, 1.4);
    const glowGain = 0.82 + clamp(glow, 0, 1.8) * 0.18;
    group.traverse((object) => {
        const material = (object as THREE.Mesh | THREE.LineSegments).material;
        if (!material || Array.isArray(material)) return;
        const base = Number(material.userData['baseOpacity']);
        if (!Number.isFinite(base)) return;
        const layer = String(material.userData['guideLayer'] ?? 'line');
        material.opacity = clamp(base * strength * (layer === 'glow' ? glowGain : 1), 0, 0.28);
        material.needsUpdate = true;
    });
}

function isFiberTube(guide: GalaxyHopfRibbonView): boolean {
    return guide.guideKind === 'dataFiber' || guide.guideKind === 'torusBand';
}

function isRouteTube(guide: GalaxyLorentzGuideView): boolean {
    return guide.guideKind === 'membership' || guide.guideKind === 'rootLane';
}

function fiberRank(guide: GalaxyHopfRibbonView): number {
    if (guide.guideKind === 'dataFiber') return 0;
    if (guide.guideKind === 'torusBand') return 1;
    if (guide.guideKind === 'crossFiberBraid') return 2;
    if (guide.guideKind === 'spaceFiber') return 3;
    return 4;
}

function routeRank(guide: GalaxyLorentzGuideView): number {
    if (guide.guideKind === 'rootLane') return 0;
    if (guide.guideKind === 'membership') return 1;
    if (guide.guideKind === 'levelShell') return 2;
    return 3;
}

function tubeRadius(
    family: GuideFamily,
    layer: 'glow' | 'core',
    weight: number,
): number {
    const base = family === 'fibers'
        ? layer === 'glow' ? 0.013 : 0.0052
        : layer === 'glow' ? 0.009 : 0.0039;
    return base * clamp(0.84 + Math.sqrt(Math.max(0.08, weight)) * 0.24, 0.9, 1.18);
}

function usableFloatCount(positions: Float32Array): number {
    return Math.floor(positions.length / 6) * 6;
}

function namedGroup(name: string): THREE.Group {
    const group = new THREE.Group();
    group.name = name;
    return group;
}

function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}
