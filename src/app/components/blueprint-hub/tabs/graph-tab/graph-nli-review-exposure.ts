export interface GraphNliReviewExposure {
    decision: string;
    nliSource: string;
    nliRole: string;
    confidenceMillis: number | null;
    entailmentMillis: number | null;
    contradictionMillis: number | null;
    neutralMillis: number | null;
    routeSource: string;
    routeRole: string;
    routeLabel: string;
    routeScoreMillis: number | null;
    claimId: string;
    evidenceId: string;
    evidenceRefs: string[];
    receiptIds: string[];
}

export function nliReviewExposure(decisionEvidence: string[]): GraphNliReviewExposure | null {
    const evidence = evidenceValues(decisionEvidence);
    const decision = firstEvidence(evidence, 'nli_decision');
    if (!decision) return null;
    const routeLabel = firstEvidence(evidence, 'classification_label');
    return {
        decision,
        nliSource: firstEvidence(evidence, 'nli_source') || 'modernBertNli',
        nliRole: firstEvidence(evidence, 'nli_role'),
        confidenceMillis: numberEvidence(evidence, 'nli_confidence_millis'),
        entailmentMillis: numberEvidence(evidence, 'nli_entailment_millis'),
        contradictionMillis: numberEvidence(evidence, 'nli_contradiction_millis'),
        neutralMillis: numberEvidence(evidence, 'nli_neutral_millis'),
        routeSource: firstEvidence(evidence, 'classification_source') || (routeLabel ? 'gliclass' : ''),
        routeRole: firstEvidence(evidence, 'classification_role'),
        routeLabel,
        routeScoreMillis: numberEvidence(evidence, 'classification_score_millis'),
        claimId: firstEvidence(evidence, 'claim'),
        evidenceId: firstEvidence(evidence, 'evidence'),
        evidenceRefs: evidenceList(evidence, 'evidence_ref'),
        receiptIds: unique([
            ...evidenceList(evidence, 'receipt'),
            firstEvidence(evidence, 'judgment'),
        ]),
    };
}

export function nliReviewDetail(nli: GraphNliReviewExposure): string {
    return [
        `NLI ${titleCase(nli.decision)}`,
        nli.routeLabel ? `${modelLabel(nli.routeSource)} ${nli.routeLabel}` : '',
        nli.confidenceMillis === null ? '' : `${percentMillis(nli.confidenceMillis)} confidence`,
    ].filter(Boolean).join(' / ');
}

export function nliReviewFacts(nli: GraphNliReviewExposure | null): Array<{ label: string; value: string }> {
    if (!nli) return [];
    return [
        fact('NLI vote', [
            titleCase(nli.decision),
            modelLabel(nli.nliSource),
            titleCase(nli.nliRole),
        ].filter(Boolean).join(' / ')),
        fact('GLiClass route', [
            nli.routeLabel,
            nli.routeScoreMillis === null ? '' : percentMillis(nli.routeScoreMillis),
            titleCase(nli.routeRole),
        ].filter(Boolean).join(' / ')),
        fact('NLI confidence', nli.confidenceMillis === null ? '' : percentMillis(nli.confidenceMillis)),
        fact('NLI scores', nliScoreSummary(nli)),
        fact('Receipts', nli.receiptIds.join(' / ')),
        fact('Claim', nli.claimId),
        fact('Evidence', [nli.evidenceId, ...nli.evidenceRefs].filter(Boolean).join(' / ')),
        fact('Graph impact', 'review vote only / no topology commit'),
    ];
}

export function nliVoteTag(nli: GraphNliReviewExposure): string {
    return `nli:${nli.decision}`;
}

export function nliRouteTag(nli: GraphNliReviewExposure): string {
    return nli.routeLabel ? `${nli.routeSource || 'route'}:${nli.routeLabel}` : '';
}

function nliScoreSummary(nli: GraphNliReviewExposure): string {
    return [
        scorePart('entailment', nli.entailmentMillis),
        scorePart('contradiction', nli.contradictionMillis),
        scorePart('neutral', nli.neutralMillis),
    ].filter(Boolean).join(' / ');
}

function scorePart(labelValue: string, millis: number | null): string {
    return millis === null ? '' : `${labelValue} ${percentMillis(millis)}`;
}

function evidenceValues(entries: string[]): Map<string, string[]> {
    const values = new Map<string, string[]>();
    for (const entry of entries) {
        const separator = entry.indexOf(':');
        if (separator <= 0) continue;
        const key = entry.slice(0, separator).trim();
        const value = entry.slice(separator + 1).trim();
        if (!key || !value) continue;
        values.set(key, [...(values.get(key) || []), value]);
    }
    return values;
}

function firstEvidence(values: Map<string, string[]>, key: string): string {
    return values.get(key)?.[0] || '';
}

function evidenceList(values: Map<string, string[]>, key: string): string[] {
    return values.get(key) || [];
}

function numberEvidence(values: Map<string, string[]>, key: string): number | null {
    const value = Number(firstEvidence(values, key));
    return Number.isFinite(value) ? value : null;
}

function percentMillis(value: number): string {
    return `${Math.round(Math.max(0, Math.min(1, value / 1000)) * 100)}%`;
}

function modelLabel(value: string): string {
    if (value === 'modernBertNli') return 'ModernBERT NLI';
    if (value === 'gliclass') return 'GLiClass';
    return titleCase(value);
}

function fact(label: string, value: unknown): { label: string; value: string } {
    return { label, value: String(value ?? '').trim() };
}

function unique(values: Array<string | undefined>): string[] {
    return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
}

function titleCase(value: string): string {
    return value
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}
