/// <reference lib="webworker" />
// src/app/workers/tts.worker.ts
// Text-to-Speech worker - handles TTS model loading and speech synthesis off main thread

import { pipeline, env } from '@huggingface/transformers';

// ============================================================================
// Types
// ============================================================================

export type TTSWorkerMessage =
    | { type: 'LOAD_MODEL' }
    | { type: 'PRELOAD_VOICE'; payload: { voiceId: string; buffer: ArrayBuffer } }
    | { type: 'SPEAK'; payload: { text: string; voiceId: string; generation: number; requestId: number } }
    | { type: 'STOP'; payload: { generation: number } }
    | { type: 'UNLOAD_MODEL' }
    | { type: 'GET_STATUS' };

export type TTSResponseMessage =
    | { type: 'PROGRESS'; payload: { status: string; progress?: number; file?: string } }
    | { type: 'MODEL_READY' }
    | { type: 'MODEL_UNLOADED' }
    | { type: 'MODEL_ERROR'; payload: { message: string } }
    | { type: 'VOICE_READY'; payload: { voiceId: string } }
    | { type: 'VOICE_ERROR'; payload: { voiceId: string; message: string } }
    | {
        type: 'AUDIO_READY';
        payload: { generation: number; requestId: number; samples: ArrayBuffer; length: number; sampleRate: number };
    }
    | { type: 'SPEAK_ERROR'; payload: { generation: number; requestId: number; message: string } }
    | { type: 'STATUS'; payload: { modelLoaded: boolean; cachedVoices: string[] } };

interface RawAudioOutput {
    audio: Float32Array | Float32Array[];
    sampling_rate: number;
    data: Float32Array;
}

interface TTSPipeline {
    (text: string, options?: Record<string, unknown>): Promise<RawAudioOutput>;
    dispose?(): Promise<void>;
}

// ============================================================================
// Configuration
// ============================================================================

const MODEL_ID = 'onnx-community/Supertonic-TTS-2-ONNX';
const MODEL_LABEL = 'Supertonic TTS 2 browser compatibility model';

// Configure transformers.js for web worker environment
env.allowLocalModels = false;
env.useBrowserCache = true;
const onnx = env.backends.onnx;
if (onnx?.wasm) {
    onnx.wasm.wasmPaths = '/assets/onnx/';
}

// ============================================================================
// Worker State
// ============================================================================

let tts: TTSPipeline | null = null;
let isModelLoading = false;
let activeGeneration = 0;
const voiceEmbeddings = new Map<string, Float32Array>();

// ============================================================================
// Message Handler
// ============================================================================

onmessage = async (e: MessageEvent<TTSWorkerMessage>) => {
    const { type } = e.data;

    try {
        switch (type) {
            case 'LOAD_MODEL':
                await loadModel();
                break;

            case 'PRELOAD_VOICE': {
                const payload = (e.data as Extract<TTSWorkerMessage, { type: 'PRELOAD_VOICE' }>).payload;
                preloadVoice(payload.voiceId, payload.buffer);
                break;
            }

            case 'SPEAK': {
                const payload = (e.data as Extract<TTSWorkerMessage, { type: 'SPEAK' }>).payload;
                await speak(payload.text, payload.voiceId, payload.generation, payload.requestId);
                break;
            }

            case 'STOP': {
                const payload = (e.data as Extract<TTSWorkerMessage, { type: 'STOP' }>).payload;
                activeGeneration = Math.max(activeGeneration, payload.generation);
                break;
            }

            case 'UNLOAD_MODEL':
                await unloadModel();
                break;

            case 'GET_STATUS':
                postMessage({
                    type: 'STATUS',
                    payload: {
                        modelLoaded: tts !== null,
                        cachedVoices: Array.from(voiceEmbeddings.keys()),
                    }
                } as TTSResponseMessage);
                break;

            default:
                console.warn('[TTS Worker] Unknown message type:', type);
        }
    } catch (error) {
        console.error('[TTS Worker] Error:', error);
        postMessage({
            type: 'MODEL_ERROR',
            payload: { message: error instanceof Error ? error.message : String(error) }
        } as TTSResponseMessage);
    }
};

// ============================================================================
// Model Loading
// ============================================================================

async function loadModel(): Promise<void> {
    if (tts) {
        postMessage({ type: 'MODEL_READY' } as TTSResponseMessage);
        return;
    }

    if (isModelLoading) {
        console.log('[TTS Worker] Model already loading...');
        return;
    }

    isModelLoading = true;
    console.log(`[TTS Worker] Loading ${MODEL_LABEL}...`);

    try {
        const loadedPipeline = await (pipeline as any)('text-to-speech', MODEL_ID, {
            progress_callback: (progress: { status: string; progress?: number; file?: string }) => {
                postMessage({
                    type: 'PROGRESS',
                    payload: progress
                } as TTSResponseMessage);
            }
        });
        tts = loadedPipeline as TTSPipeline;

        console.log('[TTS Worker] Model loaded successfully!');
        postMessage({ type: 'MODEL_READY' } as TTSResponseMessage);
    } catch (error) {
        console.error('[TTS Worker] Failed to load model:', error);
        postMessage({
            type: 'MODEL_ERROR',
            payload: { message: error instanceof Error ? error.message : String(error) }
        } as TTSResponseMessage);
    } finally {
        isModelLoading = false;
    }
}

async function unloadModel(): Promise<void> {
    activeGeneration += 1;
    voiceEmbeddings.clear();

    if (tts?.dispose) {
        await tts.dispose();
    }
    tts = null;

    postMessage({ type: 'MODEL_UNLOADED' } as TTSResponseMessage);
}

function preloadVoice(voiceId: string, buffer: ArrayBuffer): void {
    try {
        voiceEmbeddings.set(voiceId, new Float32Array(buffer));
        postMessage({
            type: 'VOICE_READY',
            payload: { voiceId }
        } as TTSResponseMessage);
    } catch (error) {
        postMessage({
            type: 'VOICE_ERROR',
            payload: {
                voiceId,
                message: error instanceof Error ? error.message : String(error)
            }
        } as TTSResponseMessage);
    }
}

// ============================================================================
// Speech Synthesis
// ============================================================================

async function speak(text: string, voiceId: string, generation: number, requestId: number): Promise<void> {
    if (!tts) {
        postSpeakError(generation, requestId, 'Model not loaded. Call LOAD_MODEL first.');
        return;
    }

    if (!text || text.trim().length === 0) {
        postSpeakError(generation, requestId, 'No text provided.');
        return;
    }

    const embeddings = voiceEmbeddings.get(voiceId);
    if (!embeddings) {
        postSpeakError(generation, requestId, `Voice ${voiceId} is not preloaded.`);
        return;
    }

    if (generation < activeGeneration) {
        return;
    }

    console.log('[TTS Worker] Generating speech for:', text.substring(0, 100) + (text.length > 100 ? '...' : ''));

    try {
        const inputText = `<en>${text}</en>`;

        const output = await tts(inputText, {
            speaker_embeddings: embeddings,
            num_inference_steps: 5,
            speed: 1.05
        });

        if (generation < activeGeneration) {
            return;
        }

        const samples = getTransferableSamples(output);
        postMessage({
            type: 'AUDIO_READY',
            payload: {
                generation,
                requestId,
                samples: samples.buffer,
                length: samples.length,
                sampleRate: output.sampling_rate
            }
        } as TTSResponseMessage, [samples.buffer]);
    } catch (error) {
        if (generation < activeGeneration) {
            return;
        }

        console.error('[TTS Worker] Speech generation failed:', error);
        postSpeakError(generation, requestId, error instanceof Error ? error.message : String(error));
    }
}

function getTransferableSamples(output: RawAudioOutput): Float32Array {
    const audio = output.audio;

    let samples: Float32Array;
    if (audio instanceof Float32Array) {
        samples = audio;
    } else if (Array.isArray(audio) && audio.length === 1) {
        samples = audio[0];
    } else {
        samples = output.data;
    }

    if (samples.byteOffset !== 0 || samples.byteLength !== samples.buffer.byteLength) {
        return samples.slice();
    }

    return samples;
}

function postSpeakError(generation: number, requestId: number, message: string): void {
    postMessage({
        type: 'SPEAK_ERROR',
        payload: { generation, requestId, message }
    } as TTSResponseMessage);
}

console.log('[TTS Worker] Initialized and ready for messages.');
