import type { GraphRebuildChunk } from './graph-rebuild-snapshot';
import {
    buildFallbackDocumentProfileSummary,
    documentUnitWeight,
    type DocumentProfileKind,
    type GraphDocumentProfileSummary,
} from './graph-document-profile';
import type {
    GraphDocumentSemanticArgument,
    GraphDocumentSemanticAttributionFrame,
    GraphDocumentSemanticConditionalFrame,
    GraphDocumentSemanticDocument,
    GraphDocumentSemanticFactualityEnvelope,
    GraphDocumentSemanticFrame,
    GraphDocumentSemanticEventOrdering,
    GraphDocumentSemanticProposition,
    GraphDocumentSemanticRecoveredArgument,
    GraphDocumentSemanticScope,
    GraphDocumentSemanticSituationInstance,
    GraphDocumentSemanticSpeechOrBeliefFrame,
    GraphDocumentSemanticStateInterval,
    GraphDocumentSemanticSummary,
    GraphDocumentSemanticTemporalConflict,
} from './graph-document-semantic';

export type StructuralUnitKind =
    | 'document'
    | 'section'
    | 'subsection'
    | 'paragraph_group'
    | 'paragraph'
    | 'sentence'
    | 'list'
    | 'table'
    | 'figure'
    | 'code_block'
    | 'caption';

export type ProseSidecarUnitKind =
    | 'chapter'
    | 'scene'
    | 'dialogue_block'
    | 'action_block';

export type RhetoricalUnitKind =
    | 'claim'
    | 'evidence'
    | 'definition'
    | 'example'
    | 'contrast'
    | 'method'
    | 'result'
    | 'instruction'
    | 'decision'
    | 'question';

export type GraphBearingUnitKind =
    | 'event'
    | 'state_change'
    | 'relation_bundle'
    | 'procedure_step'
    | 'n_ary_claim';

export type RetrievalUnitKind =
    | 'leaf_chunk'
    | 'parent_chunk'
    | 'citation_span'
    | 'cross_doc_topic_packet';

export type DocumentUnitKind =
    | StructuralUnitKind
    | ProseSidecarUnitKind
    | RhetoricalUnitKind
    | GraphBearingUnitKind
    | RetrievalUnitKind;

export type DocumentSidecarLens =
    | 'surface'
    | 'adaptive_leaf'
    | 'parent_hierarchy'
    | 'rhetorical'
    | 'graph_fact'
    | 'cross_doc';

export interface StructureConfidence {
    score: number;
    source: DocumentSidecarLens;
    reasons: string[];
}

export interface ChunkLineage {
    noteId: string;
    documentUnitId: string;
    parentUnitIds: string[];
    chunkId?: string;
    sourceStart: number;
    sourceEnd: number;
    ordinal?: number;
    lens: DocumentSidecarLens;
}

export interface DocumentUnit {
    id: string;
    noteId: string;
    kind: DocumentUnitKind;
    label: string;
    start: number;
    end: number;
    depth: number;
    parentId?: string;
    childIds: string[];
    confidence: StructureConfidence;
    lineage: ChunkLineage;
    anchorPolicy: 'sidecar_only';
}

export interface DocumentSection extends DocumentUnit {
    kind: 'document' | 'section' | 'subsection' | 'chapter' | 'scene';
    heading?: string;
    ordinal: number;
}

export interface DocumentRegion extends DocumentUnit {
    kind: StructuralUnitKind | ProseSidecarUnitKind;
    regionRole: 'layout' | 'prose' | 'semantic';
}

export interface RhetoricalUnit extends DocumentUnit {
    kind: RhetoricalUnitKind;
    cue: string;
    evidenceSpanIds: string[];
}

export interface RetrievalUnit extends DocumentUnit {
    kind: RetrievalUnitKind;
    targetChunkIds: string[];
    evidenceSpanIds: string[];
}

export interface GraphFactCandidate extends DocumentUnit {
    kind: GraphBearingUnitKind;
    subjectSurfaces: string[];
    objectSurfaces: string[];
    roles?: GraphFactCandidateRole[];
    predicate?: string;
    relationType?: string;
    frame?: GraphDocumentSemanticFrame;
    frameFamily?: string;
    frameConfidence?: number;
    factuality?: GraphDocumentSemanticFactualityEnvelope;
    attributionFrame?: GraphDocumentSemanticAttributionFrame;
    conditionalFrame?: GraphDocumentSemanticConditionalFrame;
    speechOrBeliefFrame?: GraphDocumentSemanticSpeechOrBeliefFrame;
    documentArgumentRecoveries?: GraphDocumentSemanticRecoveredArgument[];
    semanticSituationId?: string;
    stateIntervalIds?: string[];
    eventOrderingIds?: string[];
    temporalConflictIds?: string[];
    semanticPropositionId?: string;
    scope?: GraphDocumentSemanticScope[];
    evidenceSpanIds: string[];
    reviewState: 'proposed';
}

export interface GraphFactCandidateRole {
    role: string;
    syntacticRoles?: string[];
    surfaces: string[];
    entityIds: string[];
    confidence: number;
    failureReasons: string[];
    recoveryKinds?: string[];
    detectorReasons?: string[];
}

export interface EvidenceSpan {
    id: string;
    noteId: string;
    unitId: string;
    chunkId?: string;
    start: number;
    end: number;
    preview: string;
    textHash: string;
    confidence: StructureConfidence;
    lineage: ChunkLineage;
    anchorPolicy: 'sidecar_only';
}

export interface GraphDocumentSidecarCounters {
    documents: number;
    units: number;
    sections: number;
    regions: number;
    rhetoricalUnits: number;
    retrievalUnits: number;
    graphFactCandidates: number;
    situationInstances?: number;
    stateIntervals?: number;
    eventOrderings?: number;
    temporalConflicts?: number;
    evidenceSpans: number;
    paragraphGroups: number;
    paragraphs: number;
    sentences: number;
    leafChunks: number;
    parentChunks: number;
    citationSpans: number;
    crossDocTopicPackets: number;
    userAnchorPromotions: 0;
    truncatedSentenceUnits: number;
    byKind: Record<string, number>;
}

export interface GraphDocumentSidecarSummary {
    schemaVersion: 'phoenix-document-sidecar/v1';
    anchorPolicy: 'sidecar_never_promotes_anchors';
    builtAt: number;
    noteIds: string[];
    units: DocumentUnit[];
    sections: DocumentSection[];
    regions: DocumentRegion[];
    rhetoricalUnits: RhetoricalUnit[];
    retrievalUnits: RetrievalUnit[];
    graphFactCandidates: GraphFactCandidate[];
    situationInstances?: GraphDocumentSemanticSituationInstance[];
    stateIntervals?: GraphDocumentSemanticStateInterval[];
    eventOrderings?: GraphDocumentSemanticEventOrdering[];
    temporalConflicts?: GraphDocumentSemanticTemporalConflict[];
    evidenceSpans: EvidenceSpan[];
    documentProfileSummary?: GraphDocumentProfileSummary;
    counters: GraphDocumentSidecarCounters;
}

export interface BuildGraphDocumentSidecarInput {
    noteIds: string[];
    noteTexts: Record<string, string>;
    chunks: GraphRebuildChunk[];
    builtAt: number;
    documentProfileSummary?: GraphDocumentProfileSummary;
    documentSemanticSummary?: GraphDocumentSemanticSummary;
}

interface ParagraphSpan {
    start: number;
    end: number;
    text: string;
}

interface HeadingSpan {
    start: number;
    end: number;
    level: number;
    label: string;
}

interface GraphFactProposal {
    kind: GraphBearingUnitKind;
    paragraph: ParagraphSpan;
    parentId: string;
    chunkId?: string;
    evidenceSpanId?: string;
    score: number;
    priority: number;
}

interface BuildContext {
    builtAt: number;
    units: DocumentUnit[];
    sections: DocumentSection[];
    regions: DocumentRegion[];
    rhetoricalUnits: RhetoricalUnit[];
    retrievalUnits: RetrievalUnit[];
    graphFactCandidates: GraphFactCandidate[];
    situationInstances: GraphDocumentSemanticSituationInstance[];
    stateIntervals: GraphDocumentSemanticStateInterval[];
    eventOrderings: GraphDocumentSemanticEventOrdering[];
    temporalConflicts: GraphDocumentSemanticTemporalConflict[];
    evidenceSpans: EvidenceSpan[];
    documentProfileSummary: GraphDocumentProfileSummary;
    situationByPropositionId: Map<string, GraphDocumentSemanticSituationInstance>;
    stateIntervalIdsBySituationId: Map<string, string[]>;
    eventOrderingIdsBySituationId: Map<string, string[]>;
    temporalConflictIdsBySituationId: Map<string, string[]>;
    childIdsByParent: Map<string, string[]>;
    sentenceLimitHits: number;
}

const PARAGRAPHS_PER_GROUP = 4;
const MAX_SENTENCE_UNITS_PER_NOTE = 2400;
const PREVIEW_CHARS = 180;

export function buildGraphDocumentSidecar(input: BuildGraphDocumentSidecarInput): GraphDocumentSidecarSummary {
    const documentProfileSummary = input.documentProfileSummary
        || buildFallbackDocumentProfileSummary(input.noteTexts, input.builtAt);
    const context: BuildContext = {
        builtAt: input.builtAt,
        units: [],
        sections: [],
        regions: [],
        rhetoricalUnits: [],
        retrievalUnits: [],
        graphFactCandidates: [],
        situationInstances: [],
        stateIntervals: [],
        eventOrderings: [],
        temporalConflicts: [],
        evidenceSpans: [],
        documentProfileSummary,
        situationByPropositionId: new Map(),
        stateIntervalIdsBySituationId: new Map(),
        eventOrderingIdsBySituationId: new Map(),
        temporalConflictIdsBySituationId: new Map(),
        childIdsByParent: new Map(),
        sentenceLimitHits: 0,
    };
    const chunksByNote = groupChunksByNote(input.chunks);
    const semanticsByNote = new Map(
        (input.documentSemanticSummary?.documents || []).map((document) => [document.noteId, document]),
    );
    for (const noteId of input.noteIds) {
        const text = input.noteTexts[noteId] || '';
        buildNoteSidecar(context, noteId, text, chunksByNote.get(noteId) || [], semanticsByNote.get(noteId));
    }
    buildCrossDocPackets(context, input.noteIds, input.chunks);
    for (const unit of context.units) unit.childIds = context.childIdsByParent.get(unit.id) || [];
    for (const section of context.sections) section.childIds = context.childIdsByParent.get(section.id) || [];
    return {
        schemaVersion: 'phoenix-document-sidecar/v1',
        anchorPolicy: 'sidecar_never_promotes_anchors',
        builtAt: input.builtAt,
        noteIds: [...input.noteIds],
        units: context.units,
        sections: context.sections,
        regions: context.regions,
        rhetoricalUnits: context.rhetoricalUnits,
        retrievalUnits: context.retrievalUnits,
        graphFactCandidates: context.graphFactCandidates,
        situationInstances: context.situationInstances,
        stateIntervals: context.stateIntervals,
        eventOrderings: context.eventOrderings,
        temporalConflicts: context.temporalConflicts,
        evidenceSpans: context.evidenceSpans,
        documentProfileSummary,
        counters: buildCounters(context),
    };
}

function buildNoteSidecar(context: BuildContext, noteId: string, text: string, chunks: GraphRebuildChunk[], semantics?: GraphDocumentSemanticDocument): void {
    const doc = addSection(context, noteId, 'document', 'Document', 0, text.length, 0, undefined, 0, confidence('surface', 0.98, ['note_root']));
    const headings = headingSpans(text);
    const sections = headings.length ? buildHeadingSections(context, noteId, text.length, doc, headings) : [
        addSection(context, noteId, 'section', 'Document body', 0, text.length, 1, doc.id, 0, confidence('surface', 0.56, ['implicit_section'])),
    ];
    const paragraphs = paragraphSpans(text);
    const paragraphUnits = paragraphs.map((paragraph, index) => {
        const parent = nearestSection(sections, paragraph.start);
        return addUnit(context, {
            noteId,
            kind: 'paragraph',
            label: `Paragraph ${index + 1}`,
            start: paragraph.start,
            end: paragraph.end,
            depth: parent.depth + 1,
            parentId: parent.id,
            confidence: confidence('surface', 0.9, ['blank_line_boundary']),
            lens: 'surface',
            ordinal: index,
        });
    });
    buildParagraphGroups(context, noteId, paragraphs, paragraphUnits, sections);
    buildSentenceUnits(context, noteId, paragraphs, paragraphUnits);
    buildSurfaceRegions(context, noteId, text, paragraphs, paragraphUnits);
    buildRetrievalUnits(context, noteId, chunks, sections);
    buildRhetoricalAndFactUnits(context, noteId, paragraphs, paragraphUnits, chunks, !semantics?.propositions.length);
    if (semantics?.propositions.length) {
        appendSemanticContinuity(context, semantics);
        buildSemanticFactUnits(context, noteId, paragraphs, paragraphUnits, chunks, semantics.propositions);
    }
}

function buildHeadingSections(
    context: BuildContext,
    noteId: string,
    textEnd: number,
    document: DocumentSection,
    headings: HeadingSpan[],
): DocumentSection[] {
    const sectionEnds = headingSectionEnds(headings, textEnd);
    const open: Array<{ level: number; section: DocumentSection }> = [];
    return headings.map((heading, index) => {
        while (open.length && open[open.length - 1].level >= heading.level) open.pop();
        const parent = open.length ? open[open.length - 1].section : document;
        const section = addSection(
            context,
            noteId,
            heading.level === 1 ? 'section' : 'subsection',
            heading.label,
            heading.start,
            sectionEnds[index],
            heading.level,
            parent.id,
            index,
            confidence('surface', 0.92, ['markdown_heading']),
            heading.label,
        );
        open.push({ level: heading.level, section });
        return section;
    });
}

function headingSectionEnds(headings: HeadingSpan[], textEnd: number): number[] {
    const ends = headings.map(() => textEnd);
    const open: number[] = [];
    for (let index = 0; index < headings.length; index += 1) {
        while (open.length && headings[open[open.length - 1]].level >= headings[index].level) {
            ends[open.pop() as number] = headings[index].start;
        }
        open.push(index);
    }
    return ends;
}

function appendSemanticContinuity(context: BuildContext, semantics: GraphDocumentSemanticDocument): void {
    for (const situation of semantics.situations || []) {
        context.situationInstances.push(situation);
        context.situationByPropositionId.set(situation.propositionId, situation);
    }
    for (const interval of semantics.stateIntervals || []) {
        context.stateIntervals.push(interval);
        for (const situationId of interval.mentionSituationIds) {
            appendMapValue(context.stateIntervalIdsBySituationId, situationId, interval.id);
        }
    }
    for (const ordering of semantics.eventOrderings || []) {
        context.eventOrderings.push(ordering);
        appendMapValue(context.eventOrderingIdsBySituationId, ordering.sourceSituationId, ordering.id);
        appendMapValue(context.eventOrderingIdsBySituationId, ordering.targetSituationId, ordering.id);
    }
    for (const conflict of semantics.temporalConflicts || []) {
        context.temporalConflicts.push(conflict);
        for (const situationId of conflict.situationIds) {
            appendMapValue(context.temporalConflictIdsBySituationId, situationId, conflict.id);
        }
    }
}

function appendMapValue(map: Map<string, string[]>, key: string, value: string): void {
    const values = map.get(key) || [];
    if (!values.includes(value)) values.push(value);
    map.set(key, values);
}

function buildParagraphGroups(
    context: BuildContext,
    noteId: string,
    paragraphs: ParagraphSpan[],
    paragraphUnits: DocumentUnit[],
    sections: DocumentSection[],
): void {
    for (let index = 0; index < paragraphs.length; index += PARAGRAPHS_PER_GROUP) {
        const slice = paragraphs.slice(index, index + PARAGRAPHS_PER_GROUP);
        if (!slice.length) continue;
        const first = slice[0];
        const last = slice[slice.length - 1];
        const parent = nearestSection(sections, first.start);
        const group = addRegion(context, {
            noteId,
            kind: 'paragraph_group',
            label: `Paragraph group ${Math.floor(index / PARAGRAPHS_PER_GROUP) + 1}`,
            start: first.start,
            end: last.end,
            depth: parent.depth + 1,
            parentId: parent.id,
            confidence: confidence('parent_hierarchy', 0.76, ['paragraph_group_window']),
            regionRole: 'semantic',
            lens: 'parent_hierarchy',
            ordinal: index / PARAGRAPHS_PER_GROUP,
        });
        for (const unit of paragraphUnits.slice(index, index + PARAGRAPHS_PER_GROUP)) attachChild(context, group.id, unit.id);
        addRetrievalUnit(context, noteId, 'parent_chunk', group.label, group.start, group.end, group.id, [], [], confidence('parent_hierarchy', 0.76, ['paragraph_group_parent']));
    }
}

function buildSentenceUnits(context: BuildContext, noteId: string, paragraphs: ParagraphSpan[], paragraphUnits: DocumentUnit[]): void {
    let emitted = 0;
    for (let index = 0; index < paragraphs.length; index += 1) {
        if (emitted >= MAX_SENTENCE_UNITS_PER_NOTE) {
            context.sentenceLimitHits += 1;
            return;
        }
        for (const span of sentenceSpans(paragraphs[index])) {
            if (emitted >= MAX_SENTENCE_UNITS_PER_NOTE) {
                context.sentenceLimitHits += 1;
                return;
            }
            addUnit(context, {
                noteId,
                kind: 'sentence',
                label: `Sentence ${emitted + 1}`,
                start: span.start,
                end: span.end,
                depth: paragraphUnits[index].depth + 1,
                parentId: paragraphUnits[index].id,
                confidence: confidence('surface', 0.82, ['sentence_boundary']),
                lens: 'surface',
                ordinal: emitted,
            });
            emitted += 1;
        }
    }
}

function buildSurfaceRegions(
    context: BuildContext,
    noteId: string,
    text: string,
    paragraphs: ParagraphSpan[],
    paragraphUnits: DocumentUnit[],
): void {
    addLineRegions(context, noteId, text, 'code_block', /^```/);
    addTableRegions(context, noteId, text);
    addLineRegions(context, noteId, text, 'list', /^\s*(?:[-*+]|\d+[.)])\s+/);
    for (let index = 0; index < paragraphs.length; index += 1) {
        const paragraph = paragraphs[index];
        const lower = paragraph.text.toLowerCase();
        const parentId = paragraphUnits[index].id;
        if (isDialogue(paragraph.text)) {
            addRegion(context, regionInput(noteId, 'dialogue_block', 'Dialogue block', paragraph, parentId, 'prose', 'surface', adaptedScore(context, noteId, 'dialogue_block', paragraph.start, 0.84), ['quote_or_speech_cue', 'document_profile_weighted']));
        } else if (EVENT_CUES.some((cue) => lower.includes(cue))) {
            addRegion(context, regionInput(noteId, 'action_block', 'Action block', paragraph, parentId, 'prose', 'surface', adaptedScore(context, noteId, 'action_block', paragraph.start, 0.7), ['event_cue', 'document_profile_weighted']));
        }
        const explicit = paragraph.text.match(/^\s*(chapter|scene)\s+([^\n]+)/i);
        if (explicit) {
            const kind = explicit[1].toLowerCase() as 'chapter' | 'scene';
            addSection(context, noteId, kind, explicit[0].trim(), paragraph.start, paragraph.end, 1, parentId, index, confidence('surface', adaptedScore(context, noteId, kind, paragraph.start, 0.9), ['explicit_prose_marker', 'document_profile_weighted']), explicit[0].trim());
        }
    }
}

function buildRetrievalUnits(context: BuildContext, noteId: string, chunks: GraphRebuildChunk[], sections: DocumentSection[]): void {
    for (const chunk of chunks) {
        const parent = nearestSection(sections, chunk.start);
        addRetrievalUnit(context, noteId, 'leaf_chunk', `Chunk ${chunk.ordinal + 1}`, chunk.start, chunk.end, parent.id, [chunk.id], [], confidence('adaptive_leaf', 0.95, [chunk.splitReason || chunk.source]));
    }
}

function buildRhetoricalAndFactUnits(
    context: BuildContext,
    noteId: string,
    paragraphs: ParagraphSpan[],
    paragraphUnits: DocumentUnit[],
    chunks: GraphRebuildChunk[],
    includeHeuristicFacts: boolean,
): void {
    const proposals: GraphFactProposal[] = [];
    for (let index = 0; index < paragraphs.length; index += 1) {
        const paragraph = paragraphs[index];
        const parentId = paragraphUnits[index].id;
        const rhetorical = inferRhetoricalKinds(paragraph.text)
            .slice(0, 2)
            .sort((left, right) => unitWeight(context, noteId, right.kind, paragraph.start) - unitWeight(context, noteId, left.kind, paragraph.start));
        const evidenceSpan = rhetorical.length ? addEvidenceSpan(context, noteId, paragraph, parentId, undefined, confidence('rhetorical', adaptedScore(context, noteId, 'evidence', paragraph.start, 0.72), ['paragraph_rhetorical_cue', 'document_profile_weighted'])) : undefined;
        for (const row of rhetorical) {
            const unit = addRhetoricalUnit(context, noteId, row.kind, row.kind, paragraph, parentId, row.cue, evidenceSpan ? [evidenceSpan.id] : [], adaptedScore(context, noteId, row.kind, paragraph.start, 0.72));
            if (row.kind === 'evidence' && evidenceSpan) addRetrievalUnit(context, noteId, 'citation_span', 'Citation span', paragraph.start, paragraph.end, unit.id, [], [evidenceSpan.id], confidence('rhetorical', 0.8, ['evidence_unit']));
        }
        const chunk = chunks.find((candidate) => candidate.start <= paragraph.start && candidate.end >= paragraph.end);
        if (!includeHeuristicFacts) continue;
        const profile = documentProfileAt(context, noteId, paragraph.start);
        const facts = inferGraphFactKinds(paragraph.text, chunk, profile)
            .sort((left, right) => unitWeight(context, noteId, right, paragraph.start) - unitWeight(context, noteId, left, paragraph.start));
        const fact = facts[0];
        if (fact) {
            const score = adaptedScore(context, noteId, fact, paragraph.start, 0.66);
            proposals.push({
                kind: fact,
                paragraph,
                parentId,
                chunkId: chunk?.id,
                evidenceSpanId: evidenceSpan?.id,
                score,
                priority: score + graphFactSpecificity(fact, paragraph.text, chunk) * 0.12,
            });
        }
    }
    const budget = graphFactBudget(context, noteId, chunks.length, paragraphs.length);
    proposals
        .sort((left, right) => right.priority - left.priority || left.paragraph.start - right.paragraph.start)
        .slice(0, budget)
        .sort((left, right) => left.paragraph.start - right.paragraph.start)
        .forEach((proposal) => {
            const spanId = proposal.evidenceSpanId || addEvidenceSpan(
                context,
                noteId,
                proposal.paragraph,
                proposal.parentId,
                proposal.chunkId,
                confidence('graph_fact', adaptedScore(context, noteId, proposal.kind, proposal.paragraph.start, 0.68), ['graph_fact_cue', 'document_profile_weighted']),
            ).id;
            addGraphFactCandidate(
                context,
                noteId,
                proposal.kind,
                proposal.paragraph,
                proposal.parentId,
                proposal.chunkId,
                [spanId],
                proposal.score,
            );
        });
}

function buildSemanticFactUnits(
    context: BuildContext,
    noteId: string,
    paragraphs: ParagraphSpan[],
    paragraphUnits: DocumentUnit[],
    chunks: GraphRebuildChunk[],
    propositions: GraphDocumentSemanticProposition[],
): void {
    const budget = graphFactBudget(context, noteId, chunks.length, paragraphs.length);
    const selected = propositions
        .filter((proposition) => isReviewableSemanticFact(proposition))
        .sort((left, right) => semanticFactPriority(right) - semanticFactPriority(left)
            || left.start - right.start)
        .slice(0, budget)
        .sort((left, right) => left.start - right.start);
    for (const proposition of selected) {
        const paragraphIndex = containingParagraphIndex(paragraphs, proposition.start);
        const paragraph = paragraphs[paragraphIndex];
        const parent = paragraphUnits[paragraphIndex];
        if (!paragraph || !parent) continue;
        const chunk = chunks.find((candidate) =>
            candidate.start <= proposition.start && candidate.end >= proposition.end
        );
        const span: ParagraphSpan = {
            start: proposition.start,
            end: proposition.end,
            text: proposition.preview || paragraph.text.slice(
                Math.max(0, proposition.start - paragraph.start),
                Math.max(0, proposition.end - paragraph.start),
            ),
        };
        const evidence = addEvidenceSpan(
            context,
            noteId,
            span,
            parent.id,
            chunk?.id,
            confidence('graph_fact', proposition.confidenceMillis / 1000, [
                'native_semantic_substrate',
                proposition.relationType,
            ]),
        );
        addSemanticGraphFactCandidate(
            context,
            noteId,
            proposition,
            parent.id,
            chunk?.id,
            evidence.id,
        );
    }
}

function isReviewableSemanticFact(proposition: GraphDocumentSemanticProposition): boolean {
    const predicate = proposition.predicate.toLowerCase();
    if (!predicate || predicate.length < 2 || /^(?:he|she|it|they|his|her|their|\d+(?:st|nd|rd|th))$/.test(predicate)) {
        return false;
    }
    if (proposition.reviewState === 'ledger_only' || proposition.predicateAdmission === 'ledger_only') {
        return false;
    }
    if (['participle_modifier', 'nominal_event', 'noise'].includes(proposition.predicateQuality || '')) {
        return false;
    }
    return proposition.arguments.length >= 2
        || !!proposition.attribution
        || !!proposition.conditional
        || proposition.scope.some((scope) => scope.kind !== 'assertion');
}

function semanticFactPriority(proposition: GraphDocumentSemanticProposition): number {
    const resolved = proposition.arguments.filter((argument) => !!argument.entityId).length;
    const scope = proposition.scope.filter((row) => row.kind !== 'assertion').length;
    const qualityBoost = proposition.predicateQuality === 'relation_cue' ? 80
        : proposition.predicateQuality === 'finite_verb' ? 45
            : proposition.predicateQuality === 'passive_event' || proposition.predicateQuality === 'copula_state' ? 30
                : 0;
    return proposition.confidenceMillis
        + Math.min(3, proposition.arguments.length) * 40
        + Math.min(2, resolved) * 80
        + Math.min(2, scope) * 35
        + (proposition.arguments.length >= 3 ? 60 : 0)
        + qualityBoost;
}

function addSemanticGraphFactCandidate(
    context: BuildContext,
    noteId: string,
    proposition: GraphDocumentSemanticProposition,
    parentId: string,
    chunkId: string | undefined,
    evidenceSpanId: string,
): GraphFactCandidate {
    const kind = semanticFactKind(proposition);
    const recoveredArguments = proposition.documentArgumentRecoveries || [];
    const roleRecoveries = usableRecoveredArguments(proposition);
    const roles = semanticRolesFor([...proposition.arguments, ...roleRecoveries]);
    const situation = context.situationByPropositionId.get(proposition.id);
    const unit = addUnit(context, {
        noteId,
        kind,
        label: proposition.predicate || factLabel(kind),
        start: proposition.start,
        end: proposition.end,
        depth: 4,
        parentId,
        confidence: confidence('graph_fact', proposition.confidenceMillis / 1000, [
            'native_semantic_substrate',
            proposition.relationType,
            ...(proposition.frame ? [
                `frame:${proposition.frame.frame}`,
                `frame_source:${proposition.frame.source}`,
            ] : []),
            ...(proposition.factuality ? [
                `factuality:${proposition.factuality.factuality}`,
                `speech_act:${proposition.factuality.speechAct}`,
            ] : []),
            ...roleRecoveries.slice(0, 3).map((argument) => `doc_recovery:${argument.kind}`),
            proposition.predicateQuality || 'predicate_unclassified',
            ...(proposition.qualityReasons || []).slice(0, 2),
        ]),
        lens: 'graph_fact',
    });
    const subjects = roles.filter((role) => isSubjectLikeRole(role.role)).flatMap((role) => role.surfaces);
    const objects = roles
        .filter((role) => !isSubjectLikeRole(role.role))
        .flatMap((role) => role.surfaces);
    const candidate: GraphFactCandidate = {
        ...unit,
        kind,
        subjectSurfaces: subjects,
        objectSurfaces: objects,
        roles,
        predicate: proposition.predicate,
        relationType: proposition.relationType,
        frame: proposition.frame,
        frameFamily: proposition.frame?.family,
        frameConfidence: proposition.frame ? proposition.frame.confidenceMillis / 1000 : undefined,
        factuality: proposition.factuality,
        attributionFrame: proposition.attributionFrame,
        conditionalFrame: proposition.conditionalFrame,
        speechOrBeliefFrame: proposition.speechOrBeliefFrame,
        documentArgumentRecoveries: recoveredArguments,
        semanticSituationId: situation?.id,
        stateIntervalIds: situation ? context.stateIntervalIdsBySituationId.get(situation.id) || [] : [],
        eventOrderingIds: situation ? context.eventOrderingIdsBySituationId.get(situation.id) || [] : [],
        temporalConflictIds: situation ? context.temporalConflictIdsBySituationId.get(situation.id) || [] : [],
        semanticPropositionId: proposition.id,
        scope: proposition.scope,
        evidenceSpanIds: [evidenceSpanId],
        reviewState: 'proposed',
        lineage: { ...unit.lineage, chunkId },
    };
    context.graphFactCandidates.push(candidate);
    return candidate;
}

type SemanticRoleInput = GraphDocumentSemanticArgument | GraphDocumentSemanticRecoveredArgument;

function semanticRolesFor(arguments_: SemanticRoleInput[]): GraphFactCandidateRole[] {
    const byRole = new Map<string, GraphFactCandidateRole>();
    for (const argument of arguments_) {
        if (!argument.surface) continue;
        const role = argument.semanticRole || argument.role;
        const syntacticRole = argument.syntacticRole || argument.role;
        const row = byRole.get(role) || {
            role,
            syntacticRoles: [],
            surfaces: [],
            entityIds: [],
            confidence: 0,
            failureReasons: [],
        };
        row.syntacticRoles = unique([...(row.syntacticRoles || []), syntacticRole]);
        row.surfaces = unique([...row.surfaces, argument.surface]);
        row.entityIds = unique([
            ...row.entityIds,
            ...(argument.entityId ? [argument.entityId] : []),
        ]);
        row.failureReasons = unique([
            ...row.failureReasons,
            ...failureReasonsForRole(argument),
        ]);
        row.recoveryKinds = unique([
            ...(row.recoveryKinds || []),
            ...('kind' in argument ? [argument.kind] : []),
        ]);
        row.detectorReasons = unique([
            ...(row.detectorReasons || []),
            ...('detectorReasons' in argument ? argument.detectorReasons : []),
        ]);
        const roleConfidence = isRecoveredArgument(argument)
            ? argument.confidenceMillis
            : argument.roleConfidenceMillis ?? 620;
        row.confidence = Math.max(row.confidence, Math.max(0, Math.min(1, (roleConfidence ?? 620) / 1000)));
        byRole.set(role, row);
    }
    return [...byRole.values()];
}

function failureReasonsForRole(argument: SemanticRoleInput): string[] {
    if (isRecoveredArgument(argument)) return argument.failureReasons || [];
    return argument.roleFailureReasons || [];
}

function usableRecoveredArguments(proposition: GraphDocumentSemanticProposition): GraphDocumentSemanticRecoveredArgument[] {
    return (proposition.documentArgumentRecoveries || []).filter((argument) =>
        argument.confidenceMillis >= 600,
    );
}

function isRecoveredArgument(argument: SemanticRoleInput): argument is GraphDocumentSemanticRecoveredArgument {
    return 'confidenceMillis' in argument;
}

function isSubjectLikeRole(role: string): boolean {
    return ['subject', 'actor', 'agent', 'bearer', 'experiencer', 'topic'].includes(role);
}

function semanticFactKind(proposition: GraphDocumentSemanticProposition): GraphBearingUnitKind {
    if (proposition.arguments.length + usableRecoveredArguments(proposition).length >= 3) return 'n_ary_claim';
    if (['motion', 'communication', 'causation', 'creation', 'conflict', 'decision', 'transfer'].includes(proposition.frame?.family || '')) {
        return 'event';
    }
    if (['state', 'attribute', 'identity'].some((value) => proposition.relationType.includes(value))) {
        return 'state_change';
    }
    if (['action', 'movement', 'conflict', 'creation', 'lifecycle'].includes(proposition.relationType)) {
        return 'event';
    }
    return 'relation_bundle';
}

function containingParagraphIndex(paragraphs: ParagraphSpan[], offset: number): number {
    let low = 0;
    let high = paragraphs.length - 1;
    while (low <= high) {
        const middle = low + Math.floor((high - low) / 2);
        const paragraph = paragraphs[middle];
        if (offset < paragraph.start) high = middle - 1;
        else if (offset > paragraph.end) low = middle + 1;
        else return middle;
    }
    return Math.max(0, Math.min(paragraphs.length - 1, low));
}

function buildCrossDocPackets(context: BuildContext, noteIds: string[], chunks: GraphRebuildChunk[]): void {
    if (noteIds.length < 2) return;
    const bySurface = new Map<string, Set<string>>();
    for (const chunk of chunks) {
        for (const prior of chunk.meaningFrame?.entityPriors || []) {
            const key = prior.surface.toLowerCase();
            if (!bySurface.has(key)) bySurface.set(key, new Set());
            bySurface.get(key)?.add(chunk.noteId);
        }
    }
    let ordinal = 0;
    for (const [surface, notes] of bySurface) {
        if (notes.size < 2 || ordinal >= 24) continue;
        const id = `crossdoc:${simpleId(surface)}:${ordinal}`;
        const unit = makeUnit({
            id,
            noteId: 'cross-doc',
            kind: 'cross_doc_topic_packet',
            label: surface,
            start: 0,
            end: 0,
            depth: 0,
            confidence: confidence('cross_doc', 0.7, ['surface_repeats_across_notes']),
            lens: 'cross_doc',
            ordinal,
        });
        context.units.push(unit);
        context.retrievalUnits.push({ ...unit, kind: 'cross_doc_topic_packet', targetChunkIds: [], evidenceSpanIds: [] });
        ordinal += 1;
    }
}

function addLineRegions(context: BuildContext, noteId: string, text: string, kind: 'code_block' | 'list', startsLine: RegExp): void {
    const lines = lineSpans(text);
    let runStart = -1;
    for (let index = 0; index <= lines.length; index += 1) {
        const line = lines[index];
        const match = line && startsLine.test(line.text);
        if (match && runStart < 0) runStart = index;
        if ((!match || index === lines.length) && runStart >= 0) {
            const first = lines[runStart];
            const last = lines[index - 1];
            addRegion(context, regionInput(noteId, kind, kind === 'list' ? 'List' : 'Code block', { start: first.start, end: last.end, text: text.slice(first.start, last.end) }, undefined, 'layout', 'surface', adaptedScore(context, noteId, kind, first.start, 0.9), [`${kind}_lines`, 'document_profile_weighted']));
            runStart = -1;
        }
    }
}

function addTableRegions(context: BuildContext, noteId: string, text: string): void {
    const lines = lineSpans(text);
    let runStart = -1;
    for (let index = 0; index <= lines.length; index += 1) {
        const line = lines[index];
        const match = line && line.text.includes('|') && line.text.split('|').length >= 3;
        if (match && runStart < 0) runStart = index;
        if ((!match || index === lines.length) && runStart >= 0) {
            if (index - runStart >= 2) {
                const first = lines[runStart];
                const last = lines[index - 1];
                addRegion(context, regionInput(noteId, 'table', 'Table', { start: first.start, end: last.end, text: text.slice(first.start, last.end) }, undefined, 'layout', 'surface', 0.88, ['pipe_table']));
            }
            runStart = -1;
        }
    }
}

function addSection(
    context: BuildContext,
    noteId: string,
    kind: DocumentSection['kind'],
    label: string,
    start: number,
    end: number,
    depth: number,
    parentId: string | undefined,
    ordinal: number,
    unitConfidence: StructureConfidence,
    heading?: string,
): DocumentSection {
    const unit = addUnit(context, { noteId, kind, label, start, end, depth, parentId, confidence: unitConfidence, lens: unitConfidence.source, ordinal });
    const section: DocumentSection = { ...unit, kind, heading, ordinal };
    context.sections.push(section);
    return section;
}

function addRegion(context: BuildContext, input: Omit<DocumentRegion, 'id' | 'childIds' | 'lineage' | 'anchorPolicy'> & { lens: DocumentSidecarLens; ordinal?: number }): DocumentRegion {
    const unit = addUnit(context, input);
    const region: DocumentRegion = { ...unit, kind: input.kind, regionRole: input.regionRole };
    context.regions.push(region);
    return region;
}

function addRhetoricalUnit(context: BuildContext, noteId: string, kind: RhetoricalUnitKind, label: string, paragraph: ParagraphSpan, parentId: string, cue: string, evidenceSpanIds: string[], score: number): RhetoricalUnit {
    const unit = addUnit(context, { noteId, kind, label, start: paragraph.start, end: paragraph.end, depth: 3, parentId, confidence: confidence('rhetorical', score, [cue, 'document_profile_weighted']), lens: 'rhetorical' });
    const rhetorical: RhetoricalUnit = { ...unit, kind, cue, evidenceSpanIds };
    context.rhetoricalUnits.push(rhetorical);
    return rhetorical;
}

function addRetrievalUnit(context: BuildContext, noteId: string, kind: RetrievalUnitKind, label: string, start: number, end: number, parentId: string, targetChunkIds: string[], evidenceSpanIds: string[], unitConfidence: StructureConfidence): RetrievalUnit {
    const unit = addUnit(context, { noteId, kind, label, start, end, depth: 3, parentId, confidence: unitConfidence, lens: unitConfidence.source });
    const retrieval: RetrievalUnit = { ...unit, kind, targetChunkIds, evidenceSpanIds };
    context.retrievalUnits.push(retrieval);
    return retrieval;
}

function addGraphFactCandidate(context: BuildContext, noteId: string, kind: GraphBearingUnitKind, paragraph: ParagraphSpan, parentId: string, chunkId: string | undefined, evidenceSpanIds: string[], score: number): GraphFactCandidate {
    const surfaces = namedSurfaces(paragraph.text).slice(0, 6);
    const unit = addUnit(context, { noteId, kind, label: factLabel(kind), start: paragraph.start, end: paragraph.end, depth: 4, parentId, confidence: confidence('graph_fact', score, [kind, 'document_profile_weighted']), lens: 'graph_fact' });
    const candidate: GraphFactCandidate = {
        ...unit,
        kind,
        subjectSurfaces: surfaces.slice(0, 3),
        objectSurfaces: surfaces.slice(3, 6),
        evidenceSpanIds,
        reviewState: 'proposed',
        lineage: { ...unit.lineage, chunkId },
    };
    context.graphFactCandidates.push(candidate);
    return candidate;
}

function addEvidenceSpan(context: BuildContext, noteId: string, paragraph: ParagraphSpan, unitId: string, chunkId: string | undefined, spanConfidence: StructureConfidence): EvidenceSpan {
    const span: EvidenceSpan = {
        id: `${noteId}:evidence:${paragraph.start}:${paragraph.end}`,
        noteId,
        unitId,
        chunkId,
        start: paragraph.start,
        end: paragraph.end,
        preview: paragraph.text.slice(0, PREVIEW_CHARS).replace(/\s+/g, ' ').trim(),
        textHash: simpleHash(paragraph.text),
        confidence: spanConfidence,
        lineage: { noteId, documentUnitId: unitId, parentUnitIds: [unitId], chunkId, sourceStart: paragraph.start, sourceEnd: paragraph.end, lens: spanConfidence.source },
        anchorPolicy: 'sidecar_only',
    };
    if (!context.evidenceSpans.some((existing) => existing.id === span.id)) context.evidenceSpans.push(span);
    return span;
}

function addUnit(context: BuildContext, input: Omit<DocumentUnit, 'id' | 'childIds' | 'lineage' | 'anchorPolicy'> & { lens: DocumentSidecarLens; ordinal?: number }): DocumentUnit {
    const id = `${input.noteId}:sidecar:${input.kind}:${input.start}:${input.end}:${input.ordinal ?? context.units.length}`;
    const unit = makeUnit({ ...input, id });
    context.units.push(unit);
    if (input.parentId) attachChild(context, input.parentId, id);
    return unit;
}

function makeUnit(input: Omit<DocumentUnit, 'childIds' | 'lineage' | 'anchorPolicy'> & { lens: DocumentSidecarLens; ordinal?: number }): DocumentUnit {
    return {
        id: input.id,
        noteId: input.noteId,
        kind: input.kind,
        label: input.label,
        start: input.start,
        end: input.end,
        depth: input.depth,
        parentId: input.parentId,
        childIds: [],
        confidence: input.confidence,
        lineage: { noteId: input.noteId, documentUnitId: input.id, parentUnitIds: input.parentId ? [input.parentId] : [], sourceStart: input.start, sourceEnd: input.end, ordinal: input.ordinal, lens: input.lens },
        anchorPolicy: 'sidecar_only',
    };
}

function attachChild(context: BuildContext, parentId: string, childId: string): void {
    const childIds = context.childIdsByParent.get(parentId) || [];
    if (!childIds.includes(childId)) childIds.push(childId);
    context.childIdsByParent.set(parentId, childIds);
}

function buildCounters(context: BuildContext): GraphDocumentSidecarCounters {
    const byKind = kindCounts(context.units.map((unit) => unit.kind));
    return {
        documents: byKind['document'] || 0,
        units: context.units.length,
        sections: context.sections.length,
        regions: context.regions.length,
        rhetoricalUnits: context.rhetoricalUnits.length,
        retrievalUnits: context.retrievalUnits.length,
        graphFactCandidates: context.graphFactCandidates.length,
        situationInstances: context.situationInstances.length,
        stateIntervals: context.stateIntervals.length,
        eventOrderings: context.eventOrderings.length,
        temporalConflicts: context.temporalConflicts.length,
        evidenceSpans: context.evidenceSpans.length,
        paragraphGroups: byKind['paragraph_group'] || 0,
        paragraphs: byKind['paragraph'] || 0,
        sentences: byKind['sentence'] || 0,
        leafChunks: byKind['leaf_chunk'] || 0,
        parentChunks: byKind['parent_chunk'] || 0,
        citationSpans: byKind['citation_span'] || 0,
        crossDocTopicPackets: byKind['cross_doc_topic_packet'] || 0,
        userAnchorPromotions: 0,
        truncatedSentenceUnits: context.sentenceLimitHits,
        byKind,
    };
}

function paragraphSpans(text: string): ParagraphSpan[] {
    const spans: ParagraphSpan[] = [];
    const regex = /\S[\s\S]*?(?=\r?\n\s*\r?\n|$)/g;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) !== null) {
        const raw = match[0];
        let start = match.index;
        let end = start + raw.length;
        while (start < end && /\s/.test(text[start])) start += 1;
        while (end > start && /\s/.test(text[end - 1])) end -= 1;
        if (end > start) spans.push({ start, end, text: text.slice(start, end) });
        if (regex.lastIndex === match.index) regex.lastIndex += 1;
    }
    return spans;
}

function sentenceSpans(paragraph: ParagraphSpan): ParagraphSpan[] {
    const spans: ParagraphSpan[] = [];
    let start = paragraph.start;
    for (let index = paragraph.start; index < paragraph.end; index += 1) {
        const char = paragraph.text[index - paragraph.start];
        if (char !== '.' && char !== '!' && char !== '?') continue;
        const next = paragraph.text[index - paragraph.start + 1] || '';
        if (next && !/\s|["')\]]/.test(next)) continue;
        pushSentence(spans, paragraph, start, index + 1);
        start = index + 1;
    }
    pushSentence(spans, paragraph, start, paragraph.end);
    return spans;
}

function pushSentence(spans: ParagraphSpan[], paragraph: ParagraphSpan, start: number, end: number): void {
    while (start < end && /\s/.test(paragraph.text[start - paragraph.start])) start += 1;
    while (end > start && /\s/.test(paragraph.text[end - paragraph.start - 1])) end -= 1;
    if (end > start) spans.push({ start, end, text: paragraph.text.slice(start - paragraph.start, end - paragraph.start) });
}

function headingSpans(text: string): HeadingSpan[] {
    const out: HeadingSpan[] = [];
    const regex = /^(#{1,6})\s+(.+)$/gm;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) !== null) out.push({ start: match.index, end: match.index + match[0].length, level: match[1].length, label: match[2].trim() });
    return out;
}

function lineSpans(text: string): ParagraphSpan[] {
    const spans: ParagraphSpan[] = [];
    const regex = /[^\r\n]*(?:\r?\n|$)/g;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) !== null) {
        if (!match[0] && match.index >= text.length) break;
        spans.push({ start: match.index, end: match.index + match[0].length, text: match[0] });
        if (regex.lastIndex === match.index) regex.lastIndex += 1;
    }
    return spans;
}

function nearestSection(sections: DocumentSection[], start: number): DocumentSection {
    return [...sections].reverse().find((section) => section.start <= start && section.end >= start) || sections[0];
}

function regionInput(noteId: string, kind: DocumentRegion['kind'], label: string, span: ParagraphSpan, parentId: string | undefined, regionRole: DocumentRegion['regionRole'], lens: DocumentSidecarLens, score: number, reasons: string[]) {
    return { noteId, kind, label, start: span.start, end: span.end, depth: parentId ? 3 : 1, parentId, confidence: confidence(lens, score, reasons), regionRole, lens };
}

function inferRhetoricalKinds(text: string): Array<{ kind: RhetoricalUnitKind; cue: string }> {
    const lower = text.toLowerCase();
    const out: Array<{ kind: RhetoricalUnitKind; cue: string }> = [];
    for (const [kind, cues] of RHETORICAL_CUES) {
        const cue = cues.find((entry) => lower.includes(entry));
        if (cue) out.push({ kind, cue });
    }
    if (text.includes('?')) out.push({ kind: 'question', cue: 'question_mark' });
    if (out.length === 0 && /\b(is|are|means|shows|suggests)\b/.test(lower)) out.push({ kind: 'claim', cue: 'assertive_verb' });
    return out;
}

function inferGraphFactKinds(
    text: string,
    chunk: GraphRebuildChunk | undefined,
    profile: DocumentProfileKind,
): GraphBearingUnitKind[] {
    const lower = text.toLowerCase();
    const out = new Set<GraphBearingUnitKind>();
    const surfaces = namedSurfaces(text);
    const priorCount = chunk?.meaningFrame?.entityPriors.length || 0;
    const claimCue = /\b(because|therefore|claim|shows|evidence|according to|demonstrates|indicates)\b/.test(lower);
    const stateCue = /\b(became|changed|shifted|turned|moved from|converted|increased|decreased)\b/.test(lower);
    const procedureCue = /^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:run|use|apply|install|configure|select|open|create|remove|must|should)\b/i.test(text);
    const relationCue = /\b(with|between|against|supports|contains|causes|depends on|belongs to|located in|connected to)\b/.test(lower);
    if (claimCue && (surfaces.length > 0 || ['research_paper', 'reference_article', 'legal_policy'].includes(profile))) out.add('n_ary_claim');
    if (stateCue && (surfaces.length > 0 || profile === 'prose_fiction')) out.add('state_change');
    if (EVENT_CUES.some((cue) => lower.includes(cue)) && (surfaces.length > 0 || profile === 'prose_fiction')) out.add('event');
    if (procedureCue && ['technical_docs', 'legal_policy', 'meeting_notes', 'code_heavy_notes', 'trading_system_specs'].includes(profile)) out.add('procedure_step');
    if (surfaces.length >= 2 && (relationCue || priorCount >= 2)) out.add('relation_bundle');
    return [...out];
}

function graphFactSpecificity(
    kind: GraphBearingUnitKind,
    text: string,
    chunk: GraphRebuildChunk | undefined,
): number {
    const surfaces = namedSurfaces(text).length;
    const priors = chunk?.meaningFrame?.entityPriors.length || 0;
    const kindBoost = kind === 'relation_bundle' || kind === 'n_ary_claim' ? 2 : kind === 'state_change' ? 1.5 : 1;
    return Math.min(4, kindBoost + Math.min(2, surfaces) + Math.min(1, priors / 2));
}

function graphFactBudget(
    context: BuildContext,
    noteId: string,
    chunkCount: number,
    paragraphCount: number,
): number {
    const profile = documentProfileAt(context, noteId, 0);
    const multiplier = profile === 'prose_fiction' ? 1.15
        : profile === 'research_paper' || profile === 'reference_article' ? 1.4
            : 1.6;
    return Math.min(paragraphCount, 320, Math.max(16, Math.ceil(chunkCount * multiplier)));
}

function documentProfileAt(context: BuildContext, noteId: string, sourceStart: number): DocumentProfileKind {
    const profile = context.documentProfileSummary.profiles.find((row) => row.noteId === noteId);
    const region = profile?.regions.find((row) => row.start <= sourceStart && row.end >= sourceStart);
    return region?.dominantProfile || profile?.dominantProfile || 'mixed_notebook';
}

function namedSurfaces(text: string): string[] {
    const matches = text.match(/\b[A-Z][A-Za-z'-]*(?:[-\s]+(?:of\s+|the\s+)?[A-Z][A-Za-z'-]*){0,3}\b/g) || [];
    const stop = new Set(['The', 'This', 'That', 'Then', 'After', 'Before', 'Any']);
    return unique(matches.map((value) => value.replace(/\s+/g, ' ').trim()).filter((value) => value.length > 2 && !stop.has(value)));
}

function isDialogue(text: string): boolean {
    return /["]/.test(text) || /\b(said|asked|answered|replied|murmured)\b/i.test(text);
}

function unitWeight(context: BuildContext, noteId: string, kind: string, sourceStart: number): number {
    return documentUnitWeight(context.documentProfileSummary, noteId, kind, sourceStart);
}

function adaptedScore(context: BuildContext, noteId: string, kind: string, sourceStart: number, base: number): number {
    return Math.max(0.05, Math.min(0.99, base + (unitWeight(context, noteId, kind, sourceStart) - 1) * 0.18));
}

function confidence(source: DocumentSidecarLens, score: number, reasons: string[]): StructureConfidence {
    return { source, score: Math.round(score * 100) / 100, reasons };
}

function factLabel(kind: GraphBearingUnitKind): string {
    return kind.replace(/_/g, ' ');
}

function groupChunksByNote(chunks: GraphRebuildChunk[]): Map<string, GraphRebuildChunk[]> {
    const byNote = new Map<string, GraphRebuildChunk[]>();
    for (const chunk of chunks) byNote.set(chunk.noteId, [...(byNote.get(chunk.noteId) || []), chunk]);
    return byNote;
}

function kindCounts(kinds: string[]): Record<string, number> {
    const counts = new Map<string, number>();
    for (const kind of kinds) counts.set(kind, (counts.get(kind) || 0) + 1);
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function simpleId(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'topic';
}

function simpleHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}

const EVENT_CUES = ['opened', 'moved', 'walked', 'read', 'watched', 'shifted', 'arrived', 'entered', 'detained', 'selected', 'assigned', 'changed'] as const;

const RHETORICAL_CUES: ReadonlyArray<readonly [RhetoricalUnitKind, readonly string[]]> = [
    ['definition', ['is defined as', 'refers to', 'means']],
    ['evidence', ['because', 'according to', 'evidence', 'record', 'data', 'report']],
    ['claim', ['therefore', 'shows', 'suggests', 'argues', 'claim']],
    ['example', ['for example', 'such as', 'including']],
    ['contrast', ['however', 'although', 'but ', 'whereas']],
    ['method', ['method', 'approach', 'we use', 'pipeline', 'procedure']],
    ['result', ['result', 'found', 'improved', 'reduced', 'increased']],
    ['instruction', ['must', 'should', 'click', 'run ', 'use ', 'apply']],
    ['decision', ['decided', 'approved', 'rejected', 'accepted']],
];
