import type {
    GraphRebuildChunk,
    GraphRebuildChunkEntityPrior,
    GraphRebuildChunkRole,
    GraphRebuildMeaningFrame,
} from './graph-rebuild-snapshot';

const TARGET_TOKENS = 460;
const HARD_MAX_TOKENS = 540;
const MIN_SEMANTIC_TOKENS = 260;
const OVERLAP_TOKENS = 64;
const ESTIMATED_CHARS_PER_TOKEN = 4;
const MAX_PRIORS_PER_CHUNK = 18;

interface SpanFrame {
    start: number;
    end: number;
    tokens: number;
    text: string;
    role: GraphRebuildChunkRole;
    entityPriors: GraphRebuildChunkEntityPrior[];
    eventCues: string[];
    modalCues: string[];
    temporalCues: string[];
    authorityCues: string[];
    evidenceCues: string[];
    speaker: string;
    paragraphBreakBefore: boolean;
}

export interface GraphRebuildChunkRange {
    start: number;
    end: number;
    ordinal?: number;
}

export function buildAdaptiveGraphRebuildChunks(noteId: string, text: string): GraphRebuildChunk[] {
    if (!text.trim()) return [];
    const spans = sentenceSpans(text).map((span, index, all) =>
        analyzeSpan(text, span.start, span.end, index > 0 ? text.slice(all[index - 1].end, span.start) : ''),
    );
    if (!spans.length) return [chunkFromSpans(noteId, 0, [analyzeSpan(text, 0, text.length, '')], 'single-span')];

    const chunks: GraphRebuildChunk[] = [];
    let window: SpanFrame[] = [];
    let tokens = 0;
    let pendingReason = 'document-start';
    const emit = (reason: string) => {
        if (!window.length) return;
        chunks.push(chunkFromSpans(noteId, chunks.length, window, reason));
    };

    for (const span of spans) {
        const decision = window.length ? boundaryDecision(window, span, tokens) : { cut: false, reason: pendingReason };
        if (decision.cut) {
            emit(decision.reason);
            window = overlapSpans(window);
            tokens = sumTokens(window);
            pendingReason = decision.reason;
        }
        window.push(span);
        tokens += span.tokens;
        if (tokens >= HARD_MAX_TOKENS) {
            emit('hard-token-cap');
            window = overlapSpans(window);
            tokens = sumTokens(window);
            pendingReason = 'hard-token-cap';
        }
    }
    emit(pendingReason);
    return chunks;
}

export function buildGraphRebuildChunksFromRanges(
    noteId: string,
    text: string,
    ranges: GraphRebuildChunkRange[],
): GraphRebuildChunk[] {
    if (!text.trim() || !ranges.length) return [];
    const sourceSpans = sentenceSpans(text).map((span, index, all) =>
        analyzeSpan(text, span.start, span.end, index > 0 ? text.slice(all[index - 1].end, span.start) : ''),
    );
    return ranges
        .filter((range) => range.start >= 0 && range.end > range.start && range.end <= text.length)
        .sort((left, right) => (left.ordinal ?? left.start) - (right.ordinal ?? right.start))
        .map((range, ordinal) => {
            const spans = sourceSpans.filter((span) => span.end > range.start && span.start < range.end);
            const framed = spans.length
                ? spans
                : [analyzeSpan(text, range.start, range.end, range.start > 0 ? text.slice(Math.max(0, range.start - 2), range.start) : '')];
            const chunk = chunkFromSpans(noteId, ordinal, framed, 'native-sentence-window');
            return { ...chunk, start: range.start, end: range.end };
        });
}

export function summarizeMeaningFrame(frame: GraphRebuildMeaningFrame | undefined): string {
    if (!frame) return '';
    const priors = frame.entityPriors
        .slice(0, 8)
        .map((prior) => `${prior.surface}:${prior.likelyKinds.join('/')}`)
        .join(', ');
    const cues = [...frame.authorityCues, ...frame.evidenceCues, ...frame.temporalCues].slice(0, 10).join(', ');
    return [
        `chunk_role:${frame.role}`,
        `split:${frame.splitReason}`,
        priors ? `entity_priors:${priors}` : '',
        cues ? `meaning_cues:${cues}` : '',
    ].filter(Boolean).join('\n');
}

function boundaryDecision(window: SpanFrame[], next: SpanFrame, tokens: number): { cut: boolean; reason: string } {
    const previous = window[window.length - 1];
    const breakPressure = boundaryBreakPressure(window, next);
    const mergePressure = boundaryMergePressure(previous, next);
    if (tokens + next.tokens > HARD_MAX_TOKENS) return { cut: true, reason: 'hard-token-cap' };
    if (tokens < MIN_SEMANTIC_TOKENS) return { cut: false, reason: 'under-minimum-window' };
    if (next.paragraphBreakBefore && tokens >= MIN_SEMANTIC_TOKENS && breakPressure >= mergePressure + 1.4) return { cut: true, reason: 'paragraph-meaning-shift' };
    if (tokens >= TARGET_TOKENS && breakPressure >= mergePressure) return { cut: true, reason: 'target-window-boundary' };
    if (tokens >= TARGET_TOKENS * 0.75 && breakPressure >= mergePressure + 3.2) return { cut: true, reason: 'semantic-frame-shift' };
    return { cut: false, reason: 'merged-continuation' };
}

function boundaryBreakPressure(window: SpanFrame[], next: SpanFrame): number {
    const previous = window[window.length - 1];
    let score = next.paragraphBreakBefore ? 1.2 : 0;
    if (previous.role !== next.role) score += roleShiftPressure(previous.role, next.role);
    if (next.role === 'authority_chain' || next.role === 'evidence_block') score += 1.1;
    if (previous.speaker && next.speaker && previous.speaker !== next.speaker) score += 1.6;
    if (next.temporalCues.length) score += 0.55;
    if (next.entityPriors.some((prior) => prior.reason.includes('regional') || prior.reason.includes('authority'))) score += 0.85;
    return score;
}

function boundaryMergePressure(previous: SpanFrame, next: SpanFrame): number {
    let score = 0.6;
    if (previous.role === next.role) score += 1.2;
    if (previous.speaker && previous.speaker === next.speaker) score += 1.4;
    if (sharedPriorSurface(previous, next)) score += 0.9;
    if (startsWithContinuation(next.text)) score += 1.1;
    if (previous.evidenceCues.length && next.evidenceCues.length) score += 0.8;
    return score;
}

function roleShiftPressure(left: GraphRebuildChunkRole, right: GraphRebuildChunkRole): number {
    if (right === 'authority_chain' || right === 'evidence_block') return 2.2;
    if (left === 'dialogue' && right !== 'dialogue') return 1.6;
    if (right === 'transition') return 1.4;
    return 1.1;
}

function chunkFromSpans(noteId: string, ordinal: number, spans: SpanFrame[], splitReason: string): GraphRebuildChunk {
    const first = spans[0];
    const last = spans[spans.length - 1];
    const frame = aggregateMeaningFrame(spans, splitReason);
    const text = spans.map((span) => span.text).join('\n');
    return {
        id: `${noteId}:chunk:${ordinal}`,
        noteId,
        start: first.start,
        end: last.end,
        ordinal,
        source: 'dynamic-chunking',
        textHash: simpleHash(text),
        role: frame.role,
        splitReason,
        meaningFrame: frame,
    };
}

function aggregateMeaningFrame(spans: SpanFrame[], splitReason: string): GraphRebuildMeaningFrame {
    const roles = spans.map((span) => span.role);
    const role = dominantRole(roles);
    const breakPressure = spans.slice(1).reduce((sum, span, index) =>
        sum + boundaryBreakPressure(spans.slice(0, index + 1), span), 0);
    const mergePressure = spans.slice(1).reduce((sum, span, index) =>
        sum + boundaryMergePressure(spans[index], span), 0);
    const entityPriors = uniquePriors(spans.flatMap((span) => span.entityPriors)).slice(0, MAX_PRIORS_PER_CHUNK);
    return {
        role,
        splitReason,
        breakPressure: round2(breakPressure),
        mergePressure: round2(mergePressure),
        entityPriors,
        eventCues: unique(spans.flatMap((span) => span.eventCues)).slice(0, 16),
        modalCues: unique(spans.flatMap((span) => span.modalCues)).slice(0, 12),
        temporalCues: unique(spans.flatMap((span) => span.temporalCues)).slice(0, 12),
        authorityCues: unique(spans.flatMap((span) => span.authorityCues)).slice(0, 14),
        evidenceCues: unique(spans.flatMap((span) => span.evidenceCues)).slice(0, 14),
        carryoverIn: carryover(spans[0]),
        carryoverOut: carryover(spans[spans.length - 1]),
    };
}

function analyzeSpan(text: string, start: number, end: number, gapBefore: string): SpanFrame {
    const spanText = text.slice(start, end);
    const lower = spanText.toLowerCase();
    const authorityCues = matchingCues(lower, AUTHORITY_CUES);
    const evidenceCues = matchingCues(lower, EVIDENCE_CUES);
    const temporalCues = matchingCues(lower, TEMPORAL_CUES);
    const modalCues = matchingCues(lower, MODAL_CUES);
    const eventCues = matchingCues(lower, EVENT_CUES);
    const entityPriors = inferEntityPriors(spanText, lower);
    return {
        start,
        end,
        tokens: estimatedTokens(start, end),
        text: spanText,
        role: inferRole(spanText, authorityCues, evidenceCues, temporalCues, modalCues),
        entityPriors,
        eventCues,
        modalCues,
        temporalCues,
        authorityCues,
        evidenceCues,
        speaker: inferSpeaker(spanText),
        paragraphBreakBefore: /\n\s*\n/.test(gapBefore),
    };
}

function inferRole(
    text: string,
    authorityCues: string[],
    evidenceCues: string[],
    temporalCues: string[],
    modalCues: string[],
): GraphRebuildChunkRole {
    if (authorityCues.length >= 2) return 'authority_chain';
    if (evidenceCues.length >= 2) return 'evidence_block';
    if (isDialogue(text) || modalCues.length >= 2) return 'dialogue';
    if (temporalCues.length >= 2) return 'transition';
    if (text.includes(':') || text.split('\n').length > 2) return 'exposition_packet';
    return 'scene_action';
}

function inferEntityPriors(text: string, lower: string): GraphRebuildChunkEntityPrior[] {
    const priors: GraphRebuildChunkEntityPrior[] = [];
    for (const surface of namedSurfaces(text)) {
        const near = localWindow(lower, text, surface).toLowerCase();
        const likelyKinds = new Set<string>();
        const reasons: string[] = [];
        if (isNetworkSurface(surface, near)) {
            likelyKinds.add('NETWORK');
            reasons.push('authority_or_group_surface');
        }
        if (isLocationSurface(surface, near)) {
            likelyKinds.add('LOCATION');
            reasons.push('regional_or_place_surface');
        }
        if (!likelyKinds.size && isCharacterSurface(surface, near)) {
            likelyKinds.add('CHARACTER');
            reasons.push('speaker_or_actor_surface');
        }
        if (!likelyKinds.size) continue;
        priors.push({
            surface,
            likelyKinds: [...likelyKinds],
            reason: reasons.join('+'),
            confidence: likelyKinds.has('NETWORK') || likelyKinds.has('LOCATION') ? 0.78 : 0.64,
        });
    }
    if (/\bmilitias?\b/.test(lower)) priors.push({ surface: 'militia', likelyKinds: ['NETWORK'], reason: 'group_common_noun', confidence: 0.72 });
    if (/\bmilitary\b/.test(lower)) priors.push({ surface: 'military', likelyKinds: ['NETWORK'], reason: 'authority_common_noun', confidence: 0.72 });
    return uniquePriors(priors);
}

function namedSurfaces(text: string): string[] {
    const matches = text.match(/\b[A-Z][A-Za-z'’-]*(?:[-\s]+(?:of\s+|the\s+)?[A-Z][A-Za-z'’-]*){0,4}\b/g) || [];
    return unique(matches.map((value) => value.replace(/\s+/g, ' ').trim()).filter((value) => value.length > 2));
}

function isNetworkSurface(surface: string, near: string): boolean {
    const lower = surface.toLowerCase();
    return /\b(table|chiefs|office|operators?|command|force|militias?|military|contractors?|recovery|atlas|phantoms?|warden|council|agency)\b/.test(lower)
        || /\b(command|authority|signed|granted|records|contract|federal|state|militia|military|operators?)\b/.test(near);
}

function isLocationSurface(surface: string, near: string): boolean {
    const lower = surface.toLowerCase();
    return /\b(rouge|mississippi|mesa|cypress|redwater|southwest|south|halcyon|blacktooth|skyglass|arcadia|city|river|range|tower)\b/.test(lower)
        || /\b(in|inside|near|from|to|across|toward|through|at)\s+$/.test(near.slice(0, 18));
}

function isCharacterSurface(surface: string, near: string): boolean {
    return !surface.includes(' ') || /\b(said|asked|answered|looked|watched|stood|walked|read|nodded|smiled|ignored|faced)\b/.test(near);
}

function inferSpeaker(text: string): string {
    const quoteLead = text.match(/^\s*[“"]?([A-Z][A-Za-z'’-]+)\b.{0,80}\b(said|asked|answered|replied|murmured|continued)\b/i);
    if (quoteLead) return quoteLead[1];
    const said = text.match(/\b([A-Z][A-Za-z'’-]+)\s+(said|asked|answered|replied|murmured|continued)\b/);
    return said?.[1] || '';
}

function sentenceSpans(text: string): Array<{ start: number; end: number }> {
    const spans: Array<{ start: number; end: number }> = [];
    let start = 0;
    for (let index = 0; index < text.length; index += 1) {
        if (!isSentenceBoundary(text, index)) continue;
        pushTrimmedSpan(spans, text, start, index + 1);
        start = index + 1;
    }
    pushTrimmedSpan(spans, text, start, text.length);
    return spans;
}

function isSentenceBoundary(text: string, index: number): boolean {
    const char = text[index];
    if (char === '\n') return text[index + 1] === '\n';
    if (char !== '.' && char !== '!' && char !== '?') return false;
    const next = text[index + 1] || '';
    return !next || /\s|["')\]]/.test(next);
}

function pushTrimmedSpan(spans: Array<{ start: number; end: number }>, text: string, start: number, end: number): void {
    while (start < end && /\s/.test(text[start])) start += 1;
    while (end > start && /\s/.test(text[end - 1])) end -= 1;
    if (end > start) spans.push({ start, end });
}

function overlapSpans(spans: SpanFrame[]): SpanFrame[] {
    const out: SpanFrame[] = [];
    let tokens = 0;
    for (let index = spans.length - 1; index >= 0; index -= 1) {
        const span = spans[index];
        if (tokens + span.tokens > OVERLAP_TOKENS) break;
        out.unshift(span);
        tokens += span.tokens;
    }
    return out;
}

function carryover(span: SpanFrame): string[] {
    return unique([
        span.speaker ? `speaker:${span.speaker}` : '',
        ...span.entityPriors.slice(0, 5).map((prior) => `${prior.likelyKinds[0].toLowerCase()}:${prior.surface}`),
    ].filter(Boolean));
}

function dominantRole(roles: GraphRebuildChunkRole[]): GraphRebuildChunkRole {
    const counts = new Map<GraphRebuildChunkRole, number>();
    for (const role of roles) counts.set(role, (counts.get(role) || 0) + roleWeight(role));
    return [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || 'mixed';
}

function roleWeight(role: GraphRebuildChunkRole): number {
    if (role === 'authority_chain' || role === 'evidence_block') return 3;
    if (role === 'dialogue') return 2;
    return 1;
}

function isDialogue(text: string): boolean {
    return /[“"]/.test(text) || /\b(said|asked|answered|replied|murmured)\b/i.test(text);
}

function startsWithContinuation(text: string): boolean {
    return /^(he|she|they|it|that|this|then|and|but|so|because|her|his|their)\b/i.test(text.trim());
}

function sharedPriorSurface(left: SpanFrame, right: SpanFrame): boolean {
    const surfaces = new Set(left.entityPriors.map((prior) => prior.surface.toLowerCase()));
    return right.entityPriors.some((prior) => surfaces.has(prior.surface.toLowerCase()));
}

function localWindow(lower: string, original: string, surface: string): string {
    const index = original.indexOf(surface);
    if (index < 0) return '';
    return lower.slice(Math.max(0, index - 80), Math.min(lower.length, index + surface.length + 80));
}

function matchingCues(text: string, cues: readonly string[]): string[] {
    return cues.filter((cue) => text.includes(cue));
}

function estimatedTokens(start: number, end: number): number {
    return Math.max(1, Math.ceil(Math.max(0, end - start) / ESTIMATED_CHARS_PER_TOKEN));
}

function sumTokens(spans: SpanFrame[]): number {
    return spans.reduce((sum, span) => sum + span.tokens, 0);
}

function uniquePriors(priors: GraphRebuildChunkEntityPrior[]): GraphRebuildChunkEntityPrior[] {
    const bySurface = new Map<string, GraphRebuildChunkEntityPrior>();
    for (const prior of priors) {
        const key = prior.surface.toLowerCase();
        const current = bySurface.get(key);
        if (!current || prior.confidence > current.confidence) bySurface.set(key, prior);
    }
    return [...bySurface.values()].sort((left, right) => right.confidence - left.confidence || left.surface.localeCompare(right.surface));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function round2(value: number): number {
    return Math.round(value * 100) / 100;
}

function simpleHash(value: string): string {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
}

const AUTHORITY_CUES = ['command', 'authority', 'chiefs', 'operator', 'operators', 'office', 'military', 'militia', 'federal', 'state', 'granted', 'signed', 'table', 'warden', 'phantom'] as const;
const EVIDENCE_CUES = ['packet', 'record', 'records', 'contract', 'files', 'slate', 'board', 'report', 'pane', 'map', 'intake', 'detention'] as const;
const TEMPORAL_CUES = ['before', 'after', 'then', 'until', 'once', 'as soon', 'current', 'replay', 'already', 'now'] as const;
const MODAL_CUES = ['said', 'asked', 'answered', 'believed', 'wanted', 'needed', 'claimed', 'ordered', 'granted', 'refused'] as const;
const EVENT_CUES = ['opened', 'moved', 'walked', 'read', 'watched', 'shifted', 'arrived', 'entered', 'detained', 'selected', 'assigned'] as const;
