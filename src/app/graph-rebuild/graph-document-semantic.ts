export type GraphDocumentSemanticReviewState = 'proposed' | 'ledger_only';
export type GraphDocumentSemanticPredicateAdmission = 'review' | 'ledger_only';

export interface GraphDocumentSemanticArgument {
    role: string;
    syntacticRole?: string;
    semanticRole?: string;
    surface: string;
    entityId?: string;
    start?: number;
    end?: number;
    roleConfidenceMillis?: number;
    roleFailureReasons?: string[];
}

export interface GraphDocumentSemanticRecoveredArgument {
    kind: string;
    role: string;
    syntacticRole: string;
    semanticRole: string;
    surface: string;
    entityId?: string;
    start?: number;
    end?: number;
    sourcePropositionId?: string;
    sourceSentenceIndex?: number;
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticScope {
    kind: string;
    polarity?: string;
    modality?: string;
}

export interface GraphDocumentSemanticAttribution {
    sourceEntityId?: string;
    start?: number;
    end?: number;
}

export interface GraphDocumentSemanticConditional {
    conditionStart?: number;
    conditionEnd?: number;
    consequentStart?: number;
    consequentEnd?: number;
}

export interface GraphDocumentSemanticQuote {
    speakerEntityId?: string;
    start: number;
    end: number;
}

export interface GraphDocumentSemanticEvidence {
    label: string;
    kind?: string;
    start: number;
    end: number;
}

export interface GraphDocumentSemanticFrame {
    frame: string;
    family: string;
    target: string;
    lexicalUnit: string;
    definition: string;
    source: string;
    confidenceMillis: number;
    expectedRoles: string[];
    matchedRoles: string[];
    missingRoles: string[];
    reasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticFactualityEnvelope {
    factuality: string;
    polarity: string;
    modality?: string;
    speechAct: string;
    asserted: boolean;
    negated: boolean;
    modal: boolean;
    hypothetical: boolean;
    conditional: boolean;
    quoted: boolean;
    reported: boolean;
    believed: boolean;
    questioned: boolean;
    commanded: boolean;
    confidenceMillis: number;
    scopeKinds: string[];
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticAttributionFrame {
    sourceEntityId?: string;
    quoteStart?: number;
    quoteEnd?: number;
    attributionKind: string;
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticConditionalFrame {
    conditionStart?: number;
    conditionEnd?: number;
    consequentStart?: number;
    consequentEnd?: number;
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticSpeechOrBeliefFrame {
    kind: string;
    speakerEntityId?: string;
    quotedStart?: number;
    quotedEnd?: number;
    embeddedFactuality: string;
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticSituationInstance {
    id: string;
    propositionId: string;
    noteId: string;
    sentenceIndex: number;
    start: number;
    end: number;
    predicate: string;
    frame: string;
    situationKind: 'event' | 'state';
    participantEntityIds: string[];
    participantSurfaces: string[];
    factuality: string;
    worldStateEligible: boolean;
    recurrenceOfSituationId?: string;
    recurrenceIndex: number;
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticStateInterval {
    id: string;
    noteId: string;
    stateKey: string;
    subjectKey: string;
    predicate: string;
    value?: string;
    polarity: string;
    status: 'open' | 'terminated' | 'superseded' | 'termination_observed';
    startSituationId: string;
    endSituationId?: string;
    mentionSituationIds: string[];
    start: number;
    end?: number;
    persists: boolean;
    terminationCue?: string;
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticEventOrdering {
    id: string;
    noteId: string;
    sourceSituationId: string;
    targetSituationId: string;
    relation: 'before' | 'overlaps' | 'recurs_after';
    cue?: string;
    source: 'explicit_cue' | 'document_order' | 'situation_recurrence';
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticTemporalConflict {
    id: string;
    noteId: string;
    kind: 'unresolved_state_transition' | 'ordering_cycle';
    stateKey?: string;
    situationIds: string[];
    stateIntervalIds: string[];
    severity: 'medium' | 'high';
    confidenceMillis: number;
    detectorReasons: string[];
    failureReasons: string[];
}

export interface GraphDocumentSemanticProposition {
    id: string;
    noteId: string;
    sentenceIndex: number;
    start: number;
    end: number;
    preview: string;
    predicate: string;
    relationType: string;
    predicateQuality?: string;
    predicateAdmission?: GraphDocumentSemanticPredicateAdmission;
    qualityReasons?: string[];
    triggerStart: number;
    triggerEnd: number;
    frame?: GraphDocumentSemanticFrame;
    factuality?: GraphDocumentSemanticFactualityEnvelope;
    attributionFrame?: GraphDocumentSemanticAttributionFrame;
    conditionalFrame?: GraphDocumentSemanticConditionalFrame;
    speechOrBeliefFrame?: GraphDocumentSemanticSpeechOrBeliefFrame;
    arguments: GraphDocumentSemanticArgument[];
    documentArgumentRecoveries?: GraphDocumentSemanticRecoveredArgument[];
    scope: GraphDocumentSemanticScope[];
    attribution?: GraphDocumentSemanticAttribution;
    conditional?: GraphDocumentSemanticConditional;
    quote?: GraphDocumentSemanticQuote;
    evidence: GraphDocumentSemanticEvidence[];
    confidenceMillis: number;
    reviewState: GraphDocumentSemanticReviewState;
}

export interface GraphDocumentSemanticCounters {
    documents: number;
    sentences: number;
    propositions: number;
    arguments: number;
    resolvedArguments: number;
    roleAnnotations?: number;
    unresolvedRoleSurfaces?: number;
    roleFailureReasons?: number;
    frameAnnotations?: number;
    lexicalFrameMatches?: number;
    fallbackFrameMatches?: number;
    lowConfidenceFrames?: number;
    frameFailureReasons?: number;
    factualityAnnotations?: number;
    scopedFactuality?: number;
    attributedFactuality?: number;
    quotedFactuality?: number;
    conditionalFactuality?: number;
    speechOrBeliefFrames?: number;
    lowConfidenceFactuality?: number;
    factualityFailureReasons?: number;
    documentArgumentRecoveries?: number;
    localCoreferenceRecoveries?: number;
    aliasContinuityRecoveries?: number;
    omittedSubjectRecoveries?: number;
    quoteSpeakerRecoveries?: number;
    repeatedEventLinks?: number;
    windowArgumentCompletions?: number;
    lowConfidenceRecoveries?: number;
    recoveryFailureReasons?: number;
    situationInstances?: number;
    stateIntervals?: number;
    eventOrderings?: number;
    explicitEventOrderings?: number;
    recurrenceOrderings?: number;
    persistentStateIntervals?: number;
    terminatedStateIntervals?: number;
    temporalConflicts?: number;
    worldStateIneligibleSituations?: number;
    negated: number;
    modal: number;
    conditional: number;
    attributed: number;
    quoted: number;
    questions: number;
    directives: number;
    nAry: number;
    reviewable: number;
    ledgerOnly?: number;
    predicateModifiers?: number;
    predicateNoise?: number;
}

export interface GraphDocumentSemanticDocument {
    noteId: string;
    textChars: number;
    propositions: GraphDocumentSemanticProposition[];
    situations?: GraphDocumentSemanticSituationInstance[];
    stateIntervals?: GraphDocumentSemanticStateInterval[];
    eventOrderings?: GraphDocumentSemanticEventOrdering[];
    temporalConflicts?: GraphDocumentSemanticTemporalConflict[];
    counters: GraphDocumentSemanticCounters;
}

export interface GraphDocumentSemanticSummary {
    schemaVersion: 'phoenix-document-semantics/v1';
    source: 'native_rust';
    documents: GraphDocumentSemanticDocument[];
    counters: GraphDocumentSemanticCounters;
}

export function isGraphDocumentSemanticSummary(
    value: unknown,
): value is GraphDocumentSemanticSummary {
    if (!value || typeof value !== 'object') return false;
    const candidate = value as Partial<GraphDocumentSemanticSummary>;
    return (
        candidate.schemaVersion === 'phoenix-document-semantics/v1' &&
        candidate.source === 'native_rust' &&
        Array.isArray(candidate.documents) &&
        !!candidate.counters
    );
}
