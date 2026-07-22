// src/app/components/editor/plugins/pretty-text-toolkit.ts
// =============================================================================
// PRETTY TEXT TOOLKIT
// =============================================================================
//
// This file contains legacy and experimental logic extracted from:
// - entityHighlighter.ts (Decoration-based, removed)
// - entityHighlighterExperimental.ts (Overlay-based, removed)
//
// These utilities are preserved for reference or future "Overlay" implementations
// but are NOT currently used by the active PrettyTextPlugin (Mark-based).
//
// =============================================================================

import type { DecorationSpan } from '../../../lib/Scanner/types';
import { getPrettyTextApi } from '../../../api/pretty-text-api';
import { getEntityColorVar } from '../../../lib/store/entityColorStore';

/**
 * Check if cursor is inside a span
 */
export function isCursorInside(span: DecorationSpan, selection: { from: number; to: number }): boolean {
    return selection.from <= span.to && selection.to >= span.from;
}

/**
 * Get subtle (editing mode) style for a span 
 */
export function getEditingStyle(span: DecorationSpan): string {
    if (span.type === 'entity' && span.kind) {
        const colorVar = getEntityColorVar(span.kind);
        return `color: hsl(var(${colorVar})); font-weight: 500;`;
    }
    if (span.type === 'entity_ref') {
        if (span.kind) {
            const colorVar = getEntityColorVar(span.kind);
            return `color: hsl(var(${colorVar})); text-decoration: underline;`;
        }
        return 'color: #8b5cf6; text-decoration: underline;';
    }
    if (span.type === 'wikilink') {
        return 'color: #3b82f6; text-decoration: underline;';
    }
    return '';
}

/**
 * Get tooltip text for a span
 */
export function getTooltip(span: DecorationSpan): string {
    switch (span.type) {
        case 'entity':
            return `Entity: ${span.label} (${span.kind})`;
        case 'entity_ref':
            if (span.resolved && span.kind) {
                return `Entity: ${span.label} (${span.kind})`;
            }
            return `Entity: ${span.label} (unresolved)`;
        case 'wikilink':
            return `Open note: ${span.target}`;
        case 'relationship':
            return `${span.sourceEntity} → ${span.targetEntity}`;
        default:
            return span.label;
    }
}

/**
 * Create widget element for a span
 * (Legacy: used mostly for decoration-based highlighting)
 */
export function createWidget(span: DecorationSpan): HTMLElement {
    const api = getPrettyTextApi();
    const mode = api.getMode();
    const widget = document.createElement('span');

    if (mode === 'subtle' || mode === 'gradient') {
        // Inline modes: no pill background, keep text editable and lightweight.
        widget.className = 'entity-widget entity-widget-subtle';
        const colorStyle = api.getStyle(span) || getEditingStyle(span);
        widget.style.cssText = `${colorStyle} padding: 0; border: none; border-radius: 0; display: inline; box-shadow: none; cursor: pointer;`;
    } else {
        // Vivid and Clean preserve the original inline widget treatment.
        widget.className = api.getClass(span) + ' entity-widget';
        widget.style.cssText = api.getStyle(span);
        widget.style.cursor = 'pointer';
    }

    widget.textContent = span.displayText || span.label;
    widget.setAttribute('data-span-type', span.type);
    widget.setAttribute('data-target', span.target || span.label);
    widget.setAttribute('title', getTooltip(span));

    return widget;
}

// =============================================================================
// OVERLAY LAYER UTILITIES (From Experimental)
// =============================================================================

export interface OverlayState {
    container: HTMLDivElement | null;
    highlights: Map<string, HTMLElement>;
}

export function createOverlayContainer(): HTMLDivElement {
    const container = document.createElement('div');
    container.className = 'entity-overlay-layer';
    container.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        pointer-events: none;
        overflow: hidden;
        z-index: 5;
    `;
    return container;
}
