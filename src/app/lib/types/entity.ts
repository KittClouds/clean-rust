/**
 * Shared entity types for use across the application.
 * These types are used by Phoenix native services, extractors, and UI components.
 */

/**
 * Entity kinds used throughout the knowledge graph.
 * These represent the categorization of entities in the system.
 */
export type EntityKind =
    | 'CHARACTER'
    | 'LOCATION'
    | 'NPC'
    | 'CREATURE'
    | 'ITEM'
    | 'FACTION'
    | 'NETWORK'
    | 'SCENE'
    | 'EVENT'
    | 'CONCEPT'
    | 'ARC'
    | 'ACT'
    | 'CHAPTER'
    | 'BEAT'
    | 'TIMELINE'
    | 'NARRATIVE';

/**
 * All valid entity kinds as a readonly array for runtime validation.
 */
export const ENTITY_KINDS: readonly EntityKind[] = [
    'CHARACTER',
    'LOCATION',
    'NPC',
    'CREATURE',
    'ITEM',
    'FACTION',
    'NETWORK',
    'SCENE',
    'EVENT',
    'CONCEPT',
    'ARC',
    'ACT',
    'CHAPTER',
    'BEAT',
    'TIMELINE',
    'NARRATIVE',
] as const;

/**
 * Graph scope types for querying.
 */
export type GraphScope = 'note' | 'folder' | 'vault' | 'narrative';

/**
 * Extraction method types for entity/relationship provenance.
 */
export type ExtractionMethod = 'regex' | 'llm' | 'manual';

/**
 * Confidence levels for extracted data.
 */
export type ConfidenceLevel = 'low' | 'medium' | 'high';

/**
 * Helper to check if a string is a valid EntityKind.
 */
export function isEntityKind(value: string): value is EntityKind {
    return ENTITY_KINDS.includes(value as EntityKind);
}

/**
 * Get display label for an entity kind.
 */
export function getEntityKindLabel(kind: EntityKind): string {
    return kind.charAt(0) + kind.slice(1).toLowerCase();
}
