import { describe, expect, it } from 'vitest';

import template from './graph-style-drawer.component.html?raw';
import source from './graph-style-drawer.component.ts?raw';

describe('GraphStyleDrawerComponent model language', () => {
    it('describes graph model colors without graph theory jargon', () => {
        const text = `${template}\n${source}`;

        expect(text).toContain('Model style controls');
        expect(text).toContain('Relationship and structure colors');
        expect(text).toContain('Relationship colors');
        expect(text).toContain('Story relationships');
        expect(text).toContain('Story structure');
        expect(text).toContain('Weak co-occurrence');
        expect(text).toContain('Document');
        expect(text).toContain('Relationship midpoint');
        expect(text).not.toContain('Graph node types');
        expect(text).not.toContain('Document atom');
        expect(text).not.toContain('Fact vertex');
    });
});
