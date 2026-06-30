// src/app/components/sidebar/sidebar.component.ts
// Sidebar with file tree and action buttons - wired to Dexie and document ingestion.

import { Component, inject, signal, computed, effect, OnInit, OnDestroy, HostListener } from '@angular/core';
import { Router, NavigationEnd } from '@angular/router';
import { CommonModule } from '@angular/common';
import { DialogModule } from 'primeng/dialog';
import { NgxGradientTextComponent } from '@omnedia/ngx-gradient-text';
import { LucideAngularModule, Plus, FolderPlus, BookOpen, Users, MapPin, Package, Lightbulb, Calendar, Clock, GitBranch, Layers, BookMarked, Film, Zap, Shield, User, Folder, PanelLeft, PanelLeftClose, FileText, Search, Undo, Redo, Sun, Moon, MoveVertical, RefreshCw, Upload, Download, MessageCircle, History } from 'lucide-angular';
import { Subscription } from 'rxjs';
import { filter } from 'rxjs/operators';
import { SidebarService } from '../../lib/services/sidebar.service';
import { FolderService } from '../../lib/services/folder.service';
import { NotesService } from '../../lib/dexie/notes.service';
import { NoteEditorStore } from '../../lib/store/note-editor.store';
import { ThemeService } from '../../lib/services/theme.service';
import { EditorService } from '../../services/editor.service';
import { ReorderService } from '../../lib/services/reorder.service';
import { PhoenixUiApiService } from '../../services/phoenix-ui-api.service';
import { FileTreeComponent } from './file-tree/file-tree.component';
import { SearchPanelComponent } from '../search-panel/search-panel.component';
import { DocumentIngestionService, DocumentIngestionMode, DocumentIngestionResult } from '../../lib/services/document-ingestion.service';
import { DocumentExportService } from '../../lib/services/document-export.service';
import type { TreeNode } from '../../lib/arborist/types';
import type { Folder as DexieFolder, Note } from '../../lib/dexie/db';
import { getSetting, setSetting } from '../../lib/dexie/settings.service';
import { PhoenixChatService } from '../../lib/services/phoenix-chat.service';
import { GraphPipelineService } from '../../services/graph-pipeline.service';

interface EntityFolderOption {
    entityKind: string;
    label: string;
    icon: any;
    color: string;
    gradientStart: string;
    gradientEnd: string;
}

interface FolderOption {
    id: string;
    name: string;
    label: string;
    entityKind: string;
    isNarrativeRoot: boolean;
}

interface CreateFolderOption {
    entityKind: string;
    label: string;
    description: string;
}

const ENTITY_FOLDER_OPTIONS: EntityFolderOption[] = [
    { entityKind: 'NARRATIVE', label: 'Narrative Timeline Folder', icon: BookOpen, color: 'hsl(270, 70%, 60%)', gradientStart: '#a855f7', gradientEnd: '#f472b6' },
    { entityKind: 'TIMELINE', label: 'General Timeline Folder', icon: Clock, color: 'hsl(180, 60%, 50%)', gradientStart: '#22d3ee', gradientEnd: '#2dd4bf' },
    { entityKind: 'ARC', label: 'Arc Folder', icon: GitBranch, color: 'hsl(280, 60%, 55%)', gradientStart: '#c084fc', gradientEnd: '#ec4899' },
    { entityKind: 'ACT', label: 'Act Folder', icon: Layers, color: 'hsl(220, 70%, 60%)', gradientStart: '#60a5fa', gradientEnd: '#818cf8' },
    { entityKind: 'CHAPTER', label: 'Chapter Folder', icon: BookMarked, color: 'hsl(30, 70%, 55%)', gradientStart: '#fb923c', gradientEnd: '#facc15' },
    { entityKind: 'EVENT', label: 'Event Folder', icon: Calendar, color: 'hsl(320, 70%, 60%)', gradientStart: '#f472b6', gradientEnd: '#fb7185' },
    { entityKind: 'CHARACTER', label: 'Character Folder', icon: Users, color: 'hsl(200, 80%, 60%)', gradientStart: '#38bdf8', gradientEnd: '#22d3ee' },
    { entityKind: 'LOCATION', label: 'Location Folder', icon: MapPin, color: 'hsl(140, 60%, 50%)', gradientStart: '#22c55e', gradientEnd: '#86efac' },
    { entityKind: 'NPC', label: 'NPC Folder', icon: User, color: 'hsl(190, 70%, 55%)', gradientStart: '#22d3ee', gradientEnd: '#67e8f9' },
    { entityKind: 'ITEM', label: 'Item Folder', icon: Package, color: 'hsl(40, 80%, 60%)', gradientStart: '#fbbf24', gradientEnd: '#fb923c' },
    { entityKind: 'CONCEPT', label: 'Concept Folder', icon: Lightbulb, color: 'hsl(60, 70%, 50%)', gradientStart: '#facc15', gradientEnd: '#bef264' },
];

const ROOT_CREATE_FOLDER_OPTIONS: CreateFolderOption[] = [
    { entityKind: '', label: 'Regular Folder', description: 'Create a plain root folder.' },
    ...ENTITY_FOLDER_OPTIONS.map(option => ({
        entityKind: option.entityKind,
        label: option.label,
        description: `Create a ${option.entityKind.toLowerCase()} root folder.`,
    })),
];

const SIDEBAR_SNAP_MS = 150;
const SIDEBAR_CONTENT_READY_MS = 32;

@Component({
    selector: 'app-sidebar',
    standalone: true,
    imports: [CommonModule, DialogModule, FileTreeComponent, LucideAngularModule, SearchPanelComponent, NgxGradientTextComponent],
    templateUrl: './sidebar.component.html',
    styleUrls: ['./sidebar.component.css']
})
export class SidebarComponent implements OnInit, OnDestroy {
    sidebarService = inject(SidebarService);
    themeService = inject(ThemeService);
    editorService = inject(EditorService);
    reorderService = inject(ReorderService);
    private folderService = inject(FolderService);
    private notesService = inject(NotesService);
    private noteEditorStore = inject(NoteEditorStore);
    private phoenixUiApi = inject(PhoenixUiApiService);
    private documentIngestionService = inject(DocumentIngestionService);
    private router = inject(Router);
    private graphPipeline = inject(GraphPipelineService);
    private documentExportService = inject(DocumentExportService);
    goChatService = inject(PhoenixChatService);

    isChatRoute = signal(false);

    private foldersSubscription?: Subscription;
    private notesSubscription?: Subscription;

    private static readonly VIEW_STORAGE_KEY = 'kittclouds_sidebar_view';
    viewMode = signal<'files' | 'search'>(this.loadSavedViewMode());

    readonly Plus = Plus;
    readonly Upload = Upload;
    readonly FolderPlus = FolderPlus;
    readonly BookOpen = BookOpen;
    readonly Folder = Folder;
    readonly PanelLeft = PanelLeft;
    readonly PanelLeftClose = PanelLeftClose;
    readonly FileText = FileText;
    readonly Calendar = Calendar;
    readonly Search = Search;
    readonly Undo = Undo;
    readonly Redo = Redo;
    readonly Sun = Sun;
    readonly Moon = Moon;
    readonly MoveVertical = MoveVertical;
    readonly RefreshCw = RefreshCw;
    readonly MessageCircle = MessageCircle;
    readonly HistoryIcon = History;
    readonly Download = Download;

    isScanning = signal(false);
    isExporting = signal(false);
    readonly entityFolderOptions = ENTITY_FOLDER_OPTIONS;
    folderDropdownOpen = signal(false);

    // Resize state for left sidebar
    sidebarWidth = getSetting<number>('kittclouds-left-sidebar-width', 240) || 240;
    isResizing = false;
    private startX = 0;
    private startWidth = 0;
    sidebarPanelVisible = signal(this.sidebarService.isOpen());
    sidebarContentReady = signal(this.sidebarService.isOpen());
    private sidebarCloseTimer: ReturnType<typeof setTimeout> | null = null;
    private sidebarContentTimer: ReturnType<typeof setTimeout> | null = null;

    private folders = signal<DexieFolder[]>([]);
    private notes = signal<Note[]>([]);

    treeData = computed<TreeNode[]>(() => this.buildTree(this.folders(), this.notes()));
    folderOptions = computed<FolderOption[]>(() => this.buildFolderOptions(this.folders()));
    selectedDestinationFolder = computed(() => this.folderOptions().find(folder => folder.id === this.importDestinationFolderId()) ?? null);
    activeExportNote = computed(() => this.noteEditorStore.currentNote());
    supportedImportFilesCount = computed(() => this.selectedImportFiles().filter(file => this.isTxtFile(file.name)).length);
    skippedImportFilesCount = computed(() => this.selectedImportFiles().length - this.supportedImportFilesCount());
    importPreviewFiles = computed(() => this.selectedImportFiles().slice(0, 6).map(file => this.getDisplayFileName(file)));
    canStartImport = computed(() => {
        return Boolean(this.importDestinationFolderId())
            && this.supportedImportFilesCount() > 0
            && !this.importInProgress();
    });

    collapsedNodes = computed<TreeNode[]>(() => {
        return this.treeData().filter(node => !node.parentId || node.parentId === '');
    });

    chatSessions = computed(() => {
        const threads = this.goChatService.threads();
        return threads.map(t => ({
            id: t.id,
            messageCount: 0,
            createdAt: t.created_at,
            preview: t.title || undefined,
        }));
    });

    importDialogOpen = signal(false);
    importMode = signal<DocumentIngestionMode>('files');
    selectedImportFiles = signal<File[]>([]);
    importInProgress = signal(false);
    importProgress = signal({ processed: 0, total: 0 });
    importResult = signal<DocumentIngestionResult | null>(null);
    importError = signal('');
    importDestinationFolderId = signal('');

    createFolderOpen = signal(false);
    createFolderName = signal('');
    createFolderEntityKind = signal('');
    createFolderOptions = signal<CreateFolderOption[]>(ROOT_CREATE_FOLDER_OPTIONS);
    createFolderError = signal('');
    createFolderInProgress = signal(false);

    constructor() {
        effect(() => {
            this.syncSidebarMotion(this.sidebarService.isOpen());
        });
    }

    private loadSavedViewMode(): 'files' | 'search' {
        const saved = getSetting<string | null>(SidebarComponent.VIEW_STORAGE_KEY, null);
        if (saved === 'files' || saved === 'search') return saved;
        return 'files';
    }

    setViewMode(mode: 'files' | 'search'): void {
        this.viewMode.set(mode);
        setSetting(SidebarComponent.VIEW_STORAGE_KEY, mode);
        this.sidebarService.open();
    }

    ngOnInit(): void {
        this.foldersSubscription = this.folderService.getAllFolders$().subscribe(folders => {
            this.folders.set(folders);
        });

        this.notesSubscription = this.notesService.getAllNotes$().subscribe(notes => {
            this.notes.set(notes);
        });

        this.router.events.pipe(
            filter(event => event instanceof NavigationEnd)
        ).subscribe((event: any) => {
            this.isChatRoute.set(event.urlAfterRedirects.includes('/chat'));
        });

        // Initial setup
        this.isChatRoute.set(this.router.url.includes('/chat'));
    }

    ngOnDestroy(): void {
        this.clearSidebarMotionTimers();
        this.foldersSubscription?.unsubscribe();
        this.notesSubscription?.unsubscribe();
    }

    private syncSidebarMotion(open: boolean): void {
        this.clearSidebarMotionTimers();
        if (open) {
            this.sidebarPanelVisible.set(true);
            this.sidebarContentTimer = setTimeout(() => {
                this.sidebarContentReady.set(true);
                this.sidebarContentTimer = null;
            }, SIDEBAR_CONTENT_READY_MS);
            return;
        }
        this.sidebarContentReady.set(false);
        this.sidebarCloseTimer = setTimeout(() => {
            this.sidebarPanelVisible.set(false);
            this.sidebarCloseTimer = null;
        }, SIDEBAR_SNAP_MS);
    }

    private clearSidebarMotionTimers(): void {
        if (this.sidebarCloseTimer) {
            clearTimeout(this.sidebarCloseTimer);
            this.sidebarCloseTimer = null;
        }
        if (this.sidebarContentTimer) {
            clearTimeout(this.sidebarContentTimer);
            this.sidebarContentTimer = null;
        }
    }

    private buildTree(folders: DexieFolder[], notes: Note[]): TreeNode[] {
        const folderChildrenMap = new Map<string, DexieFolder[]>();
        const rootFolders: DexieFolder[] = [];

        for (const folder of folders) {
            if (!folder.parentId || folder.parentId === '') {
                rootFolders.push(folder);
            } else {
                const siblings = folderChildrenMap.get(folder.parentId) || [];
                siblings.push(folder);
                folderChildrenMap.set(folder.parentId, siblings);
            }
        }

        const notesByFolder = new Map<string, Note[]>();
        const rootNotes: Note[] = [];

        for (const note of notes) {
            if (!note.folderId || note.folderId === '') {
                rootNotes.push(note);
            } else {
                const folderNotes = notesByFolder.get(note.folderId) || [];
                folderNotes.push(note);
                notesByFolder.set(note.folderId, folderNotes);
            }
        }

        const sortByOrder = (a: { order: number }, b: { order: number }) => a.order - b.order;

        const buildFolderNode = (folder: DexieFolder): TreeNode => {
            const childFolders = (folderChildrenMap.get(folder.id) || []).sort(sortByOrder);
            const childNotes = (notesByFolder.get(folder.id) || []).sort(sortByOrder);

            const children: TreeNode[] = [
                ...childFolders.map(buildFolderNode),
                ...childNotes.map(note => this.noteToTreeNode(note)),
            ];

            return {
                id: folder.id,
                name: folder.name,
                type: 'folder',
                entityKind: folder.entityKind || undefined,
                isTypedRoot: folder.isTypedRoot,
                isNarrativeRoot: folder.isNarrativeRoot,
                narrativeId: folder.narrativeId || undefined,
                children: children.length > 0 ? children : undefined,
            };
        };

        rootFolders.sort(sortByOrder);
        rootNotes.sort(sortByOrder);

        return [
            ...rootFolders.map(buildFolderNode),
            ...rootNotes.map(note => this.noteToTreeNode(note)),
        ];
    }

    private buildFolderOptions(folders: DexieFolder[]): FolderOption[] {
        const childrenByParent = new Map<string, DexieFolder[]>();
        const rootFolders: DexieFolder[] = [];
        const sortByOrder = (a: DexieFolder, b: DexieFolder) => a.order - b.order;
        const options: FolderOption[] = [];

        for (const folder of folders) {
            if (!folder.parentId) {
                rootFolders.push(folder);
                continue;
            }

            const siblings = childrenByParent.get(folder.parentId) || [];
            siblings.push(folder);
            childrenByParent.set(folder.parentId, siblings);
        }

        const walk = (folder: DexieFolder, parentPath: string): void => {
            const currentPath = parentPath ? `${parentPath} / ${folder.name}` : folder.name;
            options.push({
                id: folder.id,
                name: folder.name,
                label: currentPath,
                entityKind: folder.entityKind,
                isNarrativeRoot: folder.isNarrativeRoot,
            });

            const children = (childrenByParent.get(folder.id) || []).sort(sortByOrder);
            for (const child of children) {
                walk(child, currentPath);
            }
        };

        for (const root of rootFolders.sort(sortByOrder)) {
            walk(root, '');
        }

        return options;
    }

    private noteToTreeNode(note: Note): TreeNode {
        return {
            id: note.id,
            name: note.title,
            type: 'note',
            isEntity: note.isEntity,
            entityKind: note.entityKind || undefined,
            narrativeId: note.narrativeId || undefined,
        };
    }

    async createNote(): Promise<void> {
        const id = await this.noteEditorStore.createAndOpenNote('', '');
        console.log(`[Sidebar] Created and opened note: ${id}`);
    }

    toggleFolderDropdown(): void {
        this.folderDropdownOpen.update(open => !open);
    }

    closeFolderDropdown(): void {
        this.folderDropdownOpen.set(false);
    }

    async createEntityFolder(option: EntityFolderOption): Promise<void> {
        const isNarrativeRoot = option.entityKind === 'NARRATIVE';

        if (isNarrativeRoot) {
            const id = await this.folderService.createNarrativeVault(option.label.replace(' Folder', ''));
            console.log(`[Sidebar] Created narrative vault: ${id}`);
        } else {
            const id = await this.folderService.createTypedRootFolder(option.entityKind, option.label.replace(' Folder', ''));
            console.log(`[Sidebar] Created typed folder: ${id}`);
        }

        this.closeFolderDropdown();
    }

    async createRegularFolder(): Promise<void> {
        const id = await this.folderService.createRootFolder('New Folder');
        console.log(`[Sidebar] Created folder: ${id}`);
        this.closeFolderDropdown();
    }

    async createNarrative(): Promise<void> {
        const id = await this.folderService.createNarrativeVault('New Narrative');
        console.log(`[Sidebar] Created narrative vault: ${id}`);
    }

    async openImportDialog(): Promise<void> {
        this.closeFolderDropdown();
        this.importDialogOpen.set(true);
        this.importMode.set('files');
        this.selectedImportFiles.set([]);
        this.importInProgress.set(false);
        this.importProgress.set({ processed: 0, total: 0 });
        this.importResult.set(null);
        this.importError.set('');
        this.createFolderOpen.set(false);
        this.createFolderName.set('');
        this.createFolderError.set('');

        const destinationFolderId = await this.documentIngestionService.resolveDefaultDestinationFolderId();
        this.importDestinationFolderId.set(destinationFolderId || '');
        await this.refreshCreateFolderOptions();
    }

    closeImportDialog(): void {
        if (this.importInProgress()) return;
        this.importDialogOpen.set(false);
    }

    async chooseImportSource(mode: DocumentIngestionMode): Promise<void> {
        this.importError.set('');
        this.importResult.set(null);
        this.importMode.set(mode);

        const batch = mode === 'folder'
            ? await this.documentIngestionService.openFolderPicker()
            : await this.documentIngestionService.openFilesPicker();

        if (!batch) {
            return;
        }

        this.importMode.set(batch.mode);
        this.selectedImportFiles.set(batch.files);
        this.importProgress.set({ processed: 0, total: batch.files.filter(file => this.isTxtFile(file.name)).length });

        if (batch.files.length > 0 && batch.files.every(file => !this.isTxtFile(file.name))) {
            this.importError.set('No .txt files were found in the selection.');
        }
    }

    async setImportDestination(folderId: string): Promise<void> {
        this.importDestinationFolderId.set(folderId);
        this.createFolderError.set('');
        await this.refreshCreateFolderOptions();
    }

    toggleCreateFolderPanel(): void {
        this.createFolderOpen.update(open => !open);
        this.createFolderError.set('');
        if (this.createFolderOpen()) {
            void this.refreshCreateFolderOptions();
        }
    }

    async createFolderForImport(): Promise<void> {
        this.createFolderError.set('');
        this.createFolderInProgress.set(true);

        try {
            const folderId = await this.documentIngestionService.createDestinationFolder(
                this.importDestinationFolderId(),
                this.createFolderEntityKind(),
                this.createFolderName()
            );
            this.importDestinationFolderId.set(folderId);
            this.createFolderName.set('');
            this.createFolderOpen.set(false);
            await this.refreshCreateFolderOptions();
        } catch (error) {
            this.createFolderError.set(error instanceof Error ? error.message : 'Folder creation failed.');
        } finally {
            this.createFolderInProgress.set(false);
        }
    }

    async runImport(): Promise<void> {
        if (!this.canStartImport()) {
            if (!this.importDestinationFolderId()) {
                this.importError.set('Choose a destination folder or create one before importing.');
            } else if (this.supportedImportFilesCount() === 0) {
                this.importError.set('Select at least one .txt file before importing.');
            }
            return;
        }

        this.importError.set('');
        this.importResult.set(null);
        this.importInProgress.set(true);
        this.importProgress.set({ processed: 0, total: this.supportedImportFilesCount() });

        try {
            const result = await this.documentIngestionService.ingestDocuments({
                mode: this.importMode(),
                destinationFolderId: this.importDestinationFolderId(),
                files: this.selectedImportFiles(),
                conflictPolicy: 'suffix',
            }, (processed, total) => {
                this.importProgress.set({ processed, total });
            });

            this.importResult.set(result);
        } catch (error) {
            this.importError.set(error instanceof Error ? error.message : 'Import failed.');
        } finally {
            this.importInProgress.set(false);
        }
    }

    async exportActiveNote(): Promise<void> {
        const note = this.noteEditorStore.currentNote();
        if (!note || this.isExporting()) {
            return;
        }

        this.isExporting.set(true);
        try {
            const snapshot = this.editorService.captureSnapshot('api');
            const text = snapshot?.markdown ?? note.markdownContent ?? '';
            const result = await this.documentExportService.exportText(note.title, text);
            if (result.status === 'saved') {
                console.log(`[Sidebar] Exported note "${note.title}" as ${result.fileName}`);
            }
        } catch (error) {
            console.error('[Sidebar] Note export failed:', error);
        } finally {
            this.isExporting.set(false);
        }
    }

    async refreshCreateFolderOptions(): Promise<void> {
        const destinationFolderId = this.importDestinationFolderId();

        if (!destinationFolderId) {
            this.createFolderOptions.set(ROOT_CREATE_FOLDER_OPTIONS);
            if (!ROOT_CREATE_FOLDER_OPTIONS.some(option => option.entityKind === this.createFolderEntityKind())) {
                this.createFolderEntityKind.set(ROOT_CREATE_FOLDER_OPTIONS[0].entityKind);
            }
            return;
        }

        const destinationFolder = this.folders().find(folder => folder.id === destinationFolderId);
        if (!destinationFolder?.entityKind) {
            this.createFolderOptions.set([{ entityKind: '', label: 'Regular Folder', description: 'Create a plain subfolder here.' }]);
            this.createFolderEntityKind.set('');
            return;
        }

        const allowedSubfolders = await this.folderService.getAllowedSubfolders(destinationFolder.entityKind);
        const options: CreateFolderOption[] = [
            { entityKind: '', label: 'Regular Folder', description: 'Create a plain subfolder here.' },
            ...allowedSubfolders.map(subfolder => ({
                entityKind: subfolder.entityKind,
                label: subfolder.label,
                description: subfolder.description || `Create a ${subfolder.entityKind.toLowerCase()} subfolder here.`,
            })),
        ];

        this.createFolderOptions.set(options);
        if (!options.some(option => option.entityKind === this.createFolderEntityKind())) {
            this.createFolderEntityKind.set(options[0]?.entityKind || '');
        }
    }

    getCreateFolderParentLabel(): string {
        return this.selectedDestinationFolder()?.label || 'Root level';
    }

    getCreateFolderOptionLabel(entityKind: string): string {
        return this.createFolderOptions().find(option => option.entityKind === entityKind)?.label || 'Regular Folder';
    }

    getDisplayFileName(file: File): string {
        const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
        return relative && relative.length > 0 ? relative : file.name;
    }

    isTxtFile(fileName: string): boolean {
        return fileName.toLowerCase().endsWith('.txt');
    }

    toggleReorderMode(): void {
        this.reorderService.toggleReorderMode();
    }

    getNodeIcon(node: TreeNode): any {
        if (node.type === 'folder') {
            if (node.isNarrativeRoot) return this.BookOpen;
            return this.Folder;
        }
        return this.FileText;
    }

    onCollapsedNodeClick(node: TreeNode): void {
        if (node.type === 'note') {
            this.noteEditorStore.openNote(node.id);
        } else {
            this.sidebarService.open();
        }
    }

    toggleSearch(): void {
        if (this.viewMode() !== 'search') {
            this.setViewMode('search');
        } else {
            this.setViewMode('files');
        }
    }

    async triggerGraphScan(): Promise<void> {
        const note = this.noteEditorStore.currentNote();
        if (!note) {
            console.warn('[Sidebar] No note open to index.');
            return;
        }

        if (!this.phoenixUiApi.isReady) {
            console.warn('[Sidebar] Phoenix runtime not ready.');
            return;
        }

        this.isScanning.set(true);

        try {
            await this.graphPipeline.runNoteGraphPipeline(note);
        } catch (error) {
            console.error('[Sidebar] Graph indexing failed:', error);
        } finally {
            this.isScanning.set(false);
        }
    }

    navigateToCalendar(): void {
        this.router.navigate(['/calendar']);
    }

    navigateToChat(): void {
        this.router.navigate(['/chat']);
    }

    startResize(event: MouseEvent): void {
        event.preventDefault();
        this.isResizing = true;
        this.startX = event.clientX;
        this.startWidth = this.sidebarWidth;

        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        if (!this.sidebarService.isOpen()) {
            this.sidebarService.open();
        }
    }

    @HostListener('window:mousemove', ['$event'])
    onMouseMove(event: MouseEvent): void {
        if (!this.isResizing) return;

        const delta = event.clientX - this.startX;
        const newWidth = this.startWidth + delta;

        // Constraints
        const minWidth = 150;
        const maxWidth = 800;

        this.sidebarWidth = Math.min(Math.max(newWidth, minWidth), maxWidth);
    }

    @HostListener('window:mouseup')
    onMouseUp(): void {
        if (this.isResizing) {
            this.isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            setSetting('kittclouds-left-sidebar-width', this.sidebarWidth);
        }
    }

    async selectChatSession(id: string): Promise<void> {
        await this.goChatService.loadThread(id);
    }

    formatSessionDate(timestamp: number): string {
        const date = new Date(timestamp);
        const diff = Date.now() - date.getTime();
        if (diff < 86400000) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        if (diff < 604800000) return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
}
