import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { MainLayoutComponent } from './components/layout/main-layout/main-layout.component';
import { NgxSpinnerModule, NgxSpinnerService } from 'ngx-spinner';
import { Subscription } from 'rxjs';

import { smartGraphRegistry } from './lib/registry';
import { entityColorStore } from './lib/store/entityColorStore';
import { highlightingStore } from './lib/store/highlightingStore';
import { seedDefaultSchemas } from './lib/folders/seed';
import { setDiscoveryStore, setPhoenixUiApi } from './api/pretty-text-api';
import { AppOrchestrator, setAppOrchestrator } from './lib/core/app-orchestrator';
import { KnowledgeService } from './services/knowledge.service';
import { getNavigationApi } from './api/navigation-api';
import { NotesService } from './lib/dexie/notes.service';
import { NoteEditorStore } from './lib/store/note-editor.store';
import { cachedEditorBodyMatchesAuthoritativeHeader } from './lib/store/note-editor-session';
import { DiscoveryStore } from './lib/store/discoveryStore';
import { setPhoenixStoreBridge } from './lib/operations';
import * as ops from './lib/operations';
import { db, type Entity as DexieEntity } from './lib/dexie/db';
import { loadSettings } from './lib/dexie/settings.service';
import { PhoenixUiApiService } from './services/phoenix-ui-api.service';
import { PhoenixStoreService, type StoreBootSnapshot } from './services/phoenix-store.service';
import { detectPhoenixRuntimeTarget } from './services/phoenix-backend.service';
import { phoenixTransportAudit } from './services/phoenix-transport-audit';
import {
  PhoenixWasmMismatchError,
  isPhoenixWasmMismatchError,
} from './lib/phoenix/phoenix-runtime-compat';

interface FatalBootErrorState {
  title: string;
  message: string;
  steps: string[];
  detail?: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, MainLayoutComponent, NgxSpinnerModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'angular-notes';
  private spinner = inject(NgxSpinnerService);
  private phoenixUiApi = inject(PhoenixUiApiService);
  private phoenixStore = inject(PhoenixStoreService);
  private orchestrator = inject(AppOrchestrator);
  private notesService = inject(NotesService);
  private noteEditorStore = inject(NoteEditorStore);
  private knowledgeService = inject(KnowledgeService);
  private discoveryStore = inject(DiscoveryStore);

  // Navigation API subscriptions
  private notesSub: Subscription | null = null;
  private navUnsubscribe: (() => void) | null = null;
  private bootStep = 'boot:start';
  private bootWatchdog: ReturnType<typeof setInterval> | null = null;
  private shellRevealed = false;
  fatalBootError: FatalBootErrorState | null = null;

  async ngOnInit() {
    // Phase 0: Shell - spinner visible
    this.spinner.show();
    this.startBootWatchdog();
    phoenixTransportAudit.reset();

    // Export orchestrator for non-DI contexts
    setAppOrchestrator(this.orchestrator);

    // Wire up Phoenix to PrettyText API
    setPhoenixUiApi(this.phoenixUiApi);
    setDiscoveryStore(this.discoveryStore);

    // Initialize entity color CSS variables (sync, no deps)
    entityColorStore.initialize();

    // Wire up Navigation API
    this.wireUpNavigationApi();

    console.log('[AppComponent] Starting orchestrated boot...');

    try {
      const nativePhoenixRuntime = detectPhoenixRuntimeTarget() === 'native';
      if (nativePhoenixRuntime) {
        setPhoenixStoreBridge(this.phoenixStore);
      }

      this.setBootStep('critical-path:start');
      const settingsPromise = phoenixTransportAudit.measureBootPhase('settings.load', async () => {
        await loadSettings();
        highlightingStore.reloadFromStorage();
      });
      const seedPromise = phoenixTransportAudit.measureBootPhase('seed.schemas', () => seedDefaultSchemas());
      const runtimeLoadPromise = nativePhoenixRuntime
        ? phoenixTransportAudit.measureBootPhase('phoenix.runtime', () => this.phoenixUiApi.loadRuntime())
        : null;

      await settingsPromise;
      this.setBootStep('settings:complete');
      const hasStoredActiveNote = await this.noteEditorStore.hasStoredActiveNoteIntent();
      const cachedActiveNoteRevealed = hasStoredActiveNote
        ? await this.noteEditorStore.restoreCachedActiveNote()
        : false;
      this.shellRevealed = true;
      this.spinner.hide();
      this.setBootStep(cachedActiveNoteRevealed
        ? 'shell:cached-active-note:interactive'
        : 'shell:cached:interactive');
      console.log(cachedActiveNoteRevealed
        ? '[AppComponent] Cached active note revealed before native hydration.'
        : '[AppComponent] Cached shell revealed before native hydration.');

      this.setBootStep('seed:start');
      if (!runtimeLoadPromise) {
        console.info('[AppComponent] Phoenix native runtime unavailable in web mode; using Dexie/UI-only boot.');
      }

      await seedPromise;
      console.log('[AppComponent] Seed complete');
      this.setBootStep('seed:complete');

      if (runtimeLoadPromise) {
        this.setBootStep('phoenix:runtime:await');
        await runtimeLoadPromise;
        console.log(`[AppComponent] Phoenix runtime loaded (${this.phoenixUiApi.runtimeTarget})`);
      }
      this.orchestrator.completePhase('runtime_load');
      this.setBootStep(runtimeLoadPromise ? 'phoenix:runtime:complete' : 'phoenix:runtime:skipped:web:complete');

      if (nativePhoenixRuntime) {
        this.setBootStep('dexie:hydrate:start');
        try {
          await phoenixTransportAudit.measureBootPhase('dexie.hydrate', () => this.hydrateDexieFromPhoenix());
        } catch (error) {
          console.error('[AppComponent] Dexie hydration failed; continuing with existing Dexie cache.', error);
        }
        this.setBootStep('dexie:hydrate:complete');
        console.log('[AppComponent] Dexie hydrated from Phoenix backend');
      } else {
        this.setBootStep('dexie:hydrate:skipped:web');
      }

      this.setBootStep('registry+editor:start');
      await phoenixTransportAudit.measureBootPhase('registry.editor', async () => {
        await Promise.all([
          this.noteEditorStore.restoreActiveNote().then(() => {
            console.log('[AppComponent] Active note restored');
          }),
          smartGraphRegistry.init().then(() => {
            console.log('[AppComponent] SmartGraphRegistry hydrated');
          })
        ]);
      });
      this.orchestrator.completePhase('registry');
      this.setBootStep('registry+editor:complete');

      this.orchestrator.completePhase('runtime_hydrate');

      this.orchestrator.completePhase('ready');
      this.setBootStep('boot:ready');
      phoenixTransportAudit.printSummary('boot ready');

      this.setBootStep('background:start');
      const dictionaryPromise = nativePhoenixRuntime
        ? smartGraphRegistry.rebuildDictionaryNow()
        : Promise.resolve();
      const nativeMaintenancePromise = nativePhoenixRuntime
        ? (async () => {
            try {
              await this.phoenixStore.checkpointContentIfNeeded();
              const report = await this.phoenixStore.flushNativeStore();
              if (report) {
                console.log(
                  `[AppComponent] Native store maintenance: WAL ${report.walBytesBefore} -> ${report.walBytesAfter} bytes, segments=${report.segmentCount}`,
                );
              }
            } catch (error) {
              console.warn('[AppComponent] Native store maintenance deferred:', error);
            }
          })()
        : Promise.resolve();

      void Promise.all([dictionaryPromise, nativeMaintenancePromise]).then(() => {
        this.orchestrator.completePhase('background');
        this.setBootStep('background:complete');
      });
    } catch (err) {
      console.error('[AppComponent] Boot failed:', err);
      if (isPhoenixWasmMismatchError(err)) {
        this.fatalBootError = this.toFatalBootErrorState(err);
        this.setBootStep('boot:failed:phoenix-runtime-mismatch');
      } else {
        this.setBootStep('boot:failed');
      }
    } finally {
      this.stopBootWatchdog();
      if (!this.shellRevealed) {
        await new Promise(resolve => setTimeout(resolve, 300));
        this.spinner.hide();
      }
    }
  }

  /**
   * One-way hydration: Phoenix backend -> Dexie, with local repair guards.
   * User-curated rows may be newer than Phoenix if the app was closed before
   * an async write finished, so those rows are kept and written back.
   */
  private async hydrateDexieFromPhoenix(): Promise<void> {
    console.log('[AppComponent] Hydrating Dexie from Phoenix backend...');
    const start = Date.now();

    // Pause snapshots during hydration to prevent pointless OPFS writes
    this.phoenixStore.pauseSnapshots();

    try {
      const snapshot = await phoenixTransportAudit.measureBootPhase(
        'dexie.snapshotFetch',
        () => this.phoenixStore.getBootSnapshot(),
      );
      const [localEntities, localNotes] = await Promise.all([
        db.entities.toArray(),
        db.notes.toArray(),
      ]);
      const phoenixEntities = snapshot.entities.map(e => this.toEntity(e));
      const {
        entities: mergedEntities,
        repairs: entityRepairs,
      } = this.mergeHydratedEntities(phoenixEntities, localEntities);
      const eventNoteMap = new Map(snapshot.eventNotes.map(note => [note.id, note] as const));
      const localNoteMap = new Map(localNotes.map(note => [note.id, note] as const));
      const localNoteCount = localNotes.length;
      const preserveLocalContent =
        this.phoenixUiApi.runtimeTarget === 'native' &&
        snapshot.noteHeaders.length === 0 &&
        localNoteCount > 0;

      await phoenixTransportAudit.measureBootPhase('dexie.snapshotApply', async () => {
        await db.transaction('rw', db.notes, db.entities, db.edges, db.folders, async () => {
          const clears: Promise<unknown>[] = [db.entities.clear()];
          if (!preserveLocalContent) {
            clears.push(db.notes.clear(), db.edges.clear(), db.folders.clear());
          }
          await Promise.all(clears);

          if (!preserveLocalContent && snapshot.noteHeaders.length > 0) {
            await db.notes.bulkPut(snapshot.noteHeaders.map((note) => {
              const authoritativeBody = eventNoteMap.get(note.id);
              const cachedBody = localNoteMap.get(note.id);
              const reusableBody = authoritativeBody ?? (
                cachedEditorBodyMatchesAuthoritativeHeader(note, cachedBody)
                  ? cachedBody
                  : undefined
              );
              return this.toNote(note, reusableBody);
            }));
          }
          if (mergedEntities.length > 0) await db.entities.bulkPut(mergedEntities);
          if (!preserveLocalContent && snapshot.edges.length > 0) await db.edges.bulkPut(snapshot.edges.map(e => this.toEdge(e)));
          if (!preserveLocalContent && snapshot.folders.length > 0) await db.folders.bulkPut(snapshot.folders.map(f => this.toFolder(f)));
        });
      });
      if (preserveLocalContent) {
        console.warn(
          `[AppComponent] Native boot snapshot had 0 notes; preserved ${localNoteCount} local Dexie notes.`,
        );
      }

      await phoenixTransportAudit.measureBootPhase(
        'dexie.entityRepair',
        () => this.repairPhoenixEntities(entityRepairs),
      );

      this.logDexieBootSnapshot(Date.now() - start, snapshot);
    } finally {
      this.phoenixStore.resumeSnapshots();
    }
  }

  private logDexieBootSnapshot(durationMs: number, snapshot: StoreBootSnapshot): void {
    console.log(
      `[AppComponent] Dexie hydrated in ${durationMs}ms: ${snapshot.noteHeaders.length} notes, ${snapshot.folders.length} folders, ${snapshot.entities.length} entities, ${snapshot.edges.length} edges`,
    );
  }

  // =========================================================================
  // Mappers (Store -> Dexie)
  // =========================================================================

  private toNote(n: any, fullNote?: any): any {
    return {
      id: n.id, worldId: n.worldId, title: n.title, content: fullNote?.content || '',
      markdownContent: fullNote?.markdownContent || '', folderId: n.folderId,
      entityKind: n.entityKind, entitySubtype: n.entitySubtype,
      isEntity: n.isEntity, isPinned: n.isPinned, favorite: n.favorite,
      ownerId: n.ownerId, narrativeId: n.narrativeId, order: n.order,
      createdAt: n.createdAt, updatedAt: n.updatedAt, version: n.version ?? fullNote?.version,
      hasBody: !!fullNote,
    };
  }

  private toEntity(e: any): any {
    return {
      id: e.id, label: e.label, kind: e.kind, subtype: e.subtype,
      aliases: e.aliases, firstNote: e.firstNote, totalMentions: e.totalMentions,
      narrativeId: e.narrativeId, createdBy: e.createdBy,
      createdAt: e.createdAt, updatedAt: e.updatedAt
    };
  }

  private mergeHydratedEntities(
    phoenixEntities: DexieEntity[],
    localEntities: DexieEntity[],
  ): { entities: DexieEntity[]; repairs: DexieEntity[] } {
    if (localEntities.length === 0) {
      return { entities: phoenixEntities, repairs: [] };
    }

    const localById = new Map(localEntities.map(entity => [entity.id, entity] as const));
    const seenPhoenixIds = new Set<string>();
    const repairs: DexieEntity[] = [];
    const merged = phoenixEntities.map(entity => {
      seenPhoenixIds.add(entity.id);
      const local = localById.get(entity.id);
      if (!local || !this.shouldKeepLocalEntity(local, entity)) {
        return entity;
      }
      repairs.push(local);
      return local;
    });

    for (const local of localEntities) {
      if (!seenPhoenixIds.has(local.id)) {
        repairs.push(local);
        merged.push(local);
      }
    }

    return { entities: merged, repairs };
  }

  private shouldKeepLocalEntity(local: DexieEntity, phoenix: DexieEntity): boolean {
    const localUpdatedAt = Number(local.updatedAt || 0);
    const phoenixUpdatedAt = Number(phoenix.updatedAt || 0);
    if (localUpdatedAt > phoenixUpdatedAt) {
      return true;
    }

    return this.isStrongEntityKind(local.kind)
      && this.isWeakEntityKind(phoenix.kind)
      && local.createdBy === 'user';
  }

  private isWeakEntityKind(kind: string | undefined): boolean {
    const normalized = String(kind || '').toUpperCase();
    return normalized === 'OTHER' || normalized === 'UNKNOWN' || normalized === '';
  }

  private isStrongEntityKind(kind: string | undefined): boolean {
    return !this.isWeakEntityKind(kind);
  }

  private async repairPhoenixEntities(entities: DexieEntity[]): Promise<void> {
    if (entities.length === 0) return;

    await Promise.all(entities.map(async entity => {
      try {
        await this.phoenixStore.upsertEntity(PhoenixStoreService.fromDexieEntity(entity));
      } catch (err) {
        console.warn('[AppComponent] Failed to repair Phoenix entity during boot:', entity.id, err);
      }
    }));
  }

  private toFolder(f: any): any {
    let attributes: Record<string, any> | undefined;
    if (f.attributes) {
      try { attributes = typeof f.attributes === 'string' ? JSON.parse(f.attributes) : f.attributes; } catch { attributes = undefined; }
    }
    return {
      id: f.id, name: f.name, parentId: f.parentId || '', worldId: f.worldId,
      narrativeId: f.narrativeId || '', order: f.folderOrder,
      createdAt: f.createdAt, updatedAt: f.updatedAt,
      entityKind: f.entityKind || '', entitySubtype: f.entitySubtype || '',
      entityLabel: f.entityLabel || '', color: f.color || '',
      isTypedRoot: f.isTypedRoot || false, isSubtypeRoot: f.isSubtypeRoot || false,
      collapsed: f.collapsed || false, ownerId: f.ownerId || '',
      isNarrativeRoot: f.isNarrativeRoot || false, attributes
    };
  }

  private toEdge(e: any): any {
    return {
      id: e.id, sourceId: e.sourceId, targetId: e.targetId,
      relType: e.relType, confidence: e.confidence,
      bidirectional: e.bidirectional,
    };
  }

  ngOnDestroy(): void {
    if (this.notesSub) this.notesSub.unsubscribe();
    if (this.navUnsubscribe) this.navUnsubscribe();
    this.stopBootWatchdog();
  }

  private setBootStep(step: string): void {
    this.bootStep = step;
    console.log(`[AppComponent] Boot step -> ${step}`);
  }

  private startBootWatchdog(): void {
    this.stopBootWatchdog();
    const startedAt = Date.now();
    this.bootWatchdog = setInterval(() => {
      console.warn(
        `[AppComponent] Boot watchdog: still waiting at '${this.bootStep}' after ${Date.now() - startedAt}ms`,
      );
    }, 5000);
  }

  private stopBootWatchdog(): void {
    if (this.bootWatchdog) {
      clearInterval(this.bootWatchdog);
      this.bootWatchdog = null;
    }
  }

  private toFatalBootErrorState(error: PhoenixWasmMismatchError): FatalBootErrorState {
    return {
      title: 'Phoenix Runtime Is Out Of Date',
      message: 'KittClouds stopped booting because the Phoenix runtime does not match the current app code.',
      steps: error.repairSteps,
      detail: error.detail,
    };
  }

  /**
   * Wire up Navigation API for cross-note navigation from entity clicks.
   */
  private wireUpNavigationApi(): void {
    const navigationApi = getNavigationApi();
    this.notesSub = this.notesService.getAllNotes$().subscribe(notes => {
      navigationApi.setNotes(notes as any);
      console.log(`[AppComponent] NavigationApi synced with ${notes.length} notes`);
    });
    this.navUnsubscribe = navigationApi.onNavigate((noteId) => {
      console.log('[AppComponent] Navigation handler triggered:', noteId);
      this.noteEditorStore.openNote(noteId);
    });
    console.log('[AppComponent] Navigation API wired up');
  }
}
