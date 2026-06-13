import type { RegisteredEntity } from '../../../../lib/registry';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import type {
    GraphDiscourseWorkbenchRecord,
    GraphDiscourseWorkbenchView,
} from './graph-discourse-workbench';
import type { GraphDiscourseTone } from './graph-discourse-analytics';
import { profileLabel } from '../../../../graph-rebuild/graph-document-profile';

export type GraphOperatingRoomId =
    | 'entities'
    | 'structure'
    | 'facts'
    | 'review'
    | 'discourse'
    | 'metrics';

export interface GraphOperatingRoomTab {
    id: GraphOperatingRoomId;
    label: string;
    detail: string;
    count: number;
    tone: GraphDiscourseTone;
}

export interface GraphOperatingRoomCount {
    id: string;
    roomId: GraphOperatingRoomId;
    label: string;
    value: number;
    detail: string;
    tone: GraphDiscourseTone;
    recordIds: string[];
}

export interface GraphOperatingRoomView {
    tabs: GraphOperatingRoomTab[];
    counts: GraphOperatingRoomCount[];
    countsById: Record<string, GraphOperatingRoomCount>;
    recordsByRoom: Record<GraphOperatingRoomId, GraphDiscourseWorkbenchRecord[]>;
    recordsById: Record<string, GraphDiscourseWorkbenchRecord>;
}

const ROOM_IDS: GraphOperatingRoomId[] = ['entities', 'structure', 'facts', 'review', 'discourse', 'metrics'];

export function buildGraphOperatingRoomView(
    workbench: GraphDiscourseWorkbenchView | null,
    snapshot: GraphRebuildSnapshot | null,
    entities: RegisteredEntity[],
): GraphOperatingRoomView {
    const records = [...entityRecords(entities, snapshot), ...profileRecords(snapshot), ...(workbench?.records || [])];
    const recordsByRoom = emptyRoomMap();
    for (const row of records) {
        for (const roomId of roomsForRecord(row)) recordsByRoom[roomId].push(row);
    }
    const recordsById = Object.fromEntries(records.map((row) => [row.id, row]));
    const counts = countCards(recordsByRoom, snapshot);
    return {
        tabs: ROOM_IDS.map((id) => roomTab(id, recordsByRoom[id])),
        counts,
        countsById: Object.fromEntries(counts.map((row) => [row.id, row])),
        recordsByRoom,
        recordsById,
    };
}

function entityRecords(
    entities: RegisteredEntity[],
    snapshot: GraphRebuildSnapshot | null,
): GraphDiscourseWorkbenchRecord[] {
    const nodesByEntity = new Map((snapshot?.nodes || []).map((node) => [node.entityId, node]));
    return entities
        .slice()
        .sort((left, right) => left.label.localeCompare(right.label))
        .map((entity) => {
            const node = nodesByEntity.get(entity.id);
            return record({
                id: `operating-room:entity:${entity.id}`,
                kind: 'entity:registered',
                title: entity.label,
                subtitle: `${entity.kind || 'Entity'} / registered anchor`,
                detail: `${entity.aliases.length} aliases / ${node?.totalMentions || 0} mentions`,
                status: 'registered',
                tone: 'ready',
                focusQuery: [entity.label, ...entity.aliases, entity.kind].filter(Boolean).join(' '),
                entityIds: [entity.id],
                sourceIds: [entity.id, ...(node?.anchorIds || [])],
                targetIds: node?.noteIds || [],
                evidenceIds: node?.anchorIds || [],
                tags: ['entity', entity.kind, node ? 'graph_node' : 'registry_only'],
                actionKinds: ['inspect', 'jump_to_source_span', 'promote_sidecar_to_anchor'],
                facts: [
                    fact('Source text', entity.label),
                    fact('Lineage', 'user anchor registry'),
                    fact('Confidence', 'durable'),
                    fact('Detector', 'registered entity'),
                    fact('Related entities', entity.id),
                    fact('Graph impact', `${node?.totalMentions || 0} mentions / ${node?.anchorIds.length || 0} anchors`),
                    fact('Actions', 'Inspect / Jump / Promote'),
                ],
            });
        });
}

function profileRecords(snapshot: GraphRebuildSnapshot | null): GraphDiscourseWorkbenchRecord[] {
    const summary = snapshot?.documentSidecarSummary?.documentProfileSummary;
    if (!summary) return [];
    return summary.profiles.map((profile) => record({
        id: `document-profile:${profile.noteId}`,
        kind: 'document-profile:weighted',
        title: profileLabel(profile.dominantProfile),
        subtitle: `${Math.round(profile.confidence * 100)}% confidence / ${profile.regions.length} regions`,
        detail: profile.signals.slice(0, 4).map((signal) => `${signal.cue} x${signal.occurrences}`).join(' / ') || 'No strong lexical cue dominated.',
        status: summary.source,
        tone: summary.source === 'native_rust' ? 'ready' : 'quiet',
        focusQuery: profile.signals.slice(0, 4).map((signal) => signal.cue).join(' '),
        sourceIds: [profile.noteId],
        targetIds: profile.regions.map((region) => region.id),
        evidenceIds: profile.signals.map((signal) => signal.id),
        tags: ['document_profile', profile.dominantProfile, summary.source],
        actionKinds: ['inspect', 'jump_to_source_span'],
        rationale: profile.weights.slice(0, 4).map((weight) => `${profileLabel(weight.profile)} ${Math.round(weight.score * 100)}%`),
        facts: [
            fact('Profile', profileLabel(profile.dominantProfile)),
            fact('Confidence', `${Math.round(profile.confidence * 100)}%`),
            fact('Engine', summary.source),
            fact('Regions', profile.regions.length),
            fact('Evidence signals', profile.signals.length),
            fact('Ontology policy', 'weights only / no automatic anchors'),
        ],
    }));
}

function roomsForRecord(row: GraphDiscourseWorkbenchRecord): GraphOperatingRoomId[] {
    const rooms: GraphOperatingRoomId[] = [];
    const kind = row.kind.toLowerCase();
    const tags = row.tags.join(' ').toLowerCase();
    const status = row.status.toLowerCase();
    if (kind.startsWith('entity:') || kind.startsWith('entity-link:')) rooms.push('entities');
    if (isStructureKind(kind, tags)) rooms.push('structure');
    if (isFactKind(kind, tags)) rooms.push('facts');
    if (isReviewKind(row, status, tags)) rooms.push('review');
    if (isDiscourseKind(kind, tags)) rooms.push('discourse');
    if (kind === 'stat') rooms.push('metrics');
    return rooms.length ? uniqueRooms(rooms) : ['metrics'];
}

function isStructureKind(kind: string, tags: string): boolean {
    return kind.startsWith('document-profile:')
        || kind.includes('document-review:document_unit')
        || kind.includes('document-review:document_region')
        || kind.includes('document-review:retrieval_unit')
        || kind.includes('document-review:evidence_span')
        || kind.includes('document-compiler:document_structure_edge')
        || kind.includes('document-compiler:retrieval_overlay')
        || tags.includes('document_structure_edge')
        || tags.includes('retrieval_overlay');
}

function isFactKind(kind: string, tags: string): boolean {
    return kind === 'relationship'
        || kind.startsWith('causal:')
        || kind.startsWith('graph-link:')
        || kind.includes('graph_fact_candidate')
        || kind.includes('rhetorical_unit')
        || kind.includes('document-compiler:hyperedge')
        || kind.includes('document-compiler:evidence_backed_edge')
        || kind.includes('document-compiler:relation_candidate')
        || tags.includes('relation_candidate')
        || tags.includes('hyperedge');
}

function isReviewKind(row: GraphDiscourseWorkbenchRecord, status: string, tags: string): boolean {
    return row.tone === 'review'
        || row.tone === 'danger'
        || ['proposed', 'accepted', 'rejected', 'muted', 'deferred', 'reviewable', 'pending_commit'].includes(status)
        || tags.includes('ambiguous')
        || tags.includes('reject')
        || tags.includes('accept_fact');
}

function isDiscourseKind(kind: string, tags: string): boolean {
    return kind.startsWith('discourse:')
        || kind.startsWith('overlay:')
        || tags.includes('wormhole')
        || tags.includes('document_cluster')
        || tags.includes('cross_doc')
        || tags.includes('discourse');
}

function countCards(
    rooms: Record<GraphOperatingRoomId, GraphDiscourseWorkbenchRecord[]>,
    snapshot: GraphRebuildSnapshot | null,
): GraphOperatingRoomCount[] {
    const all = uniqueRecords(ROOM_IDS.flatMap((room) => rooms[room]));
    return [
        count('entities-total', 'entities', 'Registered', rooms.entities, `${snapshot?.counters.nodes || 0} graph nodes`, 'ready'),
        count('structure-total', 'structure', 'Structure', rooms.structure, `${snapshot?.documentSidecarSummary?.counters.units || 0} units`, toneForRows(rooms.structure)),
        count('structure-profiles', 'structure', 'Profiles', filter(rooms.structure, (row) => row.kind.startsWith('document-profile:')), 'document and region weighting', toneForRows(filter(rooms.structure, (row) => row.kind.startsWith('document-profile:')))),
        count('facts-relations', 'facts', 'Relations', filter(rooms.facts, (row) => relationLike(row)), 'relation candidates and facts', toneForRows(filter(rooms.facts, relationLike))),
        count('facts-hyperedges', 'facts', 'Hyperedges', filter(rooms.facts, (row) => row.kind.includes('hyperedge')), 'n-ary document facts', toneForRows(filter(rooms.facts, (row) => row.kind.includes('hyperedge')))),
        count('review-gaps', 'review', 'Gaps', filter(rooms.review, (row) => row.tab === 'gaps' || row.status === 'reviewable'), 'open gap records', 'review'),
        count('review-accepted', 'review', 'Accepted', filter(rooms.review, (row) => ['accepted', 'supported', 'pending_commit'].includes(row.status)), 'accepted objects', 'ready'),
        count('review-ambiguous', 'review', 'Ambiguous', filter(rooms.review, (row) => row.status === 'deferred' || row.status === 'reviewable' || row.tags.includes('ambiguous_case')), 'ambiguity queue', 'review'),
        count('discourse-wormholes', 'discourse', 'Wormholes', filter(rooms.discourse, (row) => row.tags.includes('chunk_wormhole') || row.kind.includes('wormhole')), 'wormhole evidence', toneForRows(filter(rooms.discourse, (row) => row.tags.includes('chunk_wormhole') || row.kind.includes('wormhole')))),
        count('discourse-packets', 'discourse', 'Packets', filter(rooms.discourse, (row) => row.tags.join(' ').includes('cross_doc')), 'cross-doc idea packets', toneForRows(rooms.discourse)),
        count('metrics-receipts', 'metrics', 'Receipts', filter(all, (row) => row.receiptIds.length > 0), 'receipt ledger', toneForRows(filter(all, (row) => row.receiptIds.length > 0))),
        count('metrics-health', 'metrics', 'Health', rooms.metrics, 'chunk, graph, and index health', toneForRows(rooms.metrics)),
    ];
}

function count(
    id: string,
    roomId: GraphOperatingRoomId,
    label: string,
    rows: GraphDiscourseWorkbenchRecord[],
    detail: string,
    tone: GraphDiscourseTone,
): GraphOperatingRoomCount {
    const uniqueRows = uniqueRecords(rows);
    return {
        id,
        roomId,
        label,
        value: uniqueRows.length,
        detail,
        tone,
        recordIds: uniqueRows.map((row) => row.id),
    };
}

function roomTab(id: GraphOperatingRoomId, records: GraphDiscourseWorkbenchRecord[]): GraphOperatingRoomTab {
    return { id, label: title(id), detail: roomDetail(id), count: records.length, tone: toneForRows(records) };
}

function emptyRoomMap(): Record<GraphOperatingRoomId, GraphDiscourseWorkbenchRecord[]> {
    return { entities: [], structure: [], facts: [], review: [], discourse: [], metrics: [] };
}

function roomDetail(id: GraphOperatingRoomId): string {
    if (id === 'entities') return 'anchors';
    if (id === 'structure') return 'hierarchy';
    if (id === 'facts') return 'claims';
    if (id === 'review') return 'queue';
    if (id === 'discourse') return 'bridges';
    return 'health';
}

function relationLike(row: GraphDiscourseWorkbenchRecord): boolean {
    return row.kind === 'relationship'
        || row.kind.startsWith('graph-link:')
        || row.kind.startsWith('causal:')
        || row.kind.includes('relation')
        || row.kind.includes('hyperedge');
}

function filter(
    rows: GraphDiscourseWorkbenchRecord[],
    predicate: (row: GraphDiscourseWorkbenchRecord) => boolean,
): GraphDiscourseWorkbenchRecord[] {
    return rows.filter(predicate);
}

function toneForRows(rows: GraphDiscourseWorkbenchRecord[]): GraphDiscourseTone {
    if (rows.some((row) => row.tone === 'danger')) return 'danger';
    if (rows.some((row) => row.tone === 'review')) return 'review';
    if (rows.length) return 'ready';
    return 'quiet';
}

function record(input: Partial<GraphDiscourseWorkbenchRecord> & Pick<GraphDiscourseWorkbenchRecord, 'id' | 'kind' | 'title' | 'subtitle' | 'detail' | 'status' | 'tone' | 'focusQuery'>): GraphDiscourseWorkbenchRecord {
    return {
        tab: 'insights',
        score: null,
        scoreLabel: 'data',
        candidateId: undefined,
        decisionId: undefined,
        sourceIds: [],
        targetIds: [],
        evidenceIds: [],
        entityIds: [],
        receiptIds: [],
        actionKinds: [],
        tags: [],
        rationale: [],
        facts: [],
        ...input,
    };
}

function fact(label: string, value: unknown) {
    return { label, value: String(value ?? '') };
}

function uniqueRooms(values: GraphOperatingRoomId[]): GraphOperatingRoomId[] {
    return [...new Set(values)];
}

function uniqueRecords(values: GraphDiscourseWorkbenchRecord[]): GraphDiscourseWorkbenchRecord[] {
    return [...new Map(values.map((row) => [row.id, row])).values()];
}

function title(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1);
}
