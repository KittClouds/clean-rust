import type {
    GraphCompileCounters,
    GraphCompileReceipts,
    GraphCompilerAtom,
    GraphCompilerAtomKind,
    GraphCompilerDualWriteSidecar,
    GraphCompilerEvidenceAnchor,
    GraphCompilerEvidenceBundleKind,
    GraphCompilerFactBundle,
    GraphCompilerFactLane,
    GraphCompilerFactLike,
    GraphCompilerFactRole,
    GraphCompilerOutput,
    GraphCompilerProjectedEdge,
    GraphCompilerRelationFact,
    GraphRootReceipt,
} from './graph-compiler-read-model';
import { projectUiGraphFromCompilerOutput } from './graph-compiler-read-model';
import type { GraphRebuildCausalEdge, GraphRebuildSnapshot } from './graph-rebuild-snapshot';

export function buildCompatibilityGraphCompilerSidecar(snapshot: GraphRebuildSnapshot): GraphCompilerDualWriteSidecar {
    const factGraph = buildCompatibilityGraphCompilerOutput(snapshot);
    return {
        factGraph,
        receipts: factGraph.receipts,
        projectedUiGraph: projectUiGraphFromCompilerOutput(factGraph),
    };
}

function buildCompatibilityGraphCompilerOutput(snapshot: GraphRebuildSnapshot): GraphCompilerOutput {
    const atoms: GraphCompilerAtom[] = [];
    const evidenceAnchors: GraphCompilerEvidenceAnchor[] = [];
    const evidenceSeen = new Set<string>();
    const bundles: GraphCompilerFactBundle[] = [];
    const facts: GraphCompilerRelationFact[] = [];
    const roles: GraphCompilerFactRole[] = [];
    const projectedEdges: GraphCompilerProjectedEdge[] = [];
    const provenanceByEdge = new Map<string, { factId?: string; bundleId?: string }>();
    const pushEvidence = (evidence: GraphCompilerEvidenceAnchor) => {
        if (evidenceSeen.has(evidence.id)) return;
        evidenceSeen.add(evidence.id);
        evidenceAnchors.push(evidence);
    };
    const ensureAnchorEvidence = (ids: string[]) => ids.map((id) => {
        const evidenceId = anchorEvidenceId(id);
        pushEvidence({ id: evidenceId, kind: 'sourceSpan', sourceId: id, confidence: 0.62 });
        return evidenceId;
    });

    for (const noteId of snapshot.noteIds) {
        atoms.push(atom('document', atomId('document', noteId), noteId, `Document ${noteId}`, noteId));
        atoms.push(atom('documentRoot', atomId('documentRoot', noteId), noteId, `Document root ${noteId}`, noteId));
    }
    for (const lane of compilerLanes()) atoms.push(atom('laneRoot', atomId('laneRoot', `${snapshot.scopeId}:${lane}`), `${snapshot.scopeId}:${lane}`, `${lane} root`));
    for (const chunk of snapshot.chunks) atoms.push(atom('chunk', atomId('chunk', chunk.id), chunk.id, `Chunk ${chunk.ordinal + 1}`, chunk.noteId, chunk.id));
    for (const mention of snapshot.mentions.filter((row) => row.status !== 'dropped')) {
        pushEvidence({ id: mentionEvidenceId(mention.id), kind: 'mentionPacket', noteId: mention.noteId, chunkId: mention.chunkId, sourceRange: { start: mention.sourceStart, end: mention.sourceEnd }, sourceId: mention.id, confidence: mention.confidence });
    }
    for (const anchor of snapshot.entityAnchors) {
        const evidenceId = anchorEvidenceId(anchor.id);
        pushEvidence({ id: evidenceId, kind: 'sourceSpan', noteId: anchor.noteId, chunkId: anchor.chunkId, sourceRange: { start: anchor.sourceStart, end: anchor.sourceEnd }, sourceId: anchor.id, confidence: anchor.confidence });
        atoms.push(atom('evidenceAnchor', evidenceId, anchor.id, anchor.surface, anchor.noteId, anchor.chunkId, anchor.entityId, [evidenceId]));
    }
    for (const node of snapshot.nodes) {
        atoms.push(atom(node.kind.toLowerCase() === 'concept' ? 'concept' : 'entity', atomId('entity', node.entityId), node.entityId, node.label, undefined, undefined, node.entityId, node.anchorIds.map(anchorEvidenceId)));
    }
    for (const event of snapshot.events) {
        const evidenceId = eventEvidenceId(event.id);
        pushEvidence({ id: evidenceId, kind: 'eventReference', noteId: event.noteId, chunkId: event.chunkId, sourceId: event.id, confidence: event.confidence });
        atoms.push(atom('event', atomId('event', event.id), event.id, event.label, event.noteId, event.chunkId, event.entityIds[0], [evidenceId]));
    }
    for (const state of snapshot.memoryState) atoms.push(atom('state', atomId('state', state.id), state.id, state.key, state.noteId, undefined, state.entityId, state.evidenceIds.map(anchorEvidenceId)));
    for (const receipt of snapshot.calendarRegistrySummary?.receipts || []) {
        if (receipt.status !== 'accepted_temporal_receipt' || receipt.mutationAllowed) continue;
        const evidenceId = `evidence:calendar:${receipt.id}`;
        const noteId = receipt.sourceNoteIds[0];
        pushEvidence({ id: evidenceId, kind: 'calendarRegistry', noteId, sourceId: receipt.id, confidence: 0.86 });
        atoms.push(atom(
            'timeAnchor',
            receipt.affectedGraphAtoms[0] || atomId('timeAnchor', receipt.calendarAnchorId),
            receipt.calendarAnchorId,
            receipt.displayDate,
            noteId,
            undefined,
            undefined,
            [evidenceId],
        ));
    }

    for (const relationship of snapshot.relationships) {
        const id = `fact:relationship:${relationship.id}`;
        const lane = isCooccurrence(relationship.relationType) ? 'cooccurrenceWeak' : 'relationshipFact';
        const evidenceIds = ensureAnchorEvidence(relationship.evidenceAnchorIds);
        const edgeKey = compilerEdgeKey(relationship.sourceEntityId, relationship.targetEntityId, relationship.relationType);
        const legacyKey = compilerEdgeKey(relationship.sourceEntityId, relationship.targetEntityId, relationship.relationType === 'co_occurs_with' ? 'anchored-cooccurrence' : relationship.relationType);
        if (lane === 'cooccurrenceWeak') {
            bundles.push(bundleLike(id, lane, relationship.relationType, relationship.id, relationship.status, evidenceIds, relationship.confidence, relationship.sourceEntityId, relationship.targetEntityId));
            provenanceByEdge.set(edgeKey, { bundleId: id });
            provenanceByEdge.set(legacyKey, { bundleId: id });
            continue;
        }
        facts.push(factLike(id, lane, relationship.relationType, relationship.id, relationship.status, evidenceIds, relationship.confidence));
        roles.push(role(id, 'source', atomId('entity', relationship.sourceEntityId), relationship.confidence), role(id, 'target', atomId('entity', relationship.targetEntityId), relationship.confidence));
        for (const evidenceId of evidenceIds) roles.push(role(id, 'evidence', evidenceId, relationship.confidence));
        projectedEdges.push(projection(`projection:fact-role:${relationship.id}:source`, id, atomId('entity', relationship.sourceEntityId), 'role:source', 'factRole', relationship.confidence, id));
        projectedEdges.push(projection(`projection:fact-role:${relationship.id}:target`, id, atomId('entity', relationship.targetEntityId), 'role:target', 'factRole', relationship.confidence, id));
        provenanceByEdge.set(edgeKey, { factId: id });
        provenanceByEdge.set(legacyKey, { factId: id });
    }
    for (const edge of snapshot.temporalEdges) pushStoryFact(edge.id, 'temporalFact', edge.relationType, edge.sourceId, edge.targetId, edge.evidenceIds, edge.confidence, 'accepted', 'source', 'target');
    for (const edge of snapshot.causalEdges) pushStoryFact(edge.id, 'causalFact', edge.relationType, edge.sourceId, edge.targetId, edge.evidenceIds, edge.confidence, causalCompilerStatus(edge), 'cause', 'effect');
    for (const state of snapshot.memoryState) {
        const id = `fact:memory:${state.id}`;
        const evidenceIds = ensureAnchorEvidence(state.evidenceIds);
        facts.push(factLike(id, 'memoryState', state.key, state.id, 'accepted', evidenceIds, 0.72));
        roles.push(role(id, 'subject', atomId('entity', state.entityId), 0.72), role(id, 'state', atomId('state', state.id), 0.72));
        for (const evidenceId of evidenceIds) roles.push(role(id, 'evidence', evidenceId, 0.72));
    }
    pushDocumentCompilerOutputs();
    for (const edge of snapshot.edges) {
        const provenance = provenanceByEdge.get(compilerEdgeKey(edge.sourceId, edge.targetId, edge.type)) || {};
        projectedEdges.push({ id: `projection:legacy:${edge.id}`, sourceId: atomId('entity', edge.sourceId), targetId: atomId('entity', edge.targetId), edgeType: edge.type, projectionKind: 'legacyBinary', sourceFactId: provenance.factId, sourceBundleId: provenance.bundleId, confidence: edge.confidence });
    }

    for (const fact of facts) atoms.push(atom('relationFact', atomId('relationFact', fact.id), fact.id, fact.predicate, undefined, undefined, undefined, fact.evidenceIds));
    const output: GraphCompilerOutput = { schemaVersion: 'phoenix-graph-compiler/v1', scopeKind: snapshot.scopeKind, scopeId: snapshot.scopeId, builtAt: snapshot.builtAt, atoms, evidenceAnchors, bundles, facts, roles, projectedEdges, receipts: emptyReceipts() };
    output.receipts = computeReceipts(output);
    return output;

    function pushStoryFact(idSource: string, lane: GraphCompilerFactLane, predicate: string, sourceId: string, targetId: string, evidenceSourceIds: string[], confidence: number, status: string, leftRole: string, rightRole: string): void {
        const id = `fact:${lane}:${idSource}`;
        const evidenceIds = ensureAnchorEvidence(evidenceSourceIds);
        facts.push(factLike(id, lane, predicate, idSource, status, evidenceIds, confidence));
        roles.push(role(id, leftRole, atomId('event', sourceId), confidence), role(id, rightRole, atomId('event', targetId), confidence));
        for (const evidenceId of evidenceIds) roles.push(role(id, 'evidence', evidenceId, confidence));
        projectedEdges.push(projection(`projection:${lane}:${idSource}`, atomId('event', sourceId), atomId('event', targetId), predicate, 'legacyBinary', confidence, id));
    }

    function pushDocumentCompilerOutputs(): void {
        const compiler = snapshot.documentCompilerSummary;
        if (!compiler) return;
        const evidenceSpans = new Map((snapshot.documentSidecarSummary?.evidenceSpans || []).map((span) => [span.id, span]));
        const mentionAtomIds = new Map<string, string>();
        for (const mention of compiler.entityMentions.filter((row) => row.status === 'pending_commit')) {
            const evidenceIds = mention.evidenceSpanIds.map(documentEvidenceId);
            const atomIdValue = atomId('documentMention', mention.id);
            mentionAtomIds.set(mention.id, atomIdValue);
            atoms.push(atom('concept', atomIdValue, mention.id, mention.surface, mention.noteId, undefined, undefined, evidenceIds));
            for (const evidenceId of mention.evidenceSpanIds) pushDocumentEvidence(evidenceId);
        }
        for (const hyperedge of compiler.hyperedges.filter((row) => row.status === 'pending_commit')) {
            const id = `fact:document-hyperedge:${hyperedge.id}`;
            const evidenceIds = hyperedge.evidenceSpanIds.map(documentEvidenceId);
            facts.push(factLike(id, 'relationshipFact', hyperedge.predicate, hyperedge.id, 'accepted', evidenceIds, hyperedge.confidence));
            for (const evidenceId of hyperedge.evidenceSpanIds) pushDocumentEvidence(evidenceId);
            for (const [index, hyperRole] of hyperedge.roles.entries()) {
                const atomIdValue = atomIdForDocumentRole(hyperRole.targetKind, hyperRole.targetId, hyperRole.surface || hyperRole.role);
                roles.push(role(id, hyperRole.role, atomIdValue, hyperRole.confidence));
                projectedEdges.push(projection(
                    `projection:document-hyperedge:${slug(`${hyperedge.id}:${hyperRole.role}:${index}`)}`,
                    atomId('relationFact', id),
                    atomIdValue,
                    `role:${hyperRole.role}`,
                    'factRole',
                    hyperRole.confidence,
                    id,
                ));
            }
        }

        function pushDocumentEvidence(evidenceSpanId: string): void {
            const span = evidenceSpans.get(evidenceSpanId);
            pushEvidence({
                id: documentEvidenceId(evidenceSpanId),
                kind: 'sourceSpan',
                noteId: span?.noteId,
                chunkId: span?.chunkId,
                sourceRange: span ? { start: span.start, end: span.end } : null,
                sourceId: evidenceSpanId,
                confidence: span?.confidence.score || 0.7,
            });
        }

        function atomIdForDocumentRole(targetKind: string, targetId: string, label: string): string {
            if (targetKind === 'entity_mention') return mentionAtomIds.get(targetId) || atomId('documentMention', targetId);
            if (targetKind === 'evidence_span') return documentEvidenceId(targetId);
            const atomIdValue = atomId('documentUnit', targetId);
            atoms.push(atom('claim', atomIdValue, targetId, label, undefined, undefined, undefined, []));
            return atomIdValue;
        }
    }
}

function causalCompilerStatus(edge: GraphRebuildCausalEdge): string {
    if (edge.status === 'accepted' || edge.status === 'supported') return 'accepted';
    if (edge.status === 'rejected' || edge.status === 'invalidated' || edge.status === 'contradicted') return 'rejected';
    return 'review';
}

function computeReceipts(output: GraphCompilerOutput): GraphCompileReceipts {
    const roots = new Map<GraphCompilerFactLane, GraphRootReceipt>();
    const root = (lane: GraphCompilerFactLane) => roots.get(lane) || roots.set(lane, { lane, ...emptyCounters() }).get(lane)!;
    for (const atomRow of output.atoms) root(compilerLaneForAtom(atomRow.kind)).atoms += 1;
    for (const evidence of output.evidenceAnchors) root('anchorEvidence').evidenceAnchors += 1;
    for (const bundle of output.bundles) root(bundle.lane).bundles += 1;
    for (const fact of output.facts) root(fact.lane).facts += 1;
    const factLane = new Map(output.facts.map((fact) => [fact.id, fact.lane]));
    for (const roleRow of output.roles) root(factLane.get(roleRow.factId) || 'relationshipFact').roles += 1;
    for (const edge of output.projectedEdges) root(projectionLane(edge, output)).projectedEdges += 1;
    return { roots: [...roots.values()], counters: { ...emptyCounters(), atoms: output.atoms.length, evidenceAnchors: output.evidenceAnchors.length, bundles: output.bundles.length, facts: output.facts.length, roles: output.roles.length, projectedEdges: output.projectedEdges.length }, invariantFailures: [] };
}

function projectionLane(edge: GraphCompilerProjectedEdge, output: GraphCompilerOutput): GraphCompilerFactLane {
    if (edge.sourceFactId) return output.facts.find((fact) => fact.id === edge.sourceFactId)?.lane || 'relationshipFact';
    if (edge.sourceBundleId) return output.bundles.find((bundle) => bundle.id === edge.sourceBundleId)?.lane || 'cooccurrenceWeak';
    return 'documentSpine';
}

function atom(kind: GraphCompilerAtomKind, id: string, sourceId: string, label: string, noteId?: string, chunkId?: string, entityId?: string, evidenceIds: string[] = []): GraphCompilerAtom {
    return { id, kind, sourceId, label, noteId, chunkId, entityId, evidenceIds };
}

function factLike(id: string, lane: GraphCompilerFactLane, predicate: string, sourceRecordId: string, status: string, evidenceIds: string[], confidence: number): GraphCompilerFactLike {
    return { id, lane, predicate, sourceRecordId, status, evidenceIds, confidence };
}

function bundleLike(id: string, lane: GraphCompilerFactLane, predicate: string, sourceRecordId: string, status: string, evidenceIds: string[], confidence: number, left: string, right: string): GraphCompilerFactBundle {
    return {
        ...factLike(id, lane, predicate, sourceRecordId, status, evidenceIds, confidence),
        bundleKind: bundleKind(predicate, evidenceIds.length),
        groupKey: bundleGroupKey(predicate, left, right),
    };
}

function role(factId: string, roleName: string, atomIdValue: string, confidence: number): GraphCompilerFactRole {
    return { factId, role: roleName, atomId: atomIdValue, confidence };
}

function projection(id: string, sourceId: string, targetId: string, edgeType: string, projectionKind: string, confidence: number, sourceFactId?: string): GraphCompilerProjectedEdge {
    return { id, sourceId, targetId, edgeType, projectionKind, sourceFactId, confidence };
}

function compilerLaneForAtom(kind: GraphCompilerAtomKind): GraphCompilerFactLane {
    if (kind === 'document' || kind === 'documentRoot' || kind === 'laneRoot' || kind === 'root') return 'documentSpine';
    if (kind === 'chunk') return 'chunkSpine';
    if (kind === 'entity' || kind === 'concept') return 'entityAnchor';
    if (kind === 'event' || kind === 'timeAnchor') return 'eventIdentity';
    if (kind === 'state') return 'memoryState';
    if (kind === 'claim' || kind === 'relationFact') return 'relationshipFact';
    if (kind === 'frame') return 'anchorEvidence';
    return 'anchorEvidence';
}

function compilerLanes(): GraphCompilerFactLane[] {
    return [
        'documentSpine',
        'chunkSpine',
        'entityAnchor',
        'relationshipFact',
        'cooccurrenceWeak',
        'eventIdentity',
        'temporalFact',
        'causalFact',
        'memoryState',
        'entityLinker',
        'anchorEvidence',
    ];
}

function isCooccurrence(type: string): boolean {
    return type.includes('co_occurs') || type.includes('co-occurs') || type.includes('cooccurrence');
}

function bundleKind(type: string, evidenceCount: number): GraphCompilerEvidenceBundleKind {
    const value = type.toLowerCase();
    if (value.includes('semantic') || value.includes('similar')) return 'semanticSimilarity';
    if (value.includes('shadow') || value.includes('identity')) return 'shadowIdentity';
    return evidenceCount <= 1 ? 'span' : 'neighborhood';
}

function bundleGroupKey(type: string, left: string, right: string): string {
    const [first, second] = [left, right].sort();
    return `${type}:${first}:${second}`;
}

function atomId(kind: string, sourceId: string): string {
    return `atom:${kind}:${sourceId}`;
}

function anchorEvidenceId(id: string): string {
    return `evidence:anchor:${id}`;
}

function mentionEvidenceId(id: string): string {
    return `evidence:mention:${id}`;
}

function eventEvidenceId(id: string): string {
    return `evidence:event:${id}`;
}

function documentEvidenceId(id: string): string {
    return `evidence:document:${id}`;
}

function compilerEdgeKey(left: string, right: string, edgeType: string): string {
    return [left, right].sort().join(':') + `:${edgeType}`;
}

function slug(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'row';
}

function emptyReceipts(): GraphCompileReceipts {
    return { roots: [], counters: emptyCounters(), invariantFailures: [] };
}

function emptyCounters(): GraphCompileCounters {
    return { atoms: 0, evidenceAnchors: 0, bundles: 0, facts: 0, roles: 0, projectedEdges: 0, invariantFailures: 0 };
}
