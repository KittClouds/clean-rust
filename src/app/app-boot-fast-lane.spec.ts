import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const appSource = readFileSync(join(here, 'app.component.ts'), 'utf8');
const bridgeSource = readFileSync(join(here, 'services/phoenix-taurpc-bridge.ts'), 'utf8');
const storeSource = readFileSync(join(here, 'services/phoenix-store.service.ts'), 'utf8');

describe('desktop boot fast-lane contract', () => {
    it('reveals the cached active note before awaiting native runtime hydration', () => {
        const cachedReveal = appSource.indexOf('restoreCachedActiveNote()');
        const nativeAwait = appSource.indexOf("this.setBootStep('phoenix:runtime:await')");

        expect(cachedReveal).toBeGreaterThan(-1);
        expect(nativeAwait).toBeGreaterThan(cachedReveal);
        expect(appSource.slice(cachedReveal, nativeAwait)).toContain('this.spinner.hide()');
    });

    it('marks native runtime ready before scheduling reward reconciliation', () => {
        const markReady = bridgeSource.indexOf('this.markReady(Boolean(info.ready))');
        const deferredObserver = bridgeSource.indexOf('this.deferNativeRewardHorizonObservation()', markReady);

        expect(markReady).toBeGreaterThan(-1);
        expect(deferredObserver).toBeGreaterThan(markReady);
        expect(bridgeSource.slice(markReady, deferredObserver)).not.toContain('await this.observeNativeRewardHorizons');
    });

    it('starts persistence metadata before awaiting runtime readiness', () => {
        const persistenceStart = storeSource.indexOf('const persistenceLoadPromise = this.persistence.loadManifestMeta()');
        const runtimeAwait = storeSource.indexOf('await this.phoenix.loadRuntime()', persistenceStart);
        const persistenceAwait = storeSource.indexOf('await persistenceLoadPromise', runtimeAwait);

        expect(persistenceStart).toBeGreaterThan(-1);
        expect(runtimeAwait).toBeGreaterThan(persistenceStart);
        expect(persistenceAwait).toBeGreaterThan(runtimeAwait);
    });
});
