export type GraphDocumentSemanticReviewState = 'proposed' | 'ledger_only';
export type GraphDocumentSemanticPredicateAdmission = 'review' | 'ledger_only';

export interface GraphDocumentSemanticArgument {
    role: string;
    surface: string;
    entityId?: string;
    start?: number;
    end?: number;
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
    arguments: GraphDocumentSemanticArgument[];
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
