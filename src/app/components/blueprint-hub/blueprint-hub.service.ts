import { Injectable, signal } from '@angular/core';
import { getSetting, setSetting } from '../../lib/dexie/settings.service';

const STORAGE_KEY = 'kittclouds-blueprint-hub';
const ACTIVE_TAB_STORAGE_KEY = 'kittclouds-hub-tab';
export type BlueprintHubMode = 'dock' | 'page';
export type BlueprintHubTabId = 'graph' | 'patterns' | 'plot-threads' | 'worldbuilding' | 'attributes';

export interface BlueprintHubTab {
    id: BlueprintHubTabId;
    label: string;
    icon: string;
}

/**
 * Service for Blueprint Hub state.
 * Uses local signal state with Dexie settings persistence.
 */
@Injectable({
    providedIn: 'root'
})
export class BlueprintHubService {
    private _isOpen = signal(this.loadFromStorage());
    private _mode = signal<BlueprintHubMode>('dock');
    private _activeTab = signal<BlueprintHubTabId>(this.loadActiveTab());

    readonly tabs: BlueprintHubTab[] = [
        { id: 'graph', label: 'Graph', icon: 'pi pi-share-alt' },
        { id: 'patterns', label: 'Patterns', icon: 'pi pi-code' },
        { id: 'plot-threads', label: 'Plot Threads', icon: 'pi pi-sitemap' },
        { id: 'worldbuilding', label: 'Worldbuilding', icon: 'pi pi-globe' },
        { id: 'attributes', label: 'Atlas Control', icon: 'pi pi-database' },
    ];

    /** Whether the hub is currently open (signal) */
    get isHubOpen() {
        return this._isOpen;
    }

    get mode() {
        return this._mode;
    }

    get activeTab() {
        return this._activeTab;
    }

    isPageMode(): boolean {
        return this._mode() === 'page';
    }

    private loadFromStorage(): boolean {
        return getSetting<boolean>(STORAGE_KEY, false);
    }

    private loadActiveTab(): BlueprintHubTabId {
        const stored = getSetting<string | null>(ACTIVE_TAB_STORAGE_KEY, null);
        if (this.isTabId(stored)) return stored;
        return 'graph';
    }

    private persist(): void {
        setSetting(STORAGE_KEY, this._isOpen());
    }

    private isTabId(tabId: string | null | undefined): tabId is BlueprintHubTabId {
        return !!tabId && this.tabs.some(tab => tab.id === tabId);
    }

    setActiveTab(tabId: string): void {
        if (!this.isTabId(tabId)) return;
        this._activeTab.set(tabId);
        setSetting(ACTIVE_TAB_STORAGE_KEY, tabId);
    }

    activeTabIcon(): string {
        return this.tabs.find(tab => tab.id === this._activeTab())?.icon ?? 'pi pi-info-circle';
    }

    activeTabLabel(): string {
        return this.tabs.find(tab => tab.id === this._activeTab())?.label ?? '';
    }

    /** Toggle hub open/closed */
    toggle(): void {
        this._isOpen.update(v => !v);
        this.persist();
    }

    toggleDock(): void {
        if (this.isPageMode()) {
            this._mode.set('dock');
            this.open();
            return;
        }
        this.toggle();
    }

    togglePageMode(): void {
        if (this.isPageMode()) {
            this._mode.set('dock');
            this.open();
            return;
        }
        this._mode.set('page');
        this.open();
    }

    openPage(tabId: BlueprintHubTabId = this._activeTab()): void {
        this.setActiveTab(tabId);
        this._mode.set('page');
        this.open();
    }

    /** Close the hub */
    close(): void {
        this._isOpen.set(false);
        this._mode.set('dock');
        this.persist();
    }

    /** Open the hub */
    open(): void {
        this._isOpen.set(true);
        this.persist();
    }
}
