// src/lib/Scanner/styles.ts
// Entity decoration styles
// Uses CSS variables from entityColorStore for live theming

import type { EntityKind, HighlightMode, DecorationSpan } from './types';
import { getEntityColorVar, getEntityTextColorVar } from '../store/entityColorStore';

/**
 * LEGACY: Color palette for entity kinds - DEPRECATED
 * Use getEntityColor() instead for live theme updates
 * Kept for backwards compatibility with existing code
 */
export const ENTITY_COLORS: Record<EntityKind, { bg: string; text: string }> = {
  CHARACTER: { bg: '#7c3aed', text: '#ffffff' },  // Purple
  LOCATION: { bg: '#0891b2', text: '#ffffff' },  // Cyan
  ORGANIZATION: { bg: '#db2777', text: '#ffffff' },  // Pink
  ITEM: { bg: '#ca8a04', text: '#000000' },  // Gold
  CONCEPT: { bg: '#0d9488', text: '#ffffff' },  // Teal
  EVENT: { bg: '#ea580c', text: '#ffffff' },  // Orange
  FACTION: { bg: '#dc2626', text: '#ffffff' },  // Red
  CREATURE: { bg: '#16a34a', text: '#ffffff' },  // Green
  NPC: { bg: '#9333ea', text: '#ffffff' },  // Purple-600
  SCENE: { bg: '#2563eb', text: '#ffffff' },  // Blue-600
  ARC: { bg: '#4f46e5', text: '#ffffff' },  // Indigo-600
  ACT: { bg: '#4338ca', text: '#ffffff' },  // Indigo-700
  CHAPTER: { bg: '#3730a3', text: '#ffffff' },  // Indigo-800
  BEAT: { bg: '#312e81', text: '#ffffff' },  // Indigo-900
  TIMELINE: { bg: '#059669', text: '#ffffff' },  // Emerald-600
  NARRATIVE: { bg: '#047857', text: '#ffffff' },  // Emerald-700
  NETWORK: { bg: '#059669', text: '#ffffff' },  // Emerald-600
  CUSTOM: { bg: '#6b7280', text: '#ffffff' },  // Gray
  OTHER: { bg: '#6b7280', text: '#ffffff' },  // Gray
  UNKNOWN: { bg: '#6b7280', text: '#ffffff' },  // Gray
};

/**
 * Wikilink colors (text + underline style)
 */
const WIKILINK_COLOR = '#3b82f6'; // Blue
const WIKILINK_BROKEN = '#ef4444'; // Red

/**
 * Entity ref uses same palette as entities but different default
 */
const ENTITY_REF_COLOR = '#8b5cf6'; // Purple (default for untyped refs)

/**
 * Generate inline CSS for a decoration span
 * Uses CSS variables for entity colors so they update live with ThemeTab
 */
export function getDecorationStyle(span: DecorationSpan, mode: HighlightMode): string {
  if (mode === 'off') return '';

  switch (span.type) {
    case 'entity':
      return getEntityStyle(span.kind || 'UNKNOWN', mode);
    case 'wikilink':
      return getWikilinkStyle(span.resolved !== false, mode);
    case 'entity_ref':
      return getEntityRefStyle(span.kind, span.resolved !== false, mode);
    case 'entity_implicit':
      if (span.resolved === false) {
        return getAmbiguousStyle(mode);
      }
      return getEntityStyle(span.kind || 'UNKNOWN', mode);
    case 'entity_candidate':
      return getCandidateStyle(mode);
    case 'keyword_focus':
      return getKeywordFocusStyle();
    case 'analytics_highlight':
      return getAnalyticsHighlightStyle(span.highlightKind, span.analyticsPaletteKey);
    default:
      return '';
  }
}

function getKeywordFocusStyle(): string {
  return `
    background-color: rgba(45, 212, 191, 0.18);
    box-shadow: inset 0 -1px 0 rgba(45, 212, 191, 0.55);
    border-radius: 2px;
  `;
}

function getAnalyticsHighlightStyle(
  kind: DecorationSpan['highlightKind'],
  paletteKey?: DecorationSpan['analyticsPaletteKey'],
): string {
  const resolved = paletteKey || kind;
  const palette = resolved === 'repetition'
    ? { fill: 'rgba(245, 158, 11, 0.22)', stroke: 'rgba(245, 158, 11, 0.65)' }
    : resolved === 'proximity'
      ? { fill: 'rgba(244, 63, 94, 0.18)', stroke: 'rgba(244, 63, 94, 0.6)' }
      : resolved === 'negation'
        ? { fill: 'rgba(248, 113, 113, 0.18)', stroke: 'rgba(248, 113, 113, 0.68)' }
      : resolved === 'ornament'
        ? { fill: 'rgba(217, 70, 239, 0.16)', stroke: 'rgba(217, 70, 239, 0.58)' }
      : resolved === 'distance'
        ? { fill: 'rgba(96, 165, 250, 0.16)', stroke: 'rgba(96, 165, 250, 0.58)' }
      : resolved === 'diction'
        ? { fill: 'rgba(52, 211, 153, 0.16)', stroke: 'rgba(52, 211, 153, 0.58)' }
      : resolved === 'keyword'
        ? { fill: 'rgba(45, 212, 191, 0.18)', stroke: 'rgba(45, 212, 191, 0.6)' }
      : resolved === 'meter'
        ? { fill: 'rgba(20, 184, 166, 0.2)', stroke: 'rgba(45, 212, 191, 0.68)' }
      : resolved === '1'
        ? { fill: 'rgba(167, 139, 250, 0.22)', stroke: 'rgba(139, 92, 246, 0.68)' }
        : resolved === '2-6'
          ? { fill: 'rgba(96, 165, 250, 0.2)', stroke: 'rgba(59, 130, 246, 0.64)' }
          : resolved === '7-15'
            ? { fill: 'rgba(52, 211, 153, 0.2)', stroke: 'rgba(16, 185, 129, 0.64)' }
            : resolved === '16-25'
              ? { fill: 'rgba(251, 146, 60, 0.2)', stroke: 'rgba(234, 88, 12, 0.64)' }
              : resolved === '26-39'
                ? { fill: 'rgba(248, 113, 113, 0.18)', stroke: 'rgba(220, 38, 38, 0.62)' }
                : resolved === '40+'
                  ? { fill: 'rgba(251, 113, 133, 0.18)', stroke: 'rgba(244, 63, 94, 0.62)' }
      : { fill: 'rgba(34, 211, 238, 0.18)', stroke: 'rgba(34, 211, 238, 0.58)' };

  return `
    background-color: ${palette.fill};
    box-shadow: inset 0 -2px 0 ${palette.stroke};
    border-radius: 2px;
  `;
}

function getAmbiguousStyle(mode: HighlightMode): string {
  // Gray dashed underline for ambiguous
  if (mode === 'clean') {
    return getPlainInlineStyle();
  }

  if (mode === 'vivid') {
    return `
      border-bottom: 2px dashed #9ca3af; 
      background-color: rgba(156, 163, 175, 0.1);
      cursor: help;
    `;
  }
  return `border-bottom: 2px dashed #9ca3af;`;
}

function getCandidateStyle(mode: HighlightMode): string {
  // Tealish-gray (CadetBlue) dotted underline for candidates
  // Replaces the previous yellow (#eab308)
  const color = '#5f9ea0'; // CadetBlue

  if (mode === 'clean') {
    return getPlainInlineStyle();
  }

  if (mode === 'vivid') {
    return `
        border-bottom: 2px dotted ${color}; 
        background-color: rgba(95, 158, 160, 0.15);
        cursor: help;
      `;
  }
  return `border-bottom: 2px dotted ${color};`;
}

/**
 * Entity style: Solid pill background using CSS variables
 * Uses separate text color variable for foreground
 */
function getEntityStyle(kind: EntityKind, mode: HighlightMode): string {
  const colorVar = getEntityColorVar(kind);
  const textColorVar = getEntityTextColorVar(kind);

  if (mode === 'vivid') {
    return `
      background-color: hsl(var(${colorVar}) / 0.2);
      color: hsl(var(${textColorVar}));
      border: 1px solid hsl(var(${colorVar}) / 0.3);
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: 500;
      font-size: 0.9em;
      display: inline;
      white-space: nowrap;
    `;
  }

  if (mode === 'subtle') {
    return getGradientInlineStyle(colorVar, false);
  }

  if (mode === 'gradient') {
    return getGradientInlineStyle(colorVar, true);
  }

  if (mode === 'clean') {
    return getPlainInlineStyle();
  }

  // Off bails out before styling.
  return '';
}

/**
 * Wikilink style: Colored text with underline (NOT a pill)
 */
function getWikilinkStyle(resolved: boolean, mode: HighlightMode): string {
  const color = resolved ? WIKILINK_COLOR : WIKILINK_BROKEN;
  const underline = resolved ? 'solid' : 'dashed';

  if (mode === 'clean') {
    return getPlainInlineStyle();
  }

  if (mode === 'vivid') {
    return `
      color: ${color};
      text-decoration: underline;
      text-decoration-style: ${underline};
      text-decoration-thickness: 2px;
      text-underline-offset: 3px;
      cursor: pointer;
      font-weight: 500;
    `;
  }

  // Subtle mode
  return `
    color: ${color};
    text-decoration: underline;
    text-decoration-style: ${underline};
    cursor: pointer;
  `;
}

/**
 * Entity ref style: Solid pill using CSS variables
 */
function getEntityRefStyle(kind: EntityKind | undefined, resolved: boolean, mode: HighlightMode): string {
  if (kind) {
    // Use entity colors if kind is specified
    return getEntityStyle(kind, mode);
  }

  // Default entity ref style (purple pill or gray)
  const color = resolved ? ENTITY_REF_COLOR : '#6b7280';
  // Manually calculated rgba strings for #8b5cf6 (purple) and #6b7280 (gray)
  const bg = resolved ? 'rgba(139, 92, 246, 0.2)' : 'rgba(107, 114, 128, 0.2)';
  const border = resolved ? 'rgba(139, 92, 246, 0.3)' : 'rgba(107, 114, 128, 0.3)';

  if (mode === 'clean') {
    return getPlainInlineStyle();
  }

  if (mode === 'vivid') {
    return `
      background-color: ${bg};
      color: ${color};
      border: 1px solid ${border};
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: 500;
      font-size: 0.9em;
      display: inline;
      white-space: nowrap;
      cursor: pointer;
    `;
  }

  // Subtle mode
  return `border-bottom: 2px solid ${bg}; padding-bottom: 1px; cursor: pointer;`;
}

function getGradientInlineStyle(colorVar: string, animated: boolean): string {
  return `
    background-image: linear-gradient(
      to right,
      hsl(var(${colorVar})),
      color-mix(in srgb, hsl(var(${colorVar})) 78%, hsl(var(--background)) 22%) 52%,
      color-mix(in srgb, hsl(var(${colorVar})) 64%, hsl(var(--foreground)) 36%),
      hsl(var(${colorVar}))
    );
    background-repeat: no-repeat;
    background-position: ${animated ? '0% 0' : 'center'};
    background-size: ${animated ? '300% 100%' : '100% 100%'};
    background-clip: text;
    -webkit-background-clip: text;
    color: transparent;
    -webkit-text-fill-color: transparent;
    font-weight: 600;
    ${animated ? 'animation: entity-gradient-oscillate 8s linear infinite;' : 'animation: none;'}
  `;
}

function getPlainInlineStyle(): string {
  return `
    background: transparent;
    background-image: none;
    border: none;
    border-radius: 0;
    box-shadow: none;
    color: inherit;
    -webkit-text-fill-color: currentColor;
    cursor: inherit;
    font-size: inherit;
    font-weight: inherit;
    padding: 0;
    text-decoration: none;
    text-shadow: none;
    white-space: normal;
  `;
}

/**
 * Get CSS class for a decoration span
 */
export function getDecorationClass(span: DecorationSpan): string {
  switch (span.type) {
    case 'entity':
      return `entity-pill entity-${(span.kind || 'unknown').toLowerCase()}`;
    case 'wikilink':
      return `wikilink ${span.resolved === false ? 'wikilink-broken' : ''}`;
    case 'entity_ref':
      return `entity-ref ${span.kind ? `entity-${span.kind.toLowerCase()}` : ''} ${span.resolved === false ? 'entity-ref-broken' : ''}`;
    case 'entity_implicit':
      if (span.resolved === false) {
        return `entity-implicit-ambiguous`;
      }
      return `entity-implicit entity-${(span.kind || 'unknown').toLowerCase()}`;
    case 'entity_candidate':
      return `entity-candidate`;
    case 'keyword_focus':
      return 'keyword-focus';
    case 'analytics_highlight':
      return `analytics-highlight analytics-${span.highlightKind || 'cadence'}`;
    default:
      return '';
  }
}

// Legacy export
export function getEntityClass(kind: EntityKind): string {
  return `entity-${kind.toLowerCase()}`;
}
