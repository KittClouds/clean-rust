import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));

describe('application route loading', () => {
    it('keeps the standalone fantasy calendar outside the initial bundle', () => {
        const source = readFileSync(join(here, 'app.routes.ts'), 'utf8');

        expect(source).not.toContain("import { FantasyCalendarPageComponent }");
        expect(source).toContain(
            "{ path: 'calendar', loadComponent: () => import('./pages/fantasy-calendar/fantasy-calendar-page.component')",
        );
    });
});
