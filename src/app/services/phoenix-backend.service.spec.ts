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
});
