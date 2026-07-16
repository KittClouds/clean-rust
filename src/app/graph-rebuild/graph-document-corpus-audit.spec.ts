import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { buildGraphDocumentSidecar } from './graph-document-sidecar';
import { buildAdaptiveGraphRebuildChunks } from './graph-rebuild-meaning-frames';

interface CorpusDocument {
    id: string;
    title: string;
    domain: string;
    sourceType: 'local_story' | 'government_article' | 'wikipedia' | 'arxiv';
    path: string;
}

interface CorpusManifest {
    schemaVersion: string;
    documents: CorpusDocument[];
}

interface NativeProfileDocument {
    id: string;
    dominantProfile: string;
    confidence: number;
}

interface NativeProfileReport {
    schemaVersion: string;
    documents: NativeProfileDocument[];
}

interface SidecarAuditRow {
    id: string;
    title: string;
    domain: string;
    sourceType: string;
    chars: number;
    chunks: number;
    sidecarUnits: number;
    sections: number;
    paragraphGroups: number;
    paragraphs: number;
    rhetoricalUnits: number;
    graphFactCandidates: number;
    evidenceSpans: number;
    dialogueBlocks: number;
    actionBlocks: number;
    chapters: number;
    scenes: number;
    orphanLeafChunks: number;
    userAnchorPromotions: number;
    nativeProfile: string;
    compatibilityProfile: string;
    profileParity: boolean;
    elapsedMs: number;
}

const corpusRoot = resolve(process.cwd(), 'target', 'document-profile-corpus');
const manifestPath = resolve(corpusRoot, 'manifest.json');
const nativeReportPath = resolve(corpusRoot, 'report.json');
const sidecarReportPath = resolve(corpusRoot, 'sidecar-report.json');

describe('document sidecar corpus audit', () => {
    it('keeps diverse documents inspectable without manufacturing anchors', () => {
        const manifest = readJson<CorpusManifest>(manifestPath);
        const nativeReport = readJson<NativeProfileReport>(nativeReportPath);
        const nativeProfiles = new Map(nativeReport.documents.map((document) => [document.id, document]));
        const rows: SidecarAuditRow[] = [];

        expect(manifest.schemaVersion).toBe('phoenix-document-profile-corpus/v1');
        expect(nativeReport.schemaVersion).toBe('phoenix-document-profile-corpus-report/v1');
        expect(manifest.documents.length).toBeGreaterThanOrEqual(10);

        for (const document of manifest.documents) {
            const startedAt = performance.now();
            const text = readFileSync(document.path, 'utf8');
            const chunks = buildAdaptiveGraphRebuildChunks(document.id, text);
            const sidecar = buildGraphDocumentSidecar({
                noteIds: [document.id],
                noteTexts: { [document.id]: text },
                chunks,
                builtAt: 1,
            });
            const leafChunkIds = new Set(
                sidecar.retrievalUnits
                    .filter((unit) => unit.kind === 'leaf_chunk')
                    .flatMap((unit) => unit.targetChunkIds),
            );
            const nativeProfile = nativeProfiles.get(document.id);
            const compatibilityProfile = sidecar.documentProfileSummary?.profiles[0];
            const row: SidecarAuditRow = {
                id: document.id,
                title: document.title,
                domain: document.domain,
                sourceType: document.sourceType,
                chars: text.length,
                chunks: chunks.length,
                sidecarUnits: sidecar.counters.units,
                sections: sidecar.counters.sections,
                paragraphGroups: sidecar.counters.paragraphGroups,
                paragraphs: sidecar.counters.paragraphs,
                rhetoricalUnits: sidecar.counters.rhetoricalUnits,
                graphFactCandidates: sidecar.counters.graphFactCandidates,
                evidenceSpans: sidecar.counters.evidenceSpans,
                dialogueBlocks: sidecar.counters.byKind.dialogue_block || 0,
                actionBlocks: sidecar.counters.byKind.action_block || 0,
                chapters: sidecar.counters.byKind.chapter || 0,
                scenes: sidecar.counters.byKind.scene || 0,
                orphanLeafChunks: chunks.filter((chunk) => !leafChunkIds.has(chunk.id)).length,
                userAnchorPromotions: sidecar.counters.userAnchorPromotions,
                nativeProfile: nativeProfile?.dominantProfile || 'missing',
                compatibilityProfile: compatibilityProfile?.dominantProfile || 'missing',
                profileParity: nativeProfile?.dominantProfile === compatibilityProfile?.dominantProfile,
                elapsedMs: round3(performance.now() - startedAt),
            };
            rows.push(row);

            expect(chunks.length, `${document.id} chunks`).toBeGreaterThan(0);
            expect(chunks.every((chunk) =>
                chunk.start >= 0
                && chunk.end > chunk.start
                && chunk.end <= text.length
                && text.slice(chunk.start, chunk.end).trim().length > 0,
            ), `${document.id} invalid chunk ranges`).toBe(true);
            expect(sidecar.counters.leafChunks, `${document.id} leaf chunks`).toBe(chunks.length);
            expect(row.orphanLeafChunks, `${document.id} orphan chunks`).toBe(0);
            expect(row.paragraphs, `${document.id} paragraphs`).toBeGreaterThan(0);
            expect(row.evidenceSpans, `${document.id} evidence spans`).toBeGreaterThan(0);
            expect(row.userAnchorPromotions, `${document.id} anchor promotions`).toBe(0);
            expect(sidecar.units.every((unit) => unit.anchorPolicy === 'sidecar_only')).toBe(true);

            if (document.sourceType === 'local_story') {
                expect(row.dialogueBlocks + row.actionBlocks, `${document.id} prose blocks`).toBeGreaterThan(0);
            } else {
                expect(row.sections, `${document.id} sections`).toBeGreaterThan(0);
                expect(row.rhetoricalUnits, `${document.id} rhetoric`).toBeGreaterThan(0);
            }
        }

        const report = {
            schemaVersion: 'phoenix-document-sidecar-corpus-report/v1',
            documents: rows,
            summary: {
                documents: rows.length,
                totalChars: rows.reduce((sum, row) => sum + row.chars, 0),
                totalChunks: rows.reduce((sum, row) => sum + row.chunks, 0),
                totalSidecarUnits: rows.reduce((sum, row) => sum + row.sidecarUnits, 0),
                totalGraphFactCandidates: rows.reduce((sum, row) => sum + row.graphFactCandidates, 0),
                totalEvidenceSpans: rows.reduce((sum, row) => sum + row.evidenceSpans, 0),
                totalOrphanLeafChunks: rows.reduce((sum, row) => sum + row.orphanLeafChunks, 0),
                totalUserAnchorPromotions: rows.reduce((sum, row) => sum + row.userAnchorPromotions, 0),
                profileParityMatches: rows.filter((row) => row.profileParity).length,
                elapsedMs: round3(rows.reduce((sum, row) => sum + row.elapsedMs, 0)),
            },
        };
        writeFileSync(sidecarReportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
        console.info('sidecar-corpus-audit', JSON.stringify(report.summary));

        expect(report.summary.totalOrphanLeafChunks).toBe(0);
        expect(report.summary.totalUserAnchorPromotions).toBe(0);
    }, 60_000);
});

function readJson<T>(path: string): T {
    return JSON.parse(readFileSync(path, 'utf8')) as T;
}

function round3(value: number): number {
    return Math.round(value * 1000) / 1000;
}
