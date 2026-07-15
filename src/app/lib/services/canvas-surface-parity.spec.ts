// @vitest-environment node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('Canvas run surface parity contract', () => {
    it('projects the shared durable run in both the page and side panel', () => {
        const page = source('src/app/pages/ai-chat/ai-chat-page.component.ts');
        const panel = source('src/app/components/right-sidebar/ai-chat-panel/ai-chat-panel.component.ts');

        expect(page).toContain('<app-canvas-run-inspector />');
        expect(panel).toContain('<app-canvas-run-inspector />');
        expect(panel).toContain("this.canvasRuns.startSelectionRun(text, undefined, 'side-panel')");
    });

    it('routes toolbar edits through the same run and removes direct model-to-editor streaming', () => {
        const toolbar = source('src/app/components/editor/plugins/toolbar/toolbar.component.ts');

        expect(toolbar).toContain('this.canvasRuns.startSelectionRun(');
        expect(toolbar).not.toContain('this.phoenixChat.streamChat(');
        expect(toolbar).not.toContain('beginStreamReplace(');
    });

    it('shows ordered read-only artifacts on both surfaces through the shared inspector', () => {
        const inspector = source('src/app/lib/components/canvas-run-inspector.component.ts');
        const host = source('src/app/lib/services/chat-tool-host.service.ts');
        const planner = source('rust/phoenix/crates/phoenix-runtime/src/planner.rs');

        expect(inspector).toContain('event.sequence');
        expect(inspector).toContain('data-testid="harness-artifacts"');
        expect(host).toContain("case 'app_exec'");
        expect(planner).toContain('name: "app_exec"');
        expect(planner).toContain('spec.name == "app_exec"');
    });

    it('shows the same multi-note conflict, cancellation, and scoped-trust controls on both surfaces', () => {
        const inspector = source('src/app/lib/components/canvas-run-inspector.component.ts');
        const panel = source('src/app/components/right-sidebar/ai-chat-panel/ai-chat-panel.component.ts');
        const planner = source('rust/phoenix/crates/phoenix-runtime/src/planner.rs');

        expect(inspector).toContain('data-testid="canvas-conflicts"');
        expect(inspector).toContain('Trust scope + commit');
        expect(inspector).toContain('void this.runs.cancel()');
        expect(panel).toContain("this.canvasRuns.startWorkspaceRun(text, 'side-panel')");
        expect(planner).toContain('name: "multi_note_proposal"');
        expect(planner).not.toContain('name: "assert_graph"');
    });
});

function source(path: string): string {
    return readFileSync(resolve(process.cwd(), path), 'utf8');
}
