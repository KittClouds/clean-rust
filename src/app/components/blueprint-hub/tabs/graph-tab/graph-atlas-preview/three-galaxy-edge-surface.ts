import * as THREE from 'three';

export const GALAXY_EDGE_BUCKET_COUNT = 3;
const DENSE_EDGE_THRESHOLD = 1_200;
const DENSE_EDGE_REFERENCE_PER_MEGAPIXEL = 2_000;
const MIN_EDGE_OVERDRAW_ATTENUATION = 0.18;

export const enum GalaxyGpuEdgeCurve {
    Straight = 0,
    Arc = 1,
    Surface = 2,
    Hopf = 3,
    Tube = 4,
    TreeArc = 5,
    TreeTube = 6,
    HopfCross = 7,
}

export interface GalaxyGpuEdgeSurfaceOptions {
    nodeCount: number;
    edgePairs: Uint32Array;
    curveKinds: Uint8Array;
    maxTextureSize?: number;
}

export function galaxyEdgeOverdrawAttenuation(
    edgeCount: number,
    viewportWidth: number,
    viewportHeight: number,
): number {
    const megapixels = Math.max(0, viewportWidth) * Math.max(0, viewportHeight) / 1_000_000;
    const denseThreshold = Math.max(
        DENSE_EDGE_THRESHOLD,
        DENSE_EDGE_REFERENCE_PER_MEGAPIXEL * megapixels,
    );
    if (edgeCount <= denseThreshold) return 1;
    return THREE.MathUtils.clamp(
        Math.sqrt(denseThreshold / Math.max(1, edgeCount)),
        MIN_EDGE_OVERDRAW_ATTENUATION,
        1,
    );
}

export function galaxyEdgeVisualAlpha(edgeAlpha: number): number {
    const signal = THREE.MathUtils.clamp((edgeAlpha - 0.052) / 0.288, 0, 1);
    return THREE.MathUtils.lerp(0.58, 0.9, signal);
}

interface EdgeBucket {
    geometry: THREE.InstancedBufferGeometry;
    material: THREE.RawShaderMaterial;
    emphasisMaterial: THREE.RawShaderMaterial;
    line: THREE.LineSegments;
    emphasisLine: THREE.LineSegments;
    styles: Uint8Array;
    lifts: Float32Array;
    sourceColors: Uint8Array;
    targetColors: Uint8Array;
}

const BUCKET_SEGMENTS = [1, 12, 24] as const;

export class GalaxyGpuEdgeSurface extends THREE.Group {
    private readonly buckets: EdgeBucket[] = [];
    private readonly edgeCount: number;
    private readonly edgeBucket: Uint8Array;
    private readonly edgeSlot: Uint32Array;
    private readonly positionData: Float32Array;
    private readonly positionTexture: THREE.DataTexture;
    private readonly textureWidth: number;
    private readonly textureHeight: number;

    constructor(options: GalaxyGpuEdgeSurfaceOptions) {
        super();
        const edgeCount = options.edgePairs.length / 2;
        this.edgeCount = edgeCount;
        if (options.curveKinds.length !== edgeCount) throw new Error('GPU edge curve count must match resident edge count');
        this.edgeBucket = new Uint8Array(edgeCount);
        this.edgeSlot = new Uint32Array(edgeCount);

        const maxTextureSize = Math.max(1, options.maxTextureSize ?? 4096);
        this.textureWidth = Math.min(maxTextureSize, Math.max(1, options.nodeCount));
        this.textureHeight = Math.max(1, Math.ceil(options.nodeCount / this.textureWidth));
        if (this.textureHeight > maxTextureSize) {
            throw new Error(`Resident node page exceeds GPU texture capacity (${options.nodeCount} > ${maxTextureSize * maxTextureSize})`);
        }
        this.positionData = new Float32Array(this.textureWidth * this.textureHeight * 4);
        this.positionTexture = new THREE.DataTexture(
            this.positionData,
            this.textureWidth,
            this.textureHeight,
            THREE.RGBAFormat,
            THREE.FloatType,
        );
        this.positionTexture.magFilter = THREE.NearestFilter;
        this.positionTexture.minFilter = THREE.NearestFilter;
        this.positionTexture.generateMipmaps = false;
        this.positionTexture.needsUpdate = true;

        const counts = new Uint32Array(GALAXY_EDGE_BUCKET_COUNT);
        for (let edge = 0; edge < edgeCount; edge++) {
            const bucket = edgeBucketForCurve(options.curveKinds[edge]);
            this.edgeBucket[edge] = bucket;
            this.edgeSlot[edge] = counts[bucket]++;
        }
        for (let bucket = 0; bucket < GALAXY_EDGE_BUCKET_COUNT; bucket++) {
            if (!counts[bucket]) continue;
            const entry = this.createBucket(BUCKET_SEGMENTS[bucket], counts[bucket]);
            this.buckets[bucket] = entry;
            this.add(entry.line, entry.emphasisLine);
        }
        for (let edge = 0; edge < edgeCount; edge++) {
            const bucket = this.buckets[this.edgeBucket[edge]];
            const slot = this.edgeSlot[edge];
            const endpoints = bucket.geometry.getAttribute('aEndpoints') as THREE.InstancedBufferAttribute;
            endpoints.setXY(slot, options.edgePairs[edge * 2], options.edgePairs[edge * 2 + 1]);
            bucket.styles[slot * 4] = options.curveKinds[edge];
        }
        this.frustumCulled = false;
        this.renderOrder = 2;
    }

    updateNodePositions(positions: Float32Array): void {
        const nodeCount = Math.min(positions.length / 3, this.positionData.length / 4);
        for (let node = 0; node < nodeCount; node++) {
            const source = node * 3;
            const target = node * 4;
            this.positionData[target] = positions[source];
            this.positionData[target + 1] = positions[source + 1];
            this.positionData[target + 2] = positions[source + 2];
            this.positionData[target + 3] = 1;
        }
        this.positionTexture.needsUpdate = true;
    }

    edgeCurve(edge: number): GalaxyGpuEdgeCurve {
        const bucket = this.bucketForEdge(edge);
        return bucket.styles[this.edgeSlot[edge] * 4] as GalaxyGpuEdgeCurve;
    }

    setEdgeGeometry(edge: number, lift: number, seed: number): void {
        const bucket = this.bucketForEdge(edge);
        const slot = this.edgeSlot[edge];
        const style = slot * 4;
        bucket.styles[style + 3] = packUnit(seed);
        bucket.lifts[slot] = lift;
    }

    setEdgeAppearance(
        edge: number,
        kind: number,
        focusLevel: number,
        source: THREE.Color,
        target: THREE.Color,
        alpha = 1,
    ): void {
        const bucket = this.bucketForEdge(edge);
        const slot = this.edgeSlot[edge];
        const offset = slot * 4;
        bucket.styles[offset + 1] = Math.max(0, Math.min(255, kind));
        bucket.styles[offset + 2] = Math.max(0, Math.min(255, focusLevel));
        writePackedColor(bucket.sourceColors, offset, source, alpha);
        writePackedColor(bucket.targetColors, offset, target, alpha);
    }

    commitGeometry(): void {
        for (const bucket of this.buckets) {
            if (!bucket) continue;
            (bucket.geometry.getAttribute('aStyle') as THREE.InstancedBufferAttribute).needsUpdate = true;
            (bucket.geometry.getAttribute('aLift') as THREE.InstancedBufferAttribute).needsUpdate = true;
        }
    }

    commitAppearance(): void {
        for (const bucket of this.buckets) {
            if (!bucket) continue;
            (bucket.geometry.getAttribute('aStyle') as THREE.InstancedBufferAttribute).needsUpdate = true;
            (bucket.geometry.getAttribute('aSourceColor') as THREE.InstancedBufferAttribute).needsUpdate = true;
            (bucket.geometry.getAttribute('aTargetColor') as THREE.InstancedBufferAttribute).needsUpdate = true;
        }
    }

    setPresentation(
        opacity: number,
        viewportWidth: number,
        viewportHeight: number,
        layoutKind: number,
        curveStrength: number,
        is3d: boolean,
    ): void {
        const densityAttenuation = galaxyEdgeOverdrawAttenuation(
            this.edgeCount,
            viewportWidth,
            viewportHeight,
        );
        for (const bucket of this.buckets) {
            if (!bucket) continue;
            bucket.material.uniforms['uOpacity'].value = opacity;
            bucket.emphasisMaterial.uniforms['uOpacity'].value = opacity * 0.56;
            bucket.material.uniforms['uDensityAttenuation'].value = densityAttenuation;
            bucket.emphasisMaterial.uniforms['uDensityAttenuation'].value = densityAttenuation;
            (bucket.material.uniforms['uViewport'].value as THREE.Vector2).set(
                Math.max(1, viewportWidth),
                Math.max(1, viewportHeight),
            );
            (bucket.emphasisMaterial.uniforms['uViewport'].value as THREE.Vector2).set(
                Math.max(1, viewportWidth),
                Math.max(1, viewportHeight),
            );
            bucket.material.uniforms['uLayoutKind'].value = layoutKind;
            bucket.emphasisMaterial.uniforms['uLayoutKind'].value = layoutKind;
            bucket.material.uniforms['uCurveStrength'].value = curveStrength;
            bucket.emphasisMaterial.uniforms['uCurveStrength'].value = curveStrength;
            bucket.material.uniforms['uIs3d'].value = is3d ? 1 : 0;
            bucket.emphasisMaterial.uniforms['uIs3d'].value = is3d ? 1 : 0;
        }
    }

    bucketInstanceCounts(): readonly number[] {
        return Array.from({ length: GALAXY_EDGE_BUCKET_COUNT }, (_, index) => this.buckets[index]?.geometry.instanceCount ?? 0);
    }

    dispose(): void {
        for (const bucket of this.buckets) {
            if (!bucket) continue;
            bucket.geometry.dispose();
            bucket.material.dispose();
            bucket.emphasisMaterial.dispose();
        }
        this.positionTexture.dispose();
        this.clear();
    }

    private bucketForEdge(edge: number): EdgeBucket {
        const bucket = this.buckets[this.edgeBucket[edge]];
        if (!bucket) throw new Error(`Missing GPU edge bucket for edge ${edge}`);
        return bucket;
    }

    private createBucket(segments: number, instanceCount: number): EdgeBucket {
        const geometry = new THREE.InstancedBufferGeometry();
        const template = new Float32Array(segments * 2 * 3);
        for (let segment = 0; segment < segments; segment++) {
            template[segment * 6] = segment / segments;
            template[segment * 6 + 3] = (segment + 1) / segments;
        }
        const styles = new Uint8Array(instanceCount * 4);
        const lifts = new Float32Array(instanceCount);
        const sourceColors = new Uint8Array(instanceCount * 4);
        const targetColors = new Uint8Array(instanceCount * 4);
        geometry.setAttribute('position', new THREE.BufferAttribute(template, 3));
        geometry.setAttribute('aEndpoints', new THREE.InstancedBufferAttribute(new Uint32Array(instanceCount * 2), 2));
        geometry.setAttribute('aStyle', new THREE.InstancedBufferAttribute(styles, 4, true).setUsage(THREE.DynamicDrawUsage));
        geometry.setAttribute('aLift', new THREE.InstancedBufferAttribute(lifts, 1).setUsage(THREE.DynamicDrawUsage));
        geometry.setAttribute('aSourceColor', new THREE.InstancedBufferAttribute(sourceColors, 4, true).setUsage(THREE.DynamicDrawUsage));
        geometry.setAttribute('aTargetColor', new THREE.InstancedBufferAttribute(targetColors, 4, true).setUsage(THREE.DynamicDrawUsage));
        geometry.instanceCount = instanceCount;
        const material = this.createMaterial(false);
        const emphasisMaterial = this.createMaterial(true);
        const line = new THREE.LineSegments(geometry, material);
        const emphasisLine = new THREE.LineSegments(geometry, emphasisMaterial);
        line.frustumCulled = false;
        emphasisLine.frustumCulled = false;
        line.userData['edgePass'] = 'base';
        emphasisLine.userData['edgePass'] = 'emphasis';
        emphasisLine.renderOrder = 3;
        return { geometry, material, emphasisMaterial, line, emphasisLine, styles, lifts, sourceColors, targetColors };
    }

    private createMaterial(emphasis: boolean): THREE.RawShaderMaterial {
        return new THREE.RawShaderMaterial({
            glslVersion: THREE.GLSL3,
            uniforms: {
                uNodePositions: { value: this.positionTexture },
                uTextureSize: { value: new THREE.Vector2(this.textureWidth, this.textureHeight) },
                uViewport: { value: new THREE.Vector2(1, 1) },
                uOpacity: { value: 1 },
                uDensityAttenuation: { value: 1 },
                uLayoutKind: { value: 0 },
                uCurveStrength: { value: 0.65 },
                uIs3d: { value: 1 },
                uEmphasisPass: { value: emphasis ? 1 : 0 },
            },
            vertexShader: EDGE_VERTEX_SHADER,
            fragmentShader: EDGE_FRAGMENT_SHADER,
            transparent: true,
            depthWrite: false,
            depthTest: true,
            blending: emphasis ? THREE.AdditiveBlending : THREE.NormalBlending,
            toneMapped: false,
        });
    }
}

function edgeBucketForCurve(curve: number): number {
    if (curve === GalaxyGpuEdgeCurve.Straight) return 0;
    if (curve === GalaxyGpuEdgeCurve.Hopf || curve === GalaxyGpuEdgeCurve.HopfCross || curve === GalaxyGpuEdgeCurve.Surface) return 2;
    return 1;
}

function packUnit(value: number): number {
    return Math.round(THREE.MathUtils.clamp(value, 0, 1) * 255);
}

function writePackedColor(output: Uint8Array, offset: number, color: THREE.Color, alpha: number): void {
    output[offset] = packUnit(color.r);
    output[offset + 1] = packUnit(color.g);
    output[offset + 2] = packUnit(color.b);
    output[offset + 3] = packUnit(alpha);
}

const EDGE_VERTEX_SHADER = /* glsl */ `
precision highp float;
precision highp int;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform sampler2D uNodePositions;
uniform vec2 uTextureSize;
uniform vec2 uViewport;
uniform float uLayoutKind;
uniform float uCurveStrength;
uniform float uIs3d;

in vec3 position;
in uvec2 aEndpoints;
in vec4 aStyle;
in float aLift;
in vec4 aSourceColor;
in vec4 aTargetColor;

out vec4 vColor;
out float vCurveT;
flat out float vVisible;
flat out float vImportant;
flat out float vFocused;

const float PI = 3.141592653589793;

vec3 nodePosition(uint packedNodeIndex) {
    float nodeIndex = float(packedNodeIndex);
    float y = floor(nodeIndex / uTextureSize.x);
    float x = nodeIndex - y * uTextureSize.x;
    return texelFetch(uNodePositions, ivec2(int(x), int(y)), 0).xyz;
}

vec3 surfacePoint(vec3 source, vec3 target, float t) {
    float sourceRadius = max(0.000001, length(source));
    float targetRadius = max(0.000001, length(target));
    vec3 a = source / sourceRadius;
    vec3 b = target / targetRadius;
    float radius = mix(sourceRadius, targetRadius, t);
    float cosine = clamp(dot(a, b), -1.0, 1.0);
    if (cosine > 0.9995) return normalize(mix(a, b, t)) * radius;
    float theta = acos(cosine);
    float divisor = max(0.000001, sin(theta));
    return (a * (sin((1.0 - t) * theta) / divisor) + b * (sin(t * theta) / divisor)) * radius;
}

vec3 hopfPoint(vec3 source, vec3 target, float lift, float t, float seed, bool crossBase) {
    float sourceRadius = max(0.0001, length(source));
    float targetRadius = max(0.0001, length(target));
    vec3 a = source / sourceRadius;
    vec3 b = target / targetRadius;
    float signValue = seed < 0.5 ? -1.0 : 1.0;
    vec3 normal = cross(a, b);
    if (length(normal) < 0.0001) normal = vec3(a.y * signValue - a.z * 0.38, a.z + 0.22, -a.x + a.y * 0.38);
    normal = normalize(normal);
    float sweep = sin(PI * t);
    float bend = (crossBase ? 0.36 : 0.18) * clamp(uCurveStrength, 0.25, 1.2) * sweep * signValue;
    vec3 direction = normalize(mix(a, b, t) + normal * bend);
    float radius = mix(sourceRadius, targetRadius, t) + lift * (crossBase ? 0.72 : 0.38) * sweep;
    return direction * radius;
}

vec3 tubePoint(vec3 source, vec3 target, float lift, float t, float seed, bool tree) {
    vec3 delta = target - source;
    float xy = max(0.000001, length(delta.xy));
    float signValue = seed < 0.5 ? -1.0 : 1.0;
    float sweep = sin(PI * t);
    float braid = sin(PI * 2.0 * t + signValue * 0.72) * lift * 0.08;
    float width = uLayoutKind == 1.0 ? 0.30 : 0.26;
    float tail = t > 1.0 - width ? sin(PI * (1.0 - t) / width) : 0.0;
    float layoutStyle = uLayoutKind == 2.0 ? 0.21 : uLayoutKind == 3.0 ? 0.18 : 0.16;
    float flourish = tree ? lift * layoutStyle * signValue * tail : 0.0;
    float lateral = lift * 0.34 * sweep * signValue + flourish;
    vec3 value = mix(source, target, t);
    value.x += (-delta.y / xy) * lateral;
    value.y += (delta.x / xy) * lateral + lift * 0.38 * sweep + abs(flourish) * 0.08;
    value.z += uIs3d * (lift * 0.24 * sweep * signValue + braid + flourish * 0.42);
    return value;
}

void main() {
    float t = position.x;
    vec3 source = nodePosition(aEndpoints.x);
    vec3 target = nodePosition(aEndpoints.y);
    int curve = int(round(aStyle.r * 255.0));
    float seed = aStyle.a;
    vec3 value = mix(source, target, t);
    if (curve == 1) value.y += aLift * sin(PI * t);
    else if (curve == 2) value = surfacePoint(source, target, t);
    else if (curve == 3) value = hopfPoint(source, target, aLift, t, seed, false);
    else if (curve == 4) value = tubePoint(source, target, aLift, t, seed, false);
    else if (curve == 5) value.y += aLift * sin(PI * t);
    else if (curve == 6) value = tubePoint(source, target, aLift, t, seed, true);
    else if (curve == 7) value = hopfPoint(source, target, aLift, t, seed, true);

    vec4 sourceClip = projectionMatrix * modelViewMatrix * vec4(source, 1.0);
    vec4 targetClip = projectionMatrix * modelViewMatrix * vec4(target, 1.0);
    vec2 sourceNdc = sourceClip.xy / max(0.000001, abs(sourceClip.w));
    vec2 targetNdc = targetClip.xy / max(0.000001, abs(targetClip.w));
    float pixelSpan = length((targetNdc - sourceNdc) * 0.5 * uViewport);
    bool important = aStyle.g * 255.0 > 0.5 || aStyle.b * 255.0 > 0.5;
    vVisible = important || pixelSpan >= 0.70 ? 1.0 : 0.0;
    vImportant = important ? 1.0 : 0.0;
    vFocused = aStyle.b * 255.0 > 0.5 ? 1.0 : 0.0;
    vColor = mix(aSourceColor, aTargetColor, t);
    vCurveT = t;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(value, 1.0);
}
`;

const EDGE_FRAGMENT_SHADER = /* glsl */ `
precision highp float;

uniform float uOpacity;
uniform float uEmphasisPass;
uniform float uDensityAttenuation;
in vec4 vColor;
in float vCurveT;
flat in float vVisible;
flat in float vImportant;
flat in float vFocused;
out vec4 outColor;

float terminalTaper(float t) {
    return clamp(smoothstep(0.015, 0.115, t) * (1.0 - smoothstep(0.885, 0.985, t)), 0.0, 1.0);
}

void main() {
    if (vVisible < 0.5) discard;
    if (uEmphasisPass > 0.5 && vImportant < 0.5) discard;
    float energy = uEmphasisPass > 0.5 ? 1.24 : 1.0;
    float backgroundAttenuation = uEmphasisPass > 0.5
        ? uDensityAttenuation * uDensityAttenuation
        : sqrt(uDensityAttenuation);
    float overdrawAttenuation = vFocused > 0.5 ? 1.0 : backgroundAttenuation;
    float terminal = terminalTaper(vCurveT);
    float terminalFloor = vFocused > 0.5 ? 0.34 : vImportant > 0.5 ? 0.18 : 0.0;
    float terminalAttenuation = max(terminalFloor, terminal);
    outColor = vec4(vColor.rgb * energy, vColor.a * uOpacity * overdrawAttenuation * terminalAttenuation);
}
`;
