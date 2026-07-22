import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

// =============================================================================
// Phase 0: Global Polyfills (SYNC - before any async)
// =============================================================================

// Browser-global compatibility for frontend dependencies that expect global.
(window as any).global = window;

// Fix Vue 3 Feature Flags Warning (for @tiptap/vue-3)
(window as any).__VUE_OPTIONS_API__ = true;
(window as any).__VUE_PROD_DEVTOOLS__ = false;
(window as any).__VUE_PROD_HYDRATION_MISMATCH_DETAILS__ = false;

// Polyfill 'fs' to redirect writes to console (fixes panic masking)
(window as any).fs = {
  constants: {
    O_WRONLY: -1,
    O_RDWR: -1,
    O_CREAT: -1,
    O_TRUNC: -1,
    O_APPEND: -1,
    O_EXCL: -1,
    O_RDONLY: 0,
    O_SYNC: -1
  },
  writeSync(fd: number, buf: Uint8Array) {
    const output = new TextDecoder("utf-8").decode(buf);
    if (fd === 1) console.log(output);
    else console.error(output);
    return buf.length;
  },
  write(fd: number, buf: Uint8Array, offset: number, length: number, position: number | null, callback: (err: Error | null, n: number) => void) {
    if (offset !== 0 || length !== buf.length || position !== null) {
      callback(new Error("not implemented"), 0);
      return;
    }
    const n = this.writeSync(fd, buf);
    callback(null, n);
  },
  open(path: string, flags: any, mode: any, callback: (err: Error | null, fd: number) => void) {
    const err = new Error("not implemented");
    (err as any).code = "ENOSYS";
    callback(err, 0);
  },
  fsync(fd: number, callback: (err: Error | null) => void) { callback(null); },
};

// =============================================================================
// Phase 1: Angular Bootstrap
// =============================================================================

console.log('[Main] Starting application boot...');

bootstrapApplication(AppComponent, appConfig)
  .then(async (appRef) => {
    // Expose injector globally for non-DI contexts (e.g., registry dictionary rebuild)
    (window as any).__angularInjector = appRef.injector;
    console.log('[Main] Angular bootstrapped, injector exposed');

    if (new URLSearchParams(window.location.search).get('graphPerf') === '1') {
      const { installGraphBuildDesktopBaseline } = await import(
        './app/graph-rebuild/graph-build-desktop-baseline'
      );
      installGraphBuildDesktopBaseline(appRef.injector);
    }

    // =============================================================================
    // Phase 3: Dev Session Monitor (HMR Memory Leak Prevention)
    // =============================================================================
    // Only runs in development mode to warn about long sessions that accumulate
    // Vite HMR module wrappers in memory (~12KB per module × hundreds = 794MB+)
    if (!(window as any).ngDevMode?.isDevMode?.()) {
      return;
    }

    const SESSION_START = Date.now();
    const WARNING_THRESHOLD_MS = 2 * 60 * 60 * 1000; // 2 hours
    const CHECK_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes

    const checkSessionHealth = () => {
      const elapsed = Date.now() - SESSION_START;
      const hours = Math.floor(elapsed / (60 * 60 * 1000));
      const minutes = Math.floor((elapsed % (60 * 60 * 1000)) / (60 * 1000));

      if (elapsed > WARNING_THRESHOLD_MS) {
        console.warn(
          `⚠️ [Dev Health] Long session detected (${hours}h ${minutes}m).\n` +
          `   Vite HMR may have accumulated memory.\n` +
          `   Consider refreshing the page or opening a new tab.\n` +
          `   Check: DevTools → Memory → Search "__vite_injectQuery"`
        );
      } else {
        console.log(
          `[Dev Health] Session running for ${hours}h ${minutes}m. ` +
          `Memory health OK.`
        );
      }
    };

    // Initial check after 30 seconds (let app settle first)
    setTimeout(() => {
      checkSessionHealth();
      // Then check every 30 minutes
      setInterval(checkSessionHealth, CHECK_INTERVAL_MS);
    }, 30 * 1000);

    // Expose utility to check memory manually
    (window as any).__checkHmrMemory = () => {
      checkSessionHealth();
      console.log(
        `[Dev Health] To check HMR memory:\n` +
        `   1. Open DevTools → Memory\n` +
        `   2. Take a heap snapshot\n` +
        `   3. Search for "__vite_injectQuery"\n` +
        `   4. If hundreds of instances → open a new tab`
      );
    };
    console.log(
      '[Main] Dev session monitor active. Call __checkHmrMemory() to check health.'
    );
  })
  .catch((err) => console.error('[Main] Boot failed:', err));
