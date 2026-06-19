import { Injectable, computed, inject, signal } from '@angular/core';
import {
    coalesceDiscoveryCandidates,
    type PhoenixDiscoveryCandidate,
} from '../lib/phoenix/phoenix-discovery';
import { PhoenixUiApiService } from './phoenix-ui-api.service';
import type { AtlasRichScanCandidateSummary } from './phoenix-ui-api.service';
import { NoteEditorStore } from '../lib/store/note-editor.store';
import { smartGraphRegistry } from '../lib/registry';
import { getSetting, setSetting } from '../lib/dexie/settings.service';
import { v4 as uuidv4 } from 'uuid';
import { LfmLocalEntitySuggestionProvider } from '../lib/services/lfm-local-entity-suggestion.service';
import { GlinerLocalEntitySuggestionProvider } from '../lib/services/gliner-local-entity-suggestion.service';
import type {
    EntitySuggestionProviderApi,
    EntitySuggestionProviderId,
    EntitySuggestionProviderStatus,
    EntitySuggestionScanRequest,
    LocalEntitySuggestion,
} from '../lib/entity-suggestions/entity-suggestion.types';
import {
    isLikelyJunkEntityLabel,
    mapConfidenceLevelToScore,
    mapScoreToConfidenceLevel,
    normalizeSuggestedEntityKind,
} from '../lib/entity-suggestions/lfm-local-entity-utils';
import {
    filterRejectedSuggestions,
    recordSuggestionAccepted,
    recordSuggestionRejected,
} from '../lib/entity-learning/entity-feedback';
import { recordAcceptedEntityAnchor } from '../graph-rebuild/entity-anchor-acceptance';
import type { EntityOccurrence } from '../lib/dexie/db';

class PhoenixScanEntitySuggestionProvider implements EntitySuggestionProviderApi {
    readonly id = 'dynamic_ner' as const;

    constructor(private readonly phoenixUiApi: PhoenixUiApiService) {}

    async scan(request: EntitySuggestionScanRequest): Promise<LocalEntitySuggestion[]> {
        const rawSuggestions = await this.phoenixUiApi.scanDiscovery(request.plainText);
        if (!Array.isArray(rawSuggestions) || !rawSuggestions.length) {
            return [];
        }

        const deduped = coalesceDiscoveryCandidates(
            rawSuggestions.map((suggestion) => ({
                ...suggestion,
                key: suggestion.key || normalizeSuggestionKey(suggestion.token),
            })) as PhoenixDiscoveryCandidate[],
        );

        return deduped
            .filter((candidate) => {
                const isKnown = smartGraphRegistry.isRegisteredEntity(candidate.token);
                const isPromoted = Number(candidate.status || 0) === 1;
                return !isKnown && !isPromoted;
            })
            .filter((candidate) => isPlausiblePhoenixDiscoveryCandidate(candidate, request.plainText))
            .map((candidate) => ({
                label: cleanPhoenixCandidateLabel(candidate.token) || 'Unknown',
                kind: resolvePhoenixScanKind(candidate, request.plainText),
                confidence: mapScoreToConfidenceLevel(Number(candidate.score || 0.8)),
                rawScore: Number(candidate.score || 0.8),
                reasoning: '',
                evidence: '',
                aliases: [],
            }));
    }

    async getStatus(): Promise<EntitySuggestionProviderStatus> {
        return {
            ready: true,
            loading: false,
            device: null,
        };
    }

    async dispose(): Promise<void> {
        return;
    }
}

const PERSON_LIKE_ACTIONS = [
    'said', 'says', 'asked', 'asks', 'answered', 'answers', 'replied', 'replies',
    'murmured', 'whispered', 'called', 'shouted', 'laughed', 'smiled', 'sighed',
    'huffed', 'glanced', 'looked', 'watched', 'turned', 'lifted', 'rolled',
    'stood', 'sat', 'walked', 'crossed', 'dragged', 'muttered', 'moved', 'met', 'meet', 'meets',
    'held', 'gave', 'took', 'disliked', 'followed', 'forced', 'kept',
    'responded', 'set', 'wanted', 'went',
];

const KNOWN_LOCATION_SURFACES = new Set([
    'germany',
    'dc citadel',
    'white house',
    'blackroot works',
    'baton rouge',
    'lower mississippi',
    'red mesa',
    'red mesa marker',
    'redwater',
    'black cypress',
    'blacktooth',
    'boundary keep',
    'skyglass',
    'malachor',
    'halcyon',
    'south',
    'southwest',
]);

const LOCATION_SUFFIX_PATTERN = /\b(?:citadel|works|tower|palace|house|harbor|port|city|capital|country|nation|realm|kingdom|empire|territory|province|region|mesa|keep|range|ranges|road|roads|route|routes|river|rivers|lock|locks|zone|zones|camp|camps)\b/iu;

const CONCEPT_SURFACE_PATTERN = /\b(?:concept|theory|principle|rule|law|field|system|force|rank|state|claim|claims)\b/iu;

const NPC_ROLE_SURFACE_PATTERN = /\b(?:guard|teenager|girl|woman|boy|vendor|folk|denizen|citizen|civilian|elder|soldier|warrior|mage|priest|healer|merchant)\b/iu;

const KNOWN_NETWORK_SURFACES = new Set([
    'allied table',
    'atlas',
    'joint chiefs',
    'operator office',
    'operators',
    'phantom command',
    'phantom authority',
    'phantoms',
    'warden force',
    'canton recovery',
    'federal range command',
    'state emergency command',
    'private claim crews',
    'containment forces',
    'militia',
    'militias',
    'military',
]);

const NETWORK_SUFFIX_PATTERN = /\b(?:table|chiefs|operators?|office|force|forces|command|authority|agency|alliance|guild|crew|crews|clan|council|department|directorate|committee|institution|contractors?|militia|militias|military)\b/iu;

const PHOENIX_DISCOVERY_STOPWORDS = new Set([
    'a', 'an', 'and', 'are', 'as', 'at', 'above', 'absolute', 'absolutely',
    'accepted', 'access', 'accurate', 'again', 'all', 'almost', 'already',
    'also', 'any', 'around',
    'because', 'behind', 'better', 'bigger', 'black', 'boundary', 'built', 'but', 'by', 'can',
    'came', 'could', 'did', 'do', 'does', 'down', 'every', 'for', 'from',
    'enough', 'get', 'got', 'had', 'has', 'have', 'he', 'her', 'here', 'him', 'his',
    'i', 'if', 'in', 'interlude', 'into', 'is', 'it', 'its', 'just',
    'many', 'more', 'no', 'not', 'of', 'off', 'on', 'or', 'our', 'out',
    'over', 'really', 'said', 'same', 'she', 'should', 'so', 'some',
    'still', 'that', 'the', 'their', 'them', 'then', 'there', 'these',
    'they', 'this', 'those', 'through', 'to', 'too', 'under', 'up', 'very',
    'was', 'we', 'well', 'were', 'what', 'when', 'where', 'which', 'who',
    'will', 'with', 'without', 'would', 'you', 'your',
]);

const COMMON_SENTENCE_STARTERS = new Set([
    'accepted', 'access', 'accurate', 'all', 'air', 'already', 'aye',
    'because', 'before', 'do', 'enough', 'everyone', 'hearing', 'interlude',
    'life', 'looks', 'no', 'not', 'only', 'somewhere', 'that', 'then',
    'their', 'they', 'this', 'when', 'well', 'yes',
]);

function resolvePhoenixScanKind(candidate: PhoenixDiscoveryCandidate, text: string): string {
    const normalized = normalizeSuggestedEntityKind(String(candidate.kind || 'UNKNOWN'));
    const label = String(candidate.token || '').trim();
    if (isLikelyNetworkEntityLabel(label, text)) {
        return 'NETWORK';
    }
    if (isLikelyConceptEntityLabel(label, text)) {
        return 'CONCEPT';
    }
    if (isLikelyNpcEntityLabel(label, text)) {
        return 'NPC';
    }
    if (normalized === 'CHARACTER') {
        return isLikelyCharacterName(label, text) ? 'CHARACTER' : 'UNKNOWN';
    }
    if (normalized !== 'UNKNOWN' && normalized !== 'OTHER') {
        return normalized;
    }

    if (isLikelyCharacterName(label, text)) {
        return 'CHARACTER';
    }
    if (isLikelyLocationEntityLabel(label, text)) {
        return 'LOCATION';
    }
    return normalized;
}

function isPlausiblePhoenixDiscoveryCandidate(candidate: PhoenixDiscoveryCandidate, text: string): boolean {
    const label = cleanPhoenixCandidateLabel(candidate.token);
    if (isLikelyJunkEntityLabel(label)) {
        return false;
    }

    const normalized = label.toLocaleLowerCase();
    const words = normalized.split(/\s+/).filter(Boolean);
    const casedWords = label.split(/\s+/).filter(Boolean);
    const kind = normalizeSuggestedEntityKind(String(candidate.kind || 'UNKNOWN'));
    if (!words.length || words.length > 4) {
        return false;
    }
    if (words.every((word) => PHOENIX_DISCOVERY_STOPWORDS.has(word))) {
        return false;
    }
    const locationLike = isLikelyLocationEntityLabel(label, text);
    const networkLike = isLikelyNetworkEntityLabel(label, text);
    const conceptLike = isLikelyConceptEntityLabel(label, text);
    const npcLike = isLikelyNpcEntityLabel(label, text);
    if (words.length > 1 && (
        PHOENIX_DISCOVERY_STOPWORDS.has(words[0]) ||
        PHOENIX_DISCOVERY_STOPWORDS.has(words[words.length - 1])
    ) && !locationLike && !networkLike && !conceptLike && !npcLike && (kind === 'UNKNOWN' || kind === 'OTHER')) {
        return false;
    }
    if (words.length === 1 && COMMON_SENTENCE_STARTERS.has(words[0])) {
        return false;
    }

    if (locationLike) {
        return true;
    }
    if (networkLike) {
        return true;
    }
    if (conceptLike) {
        return true;
    }
    if (npcLike) {
        return true;
    }
    if (kind === 'CHARACTER') {
        return isLikelyCharacterName(label, text);
    }
    if (kind === 'UNKNOWN') {
        return isLikelyCharacterName(label, text);
    }

    if (words.length === 1) {
        return /^[\p{Lu}][\p{L}'-]{1,31}$/u.test(label);
    }

    return casedWords.some((word) => /^[\p{Lu}]/u.test(word));
}

export function isLikelyLocationEntityLabel(label: string, text: string): boolean {
    const cleaned = cleanPhoenixCandidateLabel(label);
    if (!cleaned) return false;

    const normalized = cleaned.toLocaleLowerCase();
    if (KNOWN_LOCATION_SURFACES.has(normalized) && !hasPersonActionContext(cleaned, text)) return true;

    const words = normalized.split(/\s+/).filter(Boolean);
    if (words.length > 1 && LOCATION_SUFFIX_PATTERN.test(cleaned)) return true;

    const escaped = escapeRegExp(cleaned);
    const contextPattern = new RegExp([
        `\\b(?:in|at|near|from|to|inside|outside|through|above|below|across|around|toward|towards|within|into|onto|over|clearing)\\s+(?:the\\s+)?${escaped}\\b`,
        `\\b(?:returned\\s+from|pane\\s+from|opens?\\s+into|moved\\s+through)\\s+(?:the\\s+)?${escaped}\\b`,
        `\\b${escaped}\\b\\s+(?:government|continuity|exchange\\s+terms|observations|country|nation|city|capital|citadel|works|marker|break|route|routes|roads|river|locks|territory|range|region|map|radius|pulse|tower|mesa|opens?|sits|came\\s+first|moves\\s+first)\\b`,
        `\\b${escaped}\\b\\.\\s+(?:fuel\\s+movement|rail\\s+breaks|river\\s+locks|hospital\\s+reroutes|detention\\s+sites)\\b`,
    ].join('|'), 'iu');
    return contextPattern.test(text);
}

export function isLikelyNetworkEntityLabel(label: string, text: string): boolean {
    const cleaned = cleanPhoenixCandidateLabel(label);
    if (!cleaned) return false;

    const normalized = cleaned.toLocaleLowerCase();
    if (KNOWN_NETWORK_SURFACES.has(normalized) && !hasPersonActionContext(cleaned, text)) {
        return true;
    }

    const words = normalized.split(/\s+/).filter(Boolean);
    if (words.length > 1 && NETWORK_SUFFIX_PATTERN.test(words[words.length - 1])) {
        return true;
    }

    const escaped = escapeRegExp(cleaned);
    const contextPattern = new RegExp([
        `\\b${escaped}\\b\\s+(?:approved|understands|backing|authority|command|coverage|records|contracts?|forces?|operators?|militias?|military|signed\\s+to|wanted|believed)\\b`,
        `\\b(?:signed\\s+to|under\\s+command|backed\\s+by|bringing\\s+in|forcing\\s+records\\s+open\\s+to|direct\\s+line\\s+to)\\s+(?:the\\s+)?${escaped}\\b`,
        `\\b(?:local|private|state-backed|federal|phantom|warden)\\s+${escaped}\\b`,
    ].join('|'), 'iu');
    return contextPattern.test(text);
}

export function isLikelyConceptEntityLabel(label: string, text: string): boolean {
    const cleaned = cleanPhoenixCandidateLabel(label);
    if (!cleaned) return false;

    const normalized = cleaned.toLocaleLowerCase();
    const words = normalized.split(/\s+/).filter(Boolean);
    if (words.length > 1 && CONCEPT_SURFACE_PATTERN.test(cleaned)) {
        return true;
    }

    const escaped = escapeRegExp(cleaned);
    const contextPattern = new RegExp([
        `\\b(?:boundary|full\\s+city(?:'|\\u2019)?s\\s+worth\\s+of|worth\\s+of)\\s+${escaped}\\b`,
        `\\b${escaped}\\b\\s+(?:sitting|weight|pressure|field|settled|classification|rank|pulse|claim|claims)\\b`,
    ].join('|'), 'iu');
    return contextPattern.test(text);
}

export function isLikelyNpcEntityLabel(label: string, text: string): boolean {
    const cleaned = cleanPhoenixCandidateLabel(label);
    if (!cleaned) return false;

    if (NPC_ROLE_SURFACE_PATTERN.test(cleaned)) {
        return true;
    }

    return false;
}

function isLikelyCharacterName(label: string, text: string): boolean {
    if (!/^[\p{Lu}][\p{L}'-]{1,31}$/u.test(label)) {
        return false;
    }
    const normalized = label.toLocaleLowerCase();
    if (PHOENIX_DISCOVERY_STOPWORDS.has(normalized) || COMMON_SENTENCE_STARTERS.has(normalized)) {
        return false;
    }

    const escaped = escapeRegExp(label);
    if (hasPersonActionContext(label, text)) {
        return true;
    }

    const possessivePattern = new RegExp(`\\b${escaped}\\b(?:'|\\u2019)s\\b`, 'iu');
    return possessivePattern.test(text);
}

function hasPersonActionContext(label: string, text: string): boolean {
    const escaped = escapeRegExp(label);
    const actionPattern = PERSON_LIKE_ACTIONS.join('|');
    const actorPattern = new RegExp(
        `\\b${escaped}\\b(?:\\s+\\w+){0,2}\\s+(${actionPattern})\\b|\\b(${actionPattern})\\s+(?:\\w+\\s+){0,2}\\b${escaped}\\b`,
        'iu',
    );
    return actorPattern.test(text);
}

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeSuggestionKey(value: string): string {
    return String(value || '')
        .trim()
        .toLocaleLowerCase()
        .replace(/\s+/g, ' ');
}

function cleanPhoenixCandidateLabel(value: string): string {
    return String(value || '')
        .replace(/^["'“”‘’]+|["'“”‘’.,;:!?]+$/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

export interface NerSuggestion {
    id: string;
    label: string;
    kind: string;
    confidence: number;
    context?: string;
    llmEnhanced?: boolean;
    llmReasoning?: string;
    source: EntitySuggestionProviderId;
    kindVotes?: NerKindVote[];
    decisionStatus?: 'accepted' | 'review' | 'rejected' | string;
    reviewReason?: string;
    requiresReview?: boolean;
}

export interface NerKindVote {
    kind: string;
    source: string;
    confidence: number;
    reason: string;
}

export interface NerSuggestionAcceptanceContext {
    noteId: string;
    plainText: string;
    noteTitle?: string;
    generation?: number;
    registrationSource?: 'user' | 'extraction' | 'auto';
}

@Injectable({
    providedIn: 'root'
})
export class NerService {
    private phoenixUiApi = inject(PhoenixUiApiService);
    private noteStore = inject(NoteEditorStore);
    private lfmLocalProvider = inject(LfmLocalEntitySuggestionProvider);
    private glinerLocalProvider = inject(GlinerLocalEntitySuggestionProvider);
    private fstProvider: EntitySuggestionProviderApi;
    private readonly fstStatus = signal<EntitySuggestionProviderStatus>({
        ready: true,
        loading: false,
        device: null,
    });

    constructor() {
        this.fstProvider = new PhoenixScanEntitySuggestionProvider(this.phoenixUiApi);

        const stored = getSetting<string | null>('ner_fst_enabled', null);
        if (stored !== null) {
            const enabled = stored === 'true';
            this.fstEnabled.set(enabled);
            _globalFstEnabled = enabled;
        }
    }

    readonly suggestions = signal<NerSuggestion[]>([]);
    readonly fstEnabled = signal<boolean>(true);
    readonly isAnalyzing = signal<boolean>(false);
    readonly activeProvider = signal<EntitySuggestionProviderId | null>(null);
    readonly lastSuggestionSource = signal<EntitySuggestionProviderId | null>(null);
    readonly errorMessage = signal<string | null>(null);

    readonly providerStatuses = computed(() => ({
        atlas_surface: this.fstStatus(),
        dynamic_ner: this.fstStatus(),
        fst: this.fstStatus(),
        lfm_local_experiment: this.lfmLocalProvider.status(),
        gliner_local: this.glinerLocalProvider.status(),
    }));

    private currentText = '';

    async analyzeNote(text: string) {
        const currentNote = this.noteStore.currentNote();
        await this.runDynamicScan({
            noteId: currentNote?.id || 'manual-scan',
            noteTitle: currentNote?.title || 'Untitled Note',
            plainText: text,
        });
    }

    async runDynamicScan(request: EntitySuggestionScanRequest): Promise<void> {
        await this.runManualScan('dynamic_ner', request);
    }

    async loadAtlasSurfaceSuggestions(candidates: AtlasRichScanCandidateSummary[]): Promise<void> {
        const mapped = (candidates || [])
            .map((candidate) => {
                const label = cleanPhoenixCandidateLabel(candidate.label || '');
                const candidateText = [candidate.evidence, label].filter(Boolean).join(' ');
                const kind = resolvePhoenixScanKind({
                    key: label,
                    token: label,
                    kind: candidate.kind,
                    score: typeof candidate.confidence === 'number' ? candidate.confidence : 0.5,
                    count: 1,
                    status: 0,
                }, candidateText);
                const confidence = typeof candidate.confidence === 'number' ? candidate.confidence : 0.5;
                const kindVotes = buildKindVotes(label, kind, confidence, candidateText, candidate.kindVotes);
                return {
                    id: candidate.id || uuidv4(),
                    label: label || 'Unknown',
                    kind,
                    confidence,
                    context: candidate.evidence || undefined,
                    llmEnhanced: false,
                    llmReasoning: undefined,
                    source: 'atlas_surface' as const,
                    kindVotes,
                    decisionStatus: normalizeDecisionStatus(candidate.decisionStatus, kind, confidence),
                    reviewReason: candidate.reviewReason || reviewReason(kind, confidence, kindVotes),
                    requiresReview: requiresReview(candidate.decisionStatus, kind, confidence, kindVotes),
                };
            })
            .filter((suggestion) => !smartGraphRegistry.isRegisteredEntity(suggestion.label))
            .filter((suggestion) => !isLikelyJunkEntityLabel(suggestion.label))
            .filter((suggestion) => suggestion.kind !== 'UNKNOWN')
            .filter((suggestion) => isPlausiblePhoenixDiscoveryCandidate({
                key: suggestion.label,
                token: suggestion.label,
                kind: suggestion.kind,
                score: suggestion.confidence,
                count: 1,
                status: 0,
            }, suggestion.context || suggestion.label));
        const filtered = await filterRejectedSuggestions(mapped, 'atlas_surface');
        this.suggestions.set(filtered);
        this.lastSuggestionSource.set('atlas_surface');
        this.activeProvider.set(null);
        this.errorMessage.set(null);
        this.isAnalyzing.set(false);
    }

    async runManualScan(providerId: EntitySuggestionProviderId, request: EntitySuggestionScanRequest): Promise<void> {
        if (providerId === 'fst' && !this.fstEnabled()) {
            console.log('[NerService] FST disabled, skipping analysis');
            return;
        }

        const plainText = String(request.plainText || '');
        if (!plainText.trim()) {
            this.errorMessage.set('No rendered note text is available to scan.');
            return;
        }

        this.currentText = plainText;
        this.activeProvider.set(providerId);
        this.errorMessage.set(null);
        this.isAnalyzing.set(true);
        this.setProviderStatus(providerId, {
            ...this.getProviderStatus(providerId),
            loading: true,
            error: undefined,
        });

        const previousSuggestions = this.suggestions();
        const provider = this.getProvider(providerId);

        try {
            const providerSuggestions = await provider.scan(request);
            const mapped = this.mapProviderSuggestions(providerSuggestions, providerId);
            const filtered = await filterRejectedSuggestions(mapped, providerId);
            this.suggestions.set(filtered);
            this.lastSuggestionSource.set(providerId);
            this.setProviderStatus(providerId, await provider.getStatus());
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Entity scan failed';
            console.error('[NerService] Analysis failed', error);
            this.errorMessage.set(message);
            this.suggestions.set(previousSuggestions);
            this.setProviderStatus(providerId, {
                ...this.getProviderStatus(providerId),
                loading: false,
                error: message,
            });
        } finally {
            this.isAnalyzing.set(false);
            this.activeProvider.set(null);
        }
    }

    async acceptSuggestion(id: string) {
        const suggestion = this.suggestions().find((entry) => entry.id === id);
        if (!suggestion) {
            return;
        }
        const currentNote = this.noteStore.currentNote();
        await this.acceptResolvedSuggestion(id, suggestion, {
            noteId: currentNote?.id || 'unknown',
            noteTitle: currentNote?.title,
            plainText: this.currentText || currentNote?.markdownContent || currentNote?.content || '',
            generation: currentNote?.version || currentNote?.updatedAt || Date.now(),
            registrationSource: 'user',
        });
    }

    async acceptSuggestionForContext(id: string, context: NerSuggestionAcceptanceContext): Promise<EntityOccurrence | null> {
        const suggestion = this.suggestions().find((entry) => entry.id === id);
        if (!suggestion) return null;
        if (suggestion.requiresReview) return null;
        return this.acceptResolvedSuggestion(id, suggestion, context);
    }

    async rejectSuggestion(id: string) {
        const suggestion = this.suggestions().find((entry) => entry.id === id);
        if (!suggestion) {
            return;
        }

        const currentNote = this.noteStore.currentNote();
        await recordSuggestionRejected({
            label: suggestion.label,
            kind: suggestion.kind,
            surface: suggestion.label,
            provider: suggestion.source,
            noteId: currentNote?.id || 'unknown',
            confidence: suggestion.confidence,
            context: suggestion.context,
        }).catch(error => {
            console.warn('[NerService] Failed to record rejected suggestion:', error);
        });
        this.suggestions.update((list) => list.filter((entry) => entry.id !== id));
    }

    toggleFst(enabled: boolean) {
        this.fstEnabled.set(enabled);
        setSetting('ner_fst_enabled', String(enabled));
        if (!enabled && this.lastSuggestionSource() === 'fst') {
            this.suggestions.set([]);
            this.lastSuggestionSource.set(null);
        }
        _globalFstEnabled = enabled;
        window.dispatchEvent(new CustomEvent('fst-toggle', { detail: { enabled } }));
    }

    getProviderStatus(providerId: EntitySuggestionProviderId): EntitySuggestionProviderStatus {
        if (providerId === 'lfm_local_experiment') {
            return this.lfmLocalProvider.status();
        }
        if (providerId === 'gliner_local') {
            return this.glinerLocalProvider.status();
        }

        return this.fstStatus();
    }

    async warmProvider(providerId: EntitySuggestionProviderId): Promise<void> {
        if (providerId === 'gliner_local') {
            await this.glinerLocalProvider.warm();
            return;
        }
        if (providerId === 'lfm_local_experiment') {
            await this.lfmLocalProvider.getStatus();
            return;
        }
        this.setProviderStatus(providerId, { ready: true, loading: false, device: null });
    }

    private getProvider(providerId: EntitySuggestionProviderId): EntitySuggestionProviderApi {
        if (providerId === 'lfm_local_experiment') {
            return this.lfmLocalProvider;
        }
        if (providerId === 'gliner_local') {
            return this.glinerLocalProvider;
        }

        return this.fstProvider;
    }

    private setProviderStatus(providerId: EntitySuggestionProviderId, status: EntitySuggestionProviderStatus): void {
        if (providerId === 'lfm_local_experiment' || providerId === 'gliner_local') {
            return;
        }

        this.fstStatus.set(status);
    }

    private async acceptResolvedSuggestion(
        id: string,
        suggestion: NerSuggestion,
        context: NerSuggestionAcceptanceContext,
    ): Promise<EntityOccurrence | null> {
        const replacement = `[${suggestion.kind}|${suggestion.label}]`;
        console.log('[NerService] Accepting:', replacement);

        this.suggestions.update((list) => list.filter((entry) => entry.id !== id));

        const noteId = context.noteId || 'unknown';
        const registrationSource = context.registrationSource || 'extraction';
        const registration = smartGraphRegistry.registerEntity(
            suggestion.label,
            suggestion.kind as any,
            noteId,
            {
                source: registrationSource,
                attributes: {
                    discoverySource: suggestion.source,
                    sourceConfidence: suggestion.confidence,
                    nerDecisionStatus: suggestion.decisionStatus,
                    nerReviewReason: suggestion.reviewReason,
                    nerKindVotes: suggestion.kindVotes,
                },
            }
        );
        const occurrence = await recordAcceptedEntityAnchor({
            noteId,
            entity: registration.entity,
            surface: suggestion.label,
            plainText: context.plainText || this.currentText || '',
            confidence: suggestion.confidence,
            generation: context.generation || Date.now(),
            context: suggestion.context,
        }).catch(error => {
            console.warn('[NerService] Failed to record accepted graph anchor:', error);
            return null;
        });
        await recordSuggestionAccepted({
            entityId: registration.entity.id,
            label: registration.entity.label,
            kind: registration.entity.kind,
            surface: suggestion.label,
            provider: suggestion.source,
            noteId,
            confidence: suggestion.confidence,
            context: suggestion.context,
        }).catch(error => {
            console.warn('[NerService] Failed to record accepted suggestion:', error);
        });
        return occurrence;
    }

    private mapProviderSuggestions(
        providerSuggestions: LocalEntitySuggestion[],
        providerId: EntitySuggestionProviderId,
    ): NerSuggestion[] {
        return providerSuggestions
            .filter((suggestion) => !smartGraphRegistry.isRegisteredEntity(suggestion.label))
            .filter((suggestion) => !isLikelyJunkEntityLabel(suggestion.label))
            .filter((suggestion) => !isNativeScanProvider(providerId) || isPlausiblePhoenixDiscoveryCandidate({
                key: suggestion.label,
                token: suggestion.label,
                kind: suggestion.kind,
                score: typeof suggestion.rawScore === 'number' ? suggestion.rawScore : mapConfidenceLevelToScore(suggestion.confidence),
                count: 1,
                status: 0,
            }, this.currentText))
            .map((suggestion) => {
                const confidence = typeof suggestion.rawScore === 'number'
                    ? suggestion.rawScore
                    : mapConfidenceLevelToScore(suggestion.confidence);
                const kind = resolvedSuggestionKind(suggestion, providerId, this.currentText);
                const kindVotes = buildKindVotes(suggestion.label, kind, confidence, this.currentText);
                return {
                    id: uuidv4(),
                    label: suggestion.label || 'Unknown',
                    kind,
                    confidence,
                    context: suggestion.evidence || undefined,
                    llmEnhanced: !isNativeScanProvider(providerId),
                    llmReasoning: suggestion.reasoning || undefined,
                    source: providerId,
                    kindVotes,
                    decisionStatus: normalizeDecisionStatus(undefined, kind, confidence),
                    reviewReason: reviewReason(kind, confidence, kindVotes),
                    requiresReview: requiresReview(undefined, kind, confidence, kindVotes),
                };
            });
    }
}

function resolvedSuggestionKind(
    suggestion: LocalEntitySuggestion,
    providerId: EntitySuggestionProviderId,
    text: string,
): string {
    if (!isNativeScanProvider(providerId)) {
        return String(normalizeSuggestedEntityKind(String(suggestion.kind || 'UNKNOWN')));
    }
    return resolvePhoenixScanKind({
        key: suggestion.label,
        token: suggestion.label,
        kind: suggestion.kind,
        score: typeof suggestion.rawScore === 'number' ? suggestion.rawScore : mapConfidenceLevelToScore(suggestion.confidence),
        count: 1,
        status: 0,
    }, text);
}

function buildKindVotes(
    label: string,
    kind: string,
    confidence: number,
    text: string,
    upstreamVotes?: Array<{ kind?: string; source?: string; confidence?: number; reason?: string }>,
): NerKindVote[] {
    const votes: NerKindVote[] = [];
    for (const vote of upstreamVotes || []) {
        const normalizedKind = normalizeKindVote(vote.kind || '');
        if (!normalizedKind) continue;
        votes.push({
            kind: normalizedKind,
            source: String(vote.source || 'upstream'),
            confidence: clampScore(Number(vote.confidence || 0)),
            reason: String(vote.reason || 'upstream_vote'),
        });
    }

    const normalizedKind = normalizeKindVote(kind);
    if (normalizedKind && normalizedKind !== 'UNKNOWN' && normalizedKind !== 'OTHER') {
        votes.push({
            kind: normalizedKind,
            source: 'provider',
            confidence: clampScore(confidence),
            reason: 'provider_kind',
        });
    }

    if (isLikelyLocationEntityLabel(label, text) && normalizedKind !== 'LOCATION') {
        votes.push({
            kind: 'LOCATION',
            source: 'angular_location_context',
            confidence: 0.34,
            reason: 'review_only_location_context',
        });
    }

    if (isLikelyConceptEntityLabel(label, text) && normalizedKind !== 'CONCEPT') {
        votes.push({
            kind: 'CONCEPT',
            source: 'angular_concept_context',
            confidence: 0.48,
            reason: 'review_only_concept_context',
        });
    }

    if (isLikelyNpcEntityLabel(label, text) && normalizedKind !== 'NPC') {
        votes.push({
            kind: 'NPC',
            source: 'angular_npc_context',
            confidence: 0.44,
            reason: 'review_only_npc_context',
        });
    }

    if (isLikelyNetworkEntityLabel(label, text) && normalizedKind !== 'NETWORK') {
        votes.push({
            kind: 'NETWORK',
            source: 'angular_network_context',
            confidence: 0.42,
            reason: 'review_only_network_context',
        });
    }

    return dedupeKindVotes(votes);
}

function normalizeDecisionStatus(
    upstreamStatus: string | undefined,
    kind: string,
    confidence: number,
): 'accepted' | 'review' | 'rejected' {
    const normalizedStatus = String(upstreamStatus || '').toLocaleLowerCase();
    if (normalizedStatus === 'rejected') return 'rejected';
    if (normalizedStatus === 'review') return 'review';
    if (normalizeKindVote(kind) === 'UNKNOWN' || confidence < 0.35) return 'review';
    return 'accepted';
}

function requiresReview(
    upstreamStatus: string | undefined,
    kind: string,
    confidence: number,
    votes: NerKindVote[] = [],
): boolean {
    if (normalizeDecisionStatus(upstreamStatus, kind, confidence) !== 'accepted') return true;
    const normalizedKind = normalizeKindVote(kind);
    return votes.some((vote) => (
        (
            vote.source === 'angular_location_context'
            || vote.source === 'angular_network_context'
            || vote.source === 'angular_concept_context'
            || vote.source === 'angular_npc_context'
        )
        && vote.kind !== normalizedKind
    ));
}

function reviewReason(kind: string, confidence: number, votes: NerKindVote[]): string | undefined {
    if (normalizeKindVote(kind) === 'UNKNOWN') return 'missing_kind_vote';
    if (confidence < 0.35) return 'low_confidence';
    if (votes.some((vote) => vote.source === 'angular_location_context' && vote.kind !== normalizeKindVote(kind))) {
        return 'location_context_conflict';
    }
    if (votes.some((vote) => vote.source === 'angular_network_context' && vote.kind !== normalizeKindVote(kind))) {
        return 'network_context_conflict';
    }
    if (votes.some((vote) => vote.source === 'angular_concept_context' && vote.kind !== normalizeKindVote(kind))) {
        return 'concept_context_conflict';
    }
    if (votes.some((vote) => vote.source === 'angular_npc_context' && vote.kind !== normalizeKindVote(kind))) {
        return 'npc_context_conflict';
    }
    return undefined;
}

function normalizeKindVote(kind: string): string {
    return String(normalizeSuggestedEntityKind(String(kind || 'UNKNOWN')) || 'UNKNOWN');
}

function clampScore(value: number): number {
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(1, value));
}

function dedupeKindVotes(votes: NerKindVote[]): NerKindVote[] {
    const byKey = new Map<string, NerKindVote>();
    for (const vote of votes) {
        const key = `${vote.kind}:${vote.source}:${vote.reason}`;
        const current = byKey.get(key);
        if (!current || vote.confidence > current.confidence) {
            byKey.set(key, vote);
        }
    }
    return [...byKey.values()].sort((left, right) => right.confidence - left.confidence);
}

function isNativeScanProvider(providerId: EntitySuggestionProviderId): boolean {
    return providerId === 'atlas_surface' || providerId === 'dynamic_ner' || providerId === 'fst';
}

let _globalFstEnabled = true;
{
    const stored = getSetting<string | null>('ner_fst_enabled', null);
    if (stored !== null) {
        _globalFstEnabled = stored === 'true';
    }
}

export function isFstEnabled(): boolean {
    return _globalFstEnabled;
}
