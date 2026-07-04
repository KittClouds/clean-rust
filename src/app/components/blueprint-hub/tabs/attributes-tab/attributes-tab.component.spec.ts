import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../../../../../..');

describe('AttributesTabComponent', () => {
    it('hosts the unified atlas control surfaces', () => {
        const template = readFileSync(join(here, 'attributes-tab.component.html'), 'utf8');

        expect(template).toContain('Atlas Control');
        expect(template).toContain('Memory Governance');
        expect(template).toContain('runtimeDiagnostics');
        expect(template).toContain('Candidate decisions');
        expect(template).toContain('User pin source locked');
        expect(template).toContain('Compression bounded');
        expect(template).toContain('protected pins');
        expect(template).toContain('full proof rows');
        expect(template).toContain('bounded compression rows');
        expect(template).toContain('candidateRows');
        expect(template).toContain('Promotion Cockpit');
        expect(template).toContain('Candidate -> accepted truth');
        expect(template).toContain('Receipt gated');
        expect(template).toContain('rollback plans');
        expect(template).toContain('Witness count');
        expect(template).toContain('Temporal / causal fit');
        expect(template).toContain('NLI fit');
        expect(template).toContain('User override');
        expect(template).toContain('No durable proposal receipt verdicts');
        expect(template).toContain('Attention Required');
        expect(template).toContain('Exception lanes');
        expect(template).toContain('Negative Relation Audit');
        expect(template).toContain('<app-search-panel');
        expect(template).toContain('<app-graph-entity-sidebar');
    });

    it('replaces the hub placeholder for the attributes route', () => {
        const hubTemplate = readFileSync(
            join(root, 'src/app/components/blueprint-hub/blueprint-hub.component.html'),
            'utf8',
        );
        const hubService = readFileSync(
            join(root, 'src/app/components/blueprint-hub/blueprint-hub.service.ts'),
            'utf8',
        );

        expect(hubTemplate).toContain("@case ('attributes')");
        expect(hubTemplate).toContain('<app-attributes-tab');
        expect(hubService).toContain("label: 'Atlas Control'");
    });
});
