import type { PhoenixGraphScenePacket } from '../../../../../services/phoenix-graph-scene-packet.model';
import { decodeGraphScenePacketBuffers } from '../../../../../services/phoenix-graph-scene-packet.decode';
import type { GalaxySceneV2 } from './graph-galaxy-scene-v2';

export function graphScenePacketToV2(packet: PhoenixGraphScenePacket): GalaxySceneV2 {
    const buffers = decodeGraphScenePacketBuffers(packet);
    return {
        sourceMode: packet.sourceMode,
        layoutMode: packet.layoutMode,
        ids: packet.ids.slice(),
        labels: packet.labels.slice(),
        kinds: packet.kinds.slice(),
        groupIds: packet.groupIds.slice(),
        groups: [],
        hopfRibbons: [],
        lorentzGuides: [],
        positions3d: buffers.positions3d,
        positions2d: buffers.positions2d,
        radii: buffers.radii,
        colors: buffers.colors,
        edgePairs: buffers.edgePairs,
        edgeColors: buffers.edgeColors,
        edgeAlpha: buffers.edgeAlpha,
        edgeKinds: buffers.edgeKinds,
        hierarchyShellRadii: buffers.hierarchyShellRadii,
        hierarchyShellRanks: buffers.hierarchyShellRanks,
        hierarchyHints: packet.hierarchyHints?.slice(),
    };
}
