import '@angular/compiler';
import {
    Injector,
    createEnvironmentInjector,
    runInInjectionContext,
    type EnvironmentInjector,
} from '@angular/core';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
    PhoenixBackendService,
    withPhoenixStoreCommandTimeout,
} from './phoenix-backend.service';
import { ATLAS_RICH_SCAN_QUARANTINE_MESSAGE } from './atlas-rich-scan-quarantine';

describe('Phoenix store command watchdog', () => {
    it('returns completed commands without waiting for the watchdog', async () => {
        await expect(withPhoenixStoreCommandTimeout('note:list', Promise.resolve(['n1']), 25))
            .resolves.toEqual(['n1']);
    });

    it('rejects a wedged command with its command identity', async () => {
        const never = new Promise<never>(() => undefined);
        await expect(withPhoenixStoreCommandTimeout('note:list', never, 1))
            .rejects.toThrow('Phoenix store command timed out after 1 ms: note:list');
    });
});

describe('PhoenixBackendService native runtime guard', () => {
    let injector: EnvironmentInjector;
    let previousWindowDescriptor: PropertyDescriptor | undefined;

    beforeEach(() => {
        previousWindowDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'window');
        Object.defineProperty(globalThis, 'window', {
            configurable: true,
            value: {
                __PHOENIX_RUNTIME_TARGET__: 'native',
                __TAURI_INTERNALS__: {},
                __PHOENIX_NATIVE_BACKEND__: { isReady: false },
            },
        });
        injector = createEnvironmentInjector([], Injector.create({ providers: [] }));
    });

    afterEach(() => {
        injector.destroy();
        if (previousWindowDescriptor) {
            Object.defineProperty(globalThis, 'window', previousWindowDescriptor);
        } else {
            delete (globalThis as { window?: unknown }).window;
        }
    });

    it('rejects loadWasm on native desktop', async () => {
        const service = runInInjectionContext(injector, () => new PhoenixBackendService());

        await expect(service.loadWasm()).rejects.toThrow('disabled in native desktop');
    });

    it('rejects the legacy Atlas rich scan before consulting the native bridge', async () => {
        const service = runInInjectionContext(injector, () => new PhoenixBackendService());

        await expect(service.atlasRichScan({ documents: [{ text: 'must not cross' }] }))
            .rejects.toThrow(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
    });

    it('fails closed when the verified FORCE v2 capability is absent', async () => {
        const service = runInInjectionContext(injector, () => new PhoenixBackendService());

        await expect(service.forceRebuildV2Shadow({ contractVersion: 'phoenix-verified-force/v2' }))
            .rejects.toThrow('PHX_FORCE_V2_CAPABILITY_MISSING');
    });
});
