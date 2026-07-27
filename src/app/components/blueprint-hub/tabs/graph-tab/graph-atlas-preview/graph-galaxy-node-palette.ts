import type { EntityKind } from '../../../../../lib/Scanner/types';
import {
    DEFAULT_ENTITY_COLORS,
    DEFAULT_GRAPH_NODE_COLORS,
    entityColorStore,
    type GraphNodeColorKind,
} from '../../../../../lib/store/entityColorStore';

export const GALAXY_NODE_PALETTE_UNBOUND = 0xff;

const ENTITY_KEYS = Object.freeze(Object.keys(DEFAULT_ENTITY_COLORS) as EntityKind[]);
const GRAPH_KEYS = Object.freeze(Object.keys(DEFAULT_GRAPH_NODE_COLORS) as GraphNodeColorKind[]);
const GRAPH_OFFSET = ENTITY_KEYS.length;
const ENTITY_SLOT = new Map<EntityKind, number>(ENTITY_KEYS.map((kind, index) => [kind, index]));
const GRAPH_SLOT = new Map<GraphNodeColorKind, number>(GRAPH_KEYS.map((kind, index) => [kind, GRAPH_OFFSET + index]));

if (GRAPH_OFFSET + GRAPH_KEYS.length >= GALAXY_NODE_PALETTE_UNBOUND) {
    throw new Error('Galaxy node palette exceeds its compact u8 slot contract.');
}

export function galaxyEntityPaletteSlot(kind: EntityKind): number {
    return ENTITY_SLOT.get(kind) ?? GALAXY_NODE_PALETTE_UNBOUND;
}

export function galaxyGraphPaletteSlot(kind: GraphNodeColorKind): number {
    return GRAPH_SLOT.get(kind) ?? GALAXY_NODE_PALETTE_UNBOUND;
}

export function refreshGalaxyNodePaletteRgba8(
    target: Uint8Array,
    packed: Uint8Array,
    slots: Uint8Array,
    nodeCount: number,
): void {
    if (target.length < nodeCount * 4 || packed.length < nodeCount * 4 || slots.length < nodeCount) {
        throw new Error('Galaxy Renderer V3 palette page length drift.');
    }
    target.set(packed.subarray(0, nodeCount * 4));
    const palette = currentPaletteRgba8();
    for (let index = 0; index < nodeCount; index++) {
        const slot = slots[index];
        if (slot === GALAXY_NODE_PALETTE_UNBOUND) continue;
        const source = slot * 4;
        const destination = index * 4;
        target[destination] = palette[source];
        target[destination + 1] = palette[source + 1];
        target[destination + 2] = palette[source + 2];
        target[destination + 3] = 0xff;
    }
}

function currentPaletteRgba8(): Uint8Array {
    const output = new Uint8Array((ENTITY_KEYS.length + GRAPH_KEYS.length) * 4);
    let cursor = 0;
    for (const kind of ENTITY_KEYS) cursor = writeHsl(output, cursor, entityColorStore.getRawHsl(kind));
    for (const kind of GRAPH_KEYS) cursor = writeHsl(output, cursor, entityColorStore.getRawGraphNodeHsl(kind));
    return output;
}

function writeHsl(target: Uint8Array, offset: number, value: string): number {
    const [hueText, saturationText, lightnessText] = value.split(' ');
    const hue = ((Number.parseFloat(hueText) % 360) + 360) % 360;
    const saturation = clamp01(Number.parseFloat(saturationText) / 100);
    const lightness = clamp01(Number.parseFloat(lightnessText) / 100);
    const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
    const secondary = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
    const match = lightness - chroma / 2;
    let red = 0;
    let green = 0;
    let blue = 0;
    if (hue < 60) [red, green] = [chroma, secondary];
    else if (hue < 120) [red, green] = [secondary, chroma];
    else if (hue < 180) [green, blue] = [chroma, secondary];
    else if (hue < 240) [green, blue] = [secondary, chroma];
    else if (hue < 300) [red, blue] = [secondary, chroma];
    else [red, blue] = [chroma, secondary];
    target[offset] = Math.round((red + match) * 255);
    target[offset + 1] = Math.round((green + match) * 255);
    target[offset + 2] = Math.round((blue + match) * 255);
    target[offset + 3] = 0xff;
    return offset + 4;
}

function clamp01(value: number): number {
    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}
