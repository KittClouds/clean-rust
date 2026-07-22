export type AppIdeDomain = 'app' | 'note' | 'search' | 'index' | 'graph' | 'artifact';
export type AppIdeActionClass = 'read' | 'propose' | 'mutate' | 'destructive';
export type AppIdePolicyDecision = 'allow' | 'ask' | 'deny' | 'sandbox';
export type AppIdeCapabilityProfile = 'read_only' | 'propose';

export interface ParsedAppIdeCommand {
    raw: string;
    domain: AppIdeDomain;
    verb: string;
    positionals: string[];
    flags: Record<string, string | boolean>;
    canonical: string;
}

export interface AppIdeOutputBudget {
    inlineBytes: number;
    artifactBytes: number;
}

export interface AppIdeCommandDescriptor {
    name: string;
    version: 1;
    description: string;
    domain: AppIdeDomain;
    verb: string;
    schema: Record<string, unknown>;
    resources: string[];
    actionClass: AppIdeActionClass;
    scopeResolver: 'active_app' | 'active_narrative' | 'exact_note' | 'asserted_graph' | 'run_artifacts';
    defaultPolicy: AppIdePolicyDecision;
    profiles: AppIdeCapabilityProfile[];
    idempotency: 'safe_retry';
    timeoutMs: number;
    outputBudget: AppIdeOutputBudget;
    cancellable: boolean;
    receiptSchema: 'phoenix-app-ide-tool-result/v1';
    rendererHint: 'status' | 'table' | 'text' | 'search_results' | 'graph' | 'artifact';
}

export interface AppIdePolicyReceipt {
    id: string;
    capability: string;
    profile: AppIdeCapabilityProfile;
    decision: AppIdePolicyDecision;
    actionClass: AppIdeActionClass;
    resources: string[];
    reason: string;
    evaluatedAt: number;
}

export interface AppIdeArtifactRef {
    uri: string;
    key: string;
    kind: string;
    bytes: number;
    pinned: boolean;
}

export interface AppIdeToolResult {
    schemaVersion: 'phoenix-app-ide-tool-result/v1';
    runId: string;
    stepId: string;
    callId: string;
    sequence: number;
    capability: string;
    command: string;
    status: 'ok' | 'denied' | 'error';
    summary: string;
    inlinePayload: unknown;
    artifactRefs: AppIdeArtifactRef[];
    policyDecisionId: string;
    truncated: boolean;
    totalBytes: number;
    latencyMs: number;
    startedAt: number;
    completedAt: number;
}

const DOMAIN_SET = new Set<AppIdeDomain>(['app', 'note', 'search', 'index', 'graph', 'artifact']);

export function parseAppIdeCommand(raw: string): ParsedAppIdeCommand {
    const tokens = tokenizeAppIdeCommand(raw);
    if (tokens.shift()?.toLowerCase() !== 'phx') {
        throw new Error('App commands must start with phx.');
    }
    const domain = String(tokens.shift() || '').toLowerCase() as AppIdeDomain;
    if (!DOMAIN_SET.has(domain)) {
        throw new Error(`Unsupported app command domain: ${domain || '<missing>'}`);
    }
    const verb = String(tokens.shift() || '').toLowerCase();
    if (!verb) throw new Error(`Missing ${domain} command.`);

    const flags: Record<string, string | boolean> = {};
    const positionals: string[] = [];
    for (let index = 0; index < tokens.length; index++) {
        const token = tokens[index];
        if (!token.startsWith('--')) {
            positionals.push(token);
            continue;
        }
        const equals = token.indexOf('=');
        if (equals > 2) {
            flags[token.slice(2, equals)] = token.slice(equals + 1);
            continue;
        }
        const name = token.slice(2);
        const next = tokens[index + 1];
        if (next && !next.startsWith('--')) {
            flags[name] = next;
            index++;
        } else {
            flags[name] = true;
        }
    }
    return {
        raw,
        domain,
        verb,
        positionals,
        flags,
        canonical: ['phx', domain, verb, ...positionals].join(' '),
    };
}

export function tokenizeAppIdeCommand(raw: string): string[] {
    const tokens: string[] = [];
    let token = '';
    let quote: '"' | "'" | null = null;
    let escaped = false;
    const push = () => {
        if (token) tokens.push(token);
        token = '';
    };
    for (const char of raw.trim()) {
        if (escaped) {
            token += char;
            escaped = false;
            continue;
        }
        if (char === '\\' && quote) {
            escaped = true;
            continue;
        }
        if (quote) {
            if (char === quote) quote = null;
            else token += char;
            continue;
        }
        if (char === '"' || char === "'") {
            quote = char;
            continue;
        }
        if (/\s/.test(char)) {
            push();
            continue;
        }
        if ('|;<>'.includes(char)) {
            throw new Error(`Shell operator ${char} is not supported by phx commands.`);
        }
        token += char;
    }
    if (quote) throw new Error('Unterminated quoted app command argument.');
    if (escaped) token += '\\';
    push();
    return tokens;
}

export function stringFlag(command: ParsedAppIdeCommand, name: string): string | undefined {
    const value = command.flags[name];
    return typeof value === 'string' ? value : undefined;
}

export function numberFlag(
    command: ParsedAppIdeCommand,
    name: string,
    fallback: number,
    minimum: number,
    maximum: number,
): number {
    const raw = stringFlag(command, name);
    if (raw === undefined) return fallback;
    const value = Number(raw);
    if (!Number.isInteger(value) || value < minimum || value > maximum) {
        throw new Error(`--${name} must be an integer from ${minimum} to ${maximum}.`);
    }
    return value;
}

export function utf8Bytes(value: unknown): number {
    const text = typeof value === 'string' ? value : JSON.stringify(value);
    return new TextEncoder().encode(text ?? '').byteLength;
}

export function boundedInlinePayload(value: unknown, budgetBytes: number): {
    payload: unknown;
    truncated: boolean;
    totalBytes: number;
} {
    const serialized = typeof value === 'string' ? value : JSON.stringify(value);
    const totalBytes = utf8Bytes(serialized);
    if (totalBytes <= budgetBytes) return { payload: value, truncated: false, totalBytes };
    let end = Math.min(serialized.length, budgetBytes);
    while (end > 0 && utf8Bytes(serialized.slice(0, end)) > budgetBytes) end--;
    return {
        payload: {
            preview: serialized.slice(0, end),
            notice: `Inline output truncated at ${budgetBytes} bytes; read the artifact for the full result.`,
        },
        truncated: true,
        totalBytes,
    };
}
