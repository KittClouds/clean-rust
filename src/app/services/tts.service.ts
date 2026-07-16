import { Injectable, NgZone, computed, signal } from '@angular/core';
import type { TTSWorkerMessage, TTSResponseMessage } from '../workers/tts.worker';
import { modelCache } from '../lib/model-cache';
import { createNoopNgZone, createWorkerOutsideAngular } from '../lib/core/worker-zone';
import { createTauRPCProxy, type NativeTtsSynthResult } from '../generated/phoenix-taurpc';

export type TTSModelState = 'idle' | 'loading' | 'ready' | 'error';
export type TTSEngine = 'nativeChatterbox' | 'nativeQwenClone' | 'nativeSupertonicRust' | 'browserSupertonic';
type SpeakOptions = {
    autoLoad?: boolean;
    unloadWhenFinished?: boolean;
};

// Voice configuration
export interface TtsVoice {
    id: string;
    name: string;
    gender: 'male' | 'female';
    url: string;
}

export const SUPERTONIC3_MODEL_ID = 'Supertone/supertonic-3';

// Browser Supertonic still uses the Transformers.js v2 ONNX community package,
// whose voice files are binary embeddings. Native Rust uses Supertonic 3 JSON
// styles from the local model root.
const BROWSER_SUPERTONIC_VOICE_BASE = 'https://huggingface.co/onnx-community/Supertonic-TTS-2-ONNX/resolve/main/voices';

export const TTS_VOICES: TtsVoice[] = [
    { id: 'F1', name: 'Sofia', gender: 'female', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/F1.bin` },
    { id: 'F2', name: 'Elena', gender: 'female', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/F2.bin` },
    { id: 'F3', name: 'Maya', gender: 'female', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/F3.bin` },
    { id: 'F4', name: 'Luna', gender: 'female', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/F4.bin` },
    { id: 'F5', name: 'Iris', gender: 'female', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/F5.bin` },
    { id: 'M1', name: 'James', gender: 'male', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/M1.bin` },
    { id: 'M2', name: 'Oliver', gender: 'male', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/M2.bin` },
    { id: 'M3', name: 'Daniel', gender: 'male', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/M3.bin` },
    { id: 'M4', name: 'Henry', gender: 'male', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/M4.bin` },
    { id: 'M5', name: 'Noah', gender: 'male', url: `${BROWSER_SUPERTONIC_VOICE_BASE}/M5.bin` },
];

export const NATIVE_TTS_MODEL_ROOT = 'G:\\phoenix-tts\\chatterbox-turbo-onnx';
export const NATIVE_TTS_REFERENCE_WAV = 'G:\\phoenix-tts\\reference-sapi.wav';
export const NATIVE_TTS_MAX_NEW_TOKENS = 1024;
export const NATIVE_SUPERTONIC_RUNNER = 'C:\\phoenix-tts\\supertonic-rust\\example_onnx.exe';
export const NATIVE_SUPERTONIC_MODEL_ROOT = 'C:\\phoenix-tts\\supertonic-3';
export const NATIVE_SUPERTONIC_OUTPUT_ROOT = 'C:\\phoenix-tts\\supertonic-rust-outputs';
export const NATIVE_SUPERTONIC_TOTAL_STEP = 5;
export const NATIVE_SUPERTONIC_SPEED = 1.05;
export const NATIVE_QWEN_RUNNER = 'G:\\phoenix-tts\\qwen3-tts-rs\\bin\\qwen-tts.exe';
export const NATIVE_QWEN_MODEL = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base';
export const NATIVE_QWEN_OUTPUT_ROOT = 'G:\\phoenix-tts\\qwen-tts-outputs';
export const NATIVE_QWEN_LANGUAGE = 'english';
export const NATIVE_QWEN_DEVICE = 'cpu';
export const NATIVE_QWEN_DTYPE = 'f32';
export const NATIVE_QWEN_MAX_TOKENS = 1536;
export const NATIVE_QWEN_TIMEOUT_SECS = 600;
export const NATIVE_QWEN_PROMPT_CACHE = 'G:\\phoenix-tts\\qwen-reference-prompt.json';
const QWEN_REF_AUDIO_KEY = 'phoenix.tts.qwen.refAudio';
const QWEN_REF_TEXT_KEY = 'phoenix.tts.qwen.refText';
const QWEN_PROMPT_KEY = 'phoenix.tts.qwen.promptPath';
const QWEN_PROMPT_CACHE_KEY = 'phoenix.tts.qwen.usePromptCache';
export type QwenCloneMode = 'prompt-cache' | 'icl' | 'x-vector';

/**
 * Get a voice embedding buffer, using cache if available.
 */
export async function getVoiceEmbeddingBuffer(voice: TtsVoice): Promise<ArrayBuffer> {
    const cacheId = `voice:${voice.id}`;
    const blob = await modelCache.fetchWithCache(cacheId, voice.url, 'voice');
    return blob.arrayBuffer();
}

@Injectable({ providedIn: 'root' })
export class TtsService {
    // ========================================================================
    // State Signals
    // ========================================================================

    private readonly _modelState = signal<TTSModelState>('idle');
    private readonly _loadProgress = signal<number>(0);
    private readonly _loadStatus = signal<string>('');
    private readonly _isPlaying = signal<boolean>(false);
    private readonly _isPaused = signal<boolean>(false);
    private readonly _errorMessage = signal<string | null>(null);
    private readonly _selectedVoice = signal<TtsVoice>(TTS_VOICES[0]);
    private readonly _selectedEngine = signal<TTSEngine>('browserSupertonic');
    private readonly _qwenCloneReferenceAudio = signal<string>(
        readStoredString(QWEN_REF_AUDIO_KEY, NATIVE_TTS_REFERENCE_WAV),
    );
    private readonly _qwenCloneReferenceText = signal<string>(
        readStoredString(QWEN_REF_TEXT_KEY, ''),
    );
    private readonly _qwenClonePromptPath = signal<string>(
        readStoredString(QWEN_PROMPT_KEY, NATIVE_QWEN_PROMPT_CACHE),
    );
    private readonly _qwenCloneUsePromptCache = signal<boolean>(
        readStoredBoolean(QWEN_PROMPT_CACHE_KEY, true),
    );

    // Public readonly signals
    readonly modelState = this._modelState.asReadonly();
    readonly loadProgress = this._loadProgress.asReadonly();
    readonly loadStatus = this._loadStatus.asReadonly();
    readonly isPlaying = this._isPlaying.asReadonly();
    readonly isPaused = this._isPaused.asReadonly();
    readonly errorMessage = this._errorMessage.asReadonly();
    readonly selectedVoice = this._selectedVoice.asReadonly();
    readonly selectedEngine = this._selectedEngine.asReadonly();
    readonly nativeReferencePath = this._qwenCloneReferenceAudio.asReadonly();
    readonly qwenCloneReferenceAudio = this._qwenCloneReferenceAudio.asReadonly();
    readonly qwenCloneReferenceText = this._qwenCloneReferenceText.asReadonly();
    readonly qwenClonePromptPath = this._qwenClonePromptPath.asReadonly();
    readonly qwenCloneUsePromptCache = this._qwenCloneUsePromptCache.asReadonly();

    // Computed
    readonly isModelReady = computed(() => this._modelState() === 'ready');
    readonly isModelLoading = computed(() => this._modelState() === 'loading');
    readonly nativeAvailable = computed(() => isTauriDesktop());
    readonly nativeSupertonicRustAvailable = computed(() => isTauriDesktop());
    readonly nativeQwenCloneAvailable = computed(() => isTauriDesktop());
    readonly qwenCloneMode = computed<QwenCloneMode>(() => {
        if (this._qwenCloneUsePromptCache() && this._qwenClonePromptPath().trim()) {
            return 'prompt-cache';
        }
        return this._qwenCloneReferenceText().trim() ? 'icl' : 'x-vector';
    });

    // ========================================================================
    // Worker & Audio
    // ========================================================================

    private worker: Worker | null = null;
    private audioContext: AudioContext | null = null;
    private idleUnloadTimer: ReturnType<typeof setTimeout> | null = null;
    private nativeRpc: ReturnType<typeof createTauRPCProxy> | null = null;
    private pendingEngineSwitch: Promise<void> | null = null;

    // ========================================================================
    // Prefetch Pipeline State
    // ========================================================================

    private readonly MAX_CHUNK_SIZE = 280;
    private readonly PREFETCH_BUFFER_SIZE = 1;
    private readonly IDLE_UNLOAD_DELAY_MS = 60_000;

    private pendingChunks: string[] = [];
    private audioBufferQueue: AudioBuffer[] = [];
    private activeSourceNodes: AudioBufferSourceNode[] = [];
    private scheduledEndTime = 0;
    private isGenerating = false;
    private stopRequested = false;
    private playbackGeneration = 0;
    private nextRequestId = 0;
    private activePlaybackVoiceId: string | null = null;
    private queuedSpeakRequest: { text: string; unloadWhenFinished: boolean } | null = null;
    private unloadAfterPlayback = false;

    private readonly cachedWorkerVoiceIds = new Set<string>();
    private readonly voicePreloadPromises = new Map<string, Promise<void>>();
    private readonly voicePreloadResolvers = new Map<string, {
        resolve: () => void;
        reject: (error: Error) => void;
    }>();

    private pendingUnload: Promise<void> | null = null;
    private unloadWaiter: {
        resolve: () => void;
        timeout: ReturnType<typeof setTimeout>;
    } | null = null;

    constructor(private readonly ngZone: NgZone = createNoopNgZone()) {}

    // ========================================================================
    // Voice Selection
    // ========================================================================

    setVoice(voice: TtsVoice): void {
        this._selectedVoice.set(voice);
        console.log(`[TtsService] Voice changed to ${voice.name} (${voice.id})`);

        if (this._selectedEngine() === 'browserSupertonic' && this._modelState() === 'ready') {
            void this.preloadVoice(voice);
        }
    }

    setQwenCloneReferenceAudio(path: string): void {
        const value = path.trim();
        this._qwenCloneReferenceAudio.set(value || NATIVE_TTS_REFERENCE_WAV);
        storeString(QWEN_REF_AUDIO_KEY, this._qwenCloneReferenceAudio());
    }

    setQwenCloneReferenceText(text: string): void {
        this._qwenCloneReferenceText.set(text);
        storeString(QWEN_REF_TEXT_KEY, text);
    }

    setQwenClonePromptPath(path: string): void {
        const value = path.trim();
        this._qwenClonePromptPath.set(value || NATIVE_QWEN_PROMPT_CACHE);
        storeString(QWEN_PROMPT_KEY, this._qwenClonePromptPath());
    }

    setQwenCloneUsePromptCache(enabled: boolean): void {
        this._qwenCloneUsePromptCache.set(enabled);
        storeBoolean(QWEN_PROMPT_CACHE_KEY, enabled);
    }

    createFreshQwenPromptCache(): void {
        const stamp = new Date()
            .toISOString()
            .replaceAll('-', '')
            .replaceAll(':', '')
            .replaceAll('.', '')
            .replaceAll('T', '')
            .replaceAll('Z', '')
            .slice(0, 14);
        this.setQwenClonePromptPath(`G:\\phoenix-tts\\qwen-reference-prompt-${stamp}.json`);
        this.setQwenCloneUsePromptCache(true);
    }

    setEngine(engine: TTSEngine): void {
        const previousEngine = this._selectedEngine();
        if (engine === previousEngine) return;
        if ((engine === 'nativeChatterbox' || engine === 'nativeQwenClone' || engine === 'nativeSupertonicRust') && !isTauriDesktop()) {
            this._errorMessage.set('Native TTS engines are only available in the desktop app.');
            return;
        }

        this._selectedEngine.set(engine);
        this._modelState.set('loading');
        this._loadProgress.set(0);
        this._loadStatus.set('Switching TTS engine...');
        this._errorMessage.set(null);

        const switchPromise = this.performUnload(previousEngine, false)
            .then(() => {
                if (this._selectedEngine() !== engine) {
                    return;
                }
                this._modelState.set('idle');
                this._loadProgress.set(0);
                this._loadStatus.set('');
            })
            .catch((error) => {
                const message = error instanceof Error ? error.message : String(error);
                this._modelState.set('error');
                this._loadProgress.set(0);
                this._loadStatus.set('Engine switch failed');
                this._errorMessage.set(message);
            })
            .finally(() => {
                if (this.pendingEngineSwitch === switchPromise) {
                    this.pendingEngineSwitch = null;
                }
            });

        this.pendingEngineSwitch = switchPromise;
    }

    // ========================================================================
    // Public Methods
    // ========================================================================

    /**
     * Load the TTS model. This may take a few minutes on first load.
     */
    loadModel(): void {
        this.cancelIdleUnloadTimer();

        if (this.pendingEngineSwitch) {
            const engine = this._selectedEngine();
            void this.pendingEngineSwitch.then(() => {
                if (this._selectedEngine() === engine) {
                    this.loadModel();
                }
            });
            return;
        }

        if (this._modelState() === 'loading') {
            console.log('[TtsService] Model already loading.');
            return;
        }

        if (this._modelState() === 'ready') {
            console.log('[TtsService] Model already loaded.');
            void this.preloadVoice(this._selectedVoice());
            return;
        }

        if (this._selectedEngine() === 'nativeChatterbox') {
            void this.loadNativeModel();
            return;
        }
        if (this._selectedEngine() === 'nativeSupertonicRust') {
            this.loadNativeSupertonicRustModel();
            return;
        }
        if (this._selectedEngine() === 'nativeQwenClone') {
            this.loadNativeQwenCloneModel();
            return;
        }

        this._modelState.set('loading');
        this._loadProgress.set(0);
        this._loadStatus.set('Initializing...');
        this._errorMessage.set(null);

        this.initWorker();
        this.sendMessage({ type: 'LOAD_MODEL' });
    }

    /**
     * Synthesize speech from text and play it with prefetching for seamless playback.
     */
    speak(text: string, options: SpeakOptions = {}): void {
        const normalizedText = normalizeSpeechInput(text);
        if (!normalizedText) {
            console.warn('[TtsService] No text to speak.');
            return;
        }

        if (this._modelState() !== 'ready') {
            if (options.autoLoad) {
                this.queuedSpeakRequest = {
                    text: normalizedText,
                    unloadWhenFinished: Boolean(options.unloadWhenFinished),
                };
                this.loadModel();
                return;
            }

            console.warn('[TtsService] Model not ready. Call loadModel() first.');
            return;
        }

        void this.startPlayback(normalizedText, Boolean(options.unloadWhenFinished));
    }

    /**
     * Speak a short, user-selected excerpt and unload runtime resources afterward.
     */
    speakOnce(text: string): void {
        this.speak(text, { autoLoad: true, unloadWhenFinished: true });
    }

    /**
     * Stop current playback, clear transient buffers, and begin idle cleanup.
     */
    stop(): void {
        this.queuedSpeakRequest = null;
        this.unloadAfterPlayback = false;
        this.stopPlayback(true, 'user-stop');
    }

    /**
     * Pause current playback.
     */
    pause(): void {
        if (!this._isPlaying() || this._isPaused() || !this.audioContext) return;
        this.audioContext.suspend().then(() => {
            this._isPaused.set(true);
            this.scheduleIdleUnload();
        });
    }

    /**
     * Resume current playback.
     */
    resume(): void {
        if (!this._isPlaying() || !this._isPaused() || !this.audioContext) return;
        this.audioContext.resume().then(() => {
            this._isPaused.set(false);
            this.cancelIdleUnloadTimer();
        });
    }

    /**
     * Fully unload model/runtime resources.
     */
    async unloadModel(): Promise<void> {
        this.cancelIdleUnloadTimer();
        this.queuedSpeakRequest = null;
        this.unloadAfterPlayback = false;

        if (this.pendingUnload) {
            return this.pendingUnload;
        }

        this.pendingUnload = this.performUnload()
            .finally(() => {
                this.pendingUnload = null;
            });

        return this.pendingUnload;
    }

    /**
     * Cleanup resources.
     */
    destroy(): void {
        this.stopPlayback(false, 'destroy');
        void this.unloadModel();
    }

    private async loadNativeModel(): Promise<void> {
        if (!isTauriDesktop()) {
            this._modelState.set('error');
            this._errorMessage.set('Native Chatterbox TTS is only available in the desktop app.');
            return;
        }

        this._modelState.set('loading');
        this._loadProgress.set(5);
        this._loadStatus.set('Loading Chatterbox Turbo...');
        this._errorMessage.set(null);

        try {
            const status = await this.getNativeRpc().phoenix.tts_load({
                modelRoot: NATIVE_TTS_MODEL_ROOT,
                voiceWav: NATIVE_TTS_REFERENCE_WAV,
                dtype: 'q4f16',
                maxNewTokens: NATIVE_TTS_MAX_NEW_TOKENS,
                repetitionPenalty: 1.2,
                threads: 8,
            });
            this.ngZone.run(() => {
                this._modelState.set(status.loaded ? 'ready' : 'error');
                this._loadProgress.set(status.loaded ? 100 : 0);
                this._loadStatus.set(status.loaded ? 'Chatterbox ready' : 'Chatterbox unavailable');
                this._errorMessage.set(status.lastError ?? null);
                this.runQueuedSpeakIfReady();
            });
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            this.ngZone.run(() => {
                this._modelState.set('error');
                this._loadProgress.set(0);
                this._loadStatus.set('Chatterbox failed');
                this._errorMessage.set(message);
            });
        }
    }

    private loadNativeSupertonicRustModel(): void {
        if (!isTauriDesktop()) {
            this._modelState.set('error');
            this._errorMessage.set('Supertonic Rust is only available in the desktop app.');
            return;
        }

        this._modelState.set('ready');
        this._loadProgress.set(100);
        this._loadStatus.set('Supertonic Rust ready');
        this._errorMessage.set(null);
        this.runQueuedSpeakIfReady();
    }

    private loadNativeQwenCloneModel(): void {
        if (!isTauriDesktop()) {
            this._modelState.set('error');
            this._errorMessage.set('Qwen voice clone is only available in the desktop app.');
            return;
        }

        this._modelState.set('ready');
        this._loadProgress.set(100);
        this._loadStatus.set('Qwen 0.6B clone ready');
        this._errorMessage.set(null);
        this.runQueuedSpeakIfReady();
    }

    // ========================================================================
    // Text Chunking
    // ========================================================================

    private chunkText(text: string, maxChunkSize = this.MAX_CHUNK_SIZE): string[] {
        if (!text || text.trim().length === 0) return [];

        const sentencePattern = /[^.!?]+(?:[.!?]+|$)/g;
        const sentences = text.match(sentencePattern) || [text];

        const chunks: string[] = [];
        let currentChunk = '';

        for (const sentence of sentences) {
            const trimmedSentence = sentence.trim();
            if (!trimmedSentence) continue;

            if (trimmedSentence.length > maxChunkSize) {
                if (currentChunk.trim()) {
                    chunks.push(currentChunk.trim());
                    currentChunk = '';
                }
                chunks.push(...splitByWordBudget(trimmedSentence, maxChunkSize));
                continue;
            }

            if (currentChunk.length > 0 &&
                (currentChunk.length + trimmedSentence.length) > maxChunkSize) {
                chunks.push(currentChunk.trim());
                currentChunk = trimmedSentence;
            } else {
                currentChunk += (currentChunk ? ' ' : '') + trimmedSentence;
            }
        }

        if (currentChunk.trim()) {
            chunks.push(currentChunk.trim());
        }

        if (chunks.length === 0 && text.trim()) {
            const words = text.split(/\s+/);
            currentChunk = '';
            for (const word of words) {
                if ((currentChunk + ' ' + word).length > maxChunkSize && currentChunk) {
                    chunks.push(currentChunk.trim());
                    currentChunk = word;
                } else {
                    currentChunk += (currentChunk ? ' ' : '') + word;
                }
            }
            if (currentChunk.trim()) {
                chunks.push(currentChunk.trim());
            }
        }

        return chunks;
    }

    // ========================================================================
    // Prefetch Pipeline
    // ========================================================================

    private async startPlayback(text: string, unloadWhenFinished = false): Promise<void> {
        if (this.pendingEngineSwitch) {
            await this.pendingEngineSwitch;
        }

        if (this._isPlaying()) {
            this.stopPlayback(false, 'restart-playback');
        } else {
            this.cancelIdleUnloadTimer();
        }

        const engine = this._selectedEngine();
        const chunks = this.chunkText(text);
        if (chunks.length === 0) {
            console.warn('[TtsService] No text to speak.');
            return;
        }

        const voiceId = this._selectedVoice().id;
        const generation = ++this.playbackGeneration;

        this.resetPlaybackBuffers();
        this.pendingChunks = chunks;
        this.stopRequested = false;
        this.unloadAfterPlayback = unloadWhenFinished;
        this.activePlaybackVoiceId = voiceId;
        this._isPlaying.set(true);
        this._isPaused.set(false);
        this._errorMessage.set(null);

        try {
            await this.preloadVoice(this._selectedVoice());
            if (generation !== this.playbackGeneration || this.stopRequested) {
                return;
            }

            await this.ensureAudioContext();
            if (generation !== this.playbackGeneration || this.stopRequested) {
                return;
            }

            console.log(`[TtsService] Starting ${engine} prefetch pipeline for ${this.pendingChunks.length} chunks...`);
            this.fillPrefetchBuffer();
        } catch (error) {
            if (generation !== this.playbackGeneration) {
                return;
            }

            const message = error instanceof Error ? error.message : String(error);
            console.error('[TtsService] Failed to start playback:', message);
            this._errorMessage.set(message);
            this._isPlaying.set(false);
            this.finishOrScheduleIdleUnload();
        }
    }

    /**
     * Ensure we have enough chunks being synthesized ahead of playback.
     */
    private fillPrefetchBuffer(): void {
        while (
            !this.stopRequested &&
            !this.isGenerating &&
            this.pendingChunks.length > 0 &&
            this.audioBufferQueue.length < this.PREFETCH_BUFFER_SIZE
        ) {
            this.requestNextChunk();
        }
    }

    /**
     * Request the worker to synthesize the next chunk.
     */
    private requestNextChunk(): void {
        if (this.pendingChunks.length === 0 || this.isGenerating || !this.activePlaybackVoiceId) {
            return;
        }

        const chunk = this.pendingChunks.shift()!;
        const generation = this.playbackGeneration;
        const requestId = ++this.nextRequestId;
        this.isGenerating = true;

        if (this._selectedEngine() === 'nativeChatterbox') {
            void this.requestNativeChunk(chunk, generation, requestId);
            return;
        }
        if (this._selectedEngine() === 'nativeSupertonicRust') {
            void this.requestSupertonicRustChunk(chunk, generation, requestId);
            return;
        }
        if (this._selectedEngine() === 'nativeQwenClone') {
            void this.requestQwenCloneChunk(chunk, generation, requestId);
            return;
        }

        console.log(`[TtsService] Requesting synthesis (${this.pendingChunks.length} pending): "${chunk.substring(0, 40)}..."`);
        this.sendMessage({
            type: 'SPEAK',
            payload: {
                text: chunk,
                voiceId: this.activePlaybackVoiceId,
                generation,
                requestId
            }
        });
    }

    private async requestNativeChunk(chunk: string, generation: number, requestId: number): Promise<void> {
        try {
            const result = await this.getNativeRpc().phoenix.tts_speak({
                text: chunk,
                voiceWav: NATIVE_TTS_REFERENCE_WAV,
                maxNewTokens: NATIVE_TTS_MAX_NEW_TOKENS,
                repetitionPenalty: 1.2,
            });
            if (generation !== this.playbackGeneration || this.stopRequested) {
                return;
            }
            if (!result.stopped) {
                console.warn(
                    `[TtsService] Native Chatterbox hit the ${NATIVE_TTS_MAX_NEW_TOKENS} token cap before STOP. ` +
                    `Chunk may be incomplete: "${chunk.substring(0, 80)}..."`,
                );
            }
            const samples = pcm16ToFloat32(result);
            await this.handleAudioReady(
                samples.buffer,
                samples.length,
                result.sampleRate,
                generation,
                requestId,
            );
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            this.handleSpeakError(generation, requestId, message);
        }
    }

    private async requestSupertonicRustChunk(
        chunk: string,
        generation: number,
        requestId: number,
    ): Promise<void> {
        try {
            const voiceStyle = this.activePlaybackVoiceId || this._selectedVoice().id;
            console.log(
                `[TtsService] Requesting Supertonic Rust synthesis ` +
                `(${this.pendingChunks.length} pending, voice=${voiceStyle}): "${chunk.substring(0, 40)}..."`,
            );
            const result = await this.getNativeRpc().phoenix.tts_supertonic_speak({
                text: chunk,
                voiceStyle,
                runnerPath: NATIVE_SUPERTONIC_RUNNER,
                modelRoot: NATIVE_SUPERTONIC_MODEL_ROOT,
                outputDir: NATIVE_SUPERTONIC_OUTPUT_ROOT,
                totalStep: NATIVE_SUPERTONIC_TOTAL_STEP,
                speed: NATIVE_SUPERTONIC_SPEED,
                lang: 'en',
            });
            if (generation !== this.playbackGeneration || this.stopRequested) {
                return;
            }
            const samples = pcm16ToFloat32(result);
            await this.handleAudioReady(
                samples.buffer,
                samples.length,
                result.sampleRate,
                generation,
                requestId,
            );
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            this.handleSpeakError(generation, requestId, message);
        }
    }

    private async requestQwenCloneChunk(
        chunk: string,
        generation: number,
        requestId: number,
    ): Promise<void> {
        try {
            console.log(
                `[TtsService] Requesting Qwen 0.6B voice clone ` +
                `(${this.pendingChunks.length} pending): "${chunk.substring(0, 40)}..."`,
            );
            const refAudio = this._qwenCloneReferenceAudio().trim() || NATIVE_TTS_REFERENCE_WAV;
            const refText = this._qwenCloneReferenceText().trim();
            const promptPath = this._qwenClonePromptPath().trim() || NATIVE_QWEN_PROMPT_CACHE;
            const usePromptCache = this._qwenCloneUsePromptCache();
            const result = await this.getNativeRpc().phoenix.tts_qwen_speak({
                text: chunk,
                runnerPath: NATIVE_QWEN_RUNNER,
                model: NATIVE_QWEN_MODEL,
                modelPath: null,
                refAudio,
                refText: refText || null,
                outputDir: NATIVE_QWEN_OUTPUT_ROOT,
                loadPrompt: usePromptCache ? promptPath : null,
                savePrompt: usePromptCache ? promptPath : null,
                usePromptCache,
                language: NATIVE_QWEN_LANGUAGE,
                device: NATIVE_QWEN_DEVICE,
                dtype: NATIVE_QWEN_DTYPE,
                maxTokens: NATIVE_QWEN_MAX_TOKENS,
                greedy: false,
                xVectorOnly: !refText,
                timeoutSecs: NATIVE_QWEN_TIMEOUT_SECS,
            });
            if (generation !== this.playbackGeneration || this.stopRequested) {
                return;
            }
            const samples = pcm16ToFloat32(result);
            await this.handleAudioReady(
                samples.buffer,
                samples.length,
                result.sampleRate,
                generation,
                requestId,
            );
        } catch (error) {
            const rawMessage = error instanceof Error ? error.message : String(error);
            const message = explainNativeQwenError(rawMessage);
            this.handleSpeakError(generation, requestId, message);
        }
    }

    /**
     * Schedule the next audio buffer for playback at the precise end time.
     */
    private scheduleNextBuffer(): void {
        if (this.stopRequested || this.audioBufferQueue.length === 0) {
            if (this.pendingChunks.length === 0 && !this.isGenerating && this.audioBufferQueue.length === 0) {
                this.finishPlayback();
            }
            return;
        }

        const buffer = this.audioBufferQueue.shift()!;
        const ctx = this.audioContext!;

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);

        const now = ctx.currentTime;
        const startAt = Math.max(now, this.scheduledEndTime);

        source.start(startAt);
        this.scheduledEndTime = startAt + buffer.duration;
        this.activeSourceNodes.push(source);

        source.onended = () => {
            this.cleanupSource(source);
            this.scheduleNextBuffer();
        };

        console.log(`[TtsService] Scheduled buffer: start=${startAt.toFixed(3)}, duration=${buffer.duration.toFixed(2)}s, queue=${this.audioBufferQueue.length}`);
        this.fillPrefetchBuffer();
    }

    /**
     * Remove a source node from tracking.
     */
    private cleanupSource(source: AudioBufferSourceNode): void {
        const idx = this.activeSourceNodes.indexOf(source);
        if (idx !== -1) {
            this.activeSourceNodes.splice(idx, 1);
        }

        source.onended = null;
        source.buffer = null;

        try {
            source.disconnect();
        } catch {
            // Already disconnected
        }
    }

    /**
     * Called when all audio has finished playing.
     */
    private finishPlayback(): void {
        if (!this.stopRequested && this._isPlaying()) {
            console.log('[TtsService] Finished playing all chunks.');
            this._isPlaying.set(false);
            this.activePlaybackVoiceId = null;
            this.finishOrScheduleIdleUnload();
        }
    }

    private finishOrScheduleIdleUnload(): void {
        if (this.unloadAfterPlayback) {
            this.unloadAfterPlayback = false;
            void this.unloadModel();
            return;
        }

        this.scheduleIdleUnload();
    }

    private stopPlayback(scheduleIdleUnload: boolean, reason = 'unknown'): void {
        console.log(
            `[TtsService] Stopping playback (${reason}). ` +
            `pending=${this.pendingChunks.length}, queue=${this.audioBufferQueue.length}, ` +
            `active=${this.activeSourceNodes.length}, generating=${this.isGenerating}`,
        );

        const cancelledGeneration = ++this.playbackGeneration;
        this.stopRequested = true;
        this.isGenerating = false;
        this.activePlaybackVoiceId = null;
        this.unloadAfterPlayback = false;

        this.resetPlaybackBuffers();

        for (const source of this.activeSourceNodes) {
            source.onended = null;
            source.buffer = null;
            try {
                source.stop();
                source.disconnect();
            } catch {
                // Already stopped
            }
        }

        this.activeSourceNodes = [];
        this._isPlaying.set(false);
        this._isPaused.set(false);

        if (this.worker && this._selectedEngine() === 'browserSupertonic') {
            this.sendMessage({
                type: 'STOP',
                payload: { generation: cancelledGeneration }
            });
        }

        if (scheduleIdleUnload) {
            this.scheduleIdleUnload();
        } else {
            this.cancelIdleUnloadTimer();
        }
    }

    private resetPlaybackBuffers(): void {
        this.pendingChunks = [];
        this.audioBufferQueue = [];
        this.scheduledEndTime = 0;
    }

    // ========================================================================
    // Audio Context
    // ========================================================================

    private async ensureAudioContext(): Promise<void> {
        if (!this.audioContext) {
            this.audioContext = new AudioContext();
        }
        if (this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
        }
    }

    private async closeAudioContext(): Promise<void> {
        const ctx = this.audioContext;
        this.audioContext = null;

        if (ctx) {
            try {
                await ctx.close();
            } catch (error) {
                console.warn('[TtsService] Failed to close AudioContext:', error);
            }
        }
    }

    // ========================================================================
    // Worker Communication
    // ========================================================================

    private initWorker(): void {
        if (this.worker) return;

        this.worker = createWorkerOutsideAngular(
            this.ngZone,
            () =>
                new Worker(new URL('../workers/tts.worker', import.meta.url), {
                    type: 'module',
                }),
            (worker) => {
                worker.onmessage = (e: MessageEvent<TTSResponseMessage>) => {
                    this.handleWorkerMessage(e.data);
                };

                worker.onerror = (error) => {
                    this.ngZone.run(() => {
                        console.error('[TtsService] Worker error:', error);
                        this.resolveUnloadWaiter();
                        this.rejectAllVoicePreloads(new Error('Worker failed to initialize.'));
                        this._modelState.set('error');
                        this._errorMessage.set('Worker failed to initialize.');
                    });
                };
            },
        );
    }

    private sendMessage(msg: TTSWorkerMessage, transfer: Transferable[] = []): void {
        if (!this.worker) {
            console.error('[TtsService] Worker not initialized.');
            return;
        }

        if (transfer.length > 0) {
            this.worker.postMessage(msg, transfer);
            return;
        }

        this.worker.postMessage(msg);
    }

    private handleWorkerMessage(msg: TTSResponseMessage): void {
        switch (msg.type) {
            case 'PROGRESS':
                this.handleProgress(msg.payload);
                break;

            case 'MODEL_READY':
                this.ngZone.run(() => {
                    this._modelState.set('ready');
                    this._loadProgress.set(100);
                    this._loadStatus.set('Ready');
                    console.log('[TtsService] Model ready!');
                    void this.preloadVoice(this._selectedVoice());
                    this.runQueuedSpeakIfReady();
                });
                break;

            case 'MODEL_UNLOADED':
                this.ngZone.run(() => {
                    this.resolveUnloadWaiter();
                });
                break;

            case 'MODEL_ERROR':
                this.ngZone.run(() => {
                    this.resolveUnloadWaiter();
                    this._modelState.set('error');
                    this._errorMessage.set(msg.payload.message);
                    this.isGenerating = false;
                    console.error('[TtsService] Model load error:', msg.payload.message);
                });
                break;

            case 'VOICE_READY': {
                this.ngZone.run(() => {
                    this.cachedWorkerVoiceIds.add(msg.payload.voiceId);
                    const resolver = this.voicePreloadResolvers.get(msg.payload.voiceId);
                    if (resolver) {
                        this.voicePreloadResolvers.delete(msg.payload.voiceId);
                        resolver.resolve();
                    }
                });
                break;
            }

            case 'VOICE_ERROR': {
                this.ngZone.run(() => {
                    this.cachedWorkerVoiceIds.delete(msg.payload.voiceId);
                    const resolver = this.voicePreloadResolvers.get(msg.payload.voiceId);
                    if (resolver) {
                        this.voicePreloadResolvers.delete(msg.payload.voiceId);
                        resolver.reject(new Error(msg.payload.message));
                    }
                });
                break;
            }

            case 'AUDIO_READY':
                void this.handleAudioReady(
                    msg.payload.samples,
                    msg.payload.length,
                    msg.payload.sampleRate,
                    msg.payload.generation,
                    msg.payload.requestId
                );
                break;

            case 'SPEAK_ERROR':
                this.handleSpeakError(msg.payload.generation, msg.payload.requestId, msg.payload.message);
                break;

            case 'STATUS':
                this.ngZone.run(() => {
                    if (msg.payload.modelLoaded && this._modelState() !== 'ready') {
                        this._modelState.set('ready');
                    }
                });
                break;
        }
    }

    private handleProgress(progress: { status: string; progress?: number; file?: string }): void {
        this._loadStatus.set(progress.status);
        if (progress.progress !== undefined) {
            this._loadProgress.set(Math.round(progress.progress));
        }
        if (progress.file) {
            const shortName = progress.file.split('/').pop() || progress.file;
            this._loadStatus.set(`Loading ${shortName}...`);
        }
    }

    /**
     * Handle synthesized audio from worker and add it to the playback queue.
     */
    private async handleAudioReady(
        samplesBuffer: ArrayBufferLike,
        length: number,
        sampleRate: number,
        generation: number,
        requestId: number
    ): Promise<void> {
        if (generation !== this.playbackGeneration || this.stopRequested) {
            return;
        }

        try {
            await this.ensureAudioContext();

            if (generation !== this.playbackGeneration || this.stopRequested) {
                return;
            }

            const sourceSamples = new Float32Array(samplesBuffer, 0, length);
            const samples = new Float32Array(sourceSamples.length);
            samples.set(sourceSamples);
            const audioBuffer = this.audioContext!.createBuffer(1, samples.length, sampleRate);
            audioBuffer.copyToChannel(samples, 0);

            this.audioBufferQueue.push(audioBuffer);
            this.isGenerating = false;

            console.log(`[TtsService] Buffer received (#${requestId}). Queue size: ${this.audioBufferQueue.length}`);

            if (this.activeSourceNodes.length === 0 ||
                this.audioContext!.currentTime >= this.scheduledEndTime) {
                this.scheduleNextBuffer();
            }

            this.fillPrefetchBuffer();
        } catch (error) {
            if (generation !== this.playbackGeneration) {
                return;
            }

            console.error('[TtsService] Audio buffer error:', error);
            this.isGenerating = false;
            this.fillPrefetchBuffer();
        }
    }

    private handleSpeakError(generation: number, _requestId: number, message: string): void {
        if (generation !== this.playbackGeneration || this.stopRequested) {
            return;
        }

        console.error('[TtsService] Speak error:', message);
        this.isGenerating = false;
        this._errorMessage.set(message);
        this.fillPrefetchBuffer();
    }

    // ========================================================================
    // Voice Preload
    // ========================================================================

    private preloadVoice(voice: TtsVoice): Promise<void> {
        if (this._selectedEngine() !== 'browserSupertonic') {
            return Promise.resolve();
        }

        if (this._modelState() !== 'ready' || !this.worker) {
            return Promise.resolve();
        }

        if (this.cachedWorkerVoiceIds.has(voice.id)) {
            return Promise.resolve();
        }

        const existing = this.voicePreloadPromises.get(voice.id);
        if (existing) {
            return existing;
        }

        const promise = (async () => {
            const buffer = await getVoiceEmbeddingBuffer(voice);

            if (!this.worker) {
                throw new Error('Worker not initialized.');
            }

            const ack = new Promise<void>((resolve, reject) => {
                this.voicePreloadResolvers.set(voice.id, { resolve, reject });
            });

            this.sendMessage({
                type: 'PRELOAD_VOICE',
                payload: {
                    voiceId: voice.id,
                    buffer
                }
            }, [buffer]);

            await ack;
        })()
            .finally(() => {
                this.voicePreloadPromises.delete(voice.id);
            });

        this.voicePreloadPromises.set(voice.id, promise);
        return promise;
    }

    private rejectAllVoicePreloads(error: Error): void {
        for (const [voiceId, resolver] of this.voicePreloadResolvers.entries()) {
            this.voicePreloadResolvers.delete(voiceId);
            resolver.reject(error);
        }
        this.voicePreloadPromises.clear();
        this.cachedWorkerVoiceIds.clear();
    }

    // ========================================================================
    // Idle Unload
    // ========================================================================

    private scheduleIdleUnload(): void {
        if (
            this._isPlaying() ||
            this.isGenerating ||
            this.pendingChunks.length > 0 ||
            this.audioBufferQueue.length > 0 ||
            this.activeSourceNodes.length > 0
        ) {
            console.log('[TtsService] Skipping idle unload while playback work is active.');
            return;
        }

        this.cancelIdleUnloadTimer();
        this.idleUnloadTimer = setTimeout(() => {
            void this.unloadModel();
        }, this.IDLE_UNLOAD_DELAY_MS);
    }

    private cancelIdleUnloadTimer(): void {
        if (this.idleUnloadTimer !== null) {
            clearTimeout(this.idleUnloadTimer);
            this.idleUnloadTimer = null;
        }
    }

    private async performUnload(
        engineToUnload: TTSEngine = this._selectedEngine(),
        resetModelState = true,
    ): Promise<void> {
        this.stopPlayback(false, 'unload');
        this.rejectAllVoicePreloads(new Error('TTS model unloaded.'));
        await this.closeAudioContext();

        if (engineToUnload === 'nativeChatterbox' && isTauriDesktop()) {
            try {
                await this.getNativeRpc().phoenix.tts_unload();
            } catch (error) {
                console.warn('[TtsService] Native Chatterbox unload failed:', error);
            }
        }

        const worker = this.worker;
        if (worker) {
            const ack = this.createUnloadWaiter();
            this.sendMessage({ type: 'UNLOAD_MODEL' });
            await ack;
            worker.terminate();
            this.worker = null;
        }

        this.cachedWorkerVoiceIds.clear();
        this.activePlaybackVoiceId = null;
        this._isPlaying.set(false);
        this._isPaused.set(false);

        if (resetModelState) {
            this._modelState.set('idle');
            this._loadProgress.set(0);
            this._loadStatus.set('');
        }
    }

    private createUnloadWaiter(): Promise<void> {
        if (this.unloadWaiter) {
            clearTimeout(this.unloadWaiter.timeout);
        }

        return new Promise<void>((resolve) => {
            const timeout = setTimeout(() => {
                this.unloadWaiter = null;
                resolve();
            }, 1500);

            this.unloadWaiter = {
                resolve: () => {
                    clearTimeout(timeout);
                    this.unloadWaiter = null;
                    resolve();
                },
                timeout
            };
        });
    }

    private resolveUnloadWaiter(): void {
        if (this.unloadWaiter) {
            const waiter = this.unloadWaiter;
            this.unloadWaiter = null;
            clearTimeout(waiter.timeout);
            waiter.resolve();
        }
    }

    private runQueuedSpeakIfReady(): void {
        if (this._modelState() !== 'ready' || !this.queuedSpeakRequest) {
            return;
        }

        const request = this.queuedSpeakRequest;
        this.queuedSpeakRequest = null;
        void this.startPlayback(request.text, request.unloadWhenFinished);
    }

    private getNativeRpc(): ReturnType<typeof createTauRPCProxy> {
        if (!this.nativeRpc) {
            this.nativeRpc = createTauRPCProxy();
        }
        return this.nativeRpc;
    }
}

function isTauriDesktop(): boolean {
    return typeof window !== 'undefined'
        && Boolean((window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

function readStoredString(key: string, fallback: string): string {
    if (typeof localStorage === 'undefined') {
        return fallback;
    }
    return localStorage.getItem(key) || fallback;
}

function readStoredBoolean(key: string, fallback: boolean): boolean {
    if (typeof localStorage === 'undefined') {
        return fallback;
    }
    const value = localStorage.getItem(key);
    if (value === null) {
        return fallback;
    }
    return value === 'true';
}

function storeString(key: string, value: string): void {
    if (typeof localStorage !== 'undefined') {
        localStorage.setItem(key, value);
    }
}

function storeBoolean(key: string, value: boolean): void {
    if (typeof localStorage !== 'undefined') {
        localStorage.setItem(key, String(value));
    }
}

function explainNativeQwenError(message: string): string {
    if (message.includes('TaurPC__phoenix.tts_qwen_speak') && message.includes('not found')) {
        return 'Qwen TTS is wired in Angular, but the running desktop shell is stale. Restart the Tauri app so the new native tts_qwen_speak command is registered.';
    }
    return message;
}

function normalizeSpeechInput(text: string): string {
    return String(text || '')
        .replace(/\r\n/g, '\n')
        .replace(/[ \t\f\v]+/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function splitByWordBudget(text: string, maxChunkSize: number): string[] {
    const chunks: string[] = [];
    let currentChunk = '';
    for (const word of text.split(/\s+/)) {
        if (!word) continue;
        if (currentChunk && (currentChunk.length + 1 + word.length) > maxChunkSize) {
            chunks.push(currentChunk);
            currentChunk = word;
            continue;
        }
        currentChunk = currentChunk ? `${currentChunk} ${word}` : word;
    }
    if (currentChunk) {
        chunks.push(currentChunk);
    }
    return chunks;
}

function pcm16ToFloat32(result: NativeTtsSynthResult): Float32Array {
    const bytes = result.pcmS16Le instanceof Uint8Array
        ? result.pcmS16Le
        : new Uint8Array(result.pcmS16Le);
    const sampleCount = Math.min(result.sampleCount, Math.floor(bytes.byteLength / 2));
    const samples = new Float32Array(sampleCount);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let index = 0; index < sampleCount; index += 1) {
        samples[index] = view.getInt16(index * 2, true) / 32768;
    }
    return samples;
}
