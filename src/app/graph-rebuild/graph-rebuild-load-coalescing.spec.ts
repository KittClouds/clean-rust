import '@angular/compiler';
import { Injector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { describe, expect, it, vi } from 'vitest';

import { PhoenixBackendService } from '../services/phoenix-backend.service';
import { PhoenixStoreService } from '../services/phoenix-store.service';
import { GraphRebuildService } from './graph-rebuild.service';

describe('GraphRebuildService persisted snapshot loading', () => {
    it('coalesces concurrent same-scope hydration into one durable read', async () => {
        let finishRead!: (value: null) => void;
        const read = new Promise<null>((resolve) => { finishRead = resolve; });
        const store = { getScopedDocument: vi.fn(() => read) };
        const injector = createEnvironmentInjector([
            { provide: PhoenixStoreService, useValue: store },
            { provide: PhoenixBackendService, useValue: { target: 'web' } },
        ], Injector.create({ providers: [] }));
        const service = runInInjectionContext(injector, () => new GraphRebuildService());

        const first = service.loadPersistedSnapshot('global');
        const second = service.loadPersistedSnapshot('global');

        expect(store.getScopedDocument).toHaveBeenCalledTimes(1);
        finishRead(null);
        await expect(Promise.all([first, second])).resolves.toEqual([null, null]);
        injector.destroy();
    });
});
