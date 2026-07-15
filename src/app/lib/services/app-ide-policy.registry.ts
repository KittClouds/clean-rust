import { Injectable } from '@angular/core';
import type {
    AppIdeCapabilityProfile,
    AppIdeCommandDescriptor,
    AppIdeOutputBudget,
    AppIdePolicyReceipt,
    ParsedAppIdeCommand,
} from './app-ide-command.contract';

export interface AppIdePolicyContext {
    command: ParsedAppIdeCommand;
    activeNarrativeId?: string;
}

const READ_BUDGET = { inlineBytes: 4_096, artifactBytes: 2_000_000 } as const;
const LARGE_READ_BUDGET = { inlineBytes: 6_144, artifactBytes: 8_000_000 } as const;

export const APP_IDE_COMMANDS: readonly AppIdeCommandDescriptor[] = [
    descriptor('app.pwd', 'app', 'pwd', 'Read the active narrative and note URI.', 'active_app', 'status'),
    descriptor('app.status', 'app', 'status', 'Inspect app, editor, and durable-store state.', 'active_app', 'status'),
    descriptor('note.list', 'note', 'ls', 'List note headers in the active scope.', 'active_narrative', 'table'),
    descriptor('note.stat', 'note', 'stat', 'Read note metadata and durable revision.', 'exact_note', 'status'),
    descriptor('note.read', 'note', 'cat', 'Read a full note or exact character range.', 'exact_note', 'text', LARGE_READ_BUDGET),
    descriptor('search.lexical', 'search', 'lexical', 'Search the scoped lexical index.', 'active_narrative', 'search_results'),
    descriptor('search.semantic', 'search', 'semantic', 'Search the scoped semantic index.', 'active_narrative', 'search_results'),
    descriptor('index.status', 'index', 'status', 'Inspect scoped note and retrieval-index readiness without rebuilding.', 'active_narrative', 'status'),
    descriptor('graph.neighbors', 'graph', 'neighbors', 'Read an asserted graph neighborhood.', 'asserted_graph', 'graph', LARGE_READ_BUDGET),
    descriptor('graph.path', 'graph', 'path', 'Find a bounded path through asserted graph edges.', 'asserted_graph', 'graph', LARGE_READ_BUDGET),
    descriptor('artifact.list', 'artifact', 'ls', 'List durable artifacts for this run.', 'run_artifacts', 'table'),
    descriptor('artifact.read', 'artifact', 'cat', 'Read an exact slice from a durable run artifact.', 'run_artifacts', 'artifact', LARGE_READ_BUDGET),
];

@Injectable({ providedIn: 'root' })
export class AppIdePolicyRegistry {
    private readonly byRoute = new Map(APP_IDE_COMMANDS.map((item) => [`${item.domain}:${item.verb}`, item]));

    resolve(command: ParsedAppIdeCommand): AppIdeCommandDescriptor {
        const descriptor = this.byRoute.get(`${command.domain}:${command.verb}`);
        if (!descriptor) throw new Error(`Unknown read-only app command: ${command.domain} ${command.verb}`);
        return descriptor;
    }

    evaluate(
        descriptor: AppIdeCommandDescriptor,
        profile: AppIdeCapabilityProfile,
        runId: string,
        context?: AppIdePolicyContext,
    ): AppIdePolicyReceipt {
        let decision = descriptor.defaultPolicy;
        let reason = 'Scoped read is allowed by the registered capability policy.';
        if (!descriptor.profiles.includes(profile)) {
            decision = 'deny';
            reason = `Capability ${descriptor.name} is not visible to profile ${profile}.`;
        } else if (descriptor.actionClass !== 'read') {
            decision = 'deny';
            reason = 'Slice 2 denies every non-read action class.';
        } else if (descriptor.domain === 'graph' && descriptor.scopeResolver !== 'asserted_graph') {
            decision = 'deny';
            reason = 'Graph access must resolve through the asserted read model.';
        } else if (context && this.requestsExternalNarrative(context)) {
            decision = 'deny';
            reason = 'Read-only app commands are confined to the active narrative scope.';
        }
        return {
            id: `policy:${runId}:${descriptor.name}:${Date.now()}`,
            capability: descriptor.name,
            profile,
            decision,
            actionClass: descriptor.actionClass,
            resources: descriptor.resources,
            reason,
            evaluatedAt: Date.now(),
        };
    }

    private requestsExternalNarrative(context: AppIdePolicyContext): boolean {
        const active = context.activeNarrativeId?.trim();
        if (!active) return false;
        const scope = context.command.flags['scope'];
        if (typeof scope === 'string' && scope.startsWith('narrative:')) {
            return scope.slice('narrative:'.length) !== active;
        }
        const noteUri = context.command.positionals.find((value) => value.startsWith('note://'));
        if (!noteUri) return false;
        const narrative = noteUri.slice('note://'.length).split('/').filter(Boolean)[0];
        return !!narrative && decodeURIComponent(narrative) !== active;
    }
}

function descriptor(
    name: string,
    domain: AppIdeCommandDescriptor['domain'],
    verb: string,
    description: string,
    scopeResolver: AppIdeCommandDescriptor['scopeResolver'],
    rendererHint: AppIdeCommandDescriptor['rendererHint'],
    outputBudget: AppIdeOutputBudget = READ_BUDGET,
): AppIdeCommandDescriptor {
    return {
        name,
        version: 1,
        description,
        domain,
        verb,
        schema: commandSchema(name, domain, verb),
        resources: domain === 'graph' ? ['asserted_graph'] : [domain],
        actionClass: 'read',
        scopeResolver,
        defaultPolicy: 'allow',
        profiles: ['read_only', 'propose'],
        idempotency: 'safe_retry',
        timeoutMs: domain === 'search' || domain === 'graph' ? 15_000 : 5_000,
        outputBudget,
        cancellable: false,
        receiptSchema: 'phoenix-app-ide-tool-result/v1',
        rendererHint,
    };
}

function commandSchema(name: string, domain: string, verb: string): Record<string, unknown> {
    const requiresOne = ['note.stat', 'note.read', 'graph.neighbors', 'artifact.read'].includes(name);
    const requiresTwo = name === 'graph.path';
    const query = name.startsWith('search.');
    return {
        $id: `phoenix-app-command/${name}/v1`,
        type: 'object',
        required: ['positionals', 'flags'],
        additionalProperties: false,
        properties: {
            domain: { const: domain },
            verb: { const: verb },
            positionals: {
                type: 'array',
                items: { type: 'string' },
                minItems: query ? 1 : requiresTwo ? 2 : requiresOne ? 1 : 0,
                ...(requiresTwo || requiresOne ? { maxItems: requiresTwo ? 2 : 1 } : {}),
            },
            flags: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    scope: { type: 'string', pattern: '^(narrative|note|folder):.+' },
                    limit: { type: 'integer', minimum: 1, maximum: 200 },
                    from: { type: 'integer', minimum: 0 },
                    to: { type: 'integer', minimum: 0 },
                    depth: { type: 'integer', minimum: 1, maximum: 12 },
                },
            },
        },
    };
}
