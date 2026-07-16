// src/lib/Scanner/types.ts
// Scanner types - core data structures for entities and relationships

/**
 * Entity kinds supported by the scanner
 */
export type EntityKind =
    | 'CHARACTER'
    | 'LOCATION'
    | 'ORGANIZATION'
    | 'ITEM'
    | 'CONCEPT'
    | 'EVENT'
    | 'FACTION'
    | 'CREATURE'
    | 'NPC'
    | 'SCENE'
    | 'ARC'
    | 'ACT'
    | 'CHAPTER'
    | 'BEAT'
    | 'TIMELINE'
    | 'NARRATIVE'
    | 'NETWORK'
    | 'CUSTOM'
    | 'OTHER'
    | 'UNKNOWN';

export type SentenceVariationBucket = '1' | '2-6' | '7-15' | '16-25' | '26-39' | '40+';

export type AnalyticsHighlightKind =
    | 'keyword'
    | 'repetition'
    | 'proximity'
    | 'cadence'
    | 'sentence_variation'
    | 'meter'
    | 'negation'
    | 'ornament'
    | 'distance'
    | 'diction';

export type AnalyticsHighlightPaletteKey = AnalyticsHighlightKind | SentenceVariationBucket;

/**
 * Types of detected spans
 */
export type SpanType = 'entity' | 'wikilink' | 'entity_ref' | 'relationship' | 'entity_implicit' | 'predicate' | 'entity_candidate' | 'keyword_focus' | 'analytics_highlight';

/**
 * A decoration span representing a detected element in text
 */
export interface DecorationSpan {
    /** Type of span */
    type: SpanType;
    /** Start offset in document */
    from: number;
    /** End offset in document */
    to: number;
    /** Display label (canonical entity name) */
    label: string;
    /** Entity kind for styling (entity spans only) */
    kind?: EntityKind;
    /** Target note/entity name */
    target?: string;
    /** Display alias (for [[target|alias]] syntax) */
    displayText?: string;
    /** Actual matched text in document (for implicit matches, may differ from label) */
    matchedText?: string;
    /** Optional entity ID (if resolved) */
    entityId?: string;
    /** Optional note ID (if resolved) */
    noteId?: string;
    /** Whether the link is resolved */
    resolved?: boolean;
    /** Rust mention source for entity signals */
    matchSource?: string;
    /** Scanner confidence when available */
    confidence?: number;
    /** For relationships: source entity */
    sourceEntity?: string;
    /** For relationships: target entity */
    targetEntity?: string;
    /** For relationships: verb/relation type */
    verb?: string;
    /** For relationships: direction 'forward' | 'backward' | 'bidirectional' */
    direction?: 'forward' | 'backward' | 'bidirectional';
    /** Candidates for ambiguous matches */
    candidateIds?: string[];
    /** Labels for ambiguous candidates */
    candidateLabels?: string[];
    /** Robust anchoring for re-finding this span (Web Annotation model) */
    selector?: TextQuoteSelector;
    /** Analytics highlight family for transient editor emphasis */
    highlightKind?: AnalyticsHighlightKind;
    /** Optional analytics palette key when a highlight needs bucket-specific styling */
    analyticsPaletteKey?: AnalyticsHighlightPaletteKey;
    /** Stable selection id for transient analytics highlights */
    annotationId?: string;
}

/**
 * Web Annotation TextQuoteSelector for robust anchoring
 */
export interface TextQuoteSelector {
    /** The exact text of the selection */
    exact: string;
    /** Text immediately preceding the selection (context) */
    prefix: string;
    /** Text immediately following the selection (context) */
    suffix: string;
}

/**
 * Registered entity from the registry
 */
export interface RegisteredEntity {
    id: string;
    label: string;
    kind: EntityKind;
    aliases?: string[];
    /** Note ID where entity was first registered */
    originNoteId?: string;
    /** Timestamp of first registration */
    registeredAt: number;
}

/**
 * Result of scanning a document
 */
export interface ScanResult {
    /** Document ID that was scanned */
    docId: string;
    /** Decoded spans for decoration */
    spans: DecorationSpan[];
    /** New entities discovered in this scan */
    newEntities: RegisteredEntity[];
    /** Timestamp of scan */
    scannedAt: number;
}

/**
 * Highlighting mode
 */
export type HighlightMode = 'vivid' | 'clean' | 'subtle' | 'gradient' | 'off';

/**
 * Configuration for the highlighter
 */
export interface HighlighterConfig {
    mode: HighlightMode;
    /** Enable wikilinks [[]] */
    enableWikilinks?: boolean;
    /** Enable entity refs <<>> */
    enableEntityRefs?: boolean;
    /** Enable relationship arrows */
    enableRelationships?: boolean;
    /** Widget mode: show pills instead of inline decorations */
    widgetMode?: boolean;
}
