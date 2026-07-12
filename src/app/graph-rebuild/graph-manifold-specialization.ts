import type {
    GraphManifoldCandidateContribution,
    GraphManifoldRoleProfile,
    GraphManifoldSpecializationCounters,
    GraphManifoldSpecializationReceipt,
    GraphManifoldSpecializationSummary,
    GraphRebuildEmbeddingTargetPostProcess,
    GraphRebuildProductLaneKind,
    GraphRebuildSnapshot,
    GraphSemanticCandidate,
    GraphSemanticCandidateKind,
    GraphSemanticCandidateSummary,
    GraphSemanticManifoldKind,
} from './graph-rebuild-snapshot';
import type { GraphSemanticDerivationContext } from './graph-semantic-derivation-context';

interface ContributionDraft {
    candidate: GraphSemanticCandidate;
    manifold: GraphSemanticManifoldKind;
    ruleId: string;
    score: number;
    sourceTargetIds: string[];
    evidenceIds: string[];
    rationale: string;
}

interface SpecializationContext {
    targetRows: ReadonlyMap<string, GraphRebuildEmbeddingTargetPostProcess>;
}

const MAX_CONTRIBUTIONS = 480;
const PER_MANIFOLD_LIMIT = 96;
const PER_CANDIDATE_LIMIT = 4;
const PRODUCT_LANES = new Set<string>(['semantic', 'document', 'relation', 'temporal', 'causal', 'evidence', 'entity']);

const PROFILES: GraphManifoldRoleProfile[] = [
    {
        manifold: 'hybrid',
        manifoldRole: 'semantic_neighborhood',
        label: 'Hybrid semantic neighborhood',
        scoreInterpretation: 'Balanced semantic-neighborhood support from embedding clusters, graph-aware links, and anomaly distance.',
        candidateKinds: ['entity_link', 'relation_link', 'outlier_review'],
        contributionRules: [
            {
                id: 'hybrid-source-neighborhood',
                description: 'Candidate already carries a hybrid manifold or cluster source.',
                candidateKinds: ['entity_link', 'relation_link', 'outlier_review'],
                requiredSignals: ['source.manifold=hybrid', 'embedding cluster or graph postprocess source'],
            },
            {
                id: 'hybrid-general-retrieval',
                description: 'Candidate needs balanced semantic retrieval before a stronger specialist claims it.',
                candidateKinds: ['entity_link', 'relation_link', 'outlier_review'],
                requiredSignals: ['semantic_task', 'embedding_target', 'graph_postprocess'],
            },
        ],
    },
    {
        manifold: 'hopf',
        manifoldRole: 'recurrence_cycle',
        label: 'Hopf recurrence and alias loop',
        scoreInterpretation: 'Cyclic recurrence pressure for aliases, repeated surfaces, loop motifs, and story-return structure.',
        candidateKinds: ['entity_link', 'contradiction_review', 'outlier_review'],
        contributionRules: [
            {
                id: 'hopf-identity-cycle',
                description: 'Identity or alias candidate can form a local recurrence loop.',
                candidateKinds: ['entity_link', 'contradiction_review'],
                requiredSignals: ['identity_linker', 'identity:*', 'mention:*', 'surface:*'],
            },
            {
                id: 'hopf-recurrence-review',
                description: 'Repeated anomaly or duplicate pressure belongs to recurrence review.',
                candidateKinds: ['contradiction_review', 'outlier_review'],
                requiredSignals: ['duplicate', 'brittle', 'singleton', 'outlier'],
            },
        ],
    },
    {
        manifold: 'caps',
        manifoldRole: 'evidence_cap_hierarchy',
        label: 'Caps evidence and containment',
        scoreInterpretation: 'Evidence-cap support from document roots, ontology caps, chunk containment, and support-path coverage.',
        candidateKinds: ['entity_link', 'missing_frame', 'outlier_review'],
        contributionRules: [
            {
                id: 'caps-evidence-containment',
                description: 'Candidate is grounded in note, chunk, anchor, or evidence containment.',
                candidateKinds: ['entity_link', 'missing_frame', 'outlier_review'],
                requiredSignals: ['note:*', 'chunk:*', 'anchor:*', 'evidenceIds'],
            },
            {
                id: 'caps-frame-root',
                description: 'Unframed chunk or evidence root needs containment review.',
                candidateKinds: ['missing_frame', 'outlier_review'],
                requiredSignals: ['frame_gap', 'embedding_target chunk'],
            },
        ],
    },
    {
        manifold: 'product',
        manifoldRole: 'cross_family_bridge',
        label: 'Product cross-family bridge',
        scoreInterpretation: 'Cross-lane bridge support across entity, frame, event, relation, temporal, causal, and evidence families.',
        candidateKinds: ['entity_link', 'relation_link', 'missing_frame'],
        contributionRules: [
            {
                id: 'product-source-bridge',
                description: 'Candidate already carries product manifold, product-lane, or bridge-edge evidence.',
                candidateKinds: ['entity_link', 'relation_link', 'missing_frame'],
                requiredSignals: ['source.manifold=product', 'product lane', 'bridge edge'],
            },
            {
                id: 'product-cross-lane-targets',
                description: 'Candidate spans multiple target lanes and should be interpreted as a cross-family bridge.',
                candidateKinds: ['entity_link', 'relation_link', 'missing_frame'],
                requiredSignals: ['multiple productLaneFeatures.dominantLane values'],
            },
        ],
    },
    {
        manifold: 'siegel',
        manifoldRole: 'structured_route',
        label: 'Siegel causal and temporal route',
        scoreInterpretation: 'Structured route support for causal branches, temporal chains, and tree-like path continuations.',
        candidateKinds: ['causal_bridge', 'temporal_bridge'],
        contributionRules: [
            {
                id: 'siegel-causal-route',
                description: 'Causal bridge follows a branch or structured route.',
                candidateKinds: ['causal_bridge'],
                requiredSignals: ['causal_fact', 'causal_bridge'],
            },
            {
                id: 'siegel-temporal-route',
                description: 'Temporal bridge follows ordered route evidence.',
                candidateKinds: ['temporal_bridge'],
                requiredSignals: ['temporal_fact', 'temporal_bridge'],
            },
        ],
    },
    {
        manifold: 'lorentz',
        manifoldRole: 'hierarchy_compression',
        label: 'Lorentz hierarchy compression',
        scoreInterpretation: 'Root-to-leaf compression support for hierarchy, ancestry, boundary, and backbone relations.',
        candidateKinds: ['entity_link', 'relation_link', 'missing_frame', 'outlier_review'],
        contributionRules: [
            {
                id: 'lorentz-root-compression',
                description: 'Candidate connects roots, leaves, chunks, entities, or backbone/boundary regions.',
                candidateKinds: ['entity_link', 'relation_link', 'missing_frame', 'outlier_review'],
                requiredSignals: ['entity:*', 'chunk:*', 'backbone', 'boundary'],
            },
        ],
    },
    {
        manifold: 'hyperbolic',
        manifoldRole: 'ancestry_depth',
        label: 'Hyperbolic ancestry depth',
        scoreInterpretation: 'Depth and ancestry pressure when a candidate spans broad support paths or compressed hierarchies.',
        candidateKinds: ['entity_link', 'relation_link', 'missing_frame', 'outlier_review'],
        contributionRules: [
            {
                id: 'hyperbolic-depth-pressure',
                description: 'Candidate has enough support breadth or hierarchy depth to deserve ancestry review.',
                candidateKinds: ['entity_link', 'relation_link', 'missing_frame', 'outlier_review'],
                requiredSignals: ['sourceTargetIds.length>2', 'multi-evidence support'],
            },
        ],
    },
];

export function buildGraphManifoldSpecializationSummary(
    snapshot: GraphRebuildSnapshot,
    candidates: GraphSemanticCandidateSummary | undefined,
    generatedAt = snapshot.builtAt,
    derivationContext?: GraphSemanticDerivationContext,
): GraphManifoldSpecializationSummary {
    const context: SpecializationContext = {
        targetRows: derivationContext?.targetRows()
            || new Map((snapshot.embeddingGraphPostProcess?.targets || []).map((row) => [row.targetId, row])),
    };
    const builder = new ManifoldSpecializationBuilder(snapshot.id, generatedAt);
    for (const candidate of candidates?.candidates || []) {
        for (const draft of candidateContributionDrafts(candidate, context).slice(0, PER_CANDIDATE_LIMIT)) {
            builder.add(draft);
        }
    }
    const summary = builder.summary(candidates?.candidates || []);
    attachManifoldContributionIds(candidates, summary);
    return summary;
}

function attachManifoldContributionIds(
    candidates: GraphSemanticCandidateSummary | undefined,
    summary: GraphManifoldSpecializationSummary,
): void {
    if (!candidates) return;
    const idsByCandidate = new Map<string, string[]>();
    for (const contribution of summary.contributions) {
        const ids = idsByCandidate.get(contribution.candidateId) || [];
        ids.push(contribution.id);
        idsByCandidate.set(contribution.candidateId, ids);
    }
    for (const candidate of candidates.candidates) {
        const ids = idsByCandidate.get(candidate.id);
        if (ids?.length) candidate.manifoldContributionIds = ids;
    }
}

function candidateContributionDrafts(
    candidate: GraphSemanticCandidate,
    context: SpecializationContext,
): ContributionDraft[] {
    const drafts: ContributionDraft[] = [];
    const directManifolds = new Set(candidate.sources
        .map((source) => normalizeManifold(source.manifold))
        .filter((value): value is GraphSemanticManifoldKind => Boolean(value)));
    for (const manifold of directManifolds) {
        drafts.push(draft(candidate, manifold, sourceRuleForManifold(manifold, candidate.kind), directScore(candidate, manifold), [
            `source manifold signal:${manifold}`,
        ]));
    }

    const sourceKinds = new Set(candidate.sources.map((source) => source.kind));
    const sourceLabels = candidate.sources.map((source) => source.label.toLowerCase()).join(' ');
    const targetLaneSet = targetLanes(candidate, context);
    const targetRegionRoles = targetRegions(candidate, context);
    const hasIdentitySignal = sourceKinds.has('identity_linker')
        || candidate.sourceTargetIds.some((id) => id.startsWith('identity:') || id.startsWith('mention:') || id.startsWith('surface:'));
    const hasEvidenceContainment = candidate.evidenceIds.length > 0
        || candidate.sourceTargetIds.some((id) => /^(note|chunk|anchor|evidence):/.test(id))
        || sourceKinds.has('evidence_anchor')
        || sourceKinds.has('frame_gap');

    if (isHybridCandidate(candidate, directManifolds, sourceKinds)) {
        drafts.push(draft(candidate, 'hybrid', 'hybrid-general-retrieval', baseScore(candidate, 0.04), [
            'balanced retrieval candidate',
            `sources:${[...sourceKinds].sort().join(',')}`,
        ]));
    }
    if (candidate.kind === 'entity_link' && hasIdentitySignal) {
        drafts.push(draft(candidate, 'hopf', 'hopf-identity-cycle', baseScore(candidate, 0.1), [
            'identity/alias loop review',
            `targets:${candidate.sourceTargetIds.slice(0, 4).join(',')}`,
        ]));
    }
    if ((candidate.kind === 'contradiction_review' || candidate.kind === 'outlier_review')
        && /alias|duplicate|brittle|singleton|outlier/.test(`${sourceLabels} ${candidate.rationale.join(' ').toLowerCase()}`)) {
        drafts.push(draft(candidate, 'hopf', 'hopf-recurrence-review', baseScore(candidate, 0.02), [
            'recurrence anomaly pressure',
            `rationale:${candidate.rationale[0] || 'review'}`,
        ]));
    }
    if (hasEvidenceContainment && profile('caps').candidateKinds.includes(candidate.kind)) {
        drafts.push(draft(candidate, 'caps', candidate.kind === 'missing_frame' ? 'caps-frame-root' : 'caps-evidence-containment', baseScore(candidate, 0.06), [
            'document/evidence containment support',
            `evidence:${candidate.evidenceIds.length}`,
        ]));
    }
    if (isProductCandidate(candidate, directManifolds, targetLaneSet, sourceLabels)) {
        drafts.push(draft(candidate, 'product', directManifolds.has('product') ? 'product-source-bridge' : 'product-cross-lane-targets', productScore(candidate, targetLaneSet), [
            `lanes:${[...targetLaneSet].sort().join(',') || 'source-bridge'}`,
            `targets:${candidate.sourceTargetIds.length}`,
        ]));
    }
    if (candidate.kind === 'causal_bridge' || sourceKinds.has('causal_fact')) {
        drafts.push(draft(candidate, 'siegel', 'siegel-causal-route', baseScore(candidate, 0.12), [
            'causal branch/path candidate',
            `evidence:${candidate.evidenceIds.length}`,
        ]));
    }
    if (candidate.kind === 'temporal_bridge' || sourceKinds.has('temporal_fact')) {
        drafts.push(draft(candidate, 'siegel', 'siegel-temporal-route', baseScore(candidate, 0.1), [
            'temporal route candidate',
            `evidence:${candidate.evidenceIds.length}`,
        ]));
    }
    if (isLorentzCandidate(candidate, targetRegionRoles)) {
        drafts.push(draft(candidate, 'lorentz', 'lorentz-root-compression', baseScore(candidate, 0.03), [
            `region_roles:${[...targetRegionRoles].sort().join(',') || 'root-leaf'}`,
            `source_targets:${candidate.sourceTargetIds.length}`,
        ]));
    }
    if (isHyperbolicCandidate(candidate, targetLaneSet)) {
        drafts.push(draft(candidate, 'hyperbolic', 'hyperbolic-depth-pressure', baseScore(candidate, -0.01), [
            'support breadth/depth pressure',
            `source_targets:${candidate.sourceTargetIds.length}`,
        ]));
    }

    return dedupeDrafts(drafts).sort((left, right) =>
        right.score - left.score
        || manifoldRank(left.manifold) - manifoldRank(right.manifold)
        || left.ruleId.localeCompare(right.ruleId));
}

class ManifoldSpecializationBuilder {
    private readonly contributions: GraphManifoldCandidateContribution[] = [];
    private readonly receipts: GraphManifoldSpecializationReceipt[] = [];
    private readonly seen = new Set<string>();
    private readonly manifoldCounts = new Map<GraphSemanticManifoldKind, number>();

    constructor(private readonly snapshotId: string, private readonly generatedAt: number) {}

    add(row: ContributionDraft): void {
        if (this.contributions.length >= MAX_CONTRIBUTIONS) return;
        const count = this.manifoldCounts.get(row.manifold) || 0;
        if (count >= PER_MANIFOLD_LIMIT) return;
        const key = `${row.candidate.id}|${row.manifold}|${row.ruleId}`;
        if (this.seen.has(key)) return;
        this.seen.add(key);
        this.manifoldCounts.set(row.manifold, count + 1);
        const id = `manifold-contribution:${row.manifold}:${slug(key)}`;
        const receiptId = `manifold-receipt:${slug(id)}`;
        const profileRow = profile(row.manifold);
        this.contributions.push({
            id,
            candidateId: row.candidate.id,
            candidateKind: row.candidate.kind,
            manifold: row.manifold,
            manifoldRole: profileRow.manifoldRole,
            ruleId: row.ruleId,
            score: round(clamp(row.score, 0, 1)),
            scoreInterpretation: profileRow.scoreInterpretation,
            sourceTargetIds: unique(row.sourceTargetIds).slice(0, 12),
            evidenceIds: unique(row.evidenceIds).slice(0, 12),
            rationale: row.rationale,
            reversibleReceiptId: receiptId,
        });
        this.receipts.push({
            id: receiptId,
            contributionId: id,
            candidateId: row.candidate.id,
            manifold: row.manifold,
            reversible: true,
            mutationAllowed: false,
            invariant: 'phase3_no_topology_commit',
            evidenceIds: unique(row.evidenceIds).slice(0, 12),
            undoHint: 'no graph mutation was performed; drop this manifold contribution to undo',
            detail: `${row.manifold}:${profileRow.manifoldRole} explained ${row.candidate.kind}`,
        });
    }

    summary(candidates: GraphSemanticCandidate[]): GraphManifoldSpecializationSummary {
        const contributions = this.contributions.sort((left, right) =>
            right.score - left.score
            || left.manifold.localeCompare(right.manifold)
            || left.id.localeCompare(right.id));
        return {
            schemaVersion: 'phoenix-manifold-specialization/v1',
            generatedAt: this.generatedAt,
            sourceSnapshotId: this.snapshotId,
            profiles: PROFILES,
            contributions,
            receipts: this.receipts,
            counters: contributionCounters(candidates, contributions, this.receipts),
        };
    }
}

function draft(
    candidate: GraphSemanticCandidate,
    manifold: GraphSemanticManifoldKind,
    ruleId: string,
    score: number,
    rationale: string[],
): ContributionDraft {
    return {
        candidate,
        manifold,
        ruleId,
        score,
        sourceTargetIds: candidate.sourceTargetIds,
        evidenceIds: candidate.evidenceIds,
        rationale: compact(rationale).join(' | '),
    };
}

function isHybridCandidate(
    candidate: GraphSemanticCandidate,
    directManifolds: Set<GraphSemanticManifoldKind>,
    sourceKinds: Set<string>,
): boolean {
    if (!profile('hybrid').candidateKinds.includes(candidate.kind)) return false;
    return directManifolds.has('hybrid')
        || sourceKinds.has('semantic_task')
        || sourceKinds.has('graph_postprocess')
        || sourceKinds.has('embedding_target');
}

function isProductCandidate(
    candidate: GraphSemanticCandidate,
    directManifolds: Set<GraphSemanticManifoldKind>,
    targetLaneSet: Set<GraphRebuildProductLaneKind>,
    sourceLabels: string,
): boolean {
    if (!profile('product').candidateKinds.includes(candidate.kind)) return false;
    return directManifolds.has('product')
        || targetLaneSet.size > 1
        || /bridge|cross|product|relation|frame/.test(sourceLabels);
}

function isLorentzCandidate(candidate: GraphSemanticCandidate, regionRoles: Set<string>): boolean {
    if (!profile('lorentz').candidateKinds.includes(candidate.kind)) return false;
    return candidate.sourceTargetIds.some((id) => /^(entity|chunk|note):/.test(id))
        || regionRoles.has('backbone')
        || regionRoles.has('boundary')
        || regionRoles.has('core');
}

function isHyperbolicCandidate(candidate: GraphSemanticCandidate, lanes: Set<GraphRebuildProductLaneKind>): boolean {
    if (!profile('hyperbolic').candidateKinds.includes(candidate.kind)) return false;
    return candidate.sourceTargetIds.length > 2
        || candidate.evidenceIds.length > 2
        || lanes.size > 1;
}

function targetLanes(
    candidate: GraphSemanticCandidate,
    context: SpecializationContext,
): Set<GraphRebuildProductLaneKind> {
    const lanes = new Set<GraphRebuildProductLaneKind>();
    for (const targetId of candidate.sourceTargetIds) {
        const lane = context.targetRows.get(targetId)?.productLaneFeatures.dominantLane;
        if (lane) lanes.add(lane);
    }
    return lanes;
}

function targetRegions(candidate: GraphSemanticCandidate, context: SpecializationContext): Set<string> {
    const roles = new Set<string>();
    for (const targetId of candidate.sourceTargetIds) {
        const role = context.targetRows.get(targetId)?.productTopologyRegion.role;
        if (role) roles.add(role);
    }
    return roles;
}

function directScore(candidate: GraphSemanticCandidate, manifold: GraphSemanticManifoldKind): number {
    const specialistBoost = manifold === 'siegel' || manifold === 'product' || manifold === 'hopf' ? 0.08 : 0.04;
    return baseScore(candidate, specialistBoost);
}

function productScore(candidate: GraphSemanticCandidate, lanes: Set<GraphRebuildProductLaneKind>): number {
    return baseScore(candidate, Math.min(0.14, lanes.size * 0.04));
}

function baseScore(candidate: GraphSemanticCandidate, boost: number): number {
    return round(clamp(candidate.rank * 0.52 + candidate.confidence * 0.34 + (1 - candidate.noiseScore) * 0.14 + boost, 0, 1));
}

function normalizeManifold(value: string | undefined): GraphSemanticManifoldKind | null {
    if (!value) return null;
    const lowered = value.toLowerCase();
    if (lowered === 'hybrid' || lowered === 'hopf' || lowered === 'caps' || lowered === 'product'
        || lowered === 'siegel' || lowered === 'lorentz' || lowered === 'hyperbolic') {
        return lowered;
    }
    if (lowered === 'cap') return 'caps';
    if (PRODUCT_LANES.has(lowered)) return 'product';
    return null;
}

function sourceRuleForManifold(
    manifold: GraphSemanticManifoldKind,
    candidateKind: GraphSemanticCandidateKind,
): string {
    if (manifold === 'hybrid') return 'hybrid-source-neighborhood';
    if (manifold === 'hopf') return candidateKind === 'outlier_review' ? 'hopf-recurrence-review' : 'hopf-identity-cycle';
    if (manifold === 'caps') return candidateKind === 'missing_frame' ? 'caps-frame-root' : 'caps-evidence-containment';
    if (manifold === 'product') return 'product-source-bridge';
    if (manifold === 'siegel') return candidateKind === 'temporal_bridge' ? 'siegel-temporal-route' : 'siegel-causal-route';
    if (manifold === 'lorentz') return 'lorentz-root-compression';
    return 'hyperbolic-depth-pressure';
}

function profile(manifold: GraphSemanticManifoldKind): GraphManifoldRoleProfile {
    return PROFILES.find((row) => row.manifold === manifold)!;
}

function contributionCounters(
    candidates: GraphSemanticCandidate[],
    contributions: GraphManifoldCandidateContribution[],
    receipts: GraphManifoldSpecializationReceipt[],
): GraphManifoldSpecializationCounters {
    const explained = new Set(contributions.map((row) => row.candidateId));
    return {
        byManifold: countBy(contributions, (row) => row.manifold),
        byRole: countBy(contributions, (row) => row.manifoldRole),
        byCandidateKind: countBy(contributions, (row) => row.candidateKind),
        contributionCount: contributions.length,
        explainedCandidateCount: explained.size,
        unexplainedCandidateCount: Math.max(0, candidates.length - explained.size),
        receiptCount: receipts.length,
        reversibleReceiptCount: receipts.filter((receipt) => receipt.reversible).length,
        mutationAllowedCount: receipts.filter((receipt) => receipt.mutationAllowed).length,
        maxContributions: MAX_CONTRIBUTIONS,
    };
}

function dedupeDrafts(values: ContributionDraft[]): ContributionDraft[] {
    const seen = new Set<string>();
    return values.filter((row) => {
        const key = `${row.candidate.id}|${row.manifold}|${row.ruleId}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function manifoldRank(manifold: GraphSemanticManifoldKind): number {
    return ['product', 'siegel', 'hopf', 'caps', 'lorentz', 'hyperbolic', 'hybrid'].indexOf(manifold);
}

function countBy<T>(values: T[], keyFn: (value: T) => string): Record<string, number> {
    const counts = new Map<string, number>();
    for (const value of values) {
        const key = keyFn(value);
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Object.fromEntries([...counts.entries()].sort(([left], [right]) => left.localeCompare(right)));
}

function compact(values: Array<string | null | undefined>): string[] {
    return values.filter((value): value is string => Boolean(value && value.trim()));
}

function unique<T>(values: T[]): T[] {
    return [...new Set(values)];
}

function slug(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9:]+/g, '-').replace(/^-|-$/g, '').slice(0, 112) || 'x';
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value));
}

function round(value: number): number {
    return Math.round(value * 1000) / 1000;
}
