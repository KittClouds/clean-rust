export type DocumentProfileKind =
    | 'prose_fiction'
    | 'research_paper'
    | 'legal_policy'
    | 'technical_docs'
    | 'meeting_notes'
    | 'code_heavy_notes'
    | 'trading_system_specs'
    | 'reference_article'
    | 'mixed_notebook';

export interface DocumentProfileWeight {
    profile: DocumentProfileKind;
    score: number;
}

export interface DocumentProfileSignal {
    id: string;
    profile: DocumentProfileKind;
    cue: string;
    occurrences: number;
    contribution: number;
    start: number;
    end: number;
}

export interface DocumentUnitWeight {
    kind: string;
    weight: number;
}

export interface DocumentRegionProfile {
    id: string;
    noteId: string;
    start: number;
    end: number;
    dominantProfile: DocumentProfileKind;
    confidence: number;
    weights: DocumentProfileWeight[];
    signals: DocumentProfileSignal[];
}

export interface DocumentProfile {
    noteId: string;
    dominantProfile: DocumentProfileKind;
    confidence: number;
    weights: DocumentProfileWeight[];
    unitWeights: DocumentUnitWeight[];
    signals: DocumentProfileSignal[];
    regions: DocumentRegionProfile[];
}

export interface GraphDocumentProfileSummary {
    schemaVersion: 'phoenix-document-profile/v1';
    source: 'native_rust' | 'typescript_compatibility';
    builtAt: number;
    profiles: DocumentProfile[];
    counters: {
        documents: number;
        regions: number;
        signals: number;
        nativeProfiles: number;
        byProfile: Record<string, number>;
    };
}

type ScoreMap = Record<DocumentProfileKind, number>;

const PROFILE_KINDS: DocumentProfileKind[] = [
    'prose_fiction',
    'research_paper',
    'legal_policy',
    'technical_docs',
    'meeting_notes',
    'code_heavy_notes',
    'trading_system_specs',
    'reference_article',
    'mixed_notebook',
];

const CUES: Array<[DocumentProfileKind, string, number]> = [
    ['prose_fiction', 'chapter ', 2.4], ['prose_fiction', 'scene ', 2.2],
    ['prose_fiction', 'said', 0.65], ['prose_fiction', 'asked', 0.6],
    ['prose_fiction', 'replied', 0.65],
    ['research_paper', 'abstract', 2], ['research_paper', 'method', 1.5],
    ['research_paper', 'results', 1.6], ['research_paper', 'we show', 1.4],
    ['research_paper', 'et al.', 1.4], ['legal_policy', 'shall', 1.6],
    ['legal_policy', 'pursuant', 1.8], ['legal_policy', 'herein', 1.6],
    ['legal_policy', 'compliance', 1.2], ['technical_docs', 'api', 1.1],
    ['technical_docs', 'install', 1.2], ['technical_docs', 'configure', 1.3],
    ['technical_docs', 'architecture', 1], ['meeting_notes', 'agenda', 1.7],
    ['meeting_notes', 'attendees', 1.8], ['meeting_notes', 'action item', 1.8],
    ['meeting_notes', 'next steps', 1.5], ['meeting_notes', 'owner:', 1.4],
    ['code_heavy_notes', '```', 2.4], ['code_heavy_notes', 'fn ', 1.4],
    ['code_heavy_notes', 'class ', 1.1], ['code_heavy_notes', 'const ', 1.1],
    ['trading_system_specs', 'entry', 1], ['trading_system_specs', 'exit', 1],
    ['trading_system_specs', 'stop loss', 1.8], ['trading_system_specs', 'take profit', 1.8],
    ['trading_system_specs', 'position size', 1.6], ['trading_system_specs', 'backtest', 1.5],
    ['trading_system_specs', 'risk', 0.8],
    ['reference_article', 'overview', 1.4], ['reference_article', 'learn more', 1.5],
    ['reference_article', 'according to', 1.2], ['reference_article', 'researchers', 0.8],
    ['reference_article', 'scientists', 0.8], ['reference_article', 'for example', 0.7],
    ['reference_article', 'refers to', 0.9], ['reference_article', 'is known as', 0.9],
    ['reference_article', 'standard', 0.8],
];

const UNIT_KINDS = [
    'chapter', 'scene', 'dialogue_block', 'action_block', 'claim', 'evidence', 'definition',
    'example', 'contrast', 'method', 'result', 'instruction', 'decision', 'question', 'event',
    'state_change', 'relation_bundle', 'procedure_step', 'n_ary_claim', 'code_block',
    'citation_span', 'parent_chunk', 'cross_doc_topic_packet',
];

export function normalizeDocumentProfileSummary(value: unknown): GraphDocumentProfileSummary | null {
    if (!value || typeof value !== 'object') return null;
    const summary = value as Partial<GraphDocumentProfileSummary>;
    if (summary.schemaVersion !== 'phoenix-document-profile/v1' || !Array.isArray(summary.profiles)) return null;
    return summary as GraphDocumentProfileSummary;
}

export function buildFallbackDocumentProfileSummary(
    noteTexts: Record<string, string>,
    builtAt: number,
): GraphDocumentProfileSummary {
    const profiles = Object.entries(noteTexts).map(([noteId, text]) => classifyDocument(noteId, text));
    const byProfile: Record<string, number> = {};
    for (const profile of profiles) byProfile[profile.dominantProfile] = (byProfile[profile.dominantProfile] || 0) + 1;
    return {
        schemaVersion: 'phoenix-document-profile/v1',
        source: 'typescript_compatibility',
        builtAt,
        profiles,
        counters: {
            documents: profiles.length,
            regions: profiles.reduce((sum, profile) => sum + profile.regions.length, 0),
            signals: profiles.reduce((sum, profile) => sum + profile.signals.length, 0),
            nativeProfiles: 0,
            byProfile,
        },
    };
}

export function documentUnitWeight(
    summary: GraphDocumentProfileSummary | undefined,
    noteId: string,
    kind: string,
    sourceStart?: number,
): number {
    const profile = summary?.profiles.find((row) => row.noteId === noteId);
    if (!profile) return 1;
    if (sourceStart !== undefined) {
        const region = profile.regions.find((row) => row.start <= sourceStart && row.end >= sourceStart);
        if (region) return blendedKindWeight(region.weights, kind);
    }
    return profile.unitWeights.find((row) => row.kind === kind)?.weight ?? 1;
}

export function profileLabel(profile: DocumentProfileKind): string {
    return profile.split('_').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function classifyDocument(noteId: string, text: string): DocumentProfile {
    const classified = classifySpan(noteId, text, 0, text.length, true);
    const regions = paragraphRanges(text).slice(0, 192).map(([start, end]) => {
        const region = classifySpan(noteId, text.slice(start, end), start, end, false);
        return {
            id: `${noteId}:profile-region:${start}:${end}`,
            noteId,
            start,
            end,
            dominantProfile: region.dominantProfile,
            confidence: region.confidence,
            weights: region.weights,
            signals: region.signals,
        };
    });
    return {
        noteId,
        dominantProfile: classified.dominantProfile,
        confidence: classified.confidence,
        weights: classified.weights,
        signals: classified.signals,
        regions,
        unitWeights: UNIT_KINDS.map((kind) => ({ kind, weight: blendedKindWeight(classified.weights, kind) })),
    };
}

function classifySpan(noteId: string, text: string, start: number, end: number, includeMixed: boolean) {
    const lower = text.toLowerCase();
    const scores = Object.fromEntries(PROFILE_KINDS.map((profile) => [
        profile,
        profile === 'mixed_notebook' ? (includeMixed ? 0.12 : 0.5) : profile === 'reference_article' ? (includeMixed ? 0.55 : 0.45) : 0.35,
    ])) as ScoreMap;
    const signals: DocumentProfileSignal[] = [];
    for (const [profile, cue, weight] of CUES) {
        const occurrences = countBounded(lower, cue.trim());
        if (!occurrences) continue;
        const contribution = weight * Math.sqrt(occurrences);
        scores[profile] += contribution;
        if (signals.length < 24) signals.push({ id: `${noteId}:profile-signal:${profile}:${signals.length}`, profile, cue: cue.trim(), occurrences, contribution: round3(contribution), start, end });
    }
    addShapeSignal(scores, signals, noteId, 'prose_fiction', 'dialogue-shaped lines', text.split('\n').filter((line) => /^\s*["“]/.test(line)).length, 0.45, start, end);
    addShapeSignal(scores, signals, noteId, 'code_heavy_notes', 'code-shaped lines', lower.split('\n').filter((line) => /^\s*(fn |class |const |let |def )/.test(line) || line.trimEnd().endsWith(';')).length, 0.85, start, end);
    addShapeSignal(scores, signals, noteId, 'meeting_notes', 'checklist lines', lower.split('\n').filter((line) => /^\s*[-*]\s*\[[ x]\]/.test(line)).length, 0.75, start, end);
    addShapeSignal(scores, signals, noteId, 'reference_article', 'sectioned explanatory prose', lower.split('\n').filter((line) => /^\s*#/.test(line)).length, 0.55, start, end);
    if (lower.includes('references') || lower.includes('bibliography')) {
        const citations = Math.min(countOccurrences(lower, '('), countOccurrences(lower, ')')) || 1;
        const researchShaped = lower.includes('abstract') || lower.includes('method') || lower.includes('results');
        addShapeSignal(scores, signals, noteId, researchShaped ? 'research_paper' : 'reference_article', 'citation structure', citations, 0.32, start, end);
    }
    if (includeMixed) {
        const active = PROFILE_KINDS.slice(0, -1).filter((profile) => scores[profile] >= 1.6).length;
        const ranked = PROFILE_KINDS.slice(0, -1).map((profile) => scores[profile]).sort((a, b) => b - a);
        scores.mixed_notebook += Math.max(0, active - 1) * 0.9 + (ranked[1] || 0) / Math.max(0.01, ranked[0] || 1) * 0.8;
    }
    const total = PROFILE_KINDS.reduce((sum, profile) => sum + scores[profile], 0);
    const weights = PROFILE_KINDS.map((profile) => ({ profile, score: round3(scores[profile] / total) })).sort((a, b) => b.score - a.score);
    const top = weights[0]?.score || 0;
    const second = weights[1]?.score || 0;
    return { dominantProfile: weights[0]?.profile || 'mixed_notebook' as DocumentProfileKind, confidence: round3(Math.min(1, top + Math.max(0, top - second) * 0.7)), weights, signals };
}

function addShapeSignal(scores: ScoreMap, signals: DocumentProfileSignal[], noteId: string, profile: DocumentProfileKind, cue: string, occurrences: number, weight: number, start: number, end: number): void {
    if (!occurrences) return;
    const contribution = weight * Math.sqrt(occurrences);
    scores[profile] += contribution;
    if (signals.length < 24) signals.push({ id: `${noteId}:profile-shape:${profile}:${signals.length}`, profile, cue, occurrences, contribution: round3(contribution), start, end });
}

function blendedKindWeight(weights: DocumentProfileWeight[], kind: string): number {
    return round3(Math.max(0.55, Math.min(1.55, weights.reduce((sum, row) => sum + row.score * profileKindWeight(row.profile, kind), 0))));
}

function profileKindWeight(profile: DocumentProfileKind, kind: string): number {
    const boosted: Partial<Record<DocumentProfileKind, Record<string, number>>> = {
        prose_fiction: { chapter: 1.5, scene: 1.5, dialogue_block: 1.4, action_block: 1.4, event: 1.25, state_change: 1.25 },
        research_paper: { method: 1.5, result: 1.5, claim: 1.4, evidence: 1.4, citation_span: 1.4, n_ary_claim: 1.25 },
        legal_policy: { definition: 1.4, decision: 1.4, instruction: 1.3, claim: 1.2, evidence: 1.2 },
        technical_docs: { instruction: 1.5, procedure_step: 1.5, code_block: 1.5, definition: 1.25, example: 1.25 },
        meeting_notes: { decision: 1.45, question: 1.45, instruction: 1.45, event: 1.2, procedure_step: 1.2 },
        code_heavy_notes: { code_block: 1.55, instruction: 1.35, procedure_step: 1.35, example: 1.35 },
        trading_system_specs: { instruction: 1.45, procedure_step: 1.45, state_change: 1.45, event: 1.25, relation_bundle: 1.25 },
        reference_article: { definition: 1.4, example: 1.4, claim: 1.3, evidence: 1.3, relation_bundle: 1.3, n_ary_claim: 1.2, citation_span: 1.2 },
        mixed_notebook: {},
    };
    return boosted[profile]?.[kind] ?? (profile === 'mixed_notebook' ? 1 : kind === 'parent_chunk' || kind === 'cross_doc_topic_packet' ? 1 : 0.9);
}

function paragraphRanges(text: string): Array<[number, number]> {
    const ranges: Array<[number, number]> = [];
    const pattern = /\S[\s\S]*?(?=\r?\n\s*\r?\n|$)/g;
    for (const match of text.matchAll(pattern)) ranges.push([match.index, match.index + match[0].trimEnd().length]);
    return ranges.length ? ranges : text.trim() ? [[0, text.length]] : [];
}

function countOccurrences(text: string, cue: string): number {
    let count = 0;
    let cursor = 0;
    while ((cursor = text.indexOf(cue, cursor)) >= 0) { count += 1; cursor += cue.length; }
    return count;
}

function countBounded(text: string, cue: string): number {
    if (!cue) return 0;
    let count = 0;
    let cursor = 0;
    while ((cursor = text.indexOf(cue, cursor)) >= 0) {
        const before = cursor > 0 ? text[cursor - 1] : '';
        const after = text[cursor + cue.length] || '';
        if (!isWordCharacter(before) && !isWordCharacter(after)) count += 1;
        cursor += cue.length;
    }
    return count;
}

function isWordCharacter(value: string): boolean {
    return /[a-z0-9_]/i.test(value);
}

function round3(value: number): number { return Math.round(value * 1000) / 1000; }
