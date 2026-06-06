import type {
    GraphDiscourseSpineBridge,
    GraphDiscourseSpineBridgeKind,
    GraphDiscourseSpineBridgeStatus,
    GraphDiscourseSpineCluster,
    GraphDiscourseSpineClusterKind,
    GraphDiscourseSpineCounters,
    GraphDiscourseSpineLabel,
    GraphDiscourseSpineLabelKind,
    GraphDiscourseSpineReceipt,
    GraphDiscourseSpineScoringBundle,
    GraphDiscourseSpineTargetKind,
    GraphRebuildChunk,
    GraphRebuildEmbeddingTarget,
    GraphRebuildEntityAnchor,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import { sparseCosine, sparseEmbeddingSignature } from './graph-rebuild-embedding-signatures';

interface SpineTarget {
    target: GraphRebuildEmbeddingTarget;
    kind: GraphDiscourseSpineTargetKind;
    text: string;
    noteId?: string;
    chunkId?: string;
    ordinal: number;
    entityIds: string[];
    entitySurfaces: Map<string, string[]>;
    labels: GraphDiscourseSpineLabel[];
}

export interface GraphDiscourseSpineTargetSummary {
    targetId: string;
    sourceId: string;
    kind: GraphDiscourseSpineTargetKind;
    label: string;
    noteId?: string;
    chunkId?: string;
    parentTargetIds: string[];
    entityIds: string[];
    labelIds: string[];
}

export interface GraphDiscourseSpineSummary {
    schemaVersion: 'phoenix-discourse-spine/v1';
    generatedAt: number;
    sourceSnapshotId: string;
    implementationMode: 'deterministic_registry';
    invariant: 'wormholes_are_proposals_not_edges';
    targets: GraphDiscourseSpineTargetSummary[];
    labels: GraphDiscourseSpineLabel[];
    clusters: GraphDiscourseSpineCluster[];
    bridges: GraphDiscourseSpineBridge[];
    receipts: GraphDiscourseSpineReceipt[];
    compactBridgeLedger: {
        scopeId: string;
        builtAt: number;
        rowCount: number;
        rows: Array<{
            id: string;
            kind: GraphDiscourseSpineBridgeKind;
            status: GraphDiscourseSpineBridgeStatus;
            score: number;
            evidence: number;
            sharedLabels: number;
            sharedEntities: number;
        }>;
    };
    counters: GraphDiscourseSpineCounters;
}

const MAX_TARGETS = 160;
const MAX_BRIDGES = 96;
const RESONANCE_THRESHOLD = 0.34;
const RESOLUTION_THRESHOLD = 0.36;

export function buildGraphDiscourseSpineSummary(
    snapshot: GraphRebuildSnapshot,
    generatedAt = snapshot.builtAt,
): GraphDiscourseSpineSummary {
    const anchorsByNote = groupAnchors(snapshot.entityAnchors, (anchor) => anchor.noteId);
    const anchorsByChunk = groupAnchors(snapshot.entityAnchors, (anchor) => anchor.chunkId || '');
    const chunks = new Map(snapshot.chunks.map((chunk) => [chunk.id, chunk]));
    const targets = selectSpineTargets(snapshot.embeddingTargets)
        .map((target) => spineTarget(target, chunks.get(target.chunkId || ''), anchorsFor(target, anchorsByNote, anchorsByChunk)))
        .filter((target): target is SpineTarget => Boolean(target));
    const labels = buildLabels(targets, generatedAt);
    const clusters = buildClusters(targets, generatedAt);
    const bridges = buildBridges(snapshot, targets, generatedAt);
    const receipts = [
        ...labels.map(receiptForLabel),
        ...clusters.map(receiptForCluster),
        ...bridges.map(receiptForBridge),
    ];
    return {
        schemaVersion: 'phoenix-discourse-spine/v1',
        generatedAt,
        sourceSnapshotId: snapshot.id,
        implementationMode: 'deterministic_registry',
        invariant: 'wormholes_are_proposals_not_edges',
        targets: targets.map(targetSummary),
        labels,
        clusters,
        bridges,
        receipts,
        compactBridgeLedger: compactBridgeLedger(snapshot, bridges),
        counters: counters(targets, labels, clusters, bridges, receipts),
    };
}

function selectSpineTargets(targets: GraphRebuildEmbeddingTarget[]): GraphRebuildEmbeddingTarget[] {
    const spine = targets
        .filter((target) => targetKind(target))
        .sort((left, right) => targetRank(left) - targetRank(right) || left.id.localeCompare(right.id));
    if (spine.length <= MAX_TARGETS) return spine;
    const pinned = spine.filter((target) => targetKind(target) !== 'chunk');
    const chunks = spine.filter((target) => targetKind(target) === 'chunk');
    return [...pinned, ...spreadSample(chunks, Math.max(0, MAX_TARGETS - pinned.length))].slice(0, MAX_TARGETS);
}

function spineTarget(
    target: GraphRebuildEmbeddingTarget,
    chunk: GraphRebuildChunk | undefined,
    anchors: GraphRebuildEntityAnchor[],
): SpineTarget | null {
    const kind = targetKind(target);
    if (!kind) return null;
    return {
        target,
        kind,
        text: `${target.label}\n${target.text}`.toLowerCase(),
        noteId: target.noteId,
        chunkId: target.chunkId,
        ordinal: chunk?.ordinal ?? -1,
        entityIds: unique(anchors.map((anchor) => anchor.entityId)),
        entitySurfaces: entitySurfaceMap(anchors),
        labels: [],
    };
}

function buildLabels(targets: SpineTarget[], generatedAt: number): GraphDiscourseSpineLabel[] {
    const labels: GraphDiscourseSpineLabel[] = [];
    for (const target of targets) {
        const drafts = [
            labelDraft('domain', domainLabel(target)),
            labelDraft('story_aspect', aspectLabel(target)),
            labelDraft('narrative_function', functionLabel(target)),
            labelDraft('evidence_role', evidenceLabel(target)),
            labelDraft('temporal_scope', temporalLabel(target)),
            labelDraft('tone_mood', toneLabel(target)),
            labelDraft('world_context', worldLabel(target)),
        ];
        for (const draft of drafts) {
            const id = `discourse-label:${draft.kind}:${slug(`${target.target.id}:${draft.value}`)}`;
            const label: GraphDiscourseSpineLabel = {
                id,
                targetId: target.target.id,
                targetKind: target.kind,
                labelKind: draft.kind,
                value: draft.value,
                score: draft.score,
                cues: draft.cues.slice(0, 8),
                rationale: draft.rationale,
                receiptId: `discourse-label-receipt:${slug(id)}`,
            };
            target.labels.push(label);
            labels.push(label);
        }
    }
    labels.sort((left, right) => left.targetId.localeCompare(right.targetId) || left.labelKind.localeCompare(right.labelKind));
    void generatedAt;
    return labels;
}

function buildClusters(targets: SpineTarget[], generatedAt: number): GraphDiscourseSpineCluster[] {
    const clusters: GraphDiscourseSpineCluster[] = [];
    addLabelClusters(clusters, 'domain_region', targets, 'domain');
    addLabelClusters(clusters, 'aspect_region', targets.filter((target) => target.kind === 'chunk'), 'story_aspect');
    for (const [noteId, values] of groupBy(targets.filter((target) => target.noteId), (target) => target.noteId || '')) {
        addCluster(clusters, 'document_family', `document:${noteId}`, values, ['document root, note, and chunk family']);
    }
    void generatedAt;
    return clusters.slice(0, 72);
}

function buildBridges(snapshot: GraphRebuildSnapshot, targets: SpineTarget[], generatedAt: number): GraphDiscourseSpineBridge[] {
    const dims = Math.max(32, snapshot.embeddingProfile?.selectedDimensions || 384);
    const signatures = targets.map((target) => sparseEmbeddingSignature(target.target, dims));
    const bridges: GraphDiscourseSpineBridge[] = [];
    for (let i = 0; i < targets.length; i += 1) {
        if (targets[i].kind === 'document_root') continue;
        for (let j = i + 1; j < targets.length; j += 1) {
            if (targets[j].kind === 'document_root') continue;
            const semantic = round(sparseCosine(signatures[i], signatures[j]));
            const resonance = bridgeFor('resonance', targets[i], targets[j], semantic, generatedAt);
            if (resonance) bridges.push(resonance);
            const resolution = bridgeFor('resolution', targets[i], targets[j], semantic, generatedAt);
            if (resolution) bridges.push(resolution);
        }
    }
    return bridges
        .sort((left, right) => right.scoringBundle.finalScore - left.scoringBundle.finalScore || left.id.localeCompare(right.id))
        .slice(0, MAX_BRIDGES);
}

function bridgeFor(
    kind: GraphDiscourseSpineBridgeKind,
    left: SpineTarget,
    right: SpineTarget,
    semanticScore: number,
    generatedAt: number,
): GraphDiscourseSpineBridge | null {
    const sharedLabelIds = sharedLabels(left, right).map((label) => label.id);
    const sharedEntities = intersection(left.entityIds, right.entityIds);
    const scoringBundle = scoreBridge(kind, left, right, semanticScore, sharedLabelIds.length, sharedEntities);
    const threshold = kind === 'resonance' ? RESONANCE_THRESHOLD : RESOLUTION_THRESHOLD;
    if (kind === 'resonance' && scoringBundle.finalScore < threshold) return null;
    if (kind === 'resolution' && (!sharedEntities.length || scoringBundle.finalScore < threshold)) return null;
    const status: GraphDiscourseSpineBridgeStatus =
        scoringBundle.finalScore >= threshold + 0.12 ? 'proposed' :
        scoringBundle.finalScore >= threshold ? 'deferred' : 'rejected';
    const id = `discourse-bridge:${kind}:${slug(`${left.target.id}:${right.target.id}`)}`;
    return {
        id,
        kind,
        status,
        sourceTargetId: left.target.id,
        targetTargetId: right.target.id,
        sourceKind: left.kind,
        targetKind: right.kind,
        label: bridgeLabel(kind, left, right),
        evidenceTargetIds: [left.target.id, right.target.id],
        sharedLabelIds,
        sharedEntityIds: sharedEntities,
        scoringBundle,
        rationale: bridgeRationale(kind, scoringBundle, sharedLabelIds.length, sharedEntities.length),
        adjudicationState: 'proposed',
        mutationAllowed: false,
        receiptId: `discourse-bridge-receipt:${slug(id)}`,
        createdAt: generatedAt,
    };
}

function scoreBridge(
    kind: GraphDiscourseSpineBridgeKind,
    left: SpineTarget,
    right: SpineTarget,
    semanticScore: number,
    sharedLabelCount: number,
    sharedEntities: string[],
): GraphDiscourseSpineScoringBundle {
    const labelAgreement = round(Math.min(1, sharedLabelCount / 5));
    const entityOverlap = round(jaccard(left.entityIds, right.entityIds));
    const distanceScore = round(distanceSignal(left, right));
    const corefPressure = round(corefSignal(left, right, sharedEntities));
    const parts = kind === 'resonance'
        ? [
            part('semantic', semanticScore, 0.56),
            part('label_agreement', labelAgreement, 0.24),
            part('distance', distanceScore, 0.14),
            part('non_entity_novelty', round(1 - entityOverlap), 0.06),
        ]
        : [
            part('entity_overlap', entityOverlap, 0.42),
            part('coref_pressure', corefPressure, 0.24),
            part('semantic', semanticScore, 0.18),
            part('distance', distanceScore, 0.1),
            part('label_agreement', labelAgreement, 0.06),
        ];
    return {
        semanticScore,
        labelAgreement,
        entityOverlap,
        distanceScore,
        corefPressure,
        finalScore: round(parts.reduce((sum, row) => sum + row.score * row.weight, 0)),
        scoreParts: parts,
    };
}

function domainLabel(target: SpineTarget) {
    return bestCue(target, 'general_discourse', [
        cue('story_world', ['scene', 'dialogue', 'character', 'chapter', 'story', 'world', 'king', 'battle']),
        cue('technical_system', ['graph', 'compiler', 'model', 'pipeline', 'rust', 'angular', 'embedding']),
        cue('research_analysis', ['paper', 'study', 'dataset', 'evaluation', 'method', 'retrieval']),
        cue('temporal_causal', ['before', 'after', 'because', 'cause', 'timeline', 'calendar']),
        cue('evidence_archive', ['evidence', 'quote', 'source', 'claim', 'citation', 'reported']),
    ]);
}

function aspectLabel(target: SpineTarget) {
    return bestCue(target, 'context', [
        cue('identity', ['alias', 'identity', 'name', 'coref', 'same entity']),
        cue('relationship', ['with', 'beside', 'against', 'between', 'ally', 'enemy']),
        cue('conflict', ['war', 'fight', 'threat', 'refused', 'blocked', 'danger']),
        cue('worldbuilding', ['city', 'realm', 'calendar', 'rank', 'guild', 'place']),
        cue('memory', ['remembered', 'memory', 'again', 'echo', 'past']),
        cue('motion', ['went', 'walked', 'ran', 'entered', 'left', 'moved']),
    ]);
}

function functionLabel(target: SpineTarget) {
    if (target.kind === 'document_root') return fixed('document_hierarchy_root', 0.82, ['structure_root']);
    if (target.kind === 'document') return fixed('source_document', 0.78, ['note_target']);
    const text = target.text;
    if (text.includes('chunk_role:dialogue') || /["“”]/.test(text)) return fixed('dialogue_exchange', 0.78, ['dialogue']);
    if (text.includes('chunk_role:evidence_block')) return fixed('evidence_support', 0.78, ['evidence_block']);
    if (text.includes('chunk_role:authority_chain')) return fixed('authority_claim', 0.76, ['authority_chain']);
    if (text.includes('chunk_role:transition')) return fixed('transition', 0.72, ['transition']);
    return bestCue(target, 'semantic_cell', [
        cue('scene_motion', ['stood', 'walked', 'opened', 'entered', 'turned']),
        cue('exposition', ['was', 'were', 'known', 'history', 'explained']),
        cue('claim_packet', ['said', 'claimed', 'reported', 'warned']),
    ]);
}

function evidenceLabel(target: SpineTarget) {
    return bestCue(target, 'context_packet', [
        cue('supporting_evidence', ['evidence', 'quote', 'source', 'citation', 'reported']),
        cue('claim_bundle', ['said', 'claimed', 'warned', 'believed', 'because']),
        cue('primary_scene', ['stood', 'looked', 'held', 'walked', 'answered']),
    ]);
}

function temporalLabel(target: SpineTarget) {
    return bestCue(target, 'floating_time', [
        cue('anchored_time', ['calendar', 'date', 'year', 'month', 'day', 'timeline']),
        cue('sequence', ['before', 'after', 'then', 'later', 'again']),
        cue('causal_time', ['because', 'therefore', 'caused', 'so that']),
    ]);
}

function toneLabel(target: SpineTarget) {
    return bestCue(target, 'neutral', [
        cue('conflict_pressure', ['threat', 'war', 'refused', 'danger', 'blocked']),
        cue('reflective', ['remembered', 'wondered', 'quiet', 'thought']),
        cue('investigative', ['why', 'evidence', 'source', 'claim', 'reported']),
        cue('urgent', ['now', 'must', 'immediately', 'warning', 'crisis']),
    ]);
}

function worldLabel(target: SpineTarget) {
    if (target.target.folderLabel) return fixed(`folder:${normalizeValue(target.target.folderLabel)}`, 0.74, ['folder']);
    if (target.target.noteId) return fixed(`note:${normalizeValue(target.target.noteId)}`, 0.62, ['note']);
    return fixed('scope_local', 0.52, ['scope']);
}

function bestCue(target: SpineTarget, fallback: string, rows: Array<{ value: string; cues: string[] }>) {
    let best = { value: fallback, cues: [] as string[], score: 0.48 };
    for (const row of rows) {
        const hits = row.cues.filter((cueValue) => target.text.includes(cueValue));
        const score = round(0.52 + Math.min(0.34, hits.length * 0.085));
        if (hits.length && score > best.score) best = { value: row.value, cues: hits, score };
    }
    return { ...best, rationale: best.cues.length ? `matched cues:${best.cues.join(',')}` : 'deterministic fallback label' };
}

function fixed(value: string, score: number, cues: string[]) {
    return { value, cues, score, rationale: `structural ${value}` };
}

function labelDraft(kind: GraphDiscourseSpineLabelKind, row: ReturnType<typeof fixed>) {
    return { kind, ...row };
}

function cue(value: string, cues: string[]) {
    return { value, cues };
}

function addLabelClusters(
    out: GraphDiscourseSpineCluster[],
    kind: GraphDiscourseSpineClusterKind,
    targets: SpineTarget[],
    labelKind: GraphDiscourseSpineLabelKind,
): void {
    for (const [value, group] of groupBy(targets, (target) => target.labels.find((label) => label.labelKind === labelKind)?.value || 'unknown')) {
        if (group.length < 2) continue;
        addCluster(out, kind, value, group, [`shared_${labelKind}:${value}`]);
    }
}

function addCluster(
    out: GraphDiscourseSpineCluster[],
    kind: GraphDiscourseSpineClusterKind,
    label: string,
    targets: SpineTarget[],
    rationale: string[],
): void {
    const targetIds = unique(targets.map((target) => target.target.id));
    const id = `discourse-cluster:${kind}:${slug(label)}`;
    out.push({
        id,
        kind,
        label,
        targetIds,
        medoidTargetId: targets.sort((left, right) => targetScore(right) - targetScore(left))[0]?.target.id || targetIds[0],
        score: round(Math.min(1, 0.42 + Math.min(0.42, targetIds.length * 0.045))),
        rationale,
        receiptId: `discourse-cluster-receipt:${slug(id)}`,
    });
}

function targetKind(target: GraphRebuildEmbeddingTarget): GraphDiscourseSpineTargetKind | null {
    const kind = normalizeKind(target.kind);
    if (kind === 'note') return 'document';
    if (kind === 'chunk') return 'chunk';
    if (kind === 'structureroot' && /document-structure/i.test(target.sourceId)) return 'document_root';
    return null;
}

function anchorsFor(
    target: GraphRebuildEmbeddingTarget,
    byNote: Map<string, GraphRebuildEntityAnchor[]>,
    byChunk: Map<string, GraphRebuildEntityAnchor[]>,
): GraphRebuildEntityAnchor[] {
    return target.chunkId ? byChunk.get(target.chunkId) || [] : target.noteId ? byNote.get(target.noteId) || [] : [];
}

function entitySurfaceMap(anchors: GraphRebuildEntityAnchor[]): Map<string, string[]> {
    const map = new Map<string, string[]>();
    for (const anchor of anchors) map.set(anchor.entityId, unique([...(map.get(anchor.entityId) || []), normalizeValue(anchor.surface)]));
    return map;
}

function sharedLabels(left: SpineTarget, right: SpineTarget): GraphDiscourseSpineLabel[] {
    const rightValues = new Set(right.labels.map((label) => `${label.labelKind}:${label.value}`));
    return left.labels.filter((label) => rightValues.has(`${label.labelKind}:${label.value}`));
}

function distanceSignal(left: SpineTarget, right: SpineTarget): number {
    if (left.noteId && right.noteId && left.noteId !== right.noteId) return 1;
    if (left.ordinal >= 0 && right.ordinal >= 0) return Math.min(1, Math.abs(left.ordinal - right.ordinal) / 12);
    return left.target.id === right.target.id ? 0 : 0.25;
}

function corefSignal(left: SpineTarget, right: SpineTarget, shared: string[]): number {
    if (!shared.length) return 0;
    let forms = 0;
    for (const entityId of shared) {
        forms += new Set([...(left.entitySurfaces.get(entityId) || []), ...(right.entitySurfaces.get(entityId) || [])]).size;
    }
    return Math.min(1, 0.32 + forms * 0.17);
}

function bridgeLabel(kind: GraphDiscourseSpineBridgeKind, left: SpineTarget, right: SpineTarget): string {
    const relation = kind === 'resonance' ? 'resonates with' : 'may resolve across';
    return `${left.target.label} ${relation} ${right.target.label}`;
}

function bridgeRationale(kind: GraphDiscourseSpineBridgeKind, score: GraphDiscourseSpineScoringBundle, sharedLabels: number, sharedEntities: number): string[] {
    return [
        kind === 'resonance' ? 'semantic wormhole proposal' : 'cross-document resolver proposal',
        `final:${score.finalScore.toFixed(3)}`,
        `semantic:${score.semanticScore.toFixed(3)}`,
        `shared_labels:${sharedLabels}`,
        `shared_entities:${sharedEntities}`,
        'no topology mutation; adjudication must accept before graph promotion',
    ];
}

function targetSummary(target: SpineTarget): GraphDiscourseSpineTargetSummary {
    return {
        targetId: target.target.id,
        sourceId: target.target.sourceId,
        kind: target.kind,
        label: target.target.label,
        noteId: target.noteId,
        chunkId: target.chunkId,
        parentTargetIds: target.target.parentIds || [],
        entityIds: target.entityIds,
        labelIds: target.labels.map((label) => label.id),
    };
}

function receiptForLabel(label: GraphDiscourseSpineLabel): GraphDiscourseSpineReceipt {
    return {
        id: label.receiptId,
        labelId: label.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_spine_no_topology_commit',
        evidenceTargetIds: [label.targetId],
        undoHint: 'drop this discourse spine label row',
        detail: `${label.labelKind}:${label.value} on ${label.targetKind}`,
    };
}

function receiptForCluster(cluster: GraphDiscourseSpineCluster): GraphDiscourseSpineReceipt {
    return {
        id: cluster.receiptId,
        clusterId: cluster.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_spine_no_topology_commit',
        evidenceTargetIds: cluster.targetIds.slice(0, 16),
        undoHint: 'drop this discourse spine cluster row',
        detail: `${cluster.kind}:${cluster.label} with ${cluster.targetIds.length} targets`,
    };
}

function receiptForBridge(bridge: GraphDiscourseSpineBridge): GraphDiscourseSpineReceipt {
    return {
        id: bridge.receiptId,
        bridgeId: bridge.id,
        reversible: true,
        mutationAllowed: false,
        invariant: 'discourse_spine_no_topology_commit',
        evidenceTargetIds: bridge.evidenceTargetIds,
        undoHint: 'drop this bridge proposal; no graph edge exists to remove',
        detail: `${bridge.kind} ${bridge.status} at ${Math.round(bridge.scoringBundle.finalScore * 100)}%`,
    };
}

function compactBridgeLedger(snapshot: GraphRebuildSnapshot, bridges: GraphDiscourseSpineBridge[]): GraphDiscourseSpineSummary['compactBridgeLedger'] {
    return {
        scopeId: snapshot.scopeId,
        builtAt: snapshot.builtAt,
        rowCount: bridges.length,
        rows: bridges.map((bridge) => ({
            id: bridge.id,
            kind: bridge.kind,
            status: bridge.status,
            score: bridge.scoringBundle.finalScore,
            evidence: bridge.evidenceTargetIds.length,
            sharedLabels: bridge.sharedLabelIds.length,
            sharedEntities: bridge.sharedEntityIds.length,
        })),
    };
}

function counters(
    targets: SpineTarget[],
    labels: GraphDiscourseSpineLabel[],
    clusters: GraphDiscourseSpineCluster[],
    bridges: GraphDiscourseSpineBridge[],
    receipts: GraphDiscourseSpineReceipt[],
): GraphDiscourseSpineCounters {
    return {
        targetCount: targets.length,
        documentRoots: targets.filter((target) => target.kind === 'document_root').length,
        documents: targets.filter((target) => target.kind === 'document').length,
        chunks: targets.filter((target) => target.kind === 'chunk').length,
        labelCount: labels.length,
        clusterCount: clusters.length,
        bridgeCount: bridges.length,
        resonanceCandidates: bridges.filter((bridge) => bridge.kind === 'resonance').length,
        resolutionCandidates: bridges.filter((bridge) => bridge.kind === 'resolution').length,
        proposedBridges: bridges.filter((bridge) => bridge.status === 'proposed').length,
        deferredBridges: bridges.filter((bridge) => bridge.status === 'deferred').length,
        rejectedBridges: bridges.filter((bridge) => bridge.status === 'rejected').length,
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        mutationAllowedCount: receipts.filter((receipt) => receipt.mutationAllowed).length,
        byLabelKind: countBy(labels, (label) => label.labelKind),
        byClusterKind: countBy(clusters, (cluster) => cluster.kind),
        byBridgeKind: countBy(bridges, (bridge) => bridge.kind),
    };
}

function targetRank(target: GraphRebuildEmbeddingTarget): number {
    const kind = targetKind(target);
    if (kind === 'document_root') return 0;
    if (kind === 'document') return 1;
    return 10 + Number(target.chunkId?.match(/(\d+)$/)?.[1] || 0);
}

function targetScore(target: SpineTarget): number {
    return target.entityIds.length * 20 + target.text.length * 0.01 + (target.kind === 'document' ? 8 : 0);
}

function part(id: string, score: number, weight: number) {
    return { id, score: round(score), weight };
}

function groupAnchors(anchors: GraphRebuildEntityAnchor[], keyFn: (anchor: GraphRebuildEntityAnchor) => string): Map<string, GraphRebuildEntityAnchor[]> {
    const map = new Map<string, GraphRebuildEntityAnchor[]>();
    for (const anchor of anchors) {
        const key = keyFn(anchor);
        if (!key) continue;
        map.set(key, [...(map.get(key) || []), anchor]);
    }
    return map;
}

function groupBy<T>(values: T[], keyFn: (value: T) => string): Map<string, T[]> {
    const map = new Map<string, T[]>();
    for (const value of values) {
        const key = keyFn(value);
        map.set(key, [...(map.get(key) || []), value]);
    }
    return map;
}

function spreadSample<T>(values: T[], limit: number): T[] {
    if (limit <= 0) return [];
    if (values.length <= limit) return values;
    const out: T[] = [];
    const step = (values.length - 1) / Math.max(1, limit - 1);
    for (let index = 0; index < limit; index += 1) out.push(values[Math.round(index * step)]);
    return out;
}

function intersection(left: string[], right: string[]): string[] {
    const set = new Set(right);
    return left.filter((value) => set.has(value));
}

function jaccard(left: string[], right: string[]): number {
    const union = unique([...left, ...right]);
    return union.length ? intersection(left, right).length / union.length : 0;
}

function unique(values: string[]): string[] {
    return [...new Set(values.filter(Boolean))].sort();
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const map = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        map.set(key, (map.get(key) || 0) + 1);
    }
    return Object.fromEntries([...map.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function normalizeKind(value: string): string {
    return String(value || '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase().replace(/[-_\s]+/g, '');
}

function normalizeValue(value: string): string {
    return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'unknown';
}

function round(value: number): number {
    return Math.round(Math.max(0, Math.min(1, value)) * 1000) / 1000;
}

function slug(value: string): string {
    const normalized = value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '') || 'x';
    return `${normalized.slice(0, 96)}:${stableHash(value)}`;
}

function stableHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
}
