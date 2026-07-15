import { describe, expect, it } from 'vitest';
import {
    boundedInlinePayload,
    parseAppIdeCommand,
    tokenizeAppIdeCommand,
    utf8Bytes,
} from './app-ide-command.contract';
import { APP_IDE_COMMANDS, AppIdePolicyRegistry } from './app-ide-policy.registry';

describe('read-only app IDE command contract', () => {
    it('parses quoted shell-like commands into typed argv without invoking a shell', () => {
        const command = parseAppIdeCommand('phx search lexical "Ryan at the harbor" --scope narrative:story-1 --limit=7');

        expect(command).toEqual(expect.objectContaining({
            domain: 'search',
            verb: 'lexical',
            positionals: ['Ryan at the harbor'],
            flags: { scope: 'narrative:story-1', limit: '7' },
        }));
        expect(() => tokenizeAppIdeCommand('phx note cat n1 | powershell')).toThrow('Shell operator');
        expect(() => parseAppIdeCommand('bash -c whoami')).toThrow('must start with phx');
    });

    it('bounds UTF-8 inline output while retaining the exact total byte count', () => {
        const value = { content: 'Phoenix 🔥 '.repeat(1_000) };
        const bounded = boundedInlinePayload(value, 512);

        expect(bounded.truncated).toBe(true);
        expect(bounded.totalBytes).toBe(utf8Bytes(value));
        expect(utf8Bytes(bounded.payload)).toBeLessThan(750);
    });

    it('registers only retry-safe reads and keeps graph access asserted-only', () => {
        const registry = new AppIdePolicyRegistry();
        const graph = registry.resolve(parseAppIdeCommand('phx graph neighbors entity:ryan --depth 2'));
        const decision = registry.evaluate(graph, 'read_only', 'run-1');

        expect(APP_IDE_COMMANDS.length).toBeGreaterThanOrEqual(10);
        expect(APP_IDE_COMMANDS.every((item) => item.actionClass === 'read')).toBe(true);
        expect(APP_IDE_COMMANDS.every((item) => item.idempotency === 'safe_retry')).toBe(true);
        expect(graph.scopeResolver).toBe('asserted_graph');
        expect(decision.decision).toBe('allow');
        expect(APP_IDE_COMMANDS.some((item) => /upsert|commit|promote|write/i.test(item.name))).toBe(false);
    });

    it('denies note and search reads that escape the active narrative', () => {
        const registry = new AppIdePolicyRegistry();
        const command = parseAppIdeCommand('phx note cat note://other-story/note-9');
        const descriptor = registry.resolve(command);
        const decision = registry.evaluate(descriptor, 'read_only', 'run-1', {
            command,
            activeNarrativeId: 'story-1',
        });

        expect(decision.decision).toBe('deny');
        expect(decision.reason).toContain('active narrative');
    });
});
