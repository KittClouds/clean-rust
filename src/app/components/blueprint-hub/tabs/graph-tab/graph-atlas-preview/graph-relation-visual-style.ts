import {
    DEFAULT_GRAPH_NODE_COLORS,
    entityColorStore,
    type GraphNodeColorKind,
} from '../../../../../lib/store/entityColorStore';

export const GRAPH_RELATION_FAMILY_HSL: Record<string, string> = {
    cooccurrence: DEFAULT_GRAPH_NODE_COLORS.cooccurrence,
    observation: DEFAULT_GRAPH_NODE_COLORS.observation,
    communication: DEFAULT_GRAPH_NODE_COLORS.communication,
    authority: DEFAULT_GRAPH_NODE_COLORS.authority,
    approval: DEFAULT_GRAPH_NODE_COLORS.approval,
    family: DEFAULT_GRAPH_NODE_COLORS.family,
    intimacy: DEFAULT_GRAPH_NODE_COLORS.intimacy,
    transfer: DEFAULT_GRAPH_NODE_COLORS.transfer,
    scenePresence: DEFAULT_GRAPH_NODE_COLORS.scenePresence,
    causal: DEFAULT_GRAPH_NODE_COLORS.causal,
    temporal: DEFAULT_GRAPH_NODE_COLORS.temporal,
    relationship: DEFAULT_GRAPH_NODE_COLORS.relationship,
};

export function relationFamilyFromText(...parts: unknown[]): GraphNodeColorKind | null {
    const text = parts
        .map((part) => String(part || ''))
        .join(' ')
        .toLowerCase()
        .replace(/[_-]+/g, ' ');
    if (/\bco\s*occurs?\b|\bco\s*occurrence\b|\bcooccurs?\b|anchored\s*cooccurrence/.test(text)) return 'cooccurrence';
    if (/\bcauses?\b|\bcausal\b|\bexplains?\b|\bbecause\b|\beffect\b/.test(text)) return 'causal';
    if (/\btemporal\b|\bbefore\b|\bafter\b|\btimeline\b|\btime\s+anchor\b/.test(text)) return 'temporal';
    if (/\bobservation\b|\bobserves?\b|\bobserved\b|\bwatch(?:ed|es)?\b|\bsaw\b|\bnoticed\b|\blooked\s+at\b/.test(text)) return 'observation';
    if (/\bcommunication\b|\bcomments?\b|\bcommented\b|\bdiscuss(?:es|ed)?\b|\brelease\s+terms\b|\bwarn(?:s|ed|ing)?\b|\bsaid\b|\bsays\b|\btold\b|\basks?\b|\banswers?\b|\breplies?\b|\bspeaks?\b/.test(text)) return 'communication';
    if (/\bauthority\b|\bchain\b|\bcommand\b|\bservice\s+tie\b|\bmilitary\b|\badmiral\b|\bphantom\b|\bjoint\s+chiefs\b|\boperator\s+office\b|\bwarden\b/.test(text)) return 'authority';
    if (/\bapprov(?:es|ed|al)?\b|\baccept(?:s|ed)?\b|\bagree(?:s|d)?\b|\bproceed\b|\bsupports?\b/.test(text)) return 'approval';
    if (/\bfamily\b|\bfather\b|\bdaughter\b|\bgrandfather\b|\bhouse\s+tie\b/.test(text)) return 'family';
    if (/\bintimate\b|\bclose\s+contact\b|\bkiss\b|\bstood\s+beside\b|\bclose\s+enough\b/.test(text)) return 'intimacy';
    if (/\btransfers?\b|\breceives?\b|\bgave\b|\bhanded\b|\btook\s+it\s+from\b/.test(text)) return 'transfer';
    if (/\bscene\s+presence\b|\bentered\b|\barrived\b|\bcame\s+in\b|\bstood\s+near\b/.test(text)) return 'scenePresence';
    if (/\brelationship\b|\brelation\b|\bgraph\s+fact\b|\bfact\b|\btrusts?\b|\bbond\b|\bfriend\b/.test(text)) return 'relationship';
    return null;
}

export function relationHslFromText(...parts: unknown[]): string | null {
    const family = relationFamilyFromText(...parts);
    return family ? entityColorStore.getRawGraphNodeHsl(family) : null;
}
