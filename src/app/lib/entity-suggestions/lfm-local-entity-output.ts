import { isEntityKind, type EntityKind } from '../types/entity';
import type {
    LocalEntitySuggestion,
    LocalEntitySuggestionConfidence,
    SuggestedEntityKind,
} from './entity-suggestion.types';

const OBVIOUS_JUNK_LABELS = new Set([
    'he', 'she', 'they', 'them', 'their', 'theirs', 'him', 'her', 'hers',
    'we', 'us', 'our', 'ours', 'you', 'your', 'yours', 'i', 'me', 'my', 'mine',
    'it', 'its', 'itself', 'this', 'that', 'these', 'those',
    'someone', 'somebody', 'something', 'anyone', 'anybody', 'anything',
    'everyone', 'everybody', 'everything', 'nobody', 'nothing',
]);

const KIND_ALIASES: Record<string, EntityKind | 'UNKNOWN'> = {
    CHARACTER: 'CHARACTER',
    PER: 'CHARACTER',
    PERSON: 'CHARACTER',
    PERSON_NAME: 'CHARACTER',
    PEOPLE: 'CHARACTER',
    HUMAN: 'CHARACTER',
    PROTAGONIST: 'CHARACTER',
    SPEAKER: 'CHARACTER',
    LOCATION: 'LOCATION',
    GPE: 'LOCATION',
    GEO: 'LOCATION',
    GEOPOLITICAL_ENTITY: 'LOCATION',
    LOC: 'LOCATION',
    PLACE: 'LOCATION',
    SETTING: 'LOCATION',
    COUNTRY: 'LOCATION',
    NATION: 'LOCATION',
    CITY: 'LOCATION',
    TOWN: 'LOCATION',
    REGION: 'LOCATION',
    TERRITORY: 'LOCATION',
    PROVINCE: 'LOCATION',
    REALM: 'LOCATION',
    KINGDOM: 'LOCATION',
    EMPIRE: 'LOCATION',
    FACILITY: 'LOCATION',
    BUILDING: 'LOCATION',
    NPC: 'NPC',
    CREATURE: 'CREATURE',
    SPECIES: 'CREATURE',
    MONSTER: 'CREATURE',
    ITEM: 'ITEM',
    OBJECT: 'ITEM',
    ARTIFACT: 'ITEM',
    FACTION: 'NETWORK',
    GROUP: 'NETWORK',
    NETWORK: 'NETWORK',
    ORG: 'NETWORK',
    ORGANIZATION: 'NETWORK',
    ORGANISATION: 'NETWORK',
    ALLIANCE: 'NETWORK',
    DEPARTMENT: 'NETWORK',
    INSTITUTION: 'NETWORK',
    SCENE: 'SCENE',
    EVENT: 'EVENT',
    CONCEPT: 'CONCEPT',
    ARC: 'ARC',
    ACT: 'ACT',
    CHAPTER: 'CHAPTER',
    BEAT: 'BEAT',
    TIMELINE: 'TIMELINE',
    NARRATIVE: 'NARRATIVE',
    OTHER: 'UNKNOWN',
    UNKNOWN: 'UNKNOWN',
};

export function stripCodeFences(value: string): string {
    const trimmed = value.trim();
    const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
    return fenced ? fenced[1].trim() : trimmed;
}

export function extractFirstJsonArray(value: string): string | null {
    return extractFirstBalancedJsonValue(stripCodeFences(value), '[', ']');
}

export function extractFirstJsonObject(value: string): string | null {
    return extractFirstBalancedJsonValue(stripCodeFences(value), '{', '}');
}

function extractFirstJsonPayload(value: string): string | null {
    const text = stripCodeFences(value);
    const arrayStart = findFirstUnquotedDelimiter(text, '[');
    const objectStart = findFirstUnquotedDelimiter(text, '{');

    if (arrayStart === -1 && objectStart === -1) {
        return null;
    }

    if (arrayStart !== -1 && (objectStart === -1 || arrayStart < objectStart)) {
        return extractFirstBalancedJsonValue(text.slice(arrayStart), '[', ']');
    }

    return extractFirstBalancedJsonValue(text.slice(objectStart), '{', '}');
}

function findFirstUnquotedDelimiter(text: string, delimiter: '[' | '{'): number {
    let inString = false;
    let escaped = false;

    for (let index = 0; index < text.length; index++) {
        const character = text[index];

        if (escaped) {
            escaped = false;
            continue;
        }

        if (character === '\\') {
            escaped = inString;
            continue;
        }

        if (character === '"') {
            inString = !inString;
            continue;
        }

        if (!inString && character === delimiter) {
            return index;
        }
    }

    return -1;
}

function extractFirstBalancedJsonValue(text: string, open: '[' | '{', close: ']' | '}'): string | null {
    let start = -1;
    let depth = 0;
    let inString = false;
    let escaped = false;

    for (let index = 0; index < text.length; index++) {
        const character = text[index];

        if (escaped) {
            escaped = false;
            continue;
        }

        if (character === '\\') {
            escaped = inString;
            continue;
        }

        if (character === '"') {
            inString = !inString;
            continue;
        }

        if (inString) {
            continue;
        }

        if (character === open) {
            if (start === -1) {
                start = index;
            }
            depth += 1;
            continue;
        }

        if (character === close) {
            depth -= 1;
            if (start !== -1 && depth === 0) {
                return text.slice(start, index + 1);
            }
        }
    }

    return null;
}

function normalizeSuggestionLabel(label: string): string {
    return label
        .trim()
        .replace(/\s+/g, ' ')
        .replace(/^["'“”‘’]+|["'“”‘’]+$/g, '')
        .trim();
}

export function normalizeSuggestedEntityKind(kind: string): SuggestedEntityKind {
    const normalized = kind.trim().toUpperCase().replace(/\s+/g, '_');
    const aliased = KIND_ALIASES[normalized];
    if (aliased) {
        return aliased;
    }
    if (isEntityKind(normalized)) {
        return normalized;
    }

    return 'UNKNOWN';
}

function normalizeConfidence(confidence: string): LocalEntitySuggestionConfidence | null {
    const normalized = confidence.trim().toLowerCase();
    if (normalized === 'high' || normalized === 'medium' || normalized === 'low') {
        return normalized;
    }
    return null;
}

function normalizeConfidenceValue(confidence: unknown): LocalEntitySuggestionConfidence | null {
    if (typeof confidence === 'string') {
        const direct = normalizeConfidence(confidence);
        if (direct) {
            return direct;
        }

        const numeric = Number(confidence);
        if (Number.isFinite(numeric)) {
            return mapScoreToConfidenceLevel(numeric > 1 ? numeric / 100 : numeric);
        }
    }

    if (typeof confidence === 'number' && Number.isFinite(confidence)) {
        return mapScoreToConfidenceLevel(confidence > 1 ? confidence / 100 : confidence);
    }

    return null;
}

function dedupeAliases(aliases: string[], label: string): string[] {
    const normalizedLabel = normalizeSuggestionLabel(label).toLocaleLowerCase();
    const seen = new Set<string>();
    const result: string[] = [];

    for (const alias of aliases) {
        const cleaned = normalizeSuggestionLabel(alias);
        if (!cleaned) {
            continue;
        }

        const normalized = cleaned.toLocaleLowerCase();
        if (normalized === normalizedLabel || seen.has(normalized)) {
            continue;
        }

        seen.add(normalized);
        result.push(cleaned);
    }

    return result;
}

export function isLikelyJunkEntityLabel(label: string): boolean {
    const cleaned = normalizeSuggestionLabel(label);
    if (!cleaned) {
        return true;
    }

    if (cleaned.length < 2) {
        return true;
    }

    if (!/[\p{L}\p{N}]/u.test(cleaned)) {
        return true;
    }

    return OBVIOUS_JUNK_LABELS.has(cleaned.toLocaleLowerCase());
}

function firstString(...values: unknown[]): string | null {
    for (const value of values) {
        if (typeof value === 'string' && value.trim()) {
            return value;
        }
    }
    return null;
}

function firstConfidence(...values: unknown[]): LocalEntitySuggestionConfidence | null {
    for (const value of values) {
        const confidence = normalizeConfidenceValue(value);
        if (confidence) {
            return confidence;
        }
    }
    return null;
}

function coerceStringArray(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.filter((entry): entry is string => typeof entry === 'string');
    }

    if (typeof value === 'string' && value.trim()) {
        return [value];
    }

    return [];
}

function coerceSuggestion(candidate: unknown): LocalEntitySuggestion | null {
    if (!candidate || typeof candidate !== 'object') {
        return null;
    }

    const raw = candidate as {
        label?: unknown;
        name?: unknown;
        entity?: unknown;
        text?: unknown;
        kind?: unknown;
        type?: unknown;
        category?: unknown;
        entity_type?: unknown;
        entityType?: unknown;
        confidence?: unknown;
        score?: unknown;
        probability?: unknown;
        reasoning?: unknown;
        reason?: unknown;
        explanation?: unknown;
        evidence?: unknown;
        quote?: unknown;
        context?: unknown;
        aliases?: unknown;
        alias?: unknown;
        surface_forms?: unknown;
        surfaceForms?: unknown;
    };

    const rawLabel = firstString(raw.label, raw.name, raw.entity, raw.text);
    if (!rawLabel) {
        return null;
    }

    const label = normalizeSuggestionLabel(rawLabel);
    if (isLikelyJunkEntityLabel(label)) {
        return null;
    }

    const confidence = firstConfidence(raw.confidence, raw.score, raw.probability);
    if (!confidence) {
        return null;
    }

    const evidence = firstString(raw.evidence, raw.quote, raw.context)?.trim() ?? '';
    const reasoning = firstString(raw.reasoning, raw.reason, raw.explanation)?.trim() ?? '';
    const kind = firstString(raw.kind, raw.type, raw.category, raw.entity_type, raw.entityType);
    const aliases = coerceStringArray(raw.aliases ?? raw.alias ?? raw.surface_forms ?? raw.surfaceForms);

    return {
        label,
        kind: kind ? normalizeSuggestedEntityKind(kind) : 'UNKNOWN',
        confidence,
        reasoning,
        evidence: evidence || label,
        aliases: dedupeAliases(aliases, label),
    };
}

function coerceSuggestionArray(parsed: unknown): unknown[] {
    if (Array.isArray(parsed)) {
        return parsed;
    }

    if (!parsed || typeof parsed !== 'object') {
        return [];
    }

    const raw = parsed as {
        entities?: unknown;
        suggestions?: unknown;
        items?: unknown;
        results?: unknown;
    };

    for (const value of [raw.entities, raw.suggestions, raw.items, raw.results]) {
        if (Array.isArray(value)) {
            return value;
        }
    }

    return firstString((parsed as { label?: unknown }).label, (parsed as { name?: unknown }).name)
        ? [parsed]
        : [];
}

function parseJsonPayload(payload: string): unknown | null {
    try {
        return JSON.parse(payload);
    } catch {
        try {
            return JSON.parse(payload.replace(/,\s*([}\]])/g, '$1'));
        } catch {
            return null;
        }
    }
}

export function parseLocalEntitySuggestionsFromModelOutput(outputText: string): LocalEntitySuggestion[] {
    const jsonPayload = extractFirstJsonPayload(outputText);
    if (!jsonPayload) {
        return [];
    }

    const parsed = parseJsonPayload(jsonPayload);
    if (!parsed) {
        return [];
    }

    const candidates = coerceSuggestionArray(parsed);
    if (!candidates.length) {
        return [];
    }

    return candidates
        .map(coerceSuggestion)
        .filter((suggestion): suggestion is LocalEntitySuggestion => suggestion !== null);
}

export function getConfidenceRank(confidence: LocalEntitySuggestionConfidence): number {
    switch (confidence) {
        case 'high':
            return 3;
        case 'medium':
            return 2;
        case 'low':
        default:
            return 1;
    }
}

export function mapConfidenceLevelToScore(confidence: LocalEntitySuggestionConfidence): number {
    switch (confidence) {
        case 'high':
            return 0.9;
        case 'medium':
            return 0.7;
        case 'low':
        default:
            return 0.5;
    }
}

export function mapScoreToConfidenceLevel(score: number): LocalEntitySuggestionConfidence {
    if (score >= 0.85) {
        return 'high';
    }
    if (score >= 0.65) {
        return 'medium';
    }
    return 'low';
}

function preferKind(current: SuggestedEntityKind, incoming: SuggestedEntityKind): SuggestedEntityKind {
    if (current === 'UNKNOWN' && incoming !== 'UNKNOWN') {
        return incoming;
    }
    return current;
}

export function mergeLocalEntitySuggestions(suggestions: LocalEntitySuggestion[]): LocalEntitySuggestion[] {
    const merged = new Map<string, LocalEntitySuggestion>();

    for (const suggestion of suggestions) {
        if (isLikelyJunkEntityLabel(suggestion.label)) {
            continue;
        }

        const key = normalizeSuggestionLabel(suggestion.label).toLocaleLowerCase();
        const current = merged.get(key);
        if (!current) {
            merged.set(key, {
                ...suggestion,
                aliases: dedupeAliases(suggestion.aliases, suggestion.label),
            });
            continue;
        }

        const currentRank = getConfidenceRank(current.confidence);
        const incomingRank = getConfidenceRank(suggestion.confidence);
        const useIncoming = incomingRank > currentRank;

        merged.set(key, {
            label: current.label,
            kind: preferKind(current.kind, suggestion.kind),
            confidence: useIncoming ? suggestion.confidence : current.confidence,
            reasoning: useIncoming
                ? (suggestion.reasoning || current.reasoning)
                : (current.reasoning || suggestion.reasoning),
            evidence: useIncoming
                ? (suggestion.evidence || current.evidence)
                : (current.evidence || suggestion.evidence),
            aliases: dedupeAliases([...current.aliases, ...suggestion.aliases], current.label),
            rawScore: useIncoming ? suggestion.rawScore : current.rawScore,
        });
    }

    return Array.from(merged.values()).sort((left, right) =>
        getConfidenceRank(right.confidence) - getConfidenceRank(left.confidence) ||
        String(left.kind).localeCompare(String(right.kind)) ||
        left.label.localeCompare(right.label)
    );
}
