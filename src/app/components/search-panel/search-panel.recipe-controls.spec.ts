import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import {
    ATLAS_GRAPH_BUILD_RECIPE_IDS,
    atlasCapabilityById,
    atlasRecipeDefinitionById,
} from './atlas-capability.model';

const template = readFileSync(new URL('./search-panel.component.html', import.meta.url), 'utf8');

describe('SearchPanelComponent recipe controls', () => {
    it('keeps graph recipe execution controls visible in the Atlas panel', () => {
        expect(template).toContain('class="recipe-control-deck"');
        expect(template).toContain('(click)="warmSelectedRecipeModels()"');
        expect(template).toContain('(click)="runSelectedRecipe()"');
        expect(template).toContain('selectedPipelineRail()');
        expect(template).toContain('selectedRecipePlan().operations.length');
    });

    it('routes the adjudicated semantic recipe through the NLI capability contract', () => {
        expect(ATLAS_GRAPH_BUILD_RECIPE_IDS).toContain('adjudicatedSemanticGraph');

        const recipe = atlasRecipeDefinitionById('adjudicatedSemanticGraph');
        const capability = atlasCapabilityById('nliAdjudication');

        expect(recipe.requiredCapabilities).toContain('nliAdjudication');
        expect(recipe.requiredLanes).toContain('nli');
        expect(recipe.backendRoute).toContain('semantic:listNliJudgmentInputs');
        expect(recipe.backendRoute).toContain('semantic:applyNliJudgments');
        expect(capability.backendRoute).toContain('NliWorkerService.classifyStream');
    });
});
