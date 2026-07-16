/**
 * CrepeModelCache - Isolated IndexedDB for ML Model Storage
 * 
 * This is a stripped-down Dexie instance used ONLY for caching:
 * - TTS models (browser Supertonic v2 compatibility ONNX)
 * - Embedding models (@xenova/transformers)
 * - Voice files (.bin)
 * 
 * Completely isolated from application document and graph storage.
 * Uses its own IndexedDB quota (~500MB+).
 */

import Dexie, { Table } from 'dexie';

// =============================================================================
// INTERFACES
// =============================================================================

export interface CachedModel {
    id: string;                    // e.g., "tts:supertonic-2", "embed:mongodb-leaf-mt", "voice:F1"
    type: 'tts' | 'embedding' | 'voice' | 'onnx';
    url: string;                   // Original source URL
    blob: Blob;                    // The actual model binary
    size: number;                  // Bytes
    cachedAt: number;              // Timestamp (ms)
    version?: string;              // Model version for cache invalidation
    contentType?: string;          // MIME type
}

export interface CacheStats {
    count: number;
    totalBytes: number;
    byType: Record<string, { count: number; bytes: number }>;
}

// =============================================================================
// DATABASE CLASS
// =============================================================================

class ModelCacheDB extends Dexie {
    models!: Table<CachedModel, string>;

    constructor() {
        // NEW database name - completely isolated from old Dexie
        super('CrepeModelCache');

        this.version(1).stores({
            models: 'id, type, cachedAt, size'
        });
    }
}

// =============================================================================
// SINGLETON EXPORT
// =============================================================================

export const modelCacheDb = new ModelCacheDB();

// Debug access
if (typeof window !== 'undefined') {
    (window as any).modelCacheDb = modelCacheDb;
    console.log('[ModelCache] 🗄️ Debug: window.modelCacheDb');
}
