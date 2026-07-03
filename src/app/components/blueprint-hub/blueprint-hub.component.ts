import { Component, HostListener, Input, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BlueprintHubService } from './blueprint-hub.service';
import { GraphTabComponent } from './tabs/graph-tab/graph-tab.component';
import { PatternsTabComponent } from './tabs/patterns-tab/patterns-tab.component';
import { PlotThreadsTabComponent } from './tabs/plot-threads-tab/plot-threads-tab.component';
import { WorldbuildingTabComponent } from './tabs/worldbuilding-tab/worldbuilding-tab.component';
import { AttributesTabComponent } from './tabs/attributes-tab/attributes-tab.component';

@Component({
    selector: 'app-blueprint-hub',
    standalone: true,
    imports: [
        CommonModule,
        GraphTabComponent,
        PatternsTabComponent,
        PlotThreadsTabComponent,
        WorldbuildingTabComponent,
        AttributesTabComponent
    ],
    templateUrl: './blueprint-hub.component.html',
    styleUrl: './blueprint-hub.component.css'
})
export class BlueprintHubComponent {
    public readonly hubService = inject(BlueprintHubService);

    @Input() mode: 'overlay' | 'page' = 'overlay';

    // Active tab (signal)
    activeTab = computed(() => this.hubService.activeTab());

    // Resize state
    hubHeight = 600; // Default height in pixels
    private isResizing = false;
    private startY = 0;
    private startHeight = 0;

    get tabs() {
        return this.hubService.tabs;
    }

    get isPageMode(): boolean {
        return this.mode === 'page';
    }

    setActiveTab(tabId: string) {
        this.hubService.setActiveTab(tabId);
    }

    get activeTabIcon(): string {
        return this.hubService.activeTabIcon();
    }

    get activeTabLabel(): string {
        return this.hubService.activeTabLabel();
    }

    // Resize Logic
    startResize(event: MouseEvent) {
        if (this.isPageMode) return;
        event.preventDefault();
        this.isResizing = true;
        this.startY = event.clientY;
        this.startHeight = this.hubHeight;

        // Add cursor style to body to prevent flickering during quick drags
        document.body.style.cursor = 'row-resize';
        document.body.style.userSelect = 'none';
    }

    @HostListener('window:mousemove', ['$event'])
    onMouseMove(event: MouseEvent) {
        if (!this.isResizing || this.isPageMode) return;

        // Calculate delta: moving UP (smaller Y) means LARGER height
        const delta = this.startY - event.clientY;
        const newHeight = this.startHeight + delta;

        // Constraints
        const minHeight = 200;
        const maxHeight = window.innerHeight - 100; // Leave some space at top

        this.hubHeight = Math.min(Math.max(newHeight, minHeight), maxHeight);
    }

    @HostListener('window:mouseup')
    onMouseUp() {
        if (this.isResizing) {
            this.isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    }
}
