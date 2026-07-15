import '@angular/compiler';
import { Injector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { afterEach, describe, expect, it } from 'vitest';

import { ATLAS_RICH_SCAN_QUARANTINE_MESSAGE } from './atlas-rich-scan-quarantine';
import { AtlasScanCoordinatorService } from './atlas-scan-coordinator.service';

describe('legacy Atlas rich scan quarantine', () => {
    const injector = createEnvironmentInjector([], Injector.create({ providers: [] }));

    afterEach(() => injector.destroy());

    it('constructs without runtime dependencies and rejects before a job can start', async () => {
        const service = runInInjectionContext(injector, () => new AtlasScanCoordinatorService());

        expect(service.running()).toBe(false);
        expect(service.lastResult()).toBeNull();
        await expect(service.runRichEmbeddingScan()).rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
        expect(service.running()).toBe(false);
        expect(service.lastResult()).toBeNull();
    });
});
