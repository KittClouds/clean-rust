import type { GraphRebuildSnapshot, GraphSnapshotAuthority } from './graph-rebuild-snapshot';
import { sealGraphSnapshotAuthority } from './graph-snapshot-authority';
import type { GraphSnapshotSourceEvidence } from './graph-snapshot-source-evidence';
import { recordGraphCollapseSnapshotBoundary } from './graph-collapse-trace';

export interface FinalizeGraphRebuildSnapshotInput {
    snapshot: GraphRebuildSnapshot;
    sourceEvidence?: GraphSnapshotSourceEvidence;
    previousSnapshot?: GraphRebuildSnapshot | null;
    hasNonemptySourceText?: boolean;
    authority?: GraphSnapshotAuthority;
}

export function finalizeGraphRebuildSnapshot(input: FinalizeGraphRebuildSnapshotInput): GraphRebuildSnapshot {
    assertCommittedSnapshotShape(
        input.snapshot,
        input.sourceEvidence,
        input.previousSnapshot,
        input.hasNonemptySourceText,
    );
    sealGraphSnapshotAuthority(input.snapshot, input.authority);
    recordGraphCollapseSnapshotBoundary(input.snapshot, 'sealed_packet');
    return input.snapshot;
}

function assertCommittedSnapshotShape(
    snapshot: GraphRebuildSnapshot,
    sourceEvidence?: GraphSnapshotSourceEvidence,
    previousSnapshot?: GraphRebuildSnapshot | null,
    hasNonemptySourceText = false,
): void {
    const issues: string[] = [];
    const anchorIds = new Set(snapshot.entityAnchors.map((anchor) => anchor.id));
    if (snapshot.counters.acceptedAnchors !== snapshot.entityAnchors.length) {
        issues.push(`accepted anchor counter ${snapshot.counters.acceptedAnchors} != rows ${snapshot.entityAnchors.length}`);
    }
    for (const node of snapshot.nodes) {
        if (!node.totalMentions || !node.anchorIds.length) {
            issues.push(`registry-only graph node ${node.entityId}`);
            continue;
        }
        const missingAnchors = node.anchorIds.filter((anchorId) => !anchorIds.has(anchorId));
        if (missingAnchors.length) issues.push(`node ${node.entityId} missing source anchors ${missingAnchors.length}`);
    }
    for (const target of snapshot.embeddingTargets) {
        if (target.kind !== 'entity') continue;
        if (!target.evidenceIds?.length) issues.push(`registry-only entity target ${target.entityId || target.sourceId}`);
    }
    if (sourceEvidence && sourceEvidence.counters.total > 0 && snapshot.counters.mentions === 0 && snapshot.counters.acceptedAnchors === 0) {
        issues.push(`source evidence produced no committed rows (${sourceEvidence.counters.total})`);
    }
    const previouslyAnchoredSameScope = previousSnapshot?.scopeId === snapshot.scopeId
        && previousSnapshot.entityAnchors.length > 0;
    if (
        previouslyAnchoredSameScope
        && hasNonemptySourceText
        && sourceEvidence?.counters.total === 0
        && snapshot.counters.mentions === 0
        && snapshot.counters.acceptedAnchors === 0
    ) {
        issues.push(
            `previously anchored nonempty scope became source-empty; refusing roots-only snapshot (${previousSnapshot.entityAnchors.length} prior anchors)`,
        );
    }
    if (issues.length) {
        throw new Error(`Graph snapshot finalization failed for ${snapshot.id}: ${issues.join(', ')}`);
    }
}
