import Dexie, { type Table } from 'dexie';

import type { GraphRebuildSnapshot } from '../../../../../graph-rebuild/graph-rebuild-snapshot';
import type { AtlasManifoldMode } from '../../../../../services/manifold-atlas.types';
import {
    assertGalaxyScenePacketV2,
    openDetachedGalaxyScenePacketV2Page,
    verifyGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2';
import type {
    GalaxyScenePacketV2,
    GalaxyScenePacketV2Manifest,
    VerifiedGalaxyScenePacketV2,
} from './graph-galaxy-scene-packet-v2.model';

const DATABASE_NAME = 'phoenix-galaxy-scene-v3-cache';
const RECEIPT_SCHEMA = 'phoenix-galaxy-scene-cache-receipt/v2';
const MAX_PERSISTED_PACKETS = 25;
const MAX_PERSISTED_BYTES = 256 * 1024 * 1024;
const MAX_BOOT_SNAPSHOT_CHARS = 512 * 1024;
const MANIFOLDS: readonly AtlasManifoldMode[] = ['hybrid', 'hopf', 'lorentz', 'product', 'siegel'];

export interface GalaxyScenePacketPersistenceIdentity {
    scopeId: string;
    snapshotId: string;
    generationId: string;
    manifold: AtlasManifoldMode;
    authorityReceipt: string;
}

export interface PersistedGalaxyScenePacket {
    identity: GalaxyScenePacketPersistenceIdentity;
    snapshotShell: GraphRebuildSnapshot;
    packet: GalaxyScenePacketV2;
}

export interface GalaxyScenePacketReceiptRecord extends GalaxyScenePacketPersistenceIdentity {
    schemaVersion: typeof RECEIPT_SCHEMA;
    slotKey: string;
    manifest: GalaxyScenePacketV2Manifest;
    snapshotShell: GraphRebuildSnapshot;
    snapshotShellHash: string;
    pageIds: string[];
    totalBytes: number;
    updatedAt: number;
}

export interface GalaxyScenePacketPageRecord {
    key: string;
    slotKey: string;
    pageId: string;
    buffer: ArrayBuffer;
}

export interface GalaxyScenePacketPersistenceRecords {
    receipt: GalaxyScenePacketReceiptRecord;
    pages: GalaxyScenePacketPageRecord[];
}

export interface GalaxySceneGenerationIndexReceipt {
    schemaVersion: 'phoenix-galaxy-scene-generation-index/v1';
    scopeId: string;
    snapshotId: string;
    generationId: string;
    digestSha256: string;
    packetCount: 5;
    totalBytes: number;
    packets: Array<{
        manifold: AtlasManifoldMode;
        authorityReceipt: string;
        pageCount: number;
        totalBytes: number;
    }>;
}

export interface GalaxySceneGenerationIndexEntry {
    receipt: GalaxyScenePacketReceiptRecord;
    pageCount: number;
}

class GalaxyScenePacketCacheDatabase extends Dexie {
    receipts!: Table<GalaxyScenePacketReceiptRecord, string>;
    pages!: Table<GalaxyScenePacketPageRecord, string>;

    constructor() {
        super(DATABASE_NAME);
        this.version(1).stores({
            receipts: 'slotKey, scopeId, manifold, generationId, updatedAt',
            pages: 'key, slotKey, pageId',
        });
        this.version(2).stores({
            receipts: 'slotKey, scopeId, manifold, generationId, updatedAt',
            pages: 'key, slotKey, pageId',
        });
    }
}

const database = new GalaxyScenePacketCacheDatabase();

export async function persistGalaxyScenePacket(
    identity: GalaxyScenePacketPersistenceIdentity,
    packet: GalaxyScenePacketV2,
    snapshotShell: GraphRebuildSnapshot,
): Promise<void> {
    const records = galaxyScenePacketPersistenceRecords(identity, packet, snapshotShell);
    await database.transaction('rw', database.receipts, database.pages, async () => {
        await database.pages.where('slotKey').equals(records.receipt.slotKey).delete();
        await database.pages.bulkPut(records.pages);
        await database.receipts.put(records.receipt);
        await trimPersistedPackets(records.receipt.slotKey);
    });
}

export async function loadPersistedGalaxyScenePacket(
    scopeId: string,
    manifold: AtlasManifoldMode,
): Promise<PersistedGalaxyScenePacket | null> {
    const receipt = await database.receipts.get(galaxyScenePacketSlotKey(scopeId, manifold));
    if (!receipt) return null;
    const persistedPageCount = await database.pages.where('slotKey').equals(receipt.slotKey).count();
    const residentPageIds = receipt.manifest.pages
        .filter((page) => page.loadPolicy === 'resident')
        .map((page) => page.id);
    const loaded = await database.pages.bulkGet(
        residentPageIds.map((pageId) => galaxyScenePacketPageKey(receipt.slotKey, pageId)),
    );
    if (loaded.some((page) => !page)) {
        throw new Error('Persisted galaxy scene is missing a resident first-pixel page.');
    }
    return restoreGalaxyScenePacketHotPersistenceRecords(
        receipt,
        loaded as GalaxyScenePacketPageRecord[],
        persistedPageCount,
    );
}

/** Loads and verifies exactly one non-resident page without retaining it in the hot registry. */
export async function loadPersistedGalaxyScenePacketPage(
    scopeId: string,
    manifold: AtlasManifoldMode,
    packet: VerifiedGalaxyScenePacketV2,
    pageId: string,
): Promise<ArrayBuffer> {
    const receipt = await database.receipts.get(galaxyScenePacketSlotKey(scopeId, manifold));
    if (!receipt
        || receipt.generationId !== packet.manifest.generationId
        || receipt.authorityReceipt !== packet.manifest.authorityReceipt) {
        throw new Error('Persisted galaxy scene page authority does not match the hot packet.');
    }
    const page = await database.pages.get(galaxyScenePacketPageKey(receipt.slotKey, pageId));
    if (!page || page.slotKey !== receipt.slotKey || page.pageId !== pageId) {
        throw new Error(`Persisted galaxy scene is missing on-demand page: ${pageId}`);
    }
    return openDetachedGalaxyScenePacketV2Page(packet, pageId, page.buffer);
}

export async function loadPersistedGalaxySceneGenerationIndex(
    scopeId: string,
    generationId: string,
): Promise<GalaxySceneGenerationIndexReceipt | null> {
    const receipts = await database.receipts.where('scopeId').equals(scopeId).toArray();
    const byManifold = new Map(receipts
        .filter((receipt) => receipt.generationId === generationId)
        .map((receipt) => [receipt.manifold, receipt] as const));
    if (!MANIFOLDS.every((manifold) => byManifold.has(manifold))) return null;
    const entries: GalaxySceneGenerationIndexEntry[] = [];
    for (const manifold of MANIFOLDS) {
        const receipt = byManifold.get(manifold)!;
        const pageCount = await database.pages.where('slotKey').equals(receipt.slotKey).count();
        entries.push({ receipt, pageCount });
    }
    return galaxySceneGenerationIndexReceipt(scopeId, generationId, entries);
}

export async function galaxySceneGenerationIndexReceipt(
    scopeId: string,
    generationId: string,
    entries: readonly GalaxySceneGenerationIndexEntry[],
): Promise<GalaxySceneGenerationIndexReceipt> {
    const byManifold = new Map(entries.map((entry) => [entry.receipt.manifold, entry] as const));
    if (entries.length !== MANIFOLDS.length || !MANIFOLDS.every((manifold) => byManifold.has(manifold))) {
        throw new Error('Packed scene generation requires exactly one packet for every manifold.');
    }
    const packets: GalaxySceneGenerationIndexReceipt['packets'] = [];
    let snapshotId = '';
    let totalBytes = 0;
    for (const manifold of MANIFOLDS) {
        const { receipt, pageCount } = byManifold.get(manifold)!;
        if (!snapshotId) snapshotId = receipt.snapshotId;
        if (receipt.scopeId !== scopeId
            || receipt.snapshotId !== snapshotId
            || receipt.generationId !== generationId
            || receipt.manifold !== manifold
            || receipt.manifest.generationId !== generationId
            || receipt.manifest.authorityReceipt !== receipt.authorityReceipt) {
            throw new Error(`Persisted ${manifold} scene generation authority drift.`);
        }
        if (pageCount !== receipt.pageIds.length) {
            throw new Error(`Persisted ${manifold} scene generation has incomplete pages.`);
        }
        totalBytes += receipt.totalBytes;
        packets.push({ manifold, authorityReceipt: receipt.authorityReceipt, pageCount, totalBytes: receipt.totalBytes });
    }
    const unsigned = {
        schemaVersion: 'phoenix-galaxy-scene-generation-index/v1' as const,
        scopeId,
        snapshotId,
        generationId,
        packetCount: 5 as const,
        totalBytes,
        packets,
    };
    return { ...unsigned, digestSha256: await sha256Json(unsigned) };
}

export function galaxyScenePacketPersistenceRecords(
    identity: GalaxyScenePacketPersistenceIdentity,
    packet: GalaxyScenePacketV2,
    snapshotShell: GraphRebuildSnapshot,
    updatedAt = Date.now(),
): GalaxyScenePacketPersistenceRecords {
    assertPersistenceIdentity(identity, packet);
    assertSnapshotShellIdentity(identity, snapshotShell);
    assertGalaxyScenePacketV2(packet);
    const snapshotShellJson = JSON.stringify(snapshotShell);
    if (snapshotShellJson.length > MAX_BOOT_SNAPSHOT_CHARS) {
        throw new Error(`Persisted galaxy scene boot shell exceeds ${MAX_BOOT_SNAPSHOT_CHARS} characters.`);
    }
    const slotKey = galaxyScenePacketSlotKey(identity.scopeId, identity.manifold);
    const pageIds = packet.manifest.pages.map((page) => page.id);
    const pages = pageIds.map((pageId) => ({
        key: galaxyScenePacketPageKey(slotKey, pageId),
        slotKey,
        pageId,
        buffer: packet.pages[pageId],
    }));
    return {
        receipt: {
            schemaVersion: RECEIPT_SCHEMA,
            slotKey,
            ...identity,
            manifest: packet.manifest,
            snapshotShell,
            snapshotShellHash: hashText(snapshotShellJson),
            pageIds,
            totalBytes: pages.reduce((sum, page) => sum + page.buffer.byteLength, 0),
            updatedAt,
        },
        pages,
    };
}

export function restoreGalaxyScenePacketPersistenceRecords(
    records: GalaxyScenePacketPersistenceRecords,
): PersistedGalaxyScenePacket {
    const { receipt } = records;
    assertPersistenceReceipt(receipt);
    const expectedPageIds = new Set(receipt.pageIds);
    if (records.pages.length !== expectedPageIds.size) {
        throw new Error('Persisted galaxy scene page count drift.');
    }
    const pages: Record<string, ArrayBuffer> = {};
    let totalBytes = 0;
    for (const page of records.pages) {
        if (page.slotKey !== receipt.slotKey || !expectedPageIds.has(page.pageId) || pages[page.pageId]) {
            throw new Error(`Persisted galaxy scene page identity drift: ${page.pageId}`);
        }
        pages[page.pageId] = page.buffer;
        totalBytes += page.buffer.byteLength;
    }
    if (totalBytes !== receipt.totalBytes) throw new Error('Persisted galaxy scene byte count drift.');
    const packet: GalaxyScenePacketV2 = { manifest: receipt.manifest, pages };
    assertPersistenceIdentity(receipt, packet);
    assertGalaxyScenePacketV2(packet);
    return persistedPacket(receipt, packet);
}

export function restoreGalaxyScenePacketHotPersistenceRecords(
    receipt: GalaxyScenePacketReceiptRecord,
    records: readonly GalaxyScenePacketPageRecord[],
    persistedPageCount: number,
): PersistedGalaxyScenePacket {
    assertPersistenceReceipt(receipt);
    if (persistedPageCount !== receipt.pageIds.length) {
        throw new Error('Persisted galaxy scene page count drift.');
    }
    const expectedIds = new Set(receipt.manifest.pages
        .filter((page) => page.loadPolicy === 'resident')
        .map((page) => page.id));
    if (records.length !== expectedIds.size) {
        throw new Error('Persisted galaxy scene resident page count drift.');
    }
    const pages: Record<string, ArrayBuffer> = {};
    for (const page of records) {
        if (page.slotKey !== receipt.slotKey || !expectedIds.has(page.pageId) || pages[page.pageId]) {
            throw new Error(`Persisted galaxy scene resident page identity drift: ${page.pageId}`);
        }
        pages[page.pageId] = page.buffer;
    }
    const packet: GalaxyScenePacketV2 = { manifest: receipt.manifest, pages };
    assertPersistenceIdentity(receipt, packet);
    verifyGalaxyScenePacketV2(packet);
    return persistedPacket(receipt, packet);
}

export function assertPersistedGalaxySceneMatches(
    persisted: PersistedGalaxyScenePacket,
    expected: GalaxyScenePacketPersistenceIdentity,
): void {
    for (const field of ['scopeId', 'snapshotId', 'generationId', 'manifold', 'authorityReceipt'] as const) {
        if (persisted.identity[field] !== expected[field]) {
            throw new Error(`Persisted galaxy scene ${field} does not match current graph authority.`);
        }
    }
}

function assertPersistenceIdentity(
    identity: GalaxyScenePacketPersistenceIdentity,
    packet: GalaxyScenePacketV2,
): void {
    if (!identity.scopeId || !identity.snapshotId || !identity.generationId || !identity.authorityReceipt) {
        throw new Error('Persisted galaxy scene requires complete graph authority identity.');
    }
    if (packet.manifest.generationId !== identity.generationId) {
        throw new Error('Persisted galaxy scene generation does not match its packet.');
    }
    if (packet.manifest.authorityReceipt !== identity.authorityReceipt) {
        throw new Error('Persisted galaxy scene authority receipt does not match its packet.');
    }
    if (packet.manifest.sourceMode !== 'embeddings') {
        throw new Error('Only authoritative embedding scenes may enter the restart cache.');
    }
}

function assertPersistenceReceipt(receipt: GalaxyScenePacketReceiptRecord): void {
    if (receipt.schemaVersion !== RECEIPT_SCHEMA) {
        throw new Error(`Unsupported persisted galaxy scene receipt: ${receipt.schemaVersion}`);
    }
    if (receipt.slotKey !== galaxyScenePacketSlotKey(receipt.scopeId, receipt.manifold)) {
        throw new Error('Persisted galaxy scene slot identity drift.');
    }
    const manifestPageIds = receipt.manifest.pages.map((page) => page.id);
    if (receipt.pageIds.length !== manifestPageIds.length
        || receipt.pageIds.some((pageId, index) => pageId !== manifestPageIds[index])) {
        throw new Error('Persisted galaxy scene receipt page manifest drift.');
    }
    const snapshotShellJson = JSON.stringify(receipt.snapshotShell);
    if (snapshotShellJson.length > MAX_BOOT_SNAPSHOT_CHARS) {
        throw new Error('Persisted galaxy scene boot shell exceeds its bounded contract.');
    }
    if (hashText(snapshotShellJson) !== receipt.snapshotShellHash) {
        throw new Error('Persisted galaxy scene boot shell hash drift.');
    }
    assertSnapshotShellIdentity(receipt, receipt.snapshotShell);
}

function persistedPacket(
    receipt: GalaxyScenePacketReceiptRecord,
    packet: GalaxyScenePacketV2,
): PersistedGalaxyScenePacket {
    return {
        identity: {
            scopeId: receipt.scopeId,
            snapshotId: receipt.snapshotId,
            generationId: receipt.generationId,
            manifold: receipt.manifold,
            authorityReceipt: receipt.authorityReceipt,
        },
        snapshotShell: receipt.snapshotShell,
        packet,
    };
}

function assertSnapshotShellIdentity(
    identity: GalaxyScenePacketPersistenceIdentity,
    snapshot: GraphRebuildSnapshot,
): void {
    const authority = snapshot.authorityContract;
    const manifest = snapshot.contentManifest;
    if (snapshot.id !== identity.snapshotId || snapshot.scopeId !== identity.scopeId) {
        throw new Error('Persisted galaxy scene boot shell snapshot identity drift.');
    }
    if (!authority
        || authority.snapshotId !== identity.snapshotId
        || authority.scopeId !== identity.scopeId
        || authority.contentHash !== identity.generationId) {
        throw new Error('Persisted galaxy scene boot shell authority identity drift.');
    }
    if (!manifest
        || manifest.snapshotId !== identity.snapshotId
        || manifest.scopeId !== identity.scopeId) {
        throw new Error('Persisted galaxy scene boot shell manifest identity drift.');
    }
}

function hashText(value: string): string {
    let hash = 0x811c9dc5;
    for (let index = 0; index < value.length; index++) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193);
    }
    return `fnv32-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

async function sha256Json(value: unknown): Promise<string> {
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return `sha256-${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

async function trimPersistedPackets(currentSlotKey: string): Promise<void> {
    const receipts = await database.receipts.orderBy('updatedAt').reverse().toArray();
    let retainedBytes = 0;
    let retainedCount = 0;
    for (const receipt of receipts) {
        const mustKeep = receipt.slotKey === currentSlotKey;
        const fits = retainedCount < MAX_PERSISTED_PACKETS
            && retainedBytes + receipt.totalBytes <= MAX_PERSISTED_BYTES;
        if (mustKeep || fits) {
            retainedBytes += receipt.totalBytes;
            retainedCount += 1;
            continue;
        }
        await database.pages.where('slotKey').equals(receipt.slotKey).delete();
        await database.receipts.delete(receipt.slotKey);
    }
}

function galaxyScenePacketSlotKey(scopeId: string, manifold: AtlasManifoldMode): string {
    return `${scopeId}\u0000${manifold}`;
}

function galaxyScenePacketPageKey(slotKey: string, pageId: string): string {
    return `${slotKey}\u0001${pageId}`;
}
