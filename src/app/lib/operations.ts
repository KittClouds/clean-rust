/**
 * Operations Module — Pure SQLite CRUD
 * 
 * Architecture (Phoenix native + Dexie cache):
 * - PhoenixStoreService is the source of truth
 * - Dexie is an ephemeral, in-memory state cache for Angular UI
 * - DataSyncService is ELIMINATED
 * - All durable CRUD goes through the native Phoenix bridge
 */
import { db } from './dexie/db';
import {
    deleteNoteStructureProjection,
    replaceNoteStructureProjection,
} from './notes/note-structure-projection';
import {
    isGlobalContextScope,
    scheduleGlobalContextIslandRefresh,
} from './notes/context-islands';
import {
    deleteNoteEntityOccurrences,
} from './notes/entity-occurrence-index';
import {
    PhoenixStoreService,
    StoreEdge,
    StoreEntity,
    StoreFolder,
    StoreNote,
    StoreNoteHeader,
} from '../services/phoenix-store.service';

// =============================================================================
// INTERFACES
// =============================================================================

export interface Note {
    id: string;
    worldId: string;
    title: string;
    content: any;
    markdownContent: string;
    folderId: string;
    entityKind?: string;
    entitySubtype?: string;
    isEntity?: boolean;
    isPinned?: boolean;
    favorite?: boolean;
    ownerId: string;
    createdAt: number;
    updatedAt: number;
    version?: number;
    narrativeId?: string;
    order: number;
    hasBody?: boolean;
}

export interface Folder {
    id: string;
    worldId: string;
    name: string;
    parentId: string;
    entityKind: string;
    entitySubtype: string;
    entityLabel: string;
    color: string;
    isTypedRoot: boolean;
    isSubtypeRoot: boolean;
    collapsed: boolean;
    ownerId: string;
    createdAt: number;
    updatedAt: number;
    narrativeId: string;
    isNarrativeRoot: boolean;
    networkId?: string;
    metadata?: {
        date?: { year: number; monthIndex: number; dayIndex: number };
    };
    attributes?: Record<string, any>;
    order: number;
}

export interface Entity {
    id: string;
    label: string;
    kind: string;
    subtype?: string;
    aliases?: string[];
    firstNote?: string;
    totalMentions?: number;
    createdAt: number;
    updatedAt: number;
    createdBy?: 'user' | 'extraction' | 'auto';
    narrativeId?: string;
}

export interface Edge {
    id: string;
    sourceId: string;
    targetId: string;
    relType: string;
    confidence?: number;
    bidirectional?: boolean;
}

// =============================================================================
// STORE ACCESS (Direct to PhoenixStoreService - NO DataSyncService)
// =============================================================================

let _store: PhoenixStoreService | null = null;
let _storeResolve: (() => void) | null = null;
const _storeReady = new Promise<void>(resolve => { _storeResolve = resolve; });

export function setPhoenixStoreBridge(store: PhoenixStoreService): void {
    _store = store;
    console.log('[Operations] PhoenixStoreService connected');
    _storeResolve?.();
}
export const setGoSqliteBridge = setPhoenixStoreBridge;

function requireStore(): PhoenixStoreService {
    if (!_store || !_store.isReady) {
        throw new Error('[Operations] PhoenixStoreService not ready - called too early');
    }
    return _store;
}

async function waitForStore(): Promise<PhoenixStoreService> {
    await _storeReady;
    const store = _store!;
    if (!store.isReady) {
        await store.initialize();
    }
    return store;
}

export function getBridge(): PhoenixStoreService | null {
    return _store?.isReady ? _store : null;
}

// =============================================================================
// DEXIE WARMING (Best-effort ephemeral state cache)
// =============================================================================

function warmDexieNote(note: Note): void {
    db.notes.put({ ...note, hasBody: note.hasBody ?? true } as any).catch(() => { });
}

function warmDexieNoteHeader(note: Note | StoreNoteHeader): void {
    const existing = note as Partial<Note>;
    db.notes.put({
        id: note.id,
        worldId: note.worldId || '',
        title: note.title || '',
        content: '',
        markdownContent: '',
        folderId: note.folderId || '',
        entityKind: note.entityKind || '',
        entitySubtype: note.entitySubtype || '',
        isEntity: note.isEntity || false,
        isPinned: note.isPinned || false,
        favorite: note.favorite || false,
        ownerId: note.ownerId || '',
        createdAt: note.createdAt || Date.now(),
        updatedAt: note.updatedAt || Date.now(),
        version: existing.version,
        narrativeId: note.narrativeId || '',
        order: Number(note.order || 0),
        hasBody: false,
        ...(existing.hasBody ? {
            content: existing.content || '',
            markdownContent: existing.markdownContent || '',
            hasBody: true,
        } : {}),
    } as any).catch(() => { });
}

function warmDexieFolder(folder: Folder): void {
    db.folders.put(folder as any).catch(() => { });
}

function warmDexieEntity(entity: Entity): void {
    db.entities.put(entity as any).catch(() => { });
}

// =============================================================================
// NOTE OPERATIONS
// =============================================================================

export async function createNote(note: Omit<Note, 'id' | 'createdAt' | 'updatedAt' | 'order'>): Promise<string> {
    const store = await waitForStore();
    const id = crypto.randomUUID();
    const now = Date.now();
    const order = await getNextNoteOrder(note.folderId);

    const fullNote: Note = {
        ...note,
        id,
        order,
        createdAt: now,
        updatedAt: now,
        version: now,
    } as Note;

    await store.upsertNote(PhoenixStoreService.fromDexieNote(fullNote));
    warmDexieNote({ ...fullNote, hasBody: true });
    await refreshNoteStructureProjection({ ...fullNote, hasBody: true });
    return id;
}

export async function updateNote(id: string, updates: Partial<Note>): Promise<Note | undefined> {
    const store = await waitForStore();
    let existing = await store.getNote(id);
    if (!existing) {
        const cached = await db.notes.get(id);
        if (!cached) {
            console.warn(`[Operations] Note ${id} not found`);
            return undefined;
        }
        console.warn(`[Operations] Note ${id} missing from Phoenix store; rehydrating from Dexie cache`);
        existing = PhoenixStoreService.fromDexieNote(cached);
    }

    const now = Date.now();
    const merged = { ...existing, ...updates, updatedAt: now, version: now };
    await store.upsertNote(merged as StoreNote);
    const note = { ...storeNoteToNote(merged as StoreNote), hasBody: true };
    warmDexieNote(note);

    if (updates.content !== undefined || updates.markdownContent !== undefined || updates.title !== undefined) {
        syncNoteToDocStore(note);
    }
    if (
        updates.content !== undefined ||
        updates.markdownContent !== undefined ||
        updates.folderId !== undefined ||
        updates.narrativeId !== undefined
    ) {
        await refreshNoteStructureProjection(note);
        schedulePriorGlobalContextRefresh(existing);
    }

    return note;
}

function syncNoteToDocStore(note: Note): void {
    import('../api/pretty-text-api').then((api) => {
        const phoenixUiApi = (api as any).getPhoenixUiApi?.();
        if (phoenixUiApi) {
            const text = note.markdownContent || (typeof note.content === 'string' ? note.content : JSON.stringify(note.content));
            phoenixUiApi.upsertNote(note.id, text, note.updatedAt, {
                title: note.title,
                narrativeId: note.narrativeId,
                folderPath: note.folderId,
            }).catch((e: any) =>
                console.warn('[Operations] DocStore sync failed:', e)
            );
        }
    }).catch(() => { });
}

export async function deleteNote(id: string): Promise<void> {
    const store = await waitForStore();
    const existing = await store.getNoteHeader(id);
    await store.deleteNote(id);
    db.notes.delete(id).catch(() => { });
    await clearNoteStructureProjection(id);
    await deleteNoteEntityOccurrences(id);
    schedulePriorGlobalContextRefresh(existing || undefined);
}

export async function getNote(id: string): Promise<Note | undefined> {
    const store = getBridge();
    if (!store) return db.notes.get(id) as Promise<Note | undefined>;
    const note = await store.getNote(id);
    if (note) return { ...storeNoteToNote(note), hasBody: true };
    return db.notes.get(id) as Promise<Note | undefined>;
}

export async function getNoteHeader(id: string): Promise<Note | undefined> {
    const store = getBridge();
    if (!store) return undefined;
    const note = await store.getNoteHeader(id);
    return note ? { ...storeNoteHeaderToNote(note), hasBody: false } : undefined;
}

export async function getAllNotes(): Promise<Note[]> {
    const store = getBridge();
    if (!store) return [];
    const notes = await store.listNoteHeaders();
    return notes.map(storeNoteHeaderToNote);
}

export async function getNotesByFolder(folderId: string): Promise<Note[]> {
    const store = getBridge();
    if (!store) return [];
    const notes = await store.listNoteHeaders(folderId);
    return notes.map(storeNoteHeaderToNote);
}

export async function getNotesByNarrative(narrativeId: string): Promise<Note[]> {
    const store = getBridge();
    if (!store) return [];
    const allNotes = await store.listNoteHeaders();
    return allNotes
        .filter(n => n.narrativeId === narrativeId)
        .map(storeNoteHeaderToNote);
}

export async function getNotesByIds(ids: string[]): Promise<Note[]> {
    const store = getBridge();
    if (ids.length === 0) return [];
    if (!store) {
        const cached = await db.notes.bulkGet(ids);
        return cached.filter(Boolean).map((note) => note as unknown as Note);
    }
    const notes = await store.getNotesByIds(ids);
    const fullNotes = notes.map((note) => ({ ...storeNoteToNote(note), hasBody: true }));
    for (const note of fullNotes) warmDexieNote(note);
    const byId = new Map<string, Note>(fullNotes.map((note) => [note.id, note]));
    const missingIds = ids.filter((id) => !byId.has(id));
    if (missingIds.length) {
        const cached = await db.notes.bulkGet(missingIds);
        for (const note of cached) {
            if (note) byId.set(note.id, note as unknown as Note);
        }
    }
    return ids.map((id) => byId.get(id)).filter((note): note is Note => !!note);
}

export async function ensureNoteBodyLoaded(id: string): Promise<Note | undefined> {
    const cached = await db.notes.get(id);
    if (cached?.hasBody) {
        return cached as Note;
    }

    const note = await getNote(id);
    if (!note) {
        return undefined;
    }

    await db.notes.put({ ...note, hasBody: true } as any);
    return note;
}

export async function trimNoteBody(id: string): Promise<void> {
    const note = await db.notes.get(id);
    if (!note?.hasBody || note.entityKind === 'EVENT') {
        return;
    }
    await db.notes.update(id, {
        content: '',
        markdownContent: '',
        hasBody: false,
    } as any);
}

function storeNoteToNote(sn: StoreNote): Note {
    return {
        id: sn.id,
        worldId: sn.worldId,
        title: sn.title,
        content: sn.content,
        markdownContent: sn.markdownContent,
        folderId: sn.folderId,
        entityKind: sn.entityKind,
        entitySubtype: sn.entitySubtype,
        isEntity: sn.isEntity,
        isPinned: sn.isPinned,
        favorite: sn.favorite,
        ownerId: sn.ownerId,
        createdAt: sn.createdAt,
        updatedAt: sn.updatedAt,
        version: sn.version,
        narrativeId: sn.narrativeId,
        order: sn.order,
        hasBody: true,
    };
}

function storeNoteHeaderToNote(sn: StoreNoteHeader): Note {
    return {
        id: sn.id,
        worldId: sn.worldId,
        title: sn.title,
        content: '',
        markdownContent: '',
        folderId: sn.folderId,
        entityKind: sn.entityKind,
        entitySubtype: sn.entitySubtype,
        isEntity: sn.isEntity,
        isPinned: sn.isPinned,
        favorite: sn.favorite,
        ownerId: sn.ownerId,
        createdAt: sn.createdAt,
        updatedAt: sn.updatedAt,
        version: sn.version,
        narrativeId: sn.narrativeId,
        order: sn.order,
        hasBody: false,
    };
}

// =============================================================================
// FOLDER OPERATIONS
// =============================================================================

export async function createFolder(folder: Omit<Folder, 'id' | 'createdAt' | 'updatedAt' | 'order'>): Promise<string> {
    const store = await waitForStore();
    const id = crypto.randomUUID();
    const now = Date.now();
    const order = await getNextFolderOrder(folder.parentId);

    const fullFolder: Folder = {
        ...folder,
        id,
        order,
        createdAt: now,
        updatedAt: now,
    } as Folder;

    await store.upsertFolder(PhoenixStoreService.fromDexieFolder(fullFolder));
    warmDexieFolder(fullFolder);
    scheduleGlobalContextRefreshFor(fullFolder);
    return id;
}

export async function updateFolder(id: string, updates: Partial<Folder>): Promise<void> {
    const store = await waitForStore();
    const existing = await store.getFolder(id);
    if (!existing) {
        console.warn(`[Operations] Folder ${id} not found`);
        return;
    }

    const merged = { ...existing, ...updates, updatedAt: Date.now() };
    await store.upsertFolder(merged as StoreFolder);
    warmDexieFolder(storeFolderToFolder(merged as StoreFolder));
    scheduleGlobalContextRefreshFor(storeFolderToFolder(merged as StoreFolder));
    schedulePriorGlobalContextRefresh(existing);
}

export async function deleteFolder(id: string): Promise<void> {
    const store = await waitForStore();
    const existing = await store.getFolder(id);
    await store.deleteFolder(id);
    db.folders.delete(id).catch(() => { });
    schedulePriorGlobalContextRefresh(existing || undefined);
}

export async function getFolder(id: string): Promise<Folder | undefined> {
    const store = getBridge();
    if (!store) return undefined;
    const folder = await store.getFolder(id);
    return folder ? storeFolderToFolder(folder) : undefined;
}

export async function getAllFolders(): Promise<Folder[]> {
    const store = getBridge();
    if (!store) return [];
    const folders = await store.listFolders();
    return folders.map(storeFolderToFolder);
}

export async function getFolderChildren(parentId: string): Promise<Folder[]> {
    const store = getBridge();
    if (!store) return [];
    const allFolders = await store.listFolders();
    return allFolders
        .filter(f => f.parentId === parentId)
        .map(storeFolderToFolder);
}

function storeFolderToFolder(sf: StoreFolder): Folder {
    let attributes: Record<string, any> | undefined;
    if (sf.attributes) {
        try { attributes = typeof sf.attributes === 'string' ? JSON.parse(sf.attributes) : sf.attributes; } catch { /* ignore */ }
    }
    return {
        id: sf.id,
        worldId: sf.worldId,
        name: sf.name,
        parentId: sf.parentId || '',
        entityKind: sf.entityKind || '',
        entitySubtype: sf.entitySubtype || '',
        entityLabel: sf.entityLabel || '',
        color: sf.color || '',
        isTypedRoot: sf.isTypedRoot || false,
        isSubtypeRoot: sf.isSubtypeRoot || false,
        collapsed: sf.collapsed || false,
        ownerId: sf.ownerId || '',
        createdAt: sf.createdAt,
        updatedAt: sf.updatedAt,
        narrativeId: sf.narrativeId || '',
        isNarrativeRoot: sf.isNarrativeRoot || false,
        networkId: undefined,
        metadata: undefined,
        attributes,
        order: sf.folderOrder,
    };
}

// =============================================================================
// ENTITY OPERATIONS
// =============================================================================

export async function upsertEntity(entity: Entity): Promise<void> {
    const store = getBridge();
    if (!store) {
        console.warn('[Operations] Store not ready for entity upsert');
        return;
    }
    await store.upsertEntity(PhoenixStoreService.fromDexieEntity(entity));
    warmDexieEntity(entity);
}

export async function deleteEntity(id: string): Promise<void> {
    const store = getBridge();
    if (!store) return;
    await store.deleteEntity(id);
    db.entities.delete(id).catch(() => { });
}

export async function getEntity(id: string): Promise<Entity | undefined> {
    const store = getBridge();
    if (!store) return undefined;
    const entity = await store.getEntity(id);
    return entity ? storeEntityToEntity(entity) : undefined;
}

export async function getAllEntities(): Promise<Entity[]> {
    const store = getBridge();
    if (!store) return [];
    const entities = await store.listEntities();
    return entities.map(storeEntityToEntity);
}

export async function getEntitiesByKind(kind: string): Promise<Entity[]> {
    const store = getBridge();
    if (!store) return [];
    const entities = await store.listEntities();
    return entities.filter(e => e.kind === kind).map(storeEntityToEntity);
}

export async function getEntitiesByNarrative(narrativeId: string): Promise<Entity[]> {
    const store = getBridge();
    if (!store) return [];
    const entities = await store.listEntities();
    return entities.filter(e => e.narrativeId === narrativeId).map(storeEntityToEntity);
}

function storeEntityToEntity(se: StoreEntity): Entity {
    return {
        id: se.id,
        label: se.label,
        kind: se.kind,
        subtype: se.subtype,
        aliases: se.aliases || [],
        firstNote: se.firstNote,
        totalMentions: se.totalMentions,
        createdAt: se.createdAt,
        updatedAt: se.updatedAt,
        createdBy: se.createdBy as 'user' | 'extraction' | 'auto',
        narrativeId: se.narrativeId,
    };
}

// =============================================================================
// ORDERING HELPERS
// =============================================================================

const DEFAULT_ORDER_STEP = 1000;
const MIN_ORDER_GAP = 10;

export async function getNextNoteOrder(folderId: string): Promise<number> {
    const notes = await getNotesByFolder(folderId);
    if (notes.length === 0) return DEFAULT_ORDER_STEP;
    const maxOrder = Math.max(...notes.map(n => n.order || 0), 0);
    return maxOrder + DEFAULT_ORDER_STEP;
}

export async function getNextFolderOrder(parentId: string): Promise<number> {
    const folders = await getFolderChildren(parentId);
    if (folders.length === 0) return DEFAULT_ORDER_STEP;
    const maxOrder = Math.max(...folders.map(f => f.order || 0), 0);
    return maxOrder + DEFAULT_ORDER_STEP;
}

// =============================================================================
// REORDER OPERATIONS
// =============================================================================

function calculateNewOrder(prevOrder: number, nextOrder: number): number {
    if (prevOrder === 0 && nextOrder === 0) return DEFAULT_ORDER_STEP;
    if (nextOrder === 0) return prevOrder + DEFAULT_ORDER_STEP;
    return (prevOrder + nextOrder) / 2;
}

function needsRebalancing(orders: number[]): boolean {
    for (let i = 1; i < orders.length; i++) {
        if (orders[i] - orders[i - 1] < MIN_ORDER_GAP) return true;
    }
    return false;
}

async function rebalanceNoteOrders(folderId: string): Promise<void> {
    const store = getBridge();
    if (!store) return;
    const notes = await getNotesByFolder(folderId);
    notes.sort((a, b) => a.order - b.order);
    for (let i = 0; i < notes.length; i++) {
        const existing = await store.getNote(notes[i].id);
        if (!existing) {
            continue;
        }
        const updated = { ...existing, order: (i + 1) * DEFAULT_ORDER_STEP };
        await store.upsertNote(updated);
        warmDexieNote({
            ...storeNoteToNote(updated),
            hasBody: notes[i].hasBody || false,
            content: notes[i].hasBody ? updated.content : '',
            markdownContent: notes[i].hasBody ? updated.markdownContent : '',
        });
    }
    console.log(`[Operations] Rebalanced ${notes.length} note orders in folder ${folderId || 'root'}`);
}

async function rebalanceFolderOrders(parentId: string): Promise<void> {
    const store = getBridge();
    if (!store) return;
    const folders = await getFolderChildren(parentId);
    folders.sort((a, b) => a.order - b.order);
    for (let i = 0; i < folders.length; i++) {
        const updated = { ...folders[i], order: (i + 1) * DEFAULT_ORDER_STEP };
        await store.upsertFolder(PhoenixStoreService.fromDexieFolder(updated));
    }
    console.log(`[Operations] Rebalanced ${folders.length} folder orders in parent ${parentId || 'root'}`);
}

export async function reorderNote(noteId: string, targetIndex: number): Promise<void> {
    const store = await waitForStore();
    const note = await store.getNote(noteId);
    if (!note) throw new Error(`Note ${noteId} not found`);

    const siblings = await getNotesByFolder(note.folderId);
    siblings.sort((a, b) => a.order - b.order);
    const filteredSiblings = siblings.filter(n => n.id !== noteId);

    const prevOrder = filteredSiblings[targetIndex - 1]?.order ?? 0;
    const nextOrder = filteredSiblings[targetIndex]?.order ?? 0;
    const newOrder = calculateNewOrder(prevOrder, nextOrder);

    const updatedNote = { ...note, order: newOrder, updatedAt: Date.now() } as StoreNote;

    await store.upsertNote(updatedNote);
    warmDexieNote(storeNoteToNote(updatedNote));

    const allOrders = [...filteredSiblings.map(n => n.order), newOrder].sort((a, b) => a - b);
    if (needsRebalancing(allOrders)) {
        await rebalanceNoteOrders(note.folderId);
    }
    console.log(`[Operations] Reordered note ${noteId} to position ${targetIndex}`);
}

export async function reorderFolder(folderId: string, targetIndex: number): Promise<void> {
    const folder = await getFolder(folderId);
    if (!folder) throw new Error(`Folder ${folderId} not found`);

    const store = requireStore();
    const siblings = await getFolderChildren(folder.parentId);
    siblings.sort((a, b) => a.order - b.order);
    const filteredSiblings = siblings.filter(f => f.id !== folderId);

    const prevOrder = filteredSiblings[targetIndex - 1]?.order ?? 0;
    const nextOrder = filteredSiblings[targetIndex]?.order ?? 0;
    const newOrder = calculateNewOrder(prevOrder, nextOrder);

    const updatedFolder = { ...folder, order: newOrder, updatedAt: Date.now() };

    await store.upsertFolder(PhoenixStoreService.fromDexieFolder(updatedFolder));
    warmDexieFolder(updatedFolder);

    const allOrders = [...filteredSiblings.map(f => f.order), newOrder].sort((a, b) => a - b);
    if (needsRebalancing(allOrders)) {
        await rebalanceFolderOrders(folder.parentId);
    }
    console.log(`[Operations] Reordered folder ${folderId} to position ${targetIndex}`);
}

export async function moveNoteToFolder(noteId: string, targetFolderId: string, targetIndex: number): Promise<void> {
    const store = await waitForStore();
    const note = await store.getNote(noteId);
    if (!note) throw new Error(`Note ${noteId} not found`);

    const sourceFolderId = note.folderId || '';
    const targetFolder = targetFolderId ? await getFolder(targetFolderId) : undefined;
    const targetNarrativeId = targetFolderId
        ? (targetFolder?.narrativeId || (targetFolder?.isNarrativeRoot ? targetFolder.id : ''))
        : '';

    const siblings = await getNotesByFolder(targetFolderId);
    siblings.sort((a, b) => a.order - b.order);

    const prevOrder = siblings[targetIndex - 1]?.order ?? 0;
    const nextOrder = siblings[targetIndex]?.order ?? 0;
    const newOrder = calculateNewOrder(prevOrder, nextOrder);
    const movedNote = {
        ...note,
        folderId: targetFolderId,
        narrativeId: targetNarrativeId,
        order: newOrder,
        updatedAt: Date.now()
    } as StoreNote;

    await store.upsertNote(movedNote);
    warmDexieNote(storeNoteToNote(movedNote));
    await refreshNoteStructureProjection(storeNoteToNote(movedNote));
    schedulePriorGlobalContextRefresh(note);

    const allOrders = [...siblings.map(n => n.order), newOrder].sort((a, b) => a - b);
    if (needsRebalancing(allOrders)) {
        await rebalanceNoteOrders(targetFolderId);
    }
    if (sourceFolderId !== targetFolderId) {
        await rebalanceNoteOrders(sourceFolderId);
    }
    console.log(`[Operations] Moved note ${noteId} to folder ${targetFolderId || 'root'} with narrative ${targetNarrativeId || 'global'}`);
}

async function refreshNoteStructureProjection(note: Note): Promise<void> {
    try {
        await replaceNoteStructureProjection(note);
        scheduleGlobalContextRefreshFor(note);
    } catch (error) {
        console.warn('[Operations] Note structure projection failed:', error);
    }
}

async function clearNoteStructureProjection(noteId: string): Promise<void> {
    try {
        await deleteNoteStructureProjection(noteId);
    } catch (error) {
        console.warn('[Operations] Note structure projection cleanup failed:', error);
    }
}

function scheduleGlobalContextRefreshFor(scope: { worldId?: string; narrativeId?: string | null }): void {
    if (isGlobalContextScope(scope)) {
        scheduleGlobalContextIslandRefresh(scope.worldId || '');
    }
}

function schedulePriorGlobalContextRefresh(scope?: { worldId?: string; narrativeId?: string | null }): void {
    if (scope && isGlobalContextScope(scope)) {
        scheduleGlobalContextIslandRefresh(scope.worldId || '');
    }
}

export async function moveFolderToParent(folderId: string, targetParentId: string, targetIndex: number): Promise<void> {
    const folder = await getFolder(folderId);
    if (!folder) throw new Error(`Folder ${folderId} not found`);

    const sourceParentId = folder.parentId || '';
    const store = await waitForStore();
    const siblings = await getFolderChildren(targetParentId);
    siblings.sort((a, b) => a.order - b.order);

    const prevOrder = siblings[targetIndex - 1]?.order ?? 0;
    const nextOrder = siblings[targetIndex]?.order ?? 0;
    const newOrder = calculateNewOrder(prevOrder, nextOrder);
    const movedFolder = {
        ...folder,
        parentId: targetParentId,
        order: newOrder,
        updatedAt: Date.now()
    };

    await store.upsertFolder(PhoenixStoreService.fromDexieFolder(movedFolder));
    warmDexieFolder(movedFolder);
    scheduleGlobalContextRefreshFor(movedFolder);
    schedulePriorGlobalContextRefresh(folder);

    const allOrders = [...siblings.map(f => f.order), newOrder].sort((a, b) => a - b);
    if (needsRebalancing(allOrders)) {
        await rebalanceFolderOrders(targetParentId);
    }
    if (sourceParentId !== targetParentId) {
        await rebalanceFolderOrders(sourceParentId);
    }
    console.log(`[Operations] Moved folder ${folderId} to parent ${targetParentId}`);
}

export async function swapItems(sourceId: string, targetId: string, type: 'folder' | 'note'): Promise<void> {
    const store = await waitForStore();

    if (type === 'folder') {
        const source = await getFolder(sourceId);
        const target = await getFolder(targetId);
        if (!source || !target) throw new Error('Folder not found');

        const updatedSource = { ...source, order: target.order, updatedAt: Date.now() };
        const updatedTarget = { ...target, order: source.order, updatedAt: Date.now() };
        await store.upsertFolder(PhoenixStoreService.fromDexieFolder(updatedSource));
        await store.upsertFolder(PhoenixStoreService.fromDexieFolder(updatedTarget));
        warmDexieFolder(updatedSource);
        warmDexieFolder(updatedTarget);
    } else {
        const source = await store.getNote(sourceId);
        const target = await store.getNote(targetId);
        if (!source || !target) throw new Error('Note not found');

        const updatedSource = { ...source, order: target.order, updatedAt: Date.now() } as StoreNote;
        const updatedTarget = { ...target, order: source.order, updatedAt: Date.now() } as StoreNote;
        await store.upsertNote(updatedSource);
        await store.upsertNote(updatedTarget);
        warmDexieNote(storeNoteToNote(updatedSource));
        warmDexieNote(storeNoteToNote(updatedTarget));
    }

    console.log(`[Operations] Swapped ${type}s: ${sourceId} <-> ${targetId}`);
}


