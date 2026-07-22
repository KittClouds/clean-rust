import {
    galaxyResidencyTileKey,
    type GalaxyResidencyManifest,
    type GalaxyResidencyRequest,
    type GalaxyResidencyTileDescriptor,
    type GalaxyResidencyView,
    type GalaxyResidencyBufferSlot,
} from './graph-galaxy-residency.model';

export interface GalaxyResidencyPlanningState {
    token: number;
    slot: GalaxyResidencyBufferSlot;
    residentKeys: ReadonlySet<string>;
    inFlightKeys: ReadonlySet<string>;
}

export function planGalaxyResidencyRequests(
    manifest: GalaxyResidencyManifest,
    view: GalaxyResidencyView,
    state: GalaxyResidencyPlanningState,
): GalaxyResidencyRequest[] {
    const groups = new Map<string, GalaxyResidencyTileDescriptor[]>();
    for (const tile of manifest.tiles) {
        if (tile.generationId !== manifest.generationId || tile.manifoldId !== manifest.manifoldId) continue;
        if (!galaxySphereIntersectsFrustum(tile.bounds, view)) continue;
        const group = groups.get(tile.spatialKey) ?? [];
        group.push(tile);
        groups.set(tile.spatialKey, group);
    }

    const requests: GalaxyResidencyRequest[] = [];
    for (const tiles of groups.values()) {
        tiles.sort((left, right) => right.lod - left.lod);
        const resident = tiles.filter((tile) => state.residentKeys.has(galaxyResidencyTileKey(tile)));
        const pending = tiles.some((tile) => state.inFlightKeys.has(galaxyResidencyTileKey(tile)));
        if (pending) continue;

        let descriptor: GalaxyResidencyTileDescriptor | undefined;
        let reason: GalaxyResidencyRequest['reason'] = 'coverage';
        if (!resident.length) {
            descriptor = tiles[0];
        } else {
            const finestResidentLod = Math.min(...resident.map((tile) => tile.lod));
            const current = resident.find((tile) => tile.lod === finestResidentLod)!;
            const error = galaxyTileScreenSpaceError(current, view);
            if (error <= view.targetErrorPixels || finestResidentLod <= 0) continue;
            descriptor = tiles
                .filter((tile) => tile.lod < finestResidentLod)
                .sort((left, right) => right.lod - left.lod)[0];
            reason = 'refinement';
        }
        if (!descriptor) continue;
        const key = galaxyResidencyTileKey(descriptor);
        if (state.residentKeys.has(key) || state.inFlightKeys.has(key)) continue;
        const distance = galaxyTileDistance(descriptor, view);
        const screenSpaceError = galaxyTileScreenSpaceError(descriptor, view);
        requests.push({
            token: state.token,
            slot: state.slot,
            descriptor,
            distance,
            screenSpaceError,
            reason,
            priority: galaxyTilePriority(descriptor, distance, screenSpaceError, reason),
        });
    }
    return requests.sort((left, right) => right.priority - left.priority);
}

export function galaxySphereIntersectsFrustum(
    sphere: GalaxyResidencyTileDescriptor['bounds'],
    view: Pick<GalaxyResidencyView, 'frustum'>,
): boolean {
    for (const plane of view.frustum) {
        const signedDistance = plane.normal[0] * sphere.center[0]
            + plane.normal[1] * sphere.center[1]
            + plane.normal[2] * sphere.center[2]
            + plane.constant;
        if (signedDistance < -sphere.radius) return false;
    }
    return true;
}

export function galaxyTileDistance(
    tile: GalaxyResidencyTileDescriptor,
    view: Pick<GalaxyResidencyView, 'camera'>,
): number {
    const dx = tile.bounds.center[0] - view.camera[0];
    const dy = tile.bounds.center[1] - view.camera[1];
    const dz = tile.bounds.center[2] - view.camera[2];
    return Math.max(0.0001, Math.hypot(dx, dy, dz) - tile.bounds.radius);
}

export function galaxyTileScreenSpaceError(
    tile: GalaxyResidencyTileDescriptor,
    view: Pick<GalaxyResidencyView, 'camera' | 'viewportHeight' | 'verticalFovRadians'>,
): number {
    const distance = galaxyTileDistance(tile, view);
    const projectionScale = Math.max(1, view.viewportHeight)
        / Math.max(0.0001, 2 * Math.tan(Math.max(0.01, view.verticalFovRadians) * 0.5));
    return Math.max(0, tile.geometricError) * projectionScale / distance;
}

function galaxyTilePriority(
    tile: GalaxyResidencyTileDescriptor,
    distance: number,
    screenSpaceError: number,
    reason: GalaxyResidencyRequest['reason'],
): number {
    const nearScore = 1_000_000 / (1 + distance);
    const coverageScore = reason === 'coverage' ? 10_000_000 + tile.lod * 10_000 : 0;
    const refinementScore = reason === 'refinement' ? Math.min(5_000_000, screenSpaceError * 25_000) : 0;
    return coverageScore + nearScore + refinementScore + (tile.pinned ? 20_000_000 : 0);
}
