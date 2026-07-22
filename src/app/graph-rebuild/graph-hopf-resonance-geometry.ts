export type Vec3Tuple = [number, number, number];

export const TAU = Math.PI * 2;

export function icosahedralCenters(resolution: number): Vec3Tuple[] {
    const vertices = icosahedronVertices();
    const faces = icosahedronFaces();
    const byKey = new Map<string, Vec3Tuple>();
    for (const [a, b, c] of faces) {
        for (let i = 0; i <= resolution; i += 1) {
            for (let j = 0; j <= resolution - i; j += 1) {
                const k = resolution - i - j;
                const point = normalize3([
                    (vertices[a][0] * i + vertices[b][0] * j + vertices[c][0] * k) / resolution,
                    (vertices[a][1] * i + vertices[b][1] * j + vertices[c][1] * k) / resolution,
                    (vertices[a][2] * i + vertices[b][2] * j + vertices[c][2] * k) / resolution,
                ]);
                byKey.set(pointKey(point), point);
            }
        }
    }
    return [...byKey.values()].sort((left, right) =>
        left[2] - right[2]
        || left[1] - right[1]
        || left[0] - right[0],
    );
}

export function tangentFrame(center: Vec3Tuple): { u: Vec3Tuple; v: Vec3Tuple } {
    const ref: Vec3Tuple = Math.abs(center[2]) < 0.86 ? [0, 0, 1] : [0, 1, 0];
    const u = normalize3(cross3(ref, center));
    const v = normalize3(cross3(center, u));
    return { u, v };
}

export function fallbackTangent(frame: { u: Vec3Tuple; v: Vec3Tuple }, seed: string): Vec3Tuple {
    const angle = stableUnit(seed) * TAU;
    return normalize3(add3(scale3(frame.u, Math.cos(angle)), scale3(frame.v, Math.sin(angle))));
}

export function fallbackDirection(seed: string): Vec3Tuple {
    const a = stableUnit(`${seed}:a`) * TAU;
    const z = stableUnit(`${seed}:z`) * 2 - 1;
    const r = Math.sqrt(Math.max(0, 1 - z * z));
    return [Math.cos(a) * r, Math.sin(a) * r, z];
}

export function stableUnit(value: string): number {
    return mix32(hashString(value)) / 0xffffffff;
}

export function mix32(value: number): number {
    let out = value >>> 0;
    out ^= out >>> 16;
    out = Math.imul(out, 0x7feb352d);
    out ^= out >>> 15;
    out = Math.imul(out, 0x846ca68b);
    out ^= out >>> 16;
    return out >>> 0;
}

export function signedUnit(seed: number): number {
    return (mix32(seed) / 0x7fffffff) - 1;
}

export function clampInt(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, Math.floor(value)));
}

export function clamp01(value: number): number {
    return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

export function round(value: number): number {
    return Number.isFinite(value) ? Math.round(value * 1000) / 1000 : 0;
}

export function roundVec(vec: Vec3Tuple): Vec3Tuple {
    return [round(vec[0]), round(vec[1]), round(vec[2])];
}

export function positiveRadians(value: number): number {
    return ((value % TAU) + TAU) % TAU;
}

export function norm3(value: Vec3Tuple): number {
    return Math.sqrt(dot3(value, value));
}

export function normalize3(value: Vec3Tuple): Vec3Tuple {
    const length = norm3(value);
    return length ? [value[0] / length, value[1] / length, value[2] / length] : [0, 0, 0];
}

export function dot3(left: Vec3Tuple, right: Vec3Tuple): number {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

export function add3(left: Vec3Tuple, right: Vec3Tuple): Vec3Tuple {
    return [left[0] + right[0], left[1] + right[1], left[2] + right[2]];
}

export function sub3(left: Vec3Tuple, right: Vec3Tuple): Vec3Tuple {
    return [left[0] - right[0], left[1] - right[1], left[2] - right[2]];
}

export function scale3(value: Vec3Tuple, scale: number): Vec3Tuple {
    return [value[0] * scale, value[1] * scale, value[2] * scale];
}

function icosahedronVertices(): Vec3Tuple[] {
    const t = (1 + Math.sqrt(5)) / 2;
    const vertices: Vec3Tuple[] = [
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
    ];
    return vertices.map(normalize3);
}

function icosahedronFaces(): Array<[number, number, number]> {
    return [
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ];
}

function cross3(left: Vec3Tuple, right: Vec3Tuple): Vec3Tuple {
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ];
}

function pointKey(point: Vec3Tuple): string {
    return `${Math.round(point[0] * 1_000_000)}:${Math.round(point[1] * 1_000_000)}:${Math.round(point[2] * 1_000_000)}`;
}

function hashString(value: string): number {
    let out = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        out ^= value.charCodeAt(index);
        out = Math.imul(out, 16777619);
    }
    return out >>> 0;
}
