export const LFM_EXTRACTIVE_SMOOTHING_MODEL_ID = 'onnx-community/LFM2.5-350M-ONNX';
export const LFM_EXTRACTIVE_SMOOTHING_DEFAULT_DTYPE = 'fp16';
export const LFM_EXTRACTIVE_SMOOTHING_MAX_NEW_TOKENS = 192;

export type LfmExtractiveSmoothingSource = 'lfm2.5_fp16' | 'lfm2.5_q4' | 'deterministic_fallback';

export interface ExtractiveSummaryEvidence {
    id: string;
    text: string;
    sourceId?: string;
    weight?: number;
}

export interface ExtractiveSummaryDraftBullet {
    id?: string;
    text: string;
    evidenceIds: string[];
}

export interface LfmExtractiveSmoothingRequest {
    title?: string;
    evidence: ExtractiveSummaryEvidence[];
    draftBullets: ExtractiveSummaryDraftBullet[];
    maxBullets?: number;
}

export interface LfmExtractiveSmoothingBullet {
    text: string;
    evidenceIds: string[];
    source: LfmExtractiveSmoothingSource;
}

export interface LfmExtractiveSmoothingIssue {
    code:
        | 'empty_text'
        | 'missing_evidence'
        | 'unknown_evidence'
        | 'unsupported_atom'
        | 'too_few_supported_bullets'
        | 'no_json_payload';
    bulletIndex: number | null;
    detail: string;
}

export interface LfmExtractiveSmoothingResult {
    outcome: 'accepted' | 'partial' | 'fallback';
    bullets: LfmExtractiveSmoothingBullet[];
    modelBullets: LfmExtractiveSmoothingBullet[];
    fallbackBullets: LfmExtractiveSmoothingBullet[];
    issues: LfmExtractiveSmoothingIssue[];
    counters: {
        parsedBullets: number;
        acceptedModelBullets: number;
        fallbackBullets: number;
        issueCount: number;
    };
}

type ChatMessage = {
    role: 'system' | 'user';
    content: string;
};

const MAX_EVIDENCE = 12;
const MAX_DRAFT_BULLETS = 8;
const MAX_TEXT_CHARS = 520;
const DEFAULT_MAX_BULLETS = 4;
const MONTHS = new Set([
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
]);
const PROPER_STOPWORDS = new Set([
    'a', 'an', 'and', 'as', 'at', 'because', 'but', 'by', 'for', 'from',
    'in', 'into', 'of', 'on', 'or', 'the', 'to', 'with',
]);

export function buildLfmExtractiveSmoothingMessages(request: LfmExtractiveSmoothingRequest): ChatMessage[] {
    const targetCount = smoothingTargetCount(request);
    const evidenceLines = safeEvidence(request.evidence)
        .slice(0, MAX_EVIDENCE)
        .map(row => `[${row.id}] ${row.text}`);
    const draftLines = safeDraftBullets(request.draftBullets)
        .slice(0, MAX_DRAFT_BULLETS)
        .map(row => `- ${row.text} ${formatEvidenceRefs(row.evidenceIds)}`.trim());

    return [
        {
            role: 'system',
            content: [
                'You are a constrained rewrite engine for extractive summaries.',
                'Rewrite only the supplied draft bullets.',
                'Preserve every name, date, number, count, object, place, and relationship exactly.',
                'Do not infer, combine unsupported facts, rename entities, or add connective lore.',
                'Return only valid JSON. No markdown.',
                'Schema: [{"text":"polished bullet","evidenceIds":["e1"]}].',
            ].join(' '),
        },
        {
            role: 'user',
            content: [
                `Title: ${normalizeText(request.title || 'Untitled')}`,
                `Target bullets: ${targetCount}`,
                '',
                'Evidence:',
                ...evidenceLines,
                '',
                'Draft bullets:',
                ...draftLines,
                '',
                'Rewrite the draft bullets into concise reader-facing bullets.',
                'Every output bullet must cite one or more evidenceIds from the evidence list.',
            ].join('\n'),
        },
    ];
}

export function parseLfmExtractiveSmoothingOutput(outputText: string): LfmExtractiveSmoothingBullet[] {
    const payloads = collectJsonPayloads(outputText);
    const bullets: LfmExtractiveSmoothingBullet[] = [];

    for (const payload of payloads) {
        const parsed = parseJson(payload);
        for (const candidate of coerceBulletArray(parsed)) {
            const bullet = coerceBullet(candidate);
            if (bullet) {
                bullets.push(bullet);
            }
        }
    }

    return dedupeBullets(bullets);
}

export function verifyLfmExtractiveSmoothingBullets(
    request: LfmExtractiveSmoothingRequest,
    bullets: LfmExtractiveSmoothingBullet[],
): { acceptedBullets: LfmExtractiveSmoothingBullet[]; issues: LfmExtractiveSmoothingIssue[] } {
    const evidenceById = new Map(safeEvidence(request.evidence).map(row => [row.id, row.text] as const));
    const acceptedBullets: LfmExtractiveSmoothingBullet[] = [];
    const issues: LfmExtractiveSmoothingIssue[] = [];

    bullets.forEach((bullet, index) => {
        const text = normalizeText(bullet.text);
        if (!text) {
            issues.push({ code: 'empty_text', bulletIndex: index, detail: 'model bullet had no text' });
            return;
        }

        const evidenceIds = dedupeIds(bullet.evidenceIds);
        if (!evidenceIds.length) {
            issues.push({ code: 'missing_evidence', bulletIndex: index, detail: text });
            return;
        }

        const unknown = evidenceIds.filter(id => !evidenceById.has(id));
        if (unknown.length) {
            issues.push({ code: 'unknown_evidence', bulletIndex: index, detail: unknown.join(', ') });
            return;
        }

        const citedText = evidenceIds.map(id => evidenceById.get(id) || '').join(' ');
        const unsupported = unsupportedAtoms(text, citedText);
        if (unsupported.length) {
            issues.push({ code: 'unsupported_atom', bulletIndex: index, detail: unsupported.join(', ') });
            return;
        }

        acceptedBullets.push({ ...bullet, text, evidenceIds });
    });

    return { acceptedBullets, issues };
}

export function adjudicateLfmExtractiveSmoothingOutput(
    request: LfmExtractiveSmoothingRequest,
    outputText: string,
    source: Exclude<LfmExtractiveSmoothingSource, 'deterministic_fallback'> = 'lfm2.5_fp16',
): LfmExtractiveSmoothingResult {
    const parsed = parseLfmExtractiveSmoothingOutput(outputText).map(row => ({ ...row, source }));
    const targetCount = smoothingTargetCount(request);
    const issues: LfmExtractiveSmoothingIssue[] = [];

    if (!parsed.length) {
        issues.push({ code: 'no_json_payload', bulletIndex: null, detail: 'model output had no JSON bullets' });
    }

    const verified = verifyLfmExtractiveSmoothingBullets(request, parsed);
    issues.push(...verified.issues);

    const modelBullets = verified.acceptedBullets.slice(0, targetCount);
    if (modelBullets.length < targetCount) {
        issues.push({
            code: 'too_few_supported_bullets',
            bulletIndex: null,
            detail: `${modelBullets.length}/${targetCount} supported bullets`,
        });
    }

    const fallbackBullets = buildFallbackExtractiveSmoothingBullets(request, targetCount, modelBullets);
    const bullets = [...modelBullets, ...fallbackBullets].slice(0, targetCount);
    const outcome = modelBullets.length === 0
        ? 'fallback'
        : (fallbackBullets.length ? 'partial' : 'accepted');

    return {
        outcome,
        bullets,
        modelBullets,
        fallbackBullets,
        issues,
        counters: {
            parsedBullets: parsed.length,
            acceptedModelBullets: modelBullets.length,
            fallbackBullets: fallbackBullets.length,
            issueCount: issues.length,
        },
    };
}

export function buildFallbackExtractiveSmoothingBullets(
    request: LfmExtractiveSmoothingRequest,
    maxBullets = smoothingTargetCount(request),
    reserved: LfmExtractiveSmoothingBullet[] = [],
): LfmExtractiveSmoothingBullet[] {
    const remaining = maxBullets - reserved.length;
    if (remaining <= 0) {
        return [];
    }

    const usedEvidence = new Set(reserved.flatMap(row => row.evidenceIds));
    const bullets: LfmExtractiveSmoothingBullet[] = [];

    for (const draft of safeDraftBullets(request.draftBullets)) {
        const evidenceIds = draft.evidenceIds.filter(id => !usedEvidence.has(id));
        if (!evidenceIds.length) {
            continue;
        }
        bullets.push({
            text: stripEvidenceRefs(draft.text),
            evidenceIds,
            source: 'deterministic_fallback',
        });
        evidenceIds.forEach(id => usedEvidence.add(id));
        if (bullets.length >= remaining) {
            return bullets;
        }
    }

    for (const evidence of safeEvidence(request.evidence)) {
        if (usedEvidence.has(evidence.id)) {
            continue;
        }
        bullets.push({
            text: evidence.text,
            evidenceIds: [evidence.id],
            source: 'deterministic_fallback',
        });
        usedEvidence.add(evidence.id);
        if (bullets.length >= remaining) {
            break;
        }
    }

    return bullets;
}

function smoothingTargetCount(request: LfmExtractiveSmoothingRequest): number {
    const requested = request.maxBullets ?? Math.min(DEFAULT_MAX_BULLETS, request.draftBullets.length || request.evidence.length);
    return Math.max(1, Math.min(DEFAULT_MAX_BULLETS, requested));
}

function safeEvidence(rows: ExtractiveSummaryEvidence[]): ExtractiveSummaryEvidence[] {
    const seen = new Set<string>();
    const result: ExtractiveSummaryEvidence[] = [];
    for (const row of rows) {
        const id = normalizeId(row.id);
        const text = normalizeText(row.text).slice(0, MAX_TEXT_CHARS);
        if (!id || !text || seen.has(id)) {
            continue;
        }
        seen.add(id);
        result.push({ ...row, id, text });
    }
    return result;
}

function safeDraftBullets(rows: ExtractiveSummaryDraftBullet[]): ExtractiveSummaryDraftBullet[] {
    return rows
        .map(row => ({
            ...row,
            text: normalizeText(row.text).slice(0, MAX_TEXT_CHARS),
            evidenceIds: dedupeIds(row.evidenceIds),
        }))
        .filter(row => row.text && row.evidenceIds.length);
}

function coerceBullet(candidate: unknown): LfmExtractiveSmoothingBullet | null {
    if (!candidate || typeof candidate !== 'object') {
        return null;
    }
    const raw = candidate as {
        text?: unknown;
        summary?: unknown;
        bullet?: unknown;
        evidenceIds?: unknown;
        evidence_ids?: unknown;
        sourceIds?: unknown;
        sources?: unknown;
    };
    const text = firstString(raw.text, raw.summary, raw.bullet);
    const evidenceIds = coerceIds(raw.evidenceIds ?? raw.evidence_ids ?? raw.sourceIds ?? raw.sources);
    return text ? { text: normalizeText(text), evidenceIds, source: 'lfm2.5_fp16' } : null;
}

function coerceBulletArray(parsed: unknown): unknown[] {
    if (Array.isArray(parsed)) {
        return parsed;
    }
    if (!parsed || typeof parsed !== 'object') {
        return [];
    }
    const raw = parsed as { bullets?: unknown; summaries?: unknown; items?: unknown };
    for (const value of [raw.bullets, raw.summaries, raw.items]) {
        if (Array.isArray(value)) {
            return value;
        }
    }
    return firstString((parsed as { text?: unknown }).text, (parsed as { summary?: unknown }).summary) ? [parsed] : [];
}

function collectJsonPayloads(text: string): string[] {
    const payloads: string[] = [];
    let start = -1;
    const stack: string[] = [];
    let inString = false;
    let escaped = false;

    for (let index = 0; index < text.length; index++) {
        const char = text[index];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (char === '\\') {
            escaped = inString;
            continue;
        }
        if (char === '"') {
            inString = !inString;
            continue;
        }
        if (inString) {
            continue;
        }
        if (char === '{' || char === '[') {
            if (stack.length === 0) {
                start = index;
            }
            stack.push(char === '{' ? '}' : ']');
            continue;
        }
        if (stack.length && char === stack[stack.length - 1]) {
            stack.pop();
            if (stack.length === 0 && start >= 0) {
                payloads.push(text.slice(start, index + 1));
                start = -1;
            }
        }
    }

    return payloads;
}

function unsupportedAtoms(text: string, evidenceText: string): string[] {
    const normalizedEvidence = atomNormalize(evidenceText);
    return [...criticalAtoms(text)].filter(atom => !normalizedEvidence.includes(atomNormalize(atom)));
}

function criticalAtoms(text: string): Set<string> {
    const atoms = new Set<string>();
    const numberPattern = /\b\d+(?:[.,:/-]\d+)*(?:st|nd|rd|th)?\b/gi;
    const properPattern = /\b[A-Z][\p{L}\d]*(?:\s+[A-Z][\p{L}\d]*)*\b/gu;

    for (const match of text.matchAll(numberPattern)) {
        atoms.add(match[0]);
    }
    for (const match of text.matchAll(properPattern)) {
        const phrase = match[0].trim();
        const normalized = phrase.toLocaleLowerCase();
        if (phrase.length > 2 && !PROPER_STOPWORDS.has(normalized)) {
            atoms.add(phrase);
        }
    }
    for (const word of text.split(/\s+/)) {
        const normalized = word.replace(/[^\p{L}]/gu, '').toLocaleLowerCase();
        if (MONTHS.has(normalized)) {
            atoms.add(word.replace(/[^\p{L}]/gu, ''));
        }
    }

    return atoms;
}

function parseJson(payload: string): unknown | null {
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

function dedupeBullets(rows: LfmExtractiveSmoothingBullet[]): LfmExtractiveSmoothingBullet[] {
    const seen = new Set<string>();
    return rows.filter(row => {
        const key = `${atomNormalize(row.text)}:${row.evidenceIds.join('|')}`;
        if (seen.has(key)) {
            return false;
        }
        seen.add(key);
        return true;
    });
}

function firstString(...values: unknown[]): string | null {
    for (const value of values) {
        if (typeof value === 'string' && value.trim()) {
            return value;
        }
    }
    return null;
}

function coerceIds(value: unknown): string[] {
    if (Array.isArray(value)) {
        return dedupeIds(value.filter((entry): entry is string => typeof entry === 'string'));
    }
    if (typeof value === 'string') {
        return dedupeIds(value.split(/[, ]+/));
    }
    return [];
}

function dedupeIds(ids: string[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const id of ids) {
        const normalized = normalizeId(id);
        if (!normalized || seen.has(normalized)) {
            continue;
        }
        seen.add(normalized);
        result.push(normalized);
    }
    return result;
}

function normalizeId(value: string): string {
    return String(value || '').trim().replace(/^\[|\]$/g, '');
}

function normalizeText(value: string): string {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function atomNormalize(value: string): string {
    return normalizeText(value).toLocaleLowerCase();
}

function formatEvidenceRefs(ids: string[]): string {
    return dedupeIds(ids).map(id => `[${id}]`).join(' ');
}

function stripEvidenceRefs(value: string): string {
    return normalizeText(value.replace(/\[[^\]]+\]/g, ''));
}
