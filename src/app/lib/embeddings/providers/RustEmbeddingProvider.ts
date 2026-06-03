// src/app/lib/embeddings/providers/RustEmbeddingProvider.ts
//
// Native Rust/WASM embedding provider using kittcore's EmbedCortex.

import type { IEmbeddingProvider } from './types';
import type { EmbeddingModelDefinition } from '../models/ModelRegistry';

// NOTE: Import will be wired when kittcore WASM is built
// import { EmbedCortex } from '@/rust/kittcore/pkg/kittcore';

/**
 * Stub EmbedCortex until WASM is wired
 */
class EmbedCortex {
    loadModel(_onnx: Uint8Array, _tokenizer: string): void {
        console.warn('[EmbedCortex] Stub - WASM not loaded');
    }
    getDimensions(): number { return 384; }
    isReady(): boolean { return false; }
    embedTexts(_texts: string[]): number[][] { return []; }
    free(): void { }
}

/**
 * Model files needed for the Rust embedder
 */
interface RustModelFiles {
    onnxUrl: string;
    tokenizerUrl: string;
}

/**
 * HuggingFace model file URLs
 */
const MODEL_FILES: Record<string, RustModelFiles> = {
    'bge-small-rust': {
        onnxUrl: 'https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/main/onnx/model.onnx',
        tokenizerUrl: 'https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/main/tokenizer.json',
    },
    'minilm-rust': {
        onnxUrl: 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx',
        tokenizerUrl: 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json',
    },
    'jina-v5-nano-retrieval': {
        onnxUrl: 'https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval/resolve/main/onnx/model.onnx',
        tokenizerUrl: 'https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval/resolve/main/tokenizer.json',
    },
    'mongodb-leaf-mt': {
        onnxUrl: 'https://huggingface.co/MongoDB/mdbr-leaf-mt/resolve/main/onnx/model.onnx',
        tokenizerUrl: 'https://huggingface.co/MongoDB/mdbr-leaf-mt/resolve/main/tokenizer.json',
    },
};

/**
 * Rust-based WASM embedding provider
 * Uses kittcore's EmbedCortex with tract-onnx for inference
 */
export class RustEmbeddingProvider implements IEmbeddingProvider {
    readonly name: string;
    readonly provider = 'rust' as const;

    private modelId: string;
    private cortex: EmbedCortex | null = null;
    private modelDef: EmbeddingModelDefinition;
    private initialized = false;
    private loadProgress = 0;

    constructor(modelId: string) {
        this.modelId = modelId;
        this.modelDef = this.createModelDefinition(modelId);
        this.name = this.modelDef.name;
    }

    private createModelDefinition(modelId: string): EmbeddingModelDefinition {
        switch (modelId) {
            case 'bge-small-rust':
                return {
                    id: 'bge-small-rust',
                    name: 'BGE Small EN v1.5 (Rust)',
                    provider: 'rust',
                    dimensions: 384,
                    maxTokens: 512,
                    speed: 'fast',
                    quality: 'high',
                    costPer1kTokens: 0,
                    description: 'BGE Small via Rust/WASM ONNX inference',
                };
            case 'jina-v5-nano-retrieval':
                return {
                    id: 'jina-v5-nano-retrieval',
                    name: 'Jina Embeddings v5 Nano (768d)',
                    provider: 'rust',
                    dimensions: 768,
                    maxTokens: 8192,
                    speed: 'fast',
                    quality: 'high',
                    costPer1kTokens: 0,
                    description: 'Jina v5 Nano embeddings through the native Rust runner.',
                };
            case 'mongodb-leaf-mt':
                return {
                    id: 'mongodb-leaf-mt',
                    name: 'MDBR Leaf MT (384d)',
                    provider: 'rust',
                    dimensions: 384,
                    maxTokens: 512,
                    speed: 'fast',
                    quality: 'high',
                    costPer1kTokens: 0,
                    description: 'MDBR Leaf MT multi-task embeddings through the native Rust runner.',
                };
            default:
                return {
                    id: modelId,
                    name: `${modelId} (Rust)`,
                    provider: 'rust',
                    dimensions: 384,
                    maxTokens: 512,
                    speed: 'fast',
                    quality: 'medium',
                    costPer1kTokens: 0,
                    description: 'Rust/WASM ONNX embedding model',
                };
        }
    }

    /**
     * Initialize the Rust embedding provider
     * Downloads model files from HuggingFace and loads into WASM
     */
    async initialize(): Promise<void> {
        if (this.initialized) return;

        console.log(`[RustEmbeddingProvider] Loading model: ${this.name}`);
        this.loadProgress = 0;

        const files = MODEL_FILES[this.modelId];
        if (!files) {
            throw new Error(`No model files configured for: ${this.modelId}`);
        }

        try {
            this.cortex = new EmbedCortex();
            this.loadProgress = 10;

            console.log('[RustEmbeddingProvider] Downloading model files...');
            const [onnxResponse, tokenizerResponse] = await Promise.all([
                fetch(files.onnxUrl),
                fetch(files.tokenizerUrl),
            ]);

            if (!onnxResponse.ok) {
                throw new Error(`Failed to download ONNX model: ${onnxResponse.statusText}`);
            }
            if (!tokenizerResponse.ok) {
                throw new Error(`Failed to download tokenizer: ${tokenizerResponse.statusText}`);
            }

            this.loadProgress = 50;

            const onnxBytes = new Uint8Array(await onnxResponse.arrayBuffer());
            const tokenizerJson = await tokenizerResponse.text();

            this.loadProgress = 70;

            console.log('[RustEmbeddingProvider] Loading model into WASM...');
            this.cortex.loadModel(onnxBytes, tokenizerJson);

            this.loadProgress = 100;
            this.initialized = true;
            console.log(`[RustEmbeddingProvider] Model loaded: ${this.name} (${this.cortex.getDimensions()}d)`);

        } catch (error) {
            console.error('[RustEmbeddingProvider] Failed to initialize:', error);
            this.cortex?.free();
            this.cortex = null;
            throw error;
        }
    }

    isReady(): boolean {
        return this.initialized && this.cortex !== null && this.cortex.isReady();
    }

    async embed(texts: string | string[]): Promise<number[][]> {
        if (!this.isReady()) {
            throw new Error('RustEmbeddingProvider not initialized');
        }

        const inputTexts = Array.isArray(texts) ? texts : [texts];

        if (inputTexts.length === 0) {
            return [];
        }

        try {
            const embeddings = this.cortex!.embedTexts(inputTexts);
            return embeddings;
        } catch (error) {
            console.error('[RustEmbeddingProvider] Embed failed:', error);
            throw error;
        }
    }

    getModelInfo(): EmbeddingModelDefinition {
        return this.modelDef;
    }

    getLoadProgress(): number {
        return this.loadProgress;
    }

    async dispose(): Promise<void> {
        if (this.cortex) {
            this.cortex.free();
            this.cortex = null;
        }
        this.initialized = false;
        this.loadProgress = 0;
    }
}
