import type { EntityOccurrence } from '../lib/dexie/db';

export interface GraphSnapshotSourceEvidenceInput {
    persistedOccurrences?: readonly EntityOccurrence[];
    stagedOccurrences?: readonly EntityOccurrence[];
    cachedSnapshotOccurrences?: readonly EntityOccurrence[];
    recoveredOccurrences?: readonly EntityOccurrence[];
}

export interface GraphSnapshotSourceEvidence {
    schemaVersion: 'phoenix-graph-snapshot-source-evidence/v1';
    persistedOccurrences: EntityOccurrence[];
    stagedOccurrences: EntityOccurrence[];
    cachedSnapshotOccurrences: EntityOccurrence[];
    recoveredOccurrences: EntityOccurrence[];
    allOccurrences: EntityOccurrence[];
    counters: {
        persisted: number;
        staged: number;
        cachedSnapshot: number;
        recovered: number;
        total: number;
    };
}

export function buildGraphSnapshotSourceEvidence(
    input: GraphSnapshotSourceEvidenceInput,
): GraphSnapshotSourceEvidence {
    const persistedOccurrences = [...(input.persistedOccurrences || [])];
    const stagedOccurrences = [...(input.stagedOccurrences || [])];
    const cachedSnapshotOccurrences = [...(input.cachedSnapshotOccurrences || [])];
    const recoveredOccurrences = [...(input.recoveredOccurrences || [])];
    const allOccurrences = mergeOccurrenceLists([
        persistedOccurrences,
        stagedOccurrences,
        cachedSnapshotOccurrences,
        recoveredOccurrences,
    ]);
    return {
        schemaVersion: 'phoenix-graph-snapshot-source-evidence/v1',
        persistedOccurrences,
        stagedOccurrences,
        cachedSnapshotOccurrences,
        recoveredOccurrences,
        allOccurrences,
        counters: {
            persisted: persistedOccurrences.length,
            staged: stagedOccurrences.length,
            cachedSnapshot: cachedSnapshotOccurrences.length,
            recovered: recoveredOccurrences.length,
            total: allOccurrences.length,
        },
    };
}

export function mergeGraphRebuildOccurrences(
    persisted: readonly EntityOccurrence[],
    recovered: readonly EntityOccurrence[],
): EntityOccurrence[] {
    return mergeOccurrenceLists([persisted, recovered]);
}

function mergeOccurrenceLists(lists: readonly (readonly EntityOccurrence[])[]): EntityOccurrence[] {
    const seen = new Set<string>();
    const merged: EntityOccurrence[] = [];
    for (const list of lists) {
        for (const occurrence of list) {
            const key = occurrenceKey(occurrence);
            if (seen.has(key)) continue;
            seen.add(key);
            merged.push(occurrence);
        }
    }
    return merged;
}

function occurrenceKey(occurrence: EntityOccurrence): string {
    return `${occurrence.noteId}:${occurrence.entityId}:${occurrence.sourceStart}:${occurrence.sourceEnd}`;
}
