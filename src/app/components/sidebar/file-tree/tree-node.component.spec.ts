// @vitest-environment jsdom
import '@angular/compiler';
import { TestBed, getTestBed } from '@angular/core/testing';
import {
    BrowserDynamicTestingModule,
    platformBrowserDynamicTesting,
} from '@angular/platform-browser-dynamic/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { FlatTreeNode } from '../../../lib/arborist/types';
import { TreeNodeComponent } from './tree-node.component';

try {
    getTestBed().initTestEnvironment(
        BrowserDynamicTestingModule,
        platformBrowserDynamicTesting(),
    );
} catch {
    // Test environment already initialized for this Vitest worker.
}

describe('TreeNodeComponent actions menu', () => {
    beforeEach(async () => {
        await TestBed.configureTestingModule({
            imports: [TreeNodeComponent],
        }).compileComponents();
    });

    it('keeps the actions button reachable without a hover-only hidden state', () => {
        const fixture = TestBed.createComponent(TreeNodeComponent);
        fixture.componentRef.setInput('node', noteNode());
        fixture.detectChanges();

        const button = fixture.nativeElement.querySelector('button.kebab-menu') as HTMLButtonElement | null;

        expect(button).not.toBeNull();
        expect(button?.classList.contains('opacity-0')).toBe(false);
        expect(button?.getAttribute('aria-label')).toBe('Actions for Untitled Note');
    });

    it('opens the node menu without selecting the note row underneath', () => {
        const fixture = TestBed.createComponent(TreeNodeComponent);
        fixture.componentRef.setInput('node', noteNode());
        fixture.detectChanges();
        const component = fixture.componentInstance;
        const menuEvents: FlatTreeNode[] = [];
        const selected: FlatTreeNode[] = [];
        component.menuClick.subscribe(({ node }) => menuEvents.push(node));
        component.select.subscribe((node) => selected.push(node));

        const button = fixture.nativeElement.querySelector('button.kebab-menu') as HTMLButtonElement;
        button.dispatchEvent(new MouseEvent('click', { bubbles: true }));

        expect(menuEvents.map((node) => node.id)).toEqual(['note-1']);
        expect(selected).toEqual([]);
    });
});

function noteNode(): FlatTreeNode {
    return {
        id: 'note-1',
        name: 'Untitled Note',
        type: 'note',
        level: 0,
        isExpanded: false,
        isVisible: true,
        hasChildren: false,
        isLastChild: true,
        ancestorHasSibling: [],
    };
}
