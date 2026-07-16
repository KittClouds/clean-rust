import { describe, expect, it } from 'vitest';

import { getDecorationStyle } from './styles';
import type { DecorationSpan } from './types';

describe('getDecorationStyle', () => {
    const entitySpan: DecorationSpan = {
        type: 'entity',
        from: 0,
        to: 3,
        label: 'Kai',
        kind: 'CHARACTER',
    };

    it('renders clean entity mode as plain text without chrome', () => {
        const style = getDecorationStyle(entitySpan, 'clean');

        expect(style).toContain('color: inherit');
        expect(style).toContain('background-image: none');
        expect(style).toContain('padding: 0');
        expect(style).toContain('text-decoration: none');
    });

    it('renders subtle entity mode as a static gradient', () => {
        const style = getDecorationStyle(entitySpan, 'subtle');

        expect(style).toContain('background-image: linear-gradient');
        expect(style).toContain('background-clip: text');
        expect(style).toContain('-webkit-text-fill-color: transparent');
        expect(style).toContain('background-position: center');
        expect(style).toContain('background-size: 100% 100%');
        expect(style).toContain('animation: none');
        expect(style).not.toContain('entity-gradient-oscillate');
    });

    it('renders gradient entity mode as gradient inline text', () => {
        const style = getDecorationStyle(entitySpan, 'gradient');

        expect(style).toContain('background-image: linear-gradient');
        expect(style).toContain('background-clip: text');
        expect(style).toContain('-webkit-text-fill-color: transparent');
        expect(style).toContain('background-position: 0% 0');
        expect(style).toContain('background-size: 300% 100%');
        expect(style).toContain('animation: entity-gradient-oscillate 8s linear infinite');
    });

    it('renders clean wikilinks as plain text', () => {
        const style = getDecorationStyle(
            {
                type: 'wikilink',
                from: 0,
                to: 5,
                label: 'Atlas',
                resolved: true,
            },
            'clean',
        );

        expect(style).toContain('color: inherit');
        expect(style).toContain('text-decoration: none');
        expect(style).not.toContain('underline');
    });
});
