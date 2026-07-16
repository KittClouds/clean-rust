import { describe, expect, it } from 'vitest';

import { boundedPathSelection, nextPathSelection, pathSelectionLocksCanvasFocus } from './graph-path-selection';

describe('shortest-path endpoint selection', () => {
    it('fills two ordered slots and replaces the oldest endpoint on a third click', () => {
        expect(nextPathSelection([], 'a')).toEqual(['a']);
        expect(nextPathSelection(['a'], 'b')).toEqual(['a', 'b']);
        expect(nextPathSelection(['a', 'b'], 'c')).toEqual(['b', 'c']);
    });

    it('toggles either selected endpoint off and bounds lasso input to two unique nodes', () => {
        expect(nextPathSelection(['a', 'b'], 'a')).toEqual(['b']);
        expect(nextPathSelection(['a', 'b'], 'b')).toEqual(['a']);
        expect(boundedPathSelection(['a', 'a', 'b', 'c'])).toEqual(['a', 'b']);
        expect(pathSelectionLocksCanvasFocus(['a', 'b'])).toBe(true);
        expect(pathSelectionLocksCanvasFocus(['a'])).toBe(false);
    });
});
