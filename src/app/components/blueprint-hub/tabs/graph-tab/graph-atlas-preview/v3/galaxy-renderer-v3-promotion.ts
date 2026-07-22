export const GALAXY_RENDERER_V3_PROMOTION_GATES = [
    'packetAuthority',
    'identityParity',
    'topologyParity',
    'visualParity',
    'interactionParity',
    'failureIsolation',
    'performanceBudget',
] as const;

export type GalaxyRendererV3PromotionGate = typeof GALAXY_RENDERER_V3_PROMOTION_GATES[number];
export type GalaxyRendererV3PromotionEvidence = Record<GalaxyRendererV3PromotionGate, boolean>;

export interface GalaxyRendererV3PromotionDecision {
    promotable: boolean;
    blockers: GalaxyRendererV3PromotionGate[];
}

export function evaluateGalaxyRendererV3Promotion(
    evidence: GalaxyRendererV3PromotionEvidence,
): GalaxyRendererV3PromotionDecision {
    const blockers = GALAXY_RENDERER_V3_PROMOTION_GATES.filter((gate) => !evidence[gate]);
    return { promotable: blockers.length === 0, blockers };
}
