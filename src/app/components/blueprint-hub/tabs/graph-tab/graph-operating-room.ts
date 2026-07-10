import type { RegisteredEntity } from '../../../../lib/registry';
import type { GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import type {
    GraphDiscourseWorkbenchRecord,
    GraphDiscourseWorkbenchView,
} from './graph-discourse-workbench';
import type { GraphDiscourseTone } from './graph-discourse-analytics';
import { profileLabel } from '../../../../graph-rebuild/graph-document-profile';
import {
    buildReviewAdjudicationViewContract,
    buildReviewAdjudicationRunCertificate,
    type GraphReviewAdjudicationRunCertificate,
} from '../../../../graph-rebuild/graph-review-adjudication-certificate';
import {
    buildAtlasControlContract,
    type AtlasControlCard,
    type AtlasControlContract,
} from '../attributes-tab/atlas-control-contract';

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
    atlasControl?: AtlasControlContract,
): GraphOperatingRoomView {
    const control = atlasControl ?? buildAtlasControlContract({
        snapshot,
        entityCount: entities.length,
    });
    const records = [
        ...entityRecords(entities, snapshot),
        ...profileRecords(snapshot),
        ...reviewAdjudicationRecords(snapshot, control),
        ...(workbench?.records || []),
    ];
    const recordsByRoom = emptyRoomMap();
    for (const row of records) {
        for (const roomId of roomsForRecord(row)) recordsByRoom[roomId].push(row);
    }
    const recordsById = Object.fromEntries(records.map((row) => [row.id, row]));
    const counts = countCards(recordsByRoom, snapshot, control);
    return {
        tabs: ROOM_IDS.map((id) => roomTab(id, recordsByRoom[id], snapshot, entities.length, control)),
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

function reviewAdjudicationRecords(
    snapshot: GraphRebuildSnapshot | null,
    atlasControl?: AtlasControlContract,
): GraphDiscourseWorkbenchRecord[] {
    if (!snapshot) return [];
    const certificate = reviewAdjudicationCertificate(snapshot);
    const contract = atlasControl?.certificates.reviewAdjudication
        ?? buildReviewAdjudicationViewContract(certificate);
    const tone: GraphDiscourseTone = contract.proof.noTopologyWrites && contract.proof.dimensionContractPassed
        ? 'ready'
        : 'danger';
    const records = [
        record({
            id: `review-adjudication:inventory:${snapshot.id}`,
            kind: 'review-adjudication:inventory',
            title: 'Review Queue Inventory',
            subtitle: contract.queue.summary,
            detail: `${contract.queue.excludedLabel} / ${formatCount(contract.queue.duplicateRows)} duplicate pairs / ${formatCount(contract.queue.judgedRows)} judged`,
            status: contract.proof.modelRan ? 'accepted' : 'reviewable',
            tone,
            focusQuery: 'ModernBERT NLI review queue inventory',
            sourceIds: certificate.document.noteIds,
            tags: ['review_adjudication', 'nli_eligible', 'candidate_only'],
            actionKinds: ['inspect'],
            facts: [
                fact('Total review rows', contract.queue.totalReviewRows),
                fact('NLI eligible rows', contract.queue.nliEligibleRows),
                fact('Excluded rows', contract.queue.excludedRows),
                fact('Judged rows', contract.queue.judgedRows),
                fact('Embedding contract', contract.model.embeddingDimensionLabel || certificate.model.dimension),
                fact('Button state', contract.action.label),
                fact('Button reason', contract.action.reason),
                fact('Topology writes', contract.queue.topologyWrites),
            ],
        }),
    ];

    for (const reason of certificate.queue.excludedReasons) {
        records.push(record({
            id: `review-adjudication:excluded:${reason.id}:${snapshot.id}`,
            kind: 'review-adjudication:excluded_reason',
            title: reason.label,
            subtitle: `${reason.count} excluded rows`,
            detail: reason.detail,
            status: 'reviewable',
            tone: 'review',
            focusQuery: `ModernBERT excluded reason ${reason.label}`,
            sourceIds: certificate.document.noteIds,
            tags: ['review_adjudication', 'excluded_reason', reason.id],
            actionKinds: ['inspect'],
            facts: [
                fact('Reason', reason.label),
                fact('Rows', reason.count),
                fact('Detail', reason.detail),
            ],
        }));
    }
    return records;
}

function reviewAdjudicationCertificate(snapshot: GraphRebuildSnapshot): GraphReviewAdjudicationRunCertificate {
    return snapshot.reviewAdjudicationCertificate ?? buildReviewAdjudicationRunCertificate({
        snapshot,
        source: 'derived',
        modelId: 'onnx-community/ModernBERT-base-nli',
        modelLabel: 'ModernBERT NLI',
        dimensionLabel: snapshot.embeddingProfile?.dimensionLabel,
        embeddingDimension: snapshot.embeddingProfile?.selectedDimensions,
    });
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
        || row.kind.startsWith('review-adjudication:')
        || ['proposed', 'accepted', 'rejected', 'muted', 'deferred', 'reviewable', 'pending_commit'].includes(status)
        || tags.includes('ambiguous')
        || tags.includes('review_adjudication')
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
    atlasControl?: AtlasControlContract,
): GraphOperatingRoomCount[] {
    const all = uniqueRecords(ROOM_IDS.flatMap((room) => rooms[room]));
    const fallback = roomFallbackCounts(snapshot);
    const reviewManual = atlasCardNumber(atlasControl, 'review-manual-action', fallback.reviewGaps);
    const reviewNli = atlasCardNumber(atlasControl, 'review-nli-pairs', fallback.reviewNliEligible);
    const reviewExcluded = atlasCardNumber(atlasControl, 'review-excluded', fallback.reviewExcluded);
    return [
        count('entities-total', 'entities', 'Registered', rooms.entities, `${snapshot?.counters.nodes || 0} graph nodes`, 'ready'),
        count('structure-total', 'structure', 'Structure', rooms.structure, `${fallback.structureUnits} units`, toneForRows(rooms.structure), fallback.structureUnits),
        count('structure-profiles', 'structure', 'Profiles', filter(rooms.structure, (row) => row.kind.startsWith('document-profile:')), 'document and region weighting', toneForRows(filter(rooms.structure, (row) => row.kind.startsWith('document-profile:')))),
        count('facts-relations', 'facts', 'Relations', filter(rooms.facts, (row) => relationLike(row)), 'relation candidates and facts', toneForRows(filter(rooms.facts, relationLike)), fallback.factRelations),
        count('facts-hyperedges', 'facts', 'Hyperedges', filter(rooms.facts, (row) => row.kind.includes('hyperedge')), 'n-ary document facts', toneForRows(filter(rooms.facts, (row) => row.kind.includes('hyperedge'))), fallback.factHyperedges),
        count('review-gaps', 'review', 'Manual decisions', filter(rooms.review, (row) => row.tab === 'gaps' || row.status === 'reviewable'), atlasCardDetail(atlasControl, 'review-manual-action', 'accept/reject receipt rows'), atlasCardTone(atlasControl, 'review-manual-action', 'review'), reviewManual, reviewManual),
        count('review-nli-eligible', 'review', 'NLI eligible', filter(rooms.review, (row) => row.kind === 'review-adjudication:inventory'), atlasCardDetail(atlasControl, 'review-nli-pairs', 'ModernBERT pairwise review inputs'), atlasCardTone(atlasControl, 'review-nli-pairs', 'ready'), reviewNli, reviewNli),
        count('review-excluded', 'review', 'Excluded', filter(rooms.review, (row) => row.kind === 'review-adjudication:excluded_reason'), atlasCardDetail(atlasControl, 'review-excluded', 'rows outside the NLI pair contract'), atlasCardTone(atlasControl, 'review-excluded', reviewExcluded > 0 ? 'review' : 'quiet'), reviewExcluded, reviewExcluded),
        count('review-accepted', 'review', 'Accepted', filter(rooms.review, (row) => ['accepted', 'supported', 'pending_commit'].includes(row.status)), 'accepted objects', 'ready', fallback.reviewAccepted),
        count('review-ambiguous', 'review', 'Ambiguous', filter(rooms.review, (row) => row.status === 'deferred' || row.status === 'reviewable' || row.tags.includes('ambiguous_case')), 'ambiguity queue', 'review', fallback.reviewAmbiguous),
        count('discourse-wormholes', 'discourse', 'Wormholes', filter(rooms.discourse, (row) => row.tags.includes('chunk_wormhole') || row.kind.includes('wormhole')), 'wormhole evidence', toneForRows(filter(rooms.discourse, (row) => row.tags.includes('chunk_wormhole') || row.kind.includes('wormhole'))), fallback.discourseWormholes),
        count('discourse-packets', 'discourse', 'Packets', filter(rooms.discourse, (row) => row.tags.join(' ').includes('cross_doc')), 'cross-doc idea packets', toneForRows(rooms.discourse), fallback.discoursePackets),
        count('metrics-receipts', 'metrics', 'Receipts', filter(all, (row) => row.receiptIds.length > 0), 'receipt ledger', toneForRows(filter(all, (row) => row.receiptIds.length > 0)), fallback.receipts),
        count('metrics-health', 'metrics', 'Health', rooms.metrics, 'chunk, graph, and index health', toneForRows(rooms.metrics)),
    ];
}

interface GraphOperatingRoomFallbackCounts {
    structureUnits: number;
    factRelations: number;
    factHyperedges: number;
    reviewGaps: number;
    reviewNliEligible: number;
    reviewExcluded: number;
    reviewAccepted: number;
    reviewAmbiguous: number;
    discourseWormholes: number;
    discoursePackets: number;
    receipts: number;
}

function roomFallbackCounts(snapshot: GraphRebuildSnapshot | null): GraphOperatingRoomFallbackCounts {
    const sidecar = snapshot?.documentSidecarSummary?.counters;
    const review = snapshot?.documentReviewSummary?.counters;
    const compiler = snapshot?.documentCompilerSummary?.counters;
    const entityLinking = snapshot?.counters.entityLinking;
    return {
        structureUnits: maxCount(
            sidecar?.units,
            counter(snapshot, 'documentSidecarUnits'),
            atlasFamilies(snapshot, ['structure', 'evidence']),
        ),
        factRelations: maxCount(
            counter(snapshot, 'relationships') + counter(snapshot, 'events') + counter(snapshot, 'temporalEdges') + counter(snapshot, 'causalEdges') + counter(snapshot, 'memoryState'),
            counter(snapshot, 'documentSidecarGraphFacts') + counter(snapshot, 'documentCompilerRelationCandidates') + counter(snapshot, 'documentCompilerEvidenceEdges'),
            atlasFamilies(snapshot, ['fact', 'temporal', 'causal', 'memory']),
        ),
        factHyperedges: maxCount(
            compiler?.hyperedges,
            counter(snapshot, 'documentCompilerHyperedges'),
            atlasFamilies(snapshot, ['hypergraph']),
        ),
        reviewGaps: maxCount(
            review?.actionableRows,
            counter(snapshot, 'documentReviewActionableRows') + counter(snapshot, 'documentCompilerReviewable') + counter(snapshot, 'reviewRelationships'),
            counter(snapshot, 'semanticEvalAmbiguousCases') + counter(snapshot, 'discourseEvalAmbiguousCases') + (entityLinking?.ambiguous || 0),
        ),
        reviewNliEligible: counter(snapshot, 'reviewAdjudicationEligibleRows'),
        reviewExcluded: counter(snapshot, 'reviewAdjudicationExcludedRows'),
        reviewAccepted: maxCount(
            review?.acceptedRows,
            counter(snapshot, 'documentReviewAcceptedRows') + counter(snapshot, 'acceptedRelationships'),
            counter(snapshot, 'semanticEvalAcceptedCandidates') + counter(snapshot, 'discourseEvalAcceptedCandidates') + counter(snapshot, 'documentCompilerTopologyCommits'),
        ),
        reviewAmbiguous: maxCount(
            counter(snapshot, 'semanticEvalAmbiguousCases') + counter(snapshot, 'discourseEvalAmbiguousCases'),
            counter(snapshot, 'documentCompilerAmbiguousFacts') + (entityLinking?.ambiguous || 0),
        ),
        discourseWormholes: maxCount(
            counter(snapshot, 'discoursePromotionChunkWormholes'),
            counter(snapshot, 'discourseCompilerOverlayChunkWormholes'),
        ),
        discoursePackets: maxCount(
            counter(snapshot, 'discourseSpineTargets'),
            counter(snapshot, 'discourseBridgeCandidates') + counter(snapshot, 'discoursePromotionDocumentClusters') + counter(snapshot, 'discourseCompilerOverlayDocumentClusters'),
            atlasFamilies(snapshot, ['discourse']),
        ),
        receipts: receiptCounterTotal(snapshot),
    };
}

function count(
    id: string,
    roomId: GraphOperatingRoomId,
    label: string,
    rows: GraphDiscourseWorkbenchRecord[],
    detail: string,
    tone: GraphDiscourseTone,
    fallbackValue = 0,
    exactValue?: number,
): GraphOperatingRoomCount {
    const uniqueRows = uniqueRecords(rows);
    const value = exactValue ?? Math.max(uniqueRows.length, fallbackValue);
    return {
        id,
        roomId,
        label,
        value,
        detail,
        tone: tone === 'quiet' && value > 0 ? 'ready' : tone,
        recordIds: uniqueRows.map((row) => row.id),
    };
}

function atlasCard(atlasControl: AtlasControlContract | undefined, id: string): AtlasControlCard | undefined {
    return atlasControl?.cardsById[id];
}

function atlasCardNumber(atlasControl: AtlasControlContract | undefined, id: string, fallback: number): number {
    const value = atlasCard(atlasControl, id)?.value;
    return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function atlasCardDetail(atlasControl: AtlasControlContract | undefined, id: string, fallback: string): string {
    return atlasCard(atlasControl, id)?.detail || fallback;
}

function atlasCardTone(
    atlasControl: AtlasControlContract | undefined,
    id: string,
    fallback: GraphDiscourseTone,
): GraphDiscourseTone {
    const tone = atlasCard(atlasControl, id)?.tone;
    if (tone === 'warning') return 'review';
    if (tone === 'ready' || tone === 'review' || tone === 'danger' || tone === 'quiet') return tone;
    return fallback;
}

function roomTab(
    id: GraphOperatingRoomId,
    records: GraphDiscourseWorkbenchRecord[],
    snapshot: GraphRebuildSnapshot | null,
    entityCount: number,
    atlasControl?: AtlasControlContract,
): GraphOperatingRoomTab {
    const fallback = roomTabFallbackCount(id, snapshot, entityCount, atlasControl);
    const countValue = Math.max(records.length, fallback);
    const tone = toneForRows(records);
    return { id, label: title(id), detail: roomDetail(id), count: countValue, tone: tone === 'quiet' && countValue > 0 ? 'ready' : tone };
}

function roomTabFallbackCount(
    id: GraphOperatingRoomId,
    snapshot: GraphRebuildSnapshot | null,
    entityCount: number,
    atlasControl?: AtlasControlContract,
): number {
    const fallback = roomFallbackCounts(snapshot);
    if (id === 'entities') return Math.max(entityCount, snapshot?.atlasPacket?.counters.registryEntities || 0);
    if (id === 'structure') return fallback.structureUnits;
    if (id === 'facts') return fallback.factRelations + fallback.factHyperedges;
    if (id === 'review') {
        const localFallback = maxCount(
            counter(snapshot, 'documentReviewRows'),
            counter(snapshot, 'reviewAdjudicationTotalRows'),
            counter(snapshot, 'reviewAdjudicationEligibleRows'),
            counter(snapshot, 'semanticEvalLedgerRows') + counter(snapshot, 'discourseEvalLedgerRows'),
            fallback.reviewGaps,
            fallback.reviewAccepted,
            fallback.reviewAmbiguous,
            atlasFamilies(snapshot, ['review']),
        );
        return atlasCardNumber(atlasControl, 'review-ledger', localFallback);
    }
    if (id === 'discourse') return maxCount(fallback.discoursePackets + fallback.discourseWormholes, counter(snapshot, 'discourseEvalLedgerRows'));
    return Math.max(recordsMetricCount(snapshot), fallback.receipts);
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

function formatCount(value: number): string {
    return Math.max(0, Math.round(value || 0)).toLocaleString();
}

function uniqueRooms(values: GraphOperatingRoomId[]): GraphOperatingRoomId[] {
    return [...new Set(values)];
}

function uniqueRecords(values: GraphDiscourseWorkbenchRecord[]): GraphDiscourseWorkbenchRecord[] {
    return [...new Map(values.map((row) => [row.id, row])).values()];
}

function counter(snapshot: GraphRebuildSnapshot | null, key: string): number {
    const value = (snapshot?.counters as Record<string, unknown> | undefined)?.[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function atlasFamilies(snapshot: GraphRebuildSnapshot | null, families: string[]): number {
    const familySet = new Set(families);
    const packet = snapshot?.atlasPacket;
    const direct = packet?.objects?.filter((object) => familySet.has(object.family)).length || 0;
    const summarized = packet?.counters?.families
        ?.filter((row) => familySet.has(row.family))
        .reduce((sum, row) => sum + row.count, 0) || 0;
    return Math.max(direct, summarized);
}

function receiptCounterTotal(snapshot: GraphRebuildSnapshot | null): number {
    return [
        'documentReviewReceipts',
        'documentCompilerReceipts',
        'calendarRegistryReceipts',
        'semanticTaskReceipts',
        'semanticCandidateReceipts',
        'semanticRerankReceipts',
        'semanticAdjudicationReceipts',
        'discourseSpineReceipts',
        'discourseBridgeReceipts',
        'discourseBridgeAdjudicationReceipts',
        'discoursePromotionReceipts',
        'discourseCompilerOverlayReceipts',
        'memoryGraphRagReceipts',
        'manifoldContributionReceipts',
        'operatorMutationReceipts',
    ].reduce((sum, key) => sum + counter(snapshot, key), 0);
}

function recordsMetricCount(snapshot: GraphRebuildSnapshot | null): number {
    return [
        counter(snapshot, 'nodes'),
        counter(snapshot, 'edges'),
        counter(snapshot, 'embeddingTargets'),
        counter(snapshot, 'semanticEvalLedgerRows'),
        counter(snapshot, 'discourseEvalLedgerRows'),
        counter(snapshot, 'documentCompilerTopologyDiffs'),
        counter(snapshot, 'documentReviewRows'),
        counter(snapshot, 'calendarRegistryReceipts'),
        counter(snapshot, 'memoryGraphRagRecords'),
        counter(snapshot, 'manifoldSpecializations'),
        counter(snapshot, 'projectionRefs'),
    ].filter((value) => value > 0).length;
}

function maxCount(...values: Array<number | undefined>): number {
    return Math.max(0, ...values.map((value) => Math.max(0, Math.round(value || 0))));
}

function title(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1);
}
