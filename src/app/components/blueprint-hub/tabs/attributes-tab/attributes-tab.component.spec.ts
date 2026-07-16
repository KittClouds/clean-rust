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
        expect(template).toContain('atlas-workflow-strip');
        expect(template).toContain('workflowSteps');
        expect(template).toContain('<app-search-panel');
        expect(template).toContain('<app-atlas-control-rooms');
        expect(template).toContain('[contract]="atlasControlContract()"');
        expect(template).toContain('[paging]="atlasProofPaging()"');
        expect(template).toContain('(nextPageRequested)="loadNextAtlasProofPage()"');
        expect(template).toContain('(actionRequested)="dispatchRoomAction($event)"');
        expect(template).toContain('(roomChange)="setOperatingRoom($event)"');

        expect(template).not.toContain('reviewAdjudicationContract');
        expect(template).not.toContain('reviewDeck()');
        expect(template).not.toContain('Promotion Cockpit');
        expect(template).not.toContain('atlas-governance-queue');
        expect(template).not.toContain('<app-graph-entity-sidebar');
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
