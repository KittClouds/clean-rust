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
