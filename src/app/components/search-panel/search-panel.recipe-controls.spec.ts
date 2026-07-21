import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import {
    ATLAS_GRAPH_BUILD_RECIPE_IDS,
    atlasCapabilityById,
    atlasRecipeDefinitionById,
} from './atlas-capability.model';

const template = readFileSync(new URL('./search-panel.component.html', import.meta.url), 'utf8');

describe('SearchPanelComponent recipe controls', () => {
    it('keeps the retired recipe lane out of the Atlas panel', () => {
        expect(template).not.toContain('class="recipe-control-deck"');
        expect(template).not.toContain('Selected lane');
        expect(template).not.toContain('selectedPipelineRail()');
        expect(template).not.toContain('selectedRecipePlan()');
        expect(template).toContain('(click)="loadGraphModels()"');
        expect(template).toContain('(click)="buildGraphAtlas()"');
        expect(template).toContain('(click)="embedAtlas()"');
        expect(template).toContain('stage8-workflow');
        expect(template).toContain('ModernBERT gates');
        expect(template).toContain('(click)="runModernBertNliReview()"');
    });

    it('keeps the adjudicated semantic recipe quarantined while preserving its NLI contract', () => {
        expect(ATLAS_GRAPH_BUILD_RECIPE_IDS).toContain('adjudicatedSemanticGraph');

        const recipe = atlasRecipeDefinitionById('adjudicatedSemanticGraph');
        const capability = atlasCapabilityById('nliAdjudication');

        expect(recipe.requiredCapabilities).toContain('nliAdjudication');
        expect(recipe.requiredLanes).toContain('nli');
        expect(recipe.backendRoute).toContain('QUARANTINED');
        expect(recipe.backendRoute).toContain('legacy atlas_rich_scan');
        expect(capability.backendRoute).toContain('NliWorkerService.classifyStream');
    });
});
