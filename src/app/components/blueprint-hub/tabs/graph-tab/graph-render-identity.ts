import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';

export function graphSnapshotRenderIdentity(
    snapshot: GraphRebuildSnapshot | null | undefined,
): string {
    if (!snapshot) return '';
    const authority = snapshot.authorityContract?.contentHash || '';
    if (!snapshot.scopeId || !snapshot.id || !authority) return '';
    return `${snapshot.scopeId}\u0000${snapshot.id}\u0000${authority}`;
}

export function sameGraphRenderIdentity(
    current: GraphRebuildSnapshot | null | undefined,
    next: GraphRebuildSnapshot | null | undefined,
): boolean {
    const currentIdentity = graphSnapshotRenderIdentity(current);
    return Boolean(currentIdentity && currentIdentity === graphSnapshotRenderIdentity(next));
}

export function graphSnapshotHasHydratedCanvasPayload(
    snapshot: GraphRebuildSnapshot | null | undefined,
): boolean {
    if (!snapshot) return false;
    const targetCount = snapshot.counters?.embeddingTargets
        ?? snapshot.authorityContract?.counts?.embeddingTargets
        ?? 0;
    return targetCount === 0 || (snapshot.embeddingTargets?.length || 0) > 0;
}

export function shouldReplaceGraphRenderSnapshot(
    current: GraphRebuildSnapshot | null | undefined,
    next: GraphRebuildSnapshot | null | undefined,
): boolean {
    if (current === next) return false;
    if (!sameGraphRenderIdentity(current, next)) return true;
    if (next?.generationReceiptId && next.generationDigestSha256) return true;
    return !graphSnapshotHasHydratedCanvasPayload(current)
        && graphSnapshotHasHydratedCanvasPayload(next);
}
