// src/app/lib/embeddings/models/ModelRegistry.ts
// Model registry for semantic embedding runner targets.

export type EmbeddingProvider = 'rust';

export const DEFAULT_GRAPH_EMBEDDING_MODEL_ID = 'jina-v5-nano-retrieval';
export const DEFAULT_GRAPH_EMBEDDING_MODEL_LABEL = 'Jina v5 Nano';
export const DEFAULT_GRAPH_EMBEDDING_DIMENSION_LABEL = '768d';

export interface EmbeddingModelDefinition {
    id: string;
    name: string;
    provider: EmbeddingProvider;
    dimensions: number;
    maxTokens: number;

    // Performance characteristics
    speed: 'fast' | 'medium' | 'slow';
    quality: 'high' | 'medium' | 'low';

    // Cost
    costPer1kTokens: number; // 0 for native runner models

    // Native runner model metadata.
    localModel?: {
        modelId: string;
        quantization?: 'q8' | 'q4' | 'fp16';
        memoryMB: number; // Estimated memory usage
    };

    description: string;
}

export class EmbeddingModelRegistry {
    private static models: Map<string, EmbeddingModelDefinition> = new Map([
        // ===== NATIVE RUST RUNNER MODELS =====
        [
            'mongodb-leaf-mt',
            {
                id: 'mongodb-leaf-mt',
                name: 'MDBR Leaf MT (384d)',
                provider: 'rust',
                dimensions: 384,
                maxTokens: 512,
                speed: 'fast',
                quality: 'high',
                costPer1kTokens: 0,
                localModel: {
                    modelId: 'MongoDB/mdbr-leaf-mt',
                    quantization: 'q8',
                    memoryMB: 90,
                },
                description: 'MDBR Leaf MT through the native Phoenix Rust semantic runner for fast multi-task embeddings.',
            },
        ],
        [
            'jina-v5-nano-retrieval',
            {
                id: 'jina-v5-nano-retrieval',
                name: 'Jina Embeddings v5 Nano (768d)',
                provider: 'rust',
                dimensions: 768,
                maxTokens: 8192,
                speed: 'fast',
                quality: 'high',
                costPer1kTokens: 0,
                localModel: {
                    modelId: 'jinaai/jina-embeddings-v5-text-nano-retrieval',
                    quantization: 'fp16',
                    memoryMB: 220,
                },
                description: 'Jina v5 Nano embeddings through the native Rust ONNX runner for retrieval, classification, and graph topology.',
            },
        ],
        [
            'bge-small-en',
            {
                id: 'bge-small-en',
                name: 'BGE Small EN v1.5 (384d)',
                provider: 'rust',
                dimensions: 384,
                maxTokens: 512,
                speed: 'fast',
                quality: 'high',
                costPer1kTokens: 0,
                localModel: {
                    modelId: 'BAAI/bge-small-en-v1.5',
                    quantization: 'fp16',
                    memoryMB: 130,
                },
                description: 'BGE Small EN v1.5 through the native Phoenix Rust semantic runner.',
            },
        ],

        // ===== RUST/WASM MODELS (kittcore EmbedCortex) =====
        [
            'bge-small-rust',
            {
                id: 'bge-small-rust',
                name: 'BGE Small EN v1.5 (Rust)',
                provider: 'rust',
                dimensions: 384,
                maxTokens: 512,
                speed: 'fast',
                quality: 'high',
                costPer1kTokens: 0,
                localModel: {
                    modelId: 'BAAI/bge-small-en-v1.5',
                    memoryMB: 130,
                },
                description: 'BGE Small via Rust/WASM ONNX.',
            },
        ],

    ]);

    static getModel(id: string): EmbeddingModelDefinition | undefined {
        return this.models.get(id);
    }

    static getLocalModels(): EmbeddingModelDefinition[] {
        return [];
    }

    static getRustModels(): EmbeddingModelDefinition[] {
        return Array.from(this.models.values()).filter(m => m.provider === 'rust');
    }

    static getCloudModels(): EmbeddingModelDefinition[] {
        return [];
    }

    static getByDimension(dim: number): EmbeddingModelDefinition[] {
        return Array.from(this.models.values()).filter(m => m.dimensions === dim);
    }

    static getAllModels(): EmbeddingModelDefinition[] {
        return Array.from(this.models.values());
    }

    static getRecommended(preference: 'speed' | 'quality' | 'privacy'): string {
        switch (preference) {
            case 'speed':
                return DEFAULT_GRAPH_EMBEDDING_MODEL_ID;
            case 'quality':
                return DEFAULT_GRAPH_EMBEDDING_MODEL_ID;
            case 'privacy':
                return DEFAULT_GRAPH_EMBEDDING_MODEL_ID;
            default:
                return DEFAULT_GRAPH_EMBEDDING_MODEL_ID;
        }
    }
}
