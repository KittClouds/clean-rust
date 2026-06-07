import type {
    GraphRebuildEmbeddingProfile,
    GraphRebuildEmbeddingTarget,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import {
    normalizeEmbeddingProfile,
    sparseEmbeddingSignature,
    type SparseEmbeddingSignature,
} from './graph-rebuild-embedding-signatures';
import {
    TAU,
    add3,
    clamp01,
    clampInt,
    dot3,
    fallbackDirection,
    fallbackTangent,
    icosahedralCenters,
    mix32,
    norm3,
    normalize3,
    positiveRadians,
    round,
    roundVec,
    scale3,
    signedUnit,
    stableUnit,
    sub3,
    tangentFrame,
    type Vec3Tuple,
} from './graph-hopf-resonance-geometry';

export type HopfResonanceFiberKind =
    | 'document_chart'
    | 'structure_root'
    | 'chunk_sample'
    | 'entity_sample'
    | 'event_sample'
    | 'temporal_sample'
    | 'causal_sample'
    | 'memory_sample'
    | 'fact_sample'
    | 'evidence_sample'
    | 'support_sample';

export type HopfResonanceAssignmentRole =
    | 'document-chart'
    | 'structure-root'
    | 'fiber-sample'
    | 'evidence-support';

export interface HopfResonanceCell {
    id: string;
    ordinal: number;
    resolution: number;
    center: Vec3Tuple;
    neighborCellIds: string[];
    targetCount: number;
    sampleCount: number;
    totalWeight: number;
    dominantFiberKinds: HopfResonanceFiberKind[];
    anchorTargetIds: string[];
}

export interface HopfResonanceAssignment {
    targetId: string;
    targetKind: string;
    label: string;
    noteId?: string;
    chunkId?: string;
    entityId?: string;
    role: HopfResonanceAssignmentRole;
    fiberKind: HopfResonanceFiberKind;
    baseCellId: string;
    secondaryCellIds: string[];
    direction: Vec3Tuple;
    tangent: Vec3Tuple;
    phase: number;
    phaseRadians: number;
    strandKey: string;
    strandIndex: number;
    strandCount: number;
    phaseSpread: number;
    assignmentScore: number;
    residualScore: number;
    salience: number;
    evidenceIds: string[];
    parentIds: string[];
    receipt: string;
}

export interface HopfDocumentCellWeight {
    cellId: string;
    weight: number;
    sampleCount: number;
    fiberKinds: HopfResonanceFiberKind[];
}

export interface HopfDocumentChart {
    id: string;
    noteId: string;
    sourceTargetId?: string;
    cellWeights: HopfDocumentCellWeight[];
    dominantCellIds: string[];
    coverageEntropy: number;
    coverageSpread: number;
    sampleTargetIds: string[];
    rootTargetIds: string[];
    chunkTargetIds: string[];
}

export interface HopfResonanceFiber {
    id: string;
    cellId: string;
    fiberKind: HopfResonanceFiberKind;
    targetIds: string[];
    anchorTargetId: string;
    sampleCount: number;
    totalWeight: number;
    meanPhase: number;
    coherence: number;
    frustration: number;
}

export interface HopfResonanceBraid {
    id: string;
    kind: 'cell_neighbor' | 'fiber_neighbor';
    sourceCellId: string;
    targetCellId: string;
    sourceFiberId?: string;
    targetFiberId?: string;
    sourceTargetCount: number;
    targetTargetCount: number;
    representativeTargetIds: string[];
    score: number;
    summary: true;
    reason: string[];
}

export interface HopfResonanceSpaceCounters {
    targetCount: number;
    assignmentCount: number;
    droppedTargets: number;
    cellCount: number;
    occupiedCellCount: number;
    fiberCount: number;
    docChartCount: number;
    braidCount: number;
    documentTargets: number;
    chunkTargets: number;
    entityTargets: number;
    structureRootTargets: number;
    crowdedFiberCount: number;
    maxFiberSampleCount: number;
    mutationAllowedCount: 0;
}

export interface HopfResonanceSpace {
    schemaVersion: 'phoenix-hopf-resonance-space/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    profile: GraphRebuildEmbeddingProfile;
    cellResolution: number;
    targetCount: number;
    assignments: HopfResonanceAssignment[];
    cells: HopfResonanceCell[];
    fibers: HopfResonanceFiber[];
    docCharts: HopfDocumentChart[];
    braids: HopfResonanceBraid[];
    counters: HopfResonanceSpaceCounters;
}

export interface BuildHopfResonanceSpaceOptions {
    generatedAt?: number;
    cellResolution?: number;
    neighborCount?: number;
    secondaryCellCount?: number;
}

type MutableCell = HopfResonanceCell & {
    kindWeights: Map<HopfResonanceFiberKind, number>;
    assignments: HopfResonanceAssignment[];
};

type FiberAccumulator = {
    cellId: string;
    fiberKind: HopfResonanceFiberKind;
    assignments: HopfResonanceAssignment[];
    weight: number;
    sin: number;
    cos: number;
};

const DEFAULT_CELL_RESOLUTION = 3;
const DEFAULT_NEIGHBOR_COUNT = 6;
const DEFAULT_SECONDARY_CELL_COUNT = 3;
export function buildHopfResonanceSpace(
    snapshot: GraphRebuildSnapshot,
    options: BuildHopfResonanceSpaceOptions = {},
): HopfResonanceSpace {
    const generatedAt = options.generatedAt ?? Date.now();
    const profile = normalizeEmbeddingProfile(snapshot.embeddingProfile);
    const cellResolution = clampInt(options.cellResolution ?? DEFAULT_CELL_RESOLUTION, 1, 5);
    const neighborCount = clampInt(options.neighborCount ?? DEFAULT_NEIGHBOR_COUNT, 3, 12);
    const secondaryCellCount = clampInt(options.secondaryCellCount ?? DEFAULT_SECONDARY_CELL_COUNT, 1, 8);
    const cells = buildMutableCells(cellResolution, neighborCount);
    const directions = buildContextDirections(snapshot.embeddingTargets, profile);
    const assignments = spreadFiberPhases(snapshot.embeddingTargets.map((target) =>
        assignTargetToHopfCell(target, profile, cells, secondaryCellCount, directions.get(target.id)),
    ));

    const cellById = new Map(cells.map((cell) => [cell.id, cell]));
    for (const assignment of assignments) {
        const cell = cellById.get(assignment.baseCellId);
        if (!cell) continue;
        cell.assignments.push(assignment);
        cell.targetCount += 1;
        if (assignment.role !== 'document-chart') cell.sampleCount += 1;
        cell.totalWeight += assignment.salience;
        cell.kindWeights.set(
            assignment.fiberKind,
            (cell.kindWeights.get(assignment.fiberKind) || 0) + assignment.salience,
        );
    }

    const fibers = buildFibers(assignments);
    const fibersByCell = groupFibersByCell(fibers);
    const finalizedCells = finalizeCells(cells);
    const docCharts = buildDocumentCharts(snapshot, assignments, finalizedCells.length);
    const braids = buildCellBraids(finalizedCells, fibersByCell);

    return {
        schemaVersion: 'phoenix-hopf-resonance-space/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        profile,
        cellResolution,
        targetCount: snapshot.embeddingTargets.length,
        assignments,
        cells: finalizedCells,
        fibers,
        docCharts,
        braids,
        counters: {
            targetCount: snapshot.embeddingTargets.length,
            assignmentCount: assignments.length,
            droppedTargets: Math.max(0, snapshot.embeddingTargets.length - assignments.length),
            cellCount: finalizedCells.length,
            occupiedCellCount: finalizedCells.filter((cell) => cell.targetCount > 0).length,
            fiberCount: fibers.length,
            docChartCount: docCharts.length,
            braidCount: braids.length,
            documentTargets: assignments.filter((row) => row.role === 'document-chart').length,
            chunkTargets: assignments.filter((row) => row.fiberKind === 'chunk_sample').length,
            entityTargets: assignments.filter((row) => row.fiberKind === 'entity_sample').length,
            structureRootTargets: assignments.filter((row) => row.role === 'structure-root').length,
            crowdedFiberCount: fibers.filter((row) => row.sampleCount >= 10).length,
            maxFiberSampleCount: fibers.reduce((max, row) => Math.max(max, row.sampleCount), 0),
            mutationAllowedCount: 0,
        },
    };
}

export function hopfResonanceSpaceSummary(space: HopfResonanceSpace): Record<string, unknown> {
    const topCells = [...space.cells]
        .filter((cell) => cell.targetCount > 0)
        .sort((left, right) => right.totalWeight - left.totalWeight || left.id.localeCompare(right.id))
        .slice(0, 8)
        .map((cell) => ({
            id: cell.id,
            targets: cell.targetCount,
            samples: cell.sampleCount,
            weight: cell.totalWeight,
            kinds: cell.dominantFiberKinds,
        }));
    return {
        schemaVersion: space.schemaVersion,
        snapshot: space.sourceSnapshotId,
        model: space.profile.modelLabel,
        vectorSource: space.profile.vectorSource,
        targets: space.counters.targetCount,
        assignments: space.counters.assignmentCount,
        dropped: space.counters.droppedTargets,
        cells: space.counters.cellCount,
        occupiedCells: space.counters.occupiedCellCount,
        fibers: space.counters.fiberCount,
        docCharts: space.counters.docChartCount,
        braids: space.counters.braidCount,
        topCells,
    };
}

function assignTargetToHopfCell(
    target: GraphRebuildEmbeddingTarget,
    profile: GraphRebuildEmbeddingProfile,
    cells: MutableCell[],
    secondaryCellCount: number,
    contextDirection?: Vec3Tuple,
): HopfResonanceAssignment {
    const signature = sparseEmbeddingSignature(target, profile.selectedDimensions);
    const direction = contextDirection || signatureDirection(signature, target.id);
    const ranked = rankCells(direction, cells, secondaryCellCount + 1);
    const primary = ranked[0] || cells[0];
    const frame = tangentFrame(primary.center);
    const dot = dot3(direction, primary.center);
    const residual = sub3(direction, scale3(primary.center, dot));
    const residualNorm = norm3(residual);
    const tangent = residualNorm > 1e-6
        ? scale3(residual, 1 / residualNorm)
        : fallbackTangent(frame, target.id);
    const phaseRadians = positiveRadians(Math.atan2(dot3(tangent, frame.v), dot3(tangent, frame.u)));
    const fiberKind = targetFiberKind(target);
    const role = assignmentRole(target, fiberKind);
    return {
        targetId: target.id,
        targetKind: target.kind,
        label: target.label,
        noteId: target.noteId,
        chunkId: target.chunkId,
        entityId: target.entityId,
        role,
        fiberKind,
        baseCellId: primary.id,
        secondaryCellIds: ranked.slice(1).map((cell) => cell.id),
        direction: roundVec(direction),
        tangent: roundVec(tangent),
        phase: round(phaseRadians / TAU),
        phaseRadians: round(phaseRadians),
        strandKey: `${primary.id}:${fiberKind}`,
        strandIndex: 0,
        strandCount: 1,
        phaseSpread: 0,
        assignmentScore: round(clamp01((dot + 1) * 0.5)),
        residualScore: round(clamp01(residualNorm)),
        salience: targetSalience(target),
        evidenceIds: target.evidenceIds || [],
        parentIds: target.parentIds || [],
        receipt: 'hopf_space_assignment:no_topology_mutation',
    };
}

function buildContextDirections(
    targets: GraphRebuildEmbeddingTarget[],
    profile: GraphRebuildEmbeddingProfile,
): Map<string, Vec3Tuple> {
    const baseDirections = new Map<string, Vec3Tuple>();
    for (const target of targets) {
        baseDirections.set(target.id, signatureDirection(sparseEmbeddingSignature(target, profile.selectedDimensions), target.id));
    }
    const out = new Map<string, Vec3Tuple>();
    for (const target of targets) {
        out.set(target.id, contextDirectionForTarget(target, baseDirections));
    }
    return out;
}

function contextDirectionForTarget(
    target: GraphRebuildEmbeddingTarget,
    baseDirections: Map<string, Vec3Tuple>,
): Vec3Tuple {
    const own = baseDirections.get(target.id) || fallbackDirection(target.id);
    const fiberKind = targetFiberKind(target);
    const structuralRoot = fiberKind === 'structure_root';
    const contextual = fiberKind === 'temporal_sample' || fiberKind === 'causal_sample';
    let vector = scale3(own, structuralRoot ? 0.18 : contextual ? 0.34 : 0.72);
    let weight = structuralRoot ? 0.18 : contextual ? 0.34 : 0.72;
    for (const parentId of (target.parentIds || []).slice(0, 8)) {
        const parent = baseDirections.get(parentId);
        if (!parent) continue;
        const parentWeight = parentId.includes(':structure-root:') || parentId.includes(':root:')
            ? structuralRoot ? 0.04 : 0.08
            : structuralRoot ? 0.42 : contextual ? 0.28 : 0.14;
        vector = add3(vector, scale3(parent, parentWeight));
        weight += parentWeight;
    }
    const note = target.noteId ? baseDirections.get(`embed:note:${target.noteId}`) : undefined;
    if (note) {
        const noteWeight = structuralRoot ? 0.7 : contextual ? 0.16 : 0.08;
        vector = add3(vector, scale3(note, noteWeight));
        weight += noteWeight;
    }
    const normalized = normalize3(scale3(vector, 1 / Math.max(0.0001, weight)));
    return norm3(normalized) ? normalized : own;
}

function spreadFiberPhases(assignments: HopfResonanceAssignment[]): HopfResonanceAssignment[] {
    const out = assignments.slice();
    const groups = new Map<string, number[]>();
    for (let index = 0; index < out.length; index += 1) {
        const row = out[index];
        const key = `${row.baseCellId}:${row.fiberKind}`;
        const bucket = getOrInsert(groups, key, () => []);
        bucket.push(index);
    }
    for (const [key, indexes] of groups) {
        if (indexes.length < 4) {
            for (let rank = 0; rank < indexes.length; rank += 1) {
                const row = out[indexes[rank]];
                out[indexes[rank]] = { ...row, strandKey: key, strandIndex: rank, strandCount: indexes.length };
            }
            continue;
        }
        const sorted = indexes.sort((left, right) => strandSortKey(out[left]).localeCompare(strandSortKey(out[right])));
        const offset = stableUnit(`${key}:phase-offset`) / sorted.length;
        for (let rank = 0; rank < sorted.length; rank += 1) {
            const row = out[sorted[rank]];
            const slot = positivePhase((rank + 0.5) / sorted.length + offset);
            const blend = phaseSpreadWeight(row, sorted.length);
            const phase = circularPhaseBlend(row.phase, slot, blend);
            out[sorted[rank]] = {
                ...row,
                phase,
                phaseRadians: round(phase * TAU),
                strandKey: key,
                strandIndex: rank,
                strandCount: sorted.length,
                phaseSpread: round(circularDistance(row.phase, phase)),
            };
        }
    }
    return out;
}

function buildMutableCells(resolution: number, neighborCount: number): MutableCell[] {
    const centers = icosahedralCenters(resolution);
    const cells = centers.map((center, ordinal): MutableCell => ({
        id: `hopf:ico:r${resolution}:${ordinal.toString(36)}`,
        ordinal,
        resolution,
        center: roundVec(center),
        neighborCellIds: [],
        targetCount: 0,
        sampleCount: 0,
        totalWeight: 0,
        dominantFiberKinds: [],
        anchorTargetIds: [],
        kindWeights: new Map(),
        assignments: [],
    }));
    for (const cell of cells) {
        cell.neighborCellIds = [...cells]
            .filter((other) => other !== cell)
            .sort((left, right) =>
                dot3(right.center, cell.center) - dot3(left.center, cell.center)
                || left.id.localeCompare(right.id),
            )
            .slice(0, neighborCount)
            .map((other) => other.id);
    }
    return cells;
}

function finalizeCells(cells: MutableCell[]): HopfResonanceCell[] {
    return cells.map((cell) => {
        const dominantFiberKinds = [...cell.kindWeights.entries()]
            .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
            .slice(0, 4)
            .map(([kind]) => kind);
        const anchorTargetIds = [...cell.assignments]
            .sort((left, right) =>
                right.salience - left.salience
                || right.assignmentScore - left.assignmentScore
                || left.targetId.localeCompare(right.targetId),
            )
            .slice(0, 6)
            .map((row) => row.targetId);
        return {
            id: cell.id,
            ordinal: cell.ordinal,
            resolution: cell.resolution,
            center: cell.center,
            neighborCellIds: cell.neighborCellIds,
            targetCount: cell.targetCount,
            sampleCount: cell.sampleCount,
            totalWeight: round(cell.totalWeight),
            dominantFiberKinds,
            anchorTargetIds,
        };
    });
}

function buildFibers(assignments: HopfResonanceAssignment[]): HopfResonanceFiber[] {
    const accumulators = new Map<string, FiberAccumulator>();
    for (const assignment of assignments) {
        if (assignment.role === 'document-chart') continue;
        const key = `${assignment.baseCellId}:${assignment.fiberKind}`;
        const bucket = getOrInsert(accumulators, key, () => ({
            cellId: assignment.baseCellId,
            fiberKind: assignment.fiberKind,
            assignments: [],
            weight: 0,
            sin: 0,
            cos: 0,
        }));
        bucket.assignments.push(assignment);
        bucket.weight += assignment.salience;
        bucket.sin += Math.sin(assignment.phaseRadians) * assignment.salience;
        bucket.cos += Math.cos(assignment.phaseRadians) * assignment.salience;
    }
    return [...accumulators.entries()].map(([key, bucket]) => {
        const sorted = [...bucket.assignments].sort((left, right) =>
            right.salience - left.salience
            || right.assignmentScore - left.assignmentScore
            || left.targetId.localeCompare(right.targetId),
        );
        const coherence = bucket.weight ? Math.sqrt(bucket.sin ** 2 + bucket.cos ** 2) / bucket.weight : 0;
        const meanPhase = positiveRadians(Math.atan2(bucket.sin, bucket.cos)) / TAU;
        return {
            id: `hopf:fiber:${safeId(key)}`,
            cellId: bucket.cellId,
            fiberKind: bucket.fiberKind,
            targetIds: sorted.map((row) => row.targetId),
            anchorTargetId: sorted[0]?.targetId || '',
            sampleCount: sorted.length,
            totalWeight: round(bucket.weight),
            meanPhase: round(meanPhase),
            coherence: round(coherence),
            frustration: round(1 - coherence),
        };
    }).sort((left, right) =>
        right.totalWeight - left.totalWeight
        || left.cellId.localeCompare(right.cellId)
        || left.fiberKind.localeCompare(right.fiberKind),
    );
}

function buildDocumentCharts(
    snapshot: GraphRebuildSnapshot,
    assignments: HopfResonanceAssignment[],
    cellCount: number,
): HopfDocumentChart[] {
    const byTargetId = new Map(assignments.map((row) => [row.targetId, row]));
    const noteIds = new Set([
        ...snapshot.noteIds,
        ...snapshot.embeddingTargets.map((target) => target.noteId).filter((id): id is string => Boolean(id)),
    ]);
    return [...noteIds].sort().map((noteId) => {
        const noteTarget = byTargetId.get(`embed:note:${noteId}`);
        const noteRows = assignments.filter((row) => row.noteId === noteId);
        const rootRows = noteRows.filter((row) => row.role === 'structure-root');
        const chunkRows = noteRows.filter((row) => row.fiberKind === 'chunk_sample');
        const sampleRows = noteRows.filter((row) => row.role !== 'document-chart');
        const cellWeights = aggregateDocumentCells([...(noteTarget ? [noteTarget] : []), ...sampleRows]);
        const dominantCellIds = cellWeights.slice(0, 5).map((row) => row.cellId);
        return {
            id: `hopf:doc-chart:${safeId(noteId)}`,
            noteId,
            sourceTargetId: noteTarget?.targetId,
            cellWeights,
            dominantCellIds,
            coverageEntropy: coverageEntropy(cellWeights, cellCount),
            coverageSpread: round(cellWeights.length / Math.max(1, cellCount)),
            sampleTargetIds: sampleRows.map((row) => row.targetId),
            rootTargetIds: rootRows.map((row) => row.targetId),
            chunkTargetIds: chunkRows.map((row) => row.targetId),
        };
    });
}

function aggregateDocumentCells(assignments: HopfResonanceAssignment[]): HopfDocumentCellWeight[] {
    const cells = new Map<string, { weight: number; sampleCount: number; kinds: Set<HopfResonanceFiberKind> }>();
    for (const row of assignments) {
        const multiplier =
            row.role === 'document-chart' ? 0.85 :
            row.role === 'structure-root' ? 1.15 :
            row.fiberKind === 'chunk_sample' ? 1.6 : 1;
        const bucket = getOrInsert(cells, row.baseCellId, () => ({ weight: 0, sampleCount: 0, kinds: new Set() }));
        bucket.weight += row.salience * multiplier;
        bucket.sampleCount += 1;
        bucket.kinds.add(row.fiberKind);
    }
    return [...cells.entries()]
        .map(([cellId, row]) => ({
            cellId,
            weight: round(row.weight),
            sampleCount: row.sampleCount,
            fiberKinds: [...row.kinds].sort(),
        }))
        .sort((left, right) => right.weight - left.weight || left.cellId.localeCompare(right.cellId));
}

function buildCellBraids(
    cells: HopfResonanceCell[],
    fibersByCell: Map<string, HopfResonanceFiber[]>,
): HopfResonanceBraid[] {
    const cellById = new Map(cells.map((cell) => [cell.id, cell]));
    const braids: HopfResonanceBraid[] = [];
    const seen = new Set<string>();
    for (const cell of cells) {
        if (!cell.targetCount) continue;
        for (const neighborId of cell.neighborCellIds) {
            const neighbor = cellById.get(neighborId);
            if (!neighbor?.targetCount) continue;
            const pairKey = [cell.id, neighbor.id].sort().join(':');
            if (seen.has(pairKey)) continue;
            seen.add(pairKey);
            braids.push(...fiberBraidsForCellPair(cell, neighbor, fibersByCell));
        }
    }
    return braids.sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
}

function fiberBraidsForCellPair(
    source: HopfResonanceCell,
    target: HopfResonanceCell,
    fibersByCell: Map<string, HopfResonanceFiber[]>,
): HopfResonanceBraid[] {
    const sourceFibers = fibersByCell.get(source.id) || [];
    const targetFibers = fibersByCell.get(target.id) || [];
    const targetByKind = new Map(targetFibers.map((fiber) => [fiber.fiberKind, fiber]));
    const common = sourceFibers
        .map((fiber) => [fiber, targetByKind.get(fiber.fiberKind)] as const)
        .filter((pair): pair is readonly [HopfResonanceFiber, HopfResonanceFiber] => Boolean(pair[1]));
    const pairs = common.length ? common : topFiberPair(sourceFibers, targetFibers);
    return pairs.map(([sourceFiber, targetFiber]) => fiberBraid(source, target, sourceFiber, targetFiber));
}

function topFiberPair(
    sourceFibers: HopfResonanceFiber[],
    targetFibers: HopfResonanceFiber[],
): Array<readonly [HopfResonanceFiber, HopfResonanceFiber]> {
    if (!sourceFibers.length || !targetFibers.length) return [];
    return [[sourceFibers[0], targetFibers[0]]];
}

function fiberBraid(
    source: HopfResonanceCell,
    target: HopfResonanceCell,
    sourceFiber: HopfResonanceFiber,
    targetFiber: HopfResonanceFiber,
): HopfResonanceBraid {
    const angularAffinity = clamp01((dot3(source.center, target.center) + 1) * 0.5);
    const phaseAffinity = 1 - circularDistance(sourceFiber.meanPhase, targetFiber.meanPhase);
    const coherence = (sourceFiber.coherence + targetFiber.coherence) * 0.5;
    const score = round(angularAffinity * 0.45 + phaseAffinity * 0.28 + coherence * 0.27);
    return {
        id: `hopf:braid:${safeId(sourceFiber.id)}:${safeId(targetFiber.id)}`,
        kind: sourceFiber.fiberKind === targetFiber.fiberKind ? 'fiber_neighbor' : 'cell_neighbor',
        sourceCellId: source.id,
        targetCellId: target.id,
        sourceFiberId: sourceFiber.id,
        targetFiberId: targetFiber.id,
        sourceTargetCount: sourceFiber.sampleCount,
        targetTargetCount: targetFiber.sampleCount,
        representativeTargetIds: [
            sourceFiber.anchorTargetId,
            targetFiber.anchorTargetId,
        ].filter(Boolean),
        score,
        summary: true,
        reason: [
            'neighboring_icosahedral_cells',
            sourceFiber.fiberKind === targetFiber.fiberKind ? 'shared_fiber_kind' : 'dominant_fiber_bridge',
            'no_topology_mutation',
        ],
    };
}

function groupFibersByCell(fibers: HopfResonanceFiber[]): Map<string, HopfResonanceFiber[]> {
    const groups = new Map<string, HopfResonanceFiber[]>();
    for (const fiber of fibers) {
        const bucket = getOrInsert(groups, fiber.cellId, () => []);
        bucket.push(fiber);
    }
    for (const bucket of groups.values()) {
        bucket.sort((left, right) => right.totalWeight - left.totalWeight || left.fiberKind.localeCompare(right.fiberKind));
    }
    return groups;
}

function rankCells(direction: Vec3Tuple, cells: MutableCell[], count: number): MutableCell[] {
    return [...cells]
        .sort((left, right) =>
            dot3(right.center, direction) - dot3(left.center, direction)
            || left.id.localeCompare(right.id),
        )
        .slice(0, count);
}

function signatureDirection(signature: SparseEmbeddingSignature, seedText: string): Vec3Tuple {
    let x = 0;
    let y = 0;
    let z = 0;
    for (let i = 0; i < signature.indexes.length; i += 1) {
        const seed = mix32(signature.indexes[i] + 0x9e3779b9);
        const value = signature.values[i];
        x += signedUnit(seed ^ 0x8da6b343) * value;
        y += signedUnit(seed ^ 0xd8163841) * value;
        z += signedUnit(seed ^ 0xcb1ab31f) * value;
    }
    const vector = normalize3([x, y, z]);
    return norm3(vector) ? vector : fallbackDirection(seedText);
}

function targetFiberKind(target: GraphRebuildEmbeddingTarget): HopfResonanceFiberKind {
    const kind = normalizeKind(target.kind);
    const lane = normalizeKind(target.lane || '');
    if (kind === 'note') return 'document_chart';
    if (kind === 'structureroot') return 'structure_root';
    if (kind === 'chunk') return 'chunk_sample';
    if (kind === 'entity') return 'entity_sample';
    if (kind === 'anchor') return 'evidence_sample';
    if (kind === 'event') return 'event_sample';
    if (kind === 'temporalfact' || lane === 'temporalfact' || lane === 'temporal_fact') return 'temporal_sample';
    if (kind === 'causalfact' || lane === 'causalfact' || lane === 'causal_fact') return 'causal_sample';
    if (kind === 'memorystate' || lane === 'memory_state') return 'memory_sample';
    if (kind === 'graphfact' || lane === 'relationship_fact' || lane === 'cooccurrence_weak') return 'fact_sample';
    return 'support_sample';
}

function assignmentRole(
    target: GraphRebuildEmbeddingTarget,
    fiberKind: HopfResonanceFiberKind,
): HopfResonanceAssignmentRole {
    if (fiberKind === 'document_chart') return 'document-chart';
    if (fiberKind === 'structure_root' || normalizeKind(target.structuralRole || '') === 'root') return 'structure-root';
    if (fiberKind === 'evidence_sample') return 'evidence-support';
    return 'fiber-sample';
}

function targetSalience(target: GraphRebuildEmbeddingTarget): number {
    const kind = targetFiberKind(target);
    const evidence = Math.min(10, target.evidenceIds?.length || 0);
    const textLength = Math.min(1, Math.log1p((target.text || '').length) / 9);
    const base =
        kind === 'document_chart' ? 1.35 :
        kind === 'structure_root' ? 1.2 :
        kind === 'chunk_sample' ? 1.15 :
        kind === 'entity_sample' ? 1.1 :
        kind === 'causal_sample' || kind === 'temporal_sample' ? 1.05 : 0.9;
    return round(base + evidence * 0.08 + textLength * 0.35);
}

function coverageEntropy(rows: HopfDocumentCellWeight[], cellCount: number): number {
    const total = rows.reduce((sum, row) => sum + row.weight, 0);
    if (!total || cellCount <= 1) return 0;
    let entropy = 0;
    for (const row of rows) {
        const p = row.weight / total;
        entropy -= p > 0 ? p * Math.log(p) : 0;
    }
    return round(entropy / Math.log(cellCount));
}

function circularDistance(left: number, right: number): number {
    const delta = Math.abs(left - right) % 1;
    return Math.min(delta, 1 - delta) * 2;
}

function circularPhaseBlend(left: number, right: number, blend: number): number {
    const delta = ((right - left + 1.5) % 1) - 0.5;
    return round(positivePhase(left + delta * clamp01(blend)));
}

function phaseSpreadWeight(row: HopfResonanceAssignment, count: number): number {
    const pressure = clamp01((count - 4) / 24);
    if (row.fiberKind === 'temporal_sample' || row.fiberKind === 'causal_sample') return 0.48 + pressure * 0.34;
    if (row.role === 'document-chart') return 0.12 + pressure * 0.08;
    if (row.role === 'structure-root') return 0.22 + pressure * 0.14;
    return 0.34 + pressure * 0.28;
}

function strandSortKey(row: HopfResonanceAssignment): string {
    return [
        row.noteId || '',
        row.chunkId || '',
        row.role,
        row.targetKind,
        row.label,
        row.targetId,
    ].join('\u0001');
}

function positivePhase(value: number): number {
    return ((value % 1) + 1) % 1;
}

function normalizeKind(value: string | undefined): string {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function getOrInsert<K, V>(map: Map<K, V>, key: K, build: () => V): V {
    let value = map.get(key);
    if (value === undefined) {
        value = build();
        map.set(key, value);
    }
    return value;
}

function safeId(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'x';
}
