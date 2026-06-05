import type {
    GalaxyHybridBusemannReceipt,
    GalaxyBusemannPrototype,
    GalaxyBusemannSignature,
    GalaxyHybridInteriorState,
    GalaxyNode,
    GalaxyHybridPlacementPoint,
    GalaxyVec3,
} from './graph-galaxy-engine';

const EPS = 1e-6;

type MutableGalaxyNode = GalaxyNode & {
    x?: number;
    y?: number;
    z?: number;
    vx?: number;
    vy?: number;
    vz?: number;
    __hybridInterior?: {
        mode: 'busemannCommitment';
        family: string;
        topPrototypeId: string;
        entropy: number;
        margin: number;
        confidence: number;
        promotionReady: boolean;
        radialStrength: number;
        point?: GalaxyHybridPlacementPoint;
        source?: GalaxyHybridBusemannReceipt['source'];
    };
};

export interface ApplyHybridBusemannLayoutOptions {
    shellRadius: number;
    minInteriorRadius?: number;
    maxInteriorRadius?: number;
    preferBackendPoint?: boolean;
}

export interface BusemannHorosphereSpec {
    prototypeId: string;
    family: string;
    label: string;
    tau: number;
    center: GalaxyVec3;
    radius: number;
    opacity: number;
    colorKind?: string;
}

/**
 * Apply the evolved hybrid layout:
 *
 * - surface/caps remain the semantic world
 * - Busemann interior nodes render classification commitment
 * - unresolved/ambiguous nodes stay closer to center/intersections
 * - confident nodes move toward their top prototype/cap
 *
 * This does not create a new layout mode. Call it when layoutMode === 'hybridSpace'.
 */
export function applyHybridBusemannLayout(
    nodes: GalaxyNode[],
    prototypes: GalaxyBusemannPrototype[],
    options: ApplyHybridBusemannLayoutOptions,
): GalaxyNode[] {
    const shellRadius = finiteOr(options.shellRadius, 240);
    const minR = finiteOr(options.minInteriorRadius, shellRadius * 0.08);
    const maxR = finiteOr(options.maxInteriorRadius, shellRadius * 0.92);
    const preferBackendPoint = options.preferBackendPoint ?? true;

    const prototypeById = new Map<string, GalaxyBusemannPrototype>();

    for (const prototype of prototypes) {
        prototypeById.set(String(prototype.prototypeId), {
            ...prototype,
            prototypeId: String(prototype.prototypeId),
            direction: normalize3(prototype.direction),
        });
    }

    for (const rawNode of nodes) {
        const node = rawNode as MutableGalaxyNode;
        const state = readHybridInteriorState(node);
        const signature = state?.signature ?? readBusemannSignature(node);

        if (!signature) {
            continue;
        }

        const topPrototypeId = String(signature.topPrototypeId);
        const prototype = prototypeById.get(topPrototypeId);

        if (!prototype) {
            continue;
        }

        const confidence = clamp01(signature.classificationConfidence);
        const entropy = clamp01(signature.entropy);
        const radialStrength = clamp01(signature.radialStrength);

        let position: GalaxyVec3 | null = null;
        let positionSource: GalaxyHybridBusemannReceipt['source'] = 'frontendCommitment';

        if (preferBackendPoint) {
            position = normalizeBackendInteriorPoint(
                state?.point ?? readVec3(node.entity.metadata?.['hybridInteriorPoint']),
                shellRadius,
                maxR,
            );
            if (position) {
                positionSource = 'backendPoint';
            }
        }

        if (!position) {
            const prototypeDir = weightedPrototypeDirection(signature, prototypeById, prototype.direction);
            const semanticDir = normalizeNullable3(
                state?.surfaceDirection ??
                    readVec3(node.entity.metadata?.['hybridSurfaceDirection']) ??
                    atlasDirection(node),
            );

            /**
             * Ambiguous nodes should not snap cleanly to the prototype ray.
             * Blend in semantic direction as entropy rises.
             */
            const direction = semanticDir
                ? normalize3(mix3(prototypeDir, semanticDir, 0.15 + entropy * 0.55))
                : prototypeDir;

            /**
             * Radius means commitment/resolution strength now.
             * Not hierarchy depth.
             */
            const margin = clamp01(finiteOr(signature.margin, 0) / (Math.abs(finiteOr(signature.margin, 0)) + 1));
            const ambiguity = clamp01(signature.ambiguityScore);
            const readiness = clamp01(
                radialStrength * 0.38 +
                confidence * 0.34 +
                margin * 0.18 +
                (signature.promotionReady ? 0.1 : 0) -
                entropy * 0.22 -
                ambiguity * 0.12,
            );
            const r = lerp(minR, maxR, 0.08 + readiness * 0.86);

            position = scale3(direction, r);
        }

        node.x = position.x;
        node.y = position.y;
        node.z = position.z;

        const point = placementPointFromPosition(position, shellRadius);
        const receipt: GalaxyHybridBusemannReceipt = {
            mode: 'busemannCommitment',
            family: signature.family,
            topPrototypeId,
            entropy,
            margin: finiteOr(signature.margin, 0),
            confidence,
            promotionReady: !!signature.promotionReady,
            radialStrength,
            point,
            source: positionSource,
        };

        node.__hybridInterior = {
            mode: 'busemannCommitment',
            family: signature.family,
            topPrototypeId,
            entropy,
            margin: finiteOr(signature.margin, 0),
            confidence,
            promotionReady: !!signature.promotionReady,
            radialStrength,
            point,
            source: positionSource,
        };
        node.hybridCommitment = receipt;
        node.hybridCommitmentPoint = point;
        node.hybridRenderPoint = point;
        const metadata = node.entity.metadata ?? {};
        node.entity.metadata = {
            ...metadata,
            hybridCommitment: receipt,
            hybridCommitmentPoint: point,
            hybridRenderPoint: point,
        };
    }

    return nodes;
}

/**
 * Build horosphere descriptors for rendering.
 *
 * In the Poincare unit ball:
 *
 * B_p(x) = ln(||p - x||² / (1 - ||x||²))
 *
 * The level set B_p(x)=tau is a Euclidean sphere tangent to boundary p:
 *
 * a = exp(tau)
 * center = p / (1 + a)
 * radius = a / (1 + a)
 *
 * Negative tau hugs the prototype cap.
 * tau = 0 passes through origin.
 */
export function buildBusemannHorosphereSpecs(
    prototypes: GalaxyBusemannPrototype[],
    shellRadius: number,
    activePrototypeIds?: Set<string>,
): BusemannHorosphereSpec[] {
    const specs: BusemannHorosphereSpec[] = [];

    const tauLevels = [-3, -2, -1, 0];

    for (const prototype of prototypes) {
        const prototypeId = String(prototype.prototypeId);

        if (activePrototypeIds && !activePrototypeIds.has(prototypeId)) {
            continue;
        }

        const p = normalize3(prototype.direction);

        for (const tau of tauLevels) {
            const a = Math.exp(tau);
            const centerUnit = scale3(p, 1 / (1 + a));
            const radiusUnit = a / (1 + a);

            specs.push({
                prototypeId,
                family: prototype.family,
                label: prototype.label,
                tau,
                center: scale3(centerUnit, shellRadius),
                radius: radiusUnit * shellRadius,
                opacity: tau === 0 ? 0.05 : 0.08 + Math.abs(tau) * 0.015,
                colorKind: prototype.colorKind,
            });
        }
    }

    return specs;
}

export function activeBusemannPrototypeIds(nodes: GalaxyNode[], limit = 8): Set<string> {
    const counts = new Map<string, number>();

    for (const rawNode of nodes) {
        const node = rawNode as MutableGalaxyNode;
        const sig = readHybridInteriorState(node)?.signature ?? readBusemannSignature(node);

        if (!sig?.topPrototypeId) {
            continue;
        }

        const key = String(sig.topPrototypeId);
        counts.set(key, (counts.get(key) ?? 0) + 1);
    }

    return new Set(
        [...counts.entries()]
            .sort((a, b) => b[1] - a[1])
            .slice(0, limit)
            .map(([id]) => id),
    );
}

export function readHybridInteriorState(node: GalaxyNode): GalaxyHybridInteriorState | null {
    const value = node.entity.metadata?.['hybridInterior'];

    if (!value || typeof value !== 'object') {
        return null;
    }

    if ((value as Record<string, unknown>)['mode'] !== 'busemannCommitment') {
        return null;
    }

    return value as GalaxyHybridInteriorState;
}

export function readBusemannSignature(node: GalaxyNode): GalaxyBusemannSignature | null {
    const direct = node.entity.metadata?.['busemannSignature'];

    if (isBusemannSignature(direct)) {
        return normalizeSignatureIds(direct);
    }

    const hybridInterior = node.entity.metadata?.['hybridInterior'];
    const nested = hybridInterior && typeof hybridInterior === 'object'
        ? (hybridInterior as Record<string, unknown>)['signature']
        : undefined;

    if (isBusemannSignature(nested)) {
        return normalizeSignatureIds(nested);
    }

    return null;
}

function readVec3(value: unknown): GalaxyVec3 | undefined {
    if (!value || typeof value !== 'object') return undefined;
    const point = value as Partial<GalaxyVec3>;
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || !Number.isFinite(point.z)) return undefined;
    return { x: point.x as number, y: point.y as number, z: point.z as number };
}

function isBusemannSignature(value: unknown): value is GalaxyBusemannSignature {
    if (!value || typeof value !== 'object') {
        return false;
    }

    const sig = value as Partial<GalaxyBusemannSignature>;

    return (
        typeof sig.family === 'string' &&
        sig.topPrototypeId !== undefined &&
        Number.isFinite(sig.topScore) &&
        Number.isFinite(sig.topProbability) &&
        Number.isFinite(sig.margin) &&
        Number.isFinite(sig.entropy) &&
        Number.isFinite(sig.classificationConfidence) &&
        Number.isFinite(sig.radialStrength)
    );
}

function normalizeSignatureIds(sig: GalaxyBusemannSignature): GalaxyBusemannSignature {
    return {
        ...sig,
        topPrototypeId: String(sig.topPrototypeId),
        secondPrototypeId:
            sig.secondPrototypeId === undefined || sig.secondPrototypeId === null
                ? null
                : String(sig.secondPrototypeId),
        topKScores: sig.topKScores?.map((score) => ({
            ...score,
            prototypeId: String(score.prototypeId),
        })),
    };
}

function atlasDirection(node: GalaxyNode): GalaxyVec3 | null {
    const entity = node.entity;

    if (
        Number.isFinite(entity.atlasX) &&
        Number.isFinite(entity.atlasY) &&
        Number.isFinite(entity.atlasZ)
    ) {
        return normalize3({
            x: entity.atlasX ?? 0,
            y: entity.atlasY ?? 0,
            z: entity.atlasZ ?? 0,
        });
    }

    return null;
}

function weightedPrototypeDirection(
    signature: GalaxyBusemannSignature,
    prototypes: Map<string, GalaxyBusemannPrototype>,
    fallback: GalaxyVec3,
): GalaxyVec3 {
    const scores = signature.topKScores?.length
        ? signature.topKScores
        : [
            { prototypeId: signature.topPrototypeId, family: signature.family, score: signature.topScore, probability: signature.topProbability },
            signature.secondPrototypeId
                ? { prototypeId: signature.secondPrototypeId, family: signature.family, score: signature.secondScore ?? 0, probability: signature.secondProbability ?? 0 }
                : null,
        ].filter((score): score is NonNullable<typeof score> => !!score);
    let total = 0;
    let mixed = { x: 0, y: 0, z: 0 };

    for (const score of scores.slice(0, 5)) {
        const prototype = prototypes.get(String(score.prototypeId));
        if (!prototype) continue;
        const weight = Math.max(0, finiteOr(score.probability, 0));
        if (weight <= 0) continue;
        const direction = normalize3(prototype.direction);
        mixed = {
            x: mixed.x + direction.x * weight,
            y: mixed.y + direction.y * weight,
            z: mixed.z + direction.z * weight,
        };
        total += weight;
    }

    if (total <= EPS) return normalize3(fallback);
    return normalize3(mixed);
}

function normalizeBackendInteriorPoint(
    point: GalaxyVec3 | undefined,
    shellRadius: number,
    maxInteriorRadius: number,
): GalaxyVec3 | null {
    if (!point) {
        return null;
    }

    if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || !Number.isFinite(point.z)) {
        return null;
    }

    const norm = norm3(point);

    if (norm <= EPS) {
        return { x: 0, y: 0, z: 0 };
    }

    /**
     * Backend may send:
     * - unit-ball coordinates, norm < 1
     * - render-space coordinates, norm around shellRadius
     *
     * Accept both defensively.
     */
    if (norm <= 1.0 + EPS) {
        return scale3(point, maxInteriorRadius);
    }

    if (norm >= shellRadius) {
        return scale3(normalize3(point), maxInteriorRadius);
    }

    return point;
}

function placementPointFromPosition(position: GalaxyVec3, shellRadius: number): GalaxyHybridPlacementPoint {
    return {
        x: position.x,
        y: position.y,
        z: position.z,
        radius: clamp01(norm3(position) / Math.max(EPS, shellRadius)),
    };
}

function normalizeNullable3(value: GalaxyVec3 | null | undefined): GalaxyVec3 | null {
    if (!value) return null;
    return normalize3(value);
}

function normalize3(value: GalaxyVec3): GalaxyVec3 {
    const n = norm3(value);

    if (!Number.isFinite(n) || n <= EPS) {
        return { x: 1, y: 0, z: 0 };
    }

    return {
        x: value.x / n,
        y: value.y / n,
        z: value.z / n,
    };
}

function norm3(value: GalaxyVec3): number {
    return Math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z);
}

function scale3(value: GalaxyVec3, scalar: number): GalaxyVec3 {
    return {
        x: value.x * scalar,
        y: value.y * scalar,
        z: value.z * scalar,
    };
}

function mix3(a: GalaxyVec3, b: GalaxyVec3, t: number): GalaxyVec3 {
    const u = clamp01(t);

    return {
        x: a.x * (1 - u) + b.x * u,
        y: a.y * (1 - u) + b.y * u,
        z: a.z * (1 - u) + b.z * u,
    };
}

function lerp(a: number, b: number, t: number): number {
    return a + (b - a) * clamp01(t);
}

function clamp01(value: number): number {
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(1, value));
}

function finiteOr(value: number | undefined, fallback: number): number {
    return Number.isFinite(value) ? (value as number) : fallback;
}
