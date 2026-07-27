export function galaxyScenePacketHashBuffer(buffer: ArrayBuffer): string {
    let low = 0x811c9dc5;
    let high = 0x9e3779b9;
    for (const byte of new Uint8Array(buffer)) {
        low = Math.imul(low ^ byte, 0x01000193) >>> 0;
        high = Math.imul(high ^ byte, 0x85ebca6b) >>> 0;
    }
    return `fnv1a64:${high.toString(16).padStart(8, '0')}${low.toString(16).padStart(8, '0')}`;
}

export function galaxyScenePacketHashText(value: string): string {
    return galaxyScenePacketHashBuffer(new TextEncoder().encode(value).buffer as ArrayBuffer);
}
