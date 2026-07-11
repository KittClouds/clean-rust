import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));

describe('BlueprintHubComponent tab retention', () => {
    it('keeps one isolated Graph layer mounted while switching operating surfaces', () => {
        const template = readFileSync(join(here, 'blueprint-hub.component.html'), 'utf8');
        const styles = readFileSync(join(here, 'blueprint-hub.component.css'), 'utf8');
        const graphHosts = template.match(/<app-graph-tab/g) || [];

        expect(graphHosts).toHaveLength(1);
        expect(template).toContain("[class.blueprint-hub-tab-layer--active]=\"activeTab() === 'graph'\"");
        expect(template).toContain("[class.blueprint-hub-tab-layer--inactive]=\"activeTab() !== 'graph'\"");
        expect(template).toContain("[attr.inert]=\"activeTab() !== 'graph' ? '' : null\"");
        expect(template).toContain("@if (activeTab() !== 'graph')");
        expect(template).not.toContain("@case ('graph')");
        expect(template).toContain('<app-attributes-tab class="blueprint-hub-tab-layer blueprint-hub-tab-layer--active">');
        expect(styles).toContain('.blueprint-hub-tab-layer--inactive');
        expect(styles).toContain('visibility: hidden');
        expect(styles).toContain('pointer-events: none');
        expect(template).not.toContain('[class.hidden]');
    });
});
