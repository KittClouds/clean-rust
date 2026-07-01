import type { AtlasManifoldMode } from '../services/manifold-atlas.types';
import type { GraphAtlasFamily } from './graph-atlas-packet';
import type {
    GraphRebuildEmbeddingTarget,
    GraphRebuildRelationship,
    GraphRebuildSnapshot,
} from './graph-rebuild-snapshot';
import { buildGraphCanvasInventory } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-canvas-inventory';
import { buildGraphRebuildEmbeddingAtlas } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-rebuild-embedding-atlas';
import type { GalaxyRenderableNode } from '../components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/graph-galaxy-engine';

const STYLE_LAB_KEYS = [
    'character',
    'npc',
    'creature',
    'location',
    'network',
    'narrative',
    'arc',
    'act',
    'chapter',
    'scene',
    'beat',
    'event',
    'timeline',
    'item',
    'concept',
    'cooccurrence',
    'observation',
    'communication',
    'authority',
    'approval',
    'relationship',
    'family',
    'intimacy',
    'transfer',
    'causal',
    'temporal',
    'scenePresence',
    'document',
    'chunk',
    'anchor',
    'graphFact',
    'eventNode',
    'temporalFact',
    'causalFact',
    'memoryState',
    'decisionState',
    'rankStatus',
    'serviceContext',
    'affiliationContext',
    'familyContext',
] as const;

const MANIFOLDS: AtlasManifoldMode[] = ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'];

const CURATED_EMBED_DROP_KINDS = new Set([
    'sentence',
    'text-sentence',
    'document-sentence',
    'paragraph',
    'text-paragraph',
    'document-paragraph',
    'paragraph-group',
    'section',
    'region',
    'mention',
    'entity-mention',
    'raw-mention',
    'occurrence',
    'raw-occurrence',
    'alias-patch',
    'linker-vote',
    'receipt',
    'debug',
]);

const CURATED_DOCUMENT_UNIT_TOKENS = [
    'leaf',
    'claim',
    'actionblock',
    'action',
    'contrast',
    'looked',
    'glanced',
    'evidence',
    'decision',
];

const SENTENCE_PARAGRAPH_TAXONOMY_TOKENS = [
    'paragraph',
    'paragraphgroup',
    'sentence',
    'textsentence',
    'documentsentence',
    'textparagraph',
    'documentparagraph',
];

export interface GraphAtlasTaxonomyAudit {
    schemaVersion: 'phoenix-atlas-taxonomy-audit/v1';
    snapshot: {
        id: string;
        scopeId: string;
        builtAt: number;
        atlasPacket: boolean;
    };
    styleLabKeys: string[];
    boundaries: GraphAtlasTaxonomyBoundary[];
    styleKeyMatrix: GraphAtlasStyleKeyRow[];
    lossSignals: GraphAtlasTaxonomyLossSignal[];
    warnings: string[];
    contractChecks: GraphAtlasTaxonomyCheck[];
    embedExclusions: GraphAtlasEmbedExclusion[];
}

export interface GraphAtlasTaxonomyBoundary {
    name: string;
    total: number;
    missingStyleKey: number;
    byStyleKey: CountRow[];
    byFamily: CountRow[];
    byKind: CountRow[];
    byLane: CountRow[];
    byStatus: CountRow[];
    byStructuralRole: CountRow[];
    byDocumentUnitKind: CountRow[];
    byStateContextKind: CountRow[];
    byEntityKind: CountRow[];
    samplesByStyleKey: Record<string, string[]>;
}

export interface GraphAtlasStyleKeyRow {
    styleKey: string;
    snapshotRaw: number;
    embeddingTargets: number;
    atlasObjects: number;
    atlasTargets: number;
    graphInventory: number;
    embedHybrid: number;
    embedSiegel: number;
}

export interface GraphAtlasTaxonomyLossSignal {
    styleKey: string;
    from: string;
    to: string;
    fromCount: number;
    toCount: number;
    delta: number;
}

export interface GraphAtlasTaxonomyCheck {
    name: string;
    status: 'pass' | 'warn' | 'fail';
    message: string;
    details?: Record<string, number | string>;
}

export interface GraphAtlasEmbedExclusion {
    styleKey: string;
    reason: string;
    count: number;
    samples: string[];
}

interface AuditRecord {
    id: string;
    label: string;
    family: string;
    kind: string;
    styleKey: string;
    lane: string;
    status: string;
    structuralRole: string;
    documentUnitKind: string;
    stateContextKind: string;
    entityKind: string;
}

type CountRow = { key: string; count: number };

export function buildGraphAtlasTaxonomyAudit(snapshot: GraphRebuildSnapshot): GraphAtlasTaxonomyAudit {
    const boundaries = [
        boundary('snapshot.raw', snapshotRawRecords(snapshot)),
        boundary('snapshot.embeddingTargets', snapshot.embeddingTargets.map(embeddingTargetRecord)),
        boundary('atlasPacket.objects', (snapshot.atlasPacket?.objects || []).map((object) => ({
            id: object.id,
            label: object.label,
            family: object.family,
            kind: object.kind,
            styleKey: object.styleKey || object.stateContextKind || '',
            lane: object.lane || '',
            status: object.status || '',
            structuralRole: object.structuralRole || '',
            documentUnitKind: object.documentUnitKind || '',
            stateContextKind: object.stateContextKind || '',
            entityKind: object.family === 'registry' || object.family === 'entity' ? object.kind : '',
        }))),
        boundary('atlasPacket.manifoldTargets', (snapshot.atlasPacket?.manifoldTargets || []).map((target) => ({
            id: target.id,
            label: target.label,
            family: target.family,
            kind: target.kind,
            styleKey: target.styleKey || target.stateContextKind || '',
            lane: target.lane || '',
            status: target.admission || target.status || '',
            structuralRole: target.structuralRole || '',
            documentUnitKind: target.documentUnitKind || '',
            stateContextKind: target.stateContextKind || '',
            entityKind: target.entityKind || '',
        }))),
        boundary('graph.inventory.nodes', buildGraphCanvasInventory(snapshot).nodes.map(renderNodeRecord)),
        ...MANIFOLDS.map((manifold) => embedBoundary(snapshot, manifold)),
    ];
    const styleKeyMatrix = STYLE_LAB_KEYS.map((styleKey) => ({
        styleKey,
        snapshotRaw: countFor(boundaries, 'snapshot.raw', styleKey),
        embeddingTargets: countFor(boundaries, 'snapshot.embeddingTargets', styleKey),
        atlasObjects: countFor(boundaries, 'atlasPacket.objects', styleKey),
        atlasTargets: countFor(boundaries, 'atlasPacket.manifoldTargets', styleKey),
        graphInventory: countFor(boundaries, 'graph.inventory.nodes', styleKey),
        embedHybrid: countFor(boundaries, 'embed.hybrid.nodes', styleKey),
        embedSiegel: countFor(boundaries, 'embed.siegel.nodes', styleKey),
    }));
    const warnings = auditWarnings(snapshot, boundaries);
    const embedExclusions = embeddingTargetExclusions(snapshot.embeddingTargets);
    return {
        schemaVersion: 'phoenix-atlas-taxonomy-audit/v1',
        snapshot: {
            id: snapshot.id,
            scopeId: snapshot.scopeId,
            builtAt: snapshot.builtAt,
            atlasPacket: Boolean(snapshot.atlasPacket),
        },
        styleLabKeys: [...STYLE_LAB_KEYS],
        boundaries,
        styleKeyMatrix,
        lossSignals: lossSignals(styleKeyMatrix),
        warnings,
        contractChecks: contractChecksFor(styleKeyMatrix, boundaries, warnings, embedExclusions),
        embedExclusions,
    };
}

function auditWarnings(
    snapshot: GraphRebuildSnapshot,
    boundaries: GraphAtlasTaxonomyBoundary[],
): string[] {
    const warnings: string[] = [];
    const rawTotal = boundaryTotal(boundaries, 'snapshot.raw');
    const graphTotal = boundaryTotal(boundaries, 'graph.inventory.nodes');
    if (!snapshot.atlasPacket) {
        warnings.push('atlasPacket missing; Rust packet parity cannot be proven from this run.');
    } else if (!snapshot.atlasPacket.objects.length) {
        warnings.push('atlasPacket.objects is empty; Graph mode has no Rust-owned object inventory.');
    }
    if (rawTotal > 0 && graphTotal === 0) {
        warnings.push('graph.inventory.nodes is empty while snapshot.raw has rows; Graph mode is not rendering this snapshot boundary.');
    }
    for (const manifold of MANIFOLDS) {
        const total = boundaryTotal(boundaries, `embed.${manifold}.nodes`);
        if (rawTotal > 0 && total === 0) {
            warnings.push(`embed.${manifold}.nodes is empty while snapshot.raw has rows.`);
        }
    }
    return warnings;
}

function boundaryTotal(boundaries: GraphAtlasTaxonomyBoundary[], name: string): number {
    return boundaries.find((boundary) => boundary.name === name)?.total || 0;
}

function embedBoundary(snapshot: GraphRebuildSnapshot, manifold: AtlasManifoldMode): GraphAtlasTaxonomyBoundary {
    try {
        const atlas = buildGraphRebuildEmbeddingAtlas(snapshot, manifold);
        return boundary(`embed.${manifold}.nodes`, atlas.nodes.map(renderNodeRecord));
    } catch (error) {
        return boundary(`embed.${manifold}.nodes`, [{
            id: `error:${manifold}`,
            label: error instanceof Error ? error.message : String(error),
            family: 'error',
            kind: 'error',
            styleKey: '',
            lane: '',
            status: 'error',
            structuralRole: '',
            documentUnitKind: '',
            stateContextKind: '',
            entityKind: '',
        }]);
    }
}

function snapshotRawRecords(snapshot: GraphRebuildSnapshot): AuditRecord[] {
    return [
        ...snapshot.nodes.map((node) => ({
            id: node.id,
            label: node.label,
            family: 'registry',
            kind: node.kind,
            styleKey: node.kind,
            lane: 'entity_anchor',
            status: 'accepted',
            structuralRole: 'child',
            documentUnitKind: '',
            stateContextKind: '',
            entityKind: node.kind,
        })),
        ...snapshot.chunks.map((chunk) => ({
            id: chunk.id,
            label: `Chunk ${chunk.ordinal + 1}`,
            family: 'structure',
            kind: 'chunk',
            styleKey: 'chunk',
            lane: 'chunk_spine',
            status: 'ledgerOnly',
            structuralRole: 'spine',
            documentUnitKind: '',
            stateContextKind: '',
            entityKind: '',
        })),
        ...snapshot.entityAnchors.map((anchor) => ({
            id: anchor.id,
            label: anchor.surface,
            family: 'evidence',
            kind: 'anchor',
            styleKey: 'anchor',
            lane: 'anchor_evidence',
            status: 'accepted',
            structuralRole: 'evidence',
            documentUnitKind: '',
            stateContextKind: '',
            entityKind: '',
        })),
        ...snapshot.relationships.map(relationshipRecord),
        ...snapshot.events.map((event) => ({
            id: event.id,
            label: event.label,
            family: 'fact',
            kind: 'event',
            styleKey: 'eventNode',
            lane: 'event_identity',
            status: 'accepted',
            structuralRole: 'fact',
            documentUnitKind: '',
            stateContextKind: '',
            entityKind: '',
        })),
        ...snapshot.temporalEdges.map((edge) => storyEdgeRecord(edge.id, edge.relationType, 'temporal', 'temporalFact')),
        ...snapshot.causalEdges.map((edge) => storyEdgeRecord(edge.id, edge.relationType, 'causal', 'causalFact')),
        ...snapshot.memoryState.map((state) => {
            const styleKey = memoryStyleKey(`${state.key} ${state.value}`);
            return {
                id: state.id,
                label: state.key,
                family: 'memory',
                kind: 'memoryState',
                styleKey,
                lane: 'memory_state',
                status: 'accepted',
                structuralRole: 'child',
                documentUnitKind: '',
                stateContextKind: styleKey,
                entityKind: '',
            };
        }),
    ];
}

function embeddingTargetRecord(target: GraphRebuildEmbeddingTarget): AuditRecord {
    const kind = target.kind || 'target';
    const entityKind = kind === 'entity' ? target.entityKind || '' : '';
    const stateContextKind = target.stateContextKind || (kind === 'memoryState' ? memoryStyleKey(`${target.label} ${target.text}`) : '');
    return {
        id: target.id,
        label: target.label,
        family: target.atlasFamily || familyForTarget(target),
        kind,
        styleKey: target.styleKey || stateContextKind || styleKeyForTarget(target),
        lane: target.lane || '',
        status: target.admissionStatus || target.atlasStatus || '',
        structuralRole: target.structuralRole || '',
        documentUnitKind: target.documentUnitKind || '',
        stateContextKind,
        entityKind,
    };
}

function renderNodeRecord(node: GalaxyRenderableNode): AuditRecord {
    const meta = node.metadata || {};
    return {
        id: node.id,
        label: node.label,
        family: text(meta['atlasFamily']) || text(meta['graphFamily']) || text(meta['sourceType']),
        kind: node.kind,
        styleKey: text(meta['graphColorKind']) || text(meta['styleKey']) || text(meta['graphKind']),
        lane: text(meta['atlasLane']) || text(meta['signalLane']) || text(meta['productLaneKind']),
        status: text(meta['atlasStatus']) || text(meta['reviewState']),
        structuralRole: text(meta['atlasStructuralRole']) || text(meta['signalStructuralRole']),
        documentUnitKind: text(meta['atlasDocumentUnitKind']) || text(meta['documentUnitKind']),
        stateContextKind: text(meta['atlasStateContextKind']) || text(meta['stateContextKind']),
        entityKind: text(meta['entityKind']) || text(meta['graphEntityKind']),
    };
}

function relationshipRecord(row: GraphRebuildRelationship): AuditRecord {
    return {
        id: row.id,
        label: `${row.sourceEntityId} ${row.relationType} ${row.targetEntityId}`,
        family: 'fact',
        kind: row.relationType,
        styleKey: relationStyleKey(row.relationType, row.rationale),
        lane: 'relationship_fact',
        status: row.status,
        structuralRole: 'fact',
        documentUnitKind: '',
        stateContextKind: '',
        entityKind: '',
    };
}

function storyEdgeRecord(id: string, label: string, family: GraphAtlasFamily, styleKey: string): AuditRecord {
    return {
        id,
        label,
        family,
        kind: styleKey,
        styleKey,
        lane: `${family}_fact`,
        status: 'accepted',
        structuralRole: 'fact',
        documentUnitKind: '',
        stateContextKind: '',
        entityKind: '',
    };
}

function boundary(name: string, records: AuditRecord[]): GraphAtlasTaxonomyBoundary {
    return {
        name,
        total: records.length,
        missingStyleKey: records.filter((record) => !record.styleKey).length,
        byStyleKey: countRows(records.map((record) => normalizeStyleKey(record.styleKey) || 'missing')),
        byFamily: countRows(records.map((record) => record.family || 'missing')),
        byKind: countRows(records.map((record) => record.kind || 'missing')),
        byLane: countRows(records.map((record) => record.lane || 'missing')),
        byStatus: countRows(records.map((record) => record.status || 'missing')),
        byStructuralRole: countRows(records.map((record) => record.structuralRole || 'missing')),
        byDocumentUnitKind: countRows(records.map((record) => record.documentUnitKind || 'missing')),
        byStateContextKind: countRows(records.map((record) => record.stateContextKind || 'missing')),
        byEntityKind: countRows(records.map((record) => record.entityKind || 'missing')),
        samplesByStyleKey: sampleByStyleKey(records),
    };
}

function countRows(values: string[]): CountRow[] {
    const counts = new Map<string, number>();
    for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
    return [...counts.entries()]
        .map(([key, count]) => ({ key, count }))
        .sort((left, right) => right.count - left.count || left.key.localeCompare(right.key));
}

function sampleByStyleKey(records: AuditRecord[]): Record<string, string[]> {
    const samples: Record<string, string[]> = {};
    for (const record of records) {
        const key = normalizeStyleKey(record.styleKey) || 'missing';
        const list = samples[key] || [];
        if (list.length < 5) list.push(`${record.id} | ${record.label}`);
        samples[key] = list;
    }
    return samples;
}

function countFor(boundaries: GraphAtlasTaxonomyBoundary[], boundaryName: string, styleKey: string): number {
    return boundaries.find((boundary) => boundary.name === boundaryName)
        ?.byStyleKey.find((row) => row.key === styleKey)?.count || 0;
}

function lossSignals(rows: GraphAtlasStyleKeyRow[]): GraphAtlasTaxonomyLossSignal[] {
    const signals: GraphAtlasTaxonomyLossSignal[] = [];
    for (const row of rows) {
        pushLoss(signals, row.styleKey, 'snapshot.raw', 'graph.inventory.nodes', row.snapshotRaw, row.graphInventory);
        pushLoss(signals, row.styleKey, 'snapshot.embeddingTargets', 'embed.siegel.nodes', row.embeddingTargets, row.embedSiegel);
        pushLoss(signals, row.styleKey, 'atlasPacket.objects', 'graph.inventory.nodes', row.atlasObjects, row.graphInventory);
    }
    return signals.sort((left, right) => left.delta - right.delta || left.styleKey.localeCompare(right.styleKey));
}

function contractChecksFor(
    rows: GraphAtlasStyleKeyRow[],
    boundaries: GraphAtlasTaxonomyBoundary[],
    warnings: string[],
    embedExclusions: GraphAtlasEmbedExclusion[],
): GraphAtlasTaxonomyCheck[] {
    const atlasObjects = boundaryTotal(boundaries, 'atlasPacket.objects');
    const atlasTargets = boundaryTotal(boundaries, 'atlasPacket.manifoldTargets');
    const graphInventory = boundaryTotal(boundaries, 'graph.inventory.nodes');
    const raw = boundaryTotal(boundaries, 'snapshot.raw');
    const checks: GraphAtlasTaxonomyCheck[] = [
        {
            name: 'rust-packet-present',
            status: atlasObjects > 0 && atlasTargets > 0 ? 'pass' : 'fail',
            message: atlasObjects > 0 && atlasTargets > 0
                ? 'Rust Atlas packet has objects and manifold targets.'
                : 'Rust Atlas packet is missing objects or manifold targets.',
            details: { atlasObjects, atlasTargets },
        },
        {
            name: 'graph-inventory-present',
            status: raw > 0 && graphInventory === 0 ? 'fail' : 'pass',
            message: raw > 0 && graphInventory === 0
                ? 'Graph inventory is empty while snapshot rows exist.'
                : 'Graph inventory has renderable packet rows.',
            details: { raw, graphInventory },
        },
        parityCheck(rows, 'registry-to-graph', ['character', 'npc', 'creature', 'location', 'network', 'item', 'concept'], 'graphInventory'),
        parityCheck(rows, 'registry-to-embed-siegel', ['character', 'npc', 'creature', 'location', 'network', 'item', 'concept'], 'embedSiegel'),
        parityCheck(rows, 'state-context-to-graph', ['memoryState', 'decisionState', 'rankStatus', 'serviceContext', 'affiliationContext', 'familyContext'], 'graphInventory'),
        parityCheck(rows, 'state-context-to-embed-siegel', ['memoryState', 'decisionState', 'rankStatus', 'serviceContext', 'affiliationContext', 'familyContext'], 'embedSiegel'),
        parityCheck(rows, 'story-structure-to-graph', ['document', 'chunk', 'anchor', 'eventNode', 'temporalFact', 'causalFact'], 'graphInventory'),
    ];
    const explained = new Set(embedExclusions.map((row) => row.styleKey));
    const unexplainedEmbedLoss = rows.filter((row) =>
        row.embeddingTargets > 0
        && row.embedSiegel === 0
        && !explained.has(row.styleKey)
    );
    checks.push({
        name: 'embed-losses-explained',
        status: unexplainedEmbedLoss.length ? 'warn' : 'pass',
        message: unexplainedEmbedLoss.length
            ? 'Some Embed losses do not have an exclusion reason in the audit.'
            : 'Embed target losses are either rendered or explained by curation policy.',
        details: { unexplainedStyleKeys: unexplainedEmbedLoss.map((row) => row.styleKey).join(', ') },
    });
    if (warnings.length) {
        checks.push({
            name: 'audit-boundary-warnings',
            status: 'warn',
            message: warnings.join(' '),
        });
    }
    return checks;
}

function parityCheck(
    rows: GraphAtlasStyleKeyRow[],
    name: string,
    keys: string[],
    destination: 'graphInventory' | 'embedSiegel',
): GraphAtlasTaxonomyCheck {
    const relevant = rows.filter((row) => keys.includes(row.styleKey) && (row.snapshotRaw > 0 || row.atlasObjects > 0 || row.embeddingTargets > 0));
    const missing = relevant.filter((row) => row[destination] <= 0);
    return {
        name,
        status: missing.length ? 'fail' : 'pass',
        message: missing.length
            ? `${missing.length} Style Lab families are missing from ${destination}.`
            : `Relevant Style Lab families survive into ${destination}.`,
        details: {
            checked: relevant.length,
            missing: missing.map((row) => row.styleKey).join(', '),
        },
    };
}

function embeddingTargetExclusions(targets: GraphRebuildEmbeddingTarget[]): GraphAtlasEmbedExclusion[] {
    const rows = new Map<string, GraphAtlasEmbedExclusion>();
    for (const target of targets) {
        const reason = embedExclusionReason(target);
        if (!reason) continue;
        const styleKey = normalizeStyleKey(embeddingTargetRecord(target).styleKey) || 'missing';
        const key = `${styleKey}\n${reason}`;
        const row = rows.get(key) || { styleKey, reason, count: 0, samples: [] };
        row.count += 1;
        if (row.samples.length < 5) row.samples.push(`${target.id} | ${target.label}`);
        rows.set(key, row);
    }
    return [...rows.values()].sort((left, right) =>
        right.count - left.count || left.styleKey.localeCompare(right.styleKey) || left.reason.localeCompare(right.reason)
    );
}

function embedExclusionReason(target: GraphRebuildEmbeddingTarget): string {
    if (isWeakCooccurrenceTarget(target)) return 'weak_cooccurrence_excluded';
    const kind = displayKind(target.kind);
    if (CURATED_EMBED_DROP_KINDS.has(kind)) return `curated_drop_kind:${kind}`;
    if (isSentenceOrParagraphTarget(target, kind)) return 'sentence_or_paragraph';
    if (isRawEmbedScaffoldTarget(target, kind)) return 'raw_scaffold';
    if (kind === 'document-unit' && !isCuratedDocumentUnitTarget(target)) return 'document_unit_not_curated';
    return '';
}

function pushLoss(
    signals: GraphAtlasTaxonomyLossSignal[],
    styleKey: string,
    from: string,
    to: string,
    fromCount: number,
    toCount: number,
): void {
    if (fromCount <= 0 || toCount >= fromCount) return;
    signals.push({ styleKey, from, to, fromCount, toCount, delta: toCount - fromCount });
}

function familyForTarget(target: GraphRebuildEmbeddingTarget): string {
    const kind = target.kind;
    if (kind === 'entity') return 'registry';
    if (kind === 'note' || kind === 'chunk' || kind === 'episode' || kind === 'structureRoot' || kind === 'documentUnit') return 'structure';
    if (kind === 'anchor' || kind === 'evidenceSpan') return 'evidence';
    if (kind === 'temporalFact') return 'temporal';
    if (kind === 'causalFact') return 'causal';
    if (kind === 'memoryState') return 'memory';
    return 'fact';
}

function styleKeyForTarget(target: GraphRebuildEmbeddingTarget): string {
    if (target.kind === 'entity') return target.entityKind || 'entity';
    if (target.kind === 'note' || target.kind === 'episode' || target.kind === 'structureRoot') return 'document';
    if (target.kind === 'chunk' || target.kind === 'documentUnit') return 'chunk';
    if (target.kind === 'anchor' || target.kind === 'evidenceSpan') return 'anchor';
    if (target.kind === 'event') return 'eventNode';
    if (target.kind === 'temporalFact') return 'temporalFact';
    if (target.kind === 'causalFact') return 'causalFact';
    if (target.kind === 'memoryState') return memoryStyleKey(`${target.label} ${target.text}`);
    if (target.kind === 'graphFact') return relationStyleKey(target.label, target.text);
    return target.kind || '';
}

function relationStyleKey(kind: string, label: string): string {
    const token = compactToken(`${kind} ${label}`);
    if (token.includes('cooccurswith') || token.includes('cooccurrence') || token.includes('cooccurs')) return 'cooccurrence';
    if (token.includes('observe')) return 'observation';
    if (token.includes('comment') || token.includes('communication')) return 'communication';
    if (token.includes('authority') || token.includes('command')) return 'authority';
    if (token.includes('approval')) return 'approval';
    if (token.includes('family')) return 'family';
    if (token.includes('intimacy')) return 'intimacy';
    if (token.includes('transfer')) return 'transfer';
    if (token.includes('scenepresence')) return 'scenePresence';
    return 'relationship';
}

function memoryStyleKey(value: string): string {
    const token = compactToken(value);
    if (token.includes('decisionstate') || token.includes('decision') || token.includes('approved') || token.includes('accepted')) return 'decisionState';
    if (token.includes('rankorstatus') || token.includes('rankstatus') || token.includes('rank')) return 'rankStatus';
    if (token.includes('servicecontext') || token.includes('servicerank') || token.includes('service')) return 'serviceContext';
    if (token.includes('affiliationcontext') || token.includes('affiliatecontext') || token.includes('affiliantcontext') || token.includes('affiliation')) return 'affiliationContext';
    if (token.includes('familycontext') || token.includes('family')) return 'familyContext';
    return 'memoryState';
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function compactToken(value: string): string {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function normalizeStyleKey(value: string): string {
    const token = compactToken(value);
    const match = STYLE_LAB_KEYS.find((key) => compactToken(key) === token);
    return match || value;
}

function displayKind(kind: string): string {
    return String(kind || 'target').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
}

function compactEmbedProfileText(target: GraphRebuildEmbeddingTarget, includeBody: boolean): string {
    return compactToken([
        target.id,
        target.kind,
        target.sourceId,
        target.lane,
        target.structuralRole,
        target.label,
        includeBody ? target.text : '',
    ].filter(Boolean).join(' '));
}

function isWeakCooccurrenceTarget(target: GraphRebuildEmbeddingTarget): boolean {
    return target.lane === 'cooccurrence_weak'
        || compactToken(target.styleKey || '') === 'cooccurrence'
        || (displayKind(target.kind) === 'graph-fact'
            && relationStyleKey(target.label, `${target.text} ${target.sourceId}`) === 'cooccurrence');
}

function isCuratedDocumentUnitTarget(target: GraphRebuildEmbeddingTarget): boolean {
    const documentUnitKind = compactToken(target.documentUnitKind || '');
    if (documentUnitKind) {
        return CURATED_DOCUMENT_UNIT_TOKENS.some((token) => documentUnitKind.includes(token));
    }
    const profile = compactEmbedProfileText(target, true);
    return CURATED_DOCUMENT_UNIT_TOKENS.some((token) => profile.includes(token));
}

function isSentenceOrParagraphTarget(target: GraphRebuildEmbeddingTarget, kind: string): boolean {
    if (kind.endsWith('-sentence') || kind.endsWith('-paragraph')) return true;
    if ([
        kind,
        target.styleKey || '',
        target.stateContextKind || '',
    ].some(isSentenceOrParagraphTaxonomyToken)) {
        return true;
    }
    const documentUnitKind = compactToken(target.documentUnitKind || '');
    if (documentUnitKind) {
        return SENTENCE_PARAGRAPH_TAXONOMY_TOKENS.some((token) => documentUnitKind === token || documentUnitKind.includes(token));
    }
    const profile = compactEmbedProfileText(target, false);
    return [
        'kindparagraph',
        'kindsentence',
        'documentsidecarparagraph',
        'documentsidecarsentence',
        'paragraphgroup',
        'paragraphindex',
        'sentenceindex',
    ].some((token) => profile.includes(token));
}

function isSentenceOrParagraphTaxonomyToken(value: string): boolean {
    const token = compactToken(value);
    return Boolean(token && SENTENCE_PARAGRAPH_TAXONOMY_TOKENS.some((dropToken) => token === dropToken || token.includes(dropToken)));
}

function isRawEmbedScaffoldTarget(target: GraphRebuildEmbeddingTarget, kind: string): boolean {
    if (kind.includes('candidate') || kind.includes('receipt') || kind.includes('debug')) return true;
    const profile = compactEmbedProfileText(target, false);
    return [
        'rawmention',
        'rawoccurrence',
        'aliaspatch',
        'linkervote',
        'candidatetrace',
        'debugpacket',
    ].some((token) => profile.includes(token));
}
