export type PhoenixTransportKind = 'taurpc-json' | 'taurpc-typed' | 'boot-phase';

export interface PhoenixTransportCallSample {
    name: string;
    kind: PhoenixTransportKind;
    startedAt: number;
    durationMs: number;
    requestBytes: number;
    responseBytes: number;
    ok: boolean;
    counters?: Record<string, number>;
}

export interface PhoenixTransportAggregate {
    name: string;
    kind: PhoenixTransportKind;
    count: number;
    errors: number;
    totalMs: number;
    avgMs: number;
    maxMs: number;
    totalRequestBytes: number;
    totalResponseBytes: number;
    counters: Record<string, number>;
}

export interface PhoenixTransportAuditSnapshot {
    startedAt: number;
    totalCalls: number;
    totalErrors: number;
    totalRequestBytes: number;
    totalResponseBytes: number;
    calls: PhoenixTransportAggregate[];
    recentCalls: PhoenixTransportCallSample[];
}

declare global {
    interface Window {
        kittPhoenixTransportAudit?: () => PhoenixTransportAuditSnapshot;
        kittResetPhoenixTransportAudit?: () => void;
    }
}

const encoder = typeof TextEncoder !== 'undefined' ? new TextEncoder() : null;

function byteLengthOfString(value: string): number {
    if (!value) {
        return 0;
    }
    if (encoder) {
        return encoder.encode(value).byteLength;
    }
    return value.length;
}

function byteLengthOfJson(value: unknown): number {
    try {
        return byteLengthOfString(JSON.stringify(value ?? null));
    } catch {
        return 0;
    }
}

class PhoenixTransportAudit {
    private startedAt = Date.now();
    private readonly recentCalls: PhoenixTransportCallSample[] = [];
    private readonly aggregateByKey = new Map<string, PhoenixTransportAggregate>();

    constructor() {
        this.attachWindowDebug();
    }

    reset(): void {
        this.startedAt = Date.now();
        this.recentCalls.length = 0;
        this.aggregateByKey.clear();
        this.attachWindowDebug();
    }

    async measureJsonRpc<T>(
        name: string,
        requestJson: string,
        op: () => Promise<string>,
        parse: (raw: string) => T,
    ): Promise<T> {
        const startedAt = performance.now();
        let rawResponse = '';
        let ok = false;
        try {
            rawResponse = await op();
            ok = true;
            return parse(rawResponse);
        } finally {
            this.record({
                name,
                kind: 'taurpc-json',
                startedAt: Date.now(),
                durationMs: performance.now() - startedAt,
                requestBytes: byteLengthOfString(requestJson),
                responseBytes: byteLengthOfString(rawResponse),
                ok,
            });
        }
    }

    async measureTypedRpc<T>(name: string, request: unknown, op: () => Promise<T>): Promise<T> {
        const startedAt = performance.now();
        let response: T | undefined;
        let ok = false;
        try {
            response = await op();
            ok = true;
            return response;
        } finally {
            this.record({
                name,
                kind: 'taurpc-typed',
                startedAt: Date.now(),
                durationMs: performance.now() - startedAt,
                requestBytes: byteLengthOfJson(request),
                responseBytes: byteLengthOfJson(response),
                ok,
            });
        }
    }

    async measureBootPhase<T>(name: string, op: () => Promise<T>): Promise<T> {
        const startedAt = performance.now();
        let ok = false;
        try {
            const result = await op();
            ok = true;
            return result;
        } finally {
            this.record({
                name,
                kind: 'boot-phase',
                startedAt: Date.now(),
                durationMs: performance.now() - startedAt,
                requestBytes: 0,
                responseBytes: 0,
                ok,
            });
        }
    }

    recordPayloadCounters(name: string, kind: PhoenixTransportKind, counters: Record<string, number>): void {
        if (!Object.keys(counters).length) return;
        const current = this.aggregateByKey.get(`${kind}:${name}`);
        if (!current) return;
        mergeCounters(current.counters, counters);
    }

    snapshot(): PhoenixTransportAuditSnapshot {
        const calls = Array.from(this.aggregateByKey.values())
            .map((aggregate) => ({
                ...aggregate,
                avgMs: aggregate.count ? aggregate.totalMs / aggregate.count : 0,
            }))
            .sort((left, right) => right.totalMs - left.totalMs || left.name.localeCompare(right.name));
        return {
            startedAt: this.startedAt,
            totalCalls: calls.reduce((sum, call) => sum + call.count, 0),
            totalErrors: calls.reduce((sum, call) => sum + call.errors, 0),
            totalRequestBytes: calls.reduce((sum, call) => sum + call.totalRequestBytes, 0),
            totalResponseBytes: calls.reduce((sum, call) => sum + call.totalResponseBytes, 0),
            calls,
            recentCalls: [...this.recentCalls],
        };
    }

    printSummary(label = 'Phoenix transport audit'): void {
        const snapshot = this.snapshot();
        console.groupCollapsed(
            `[PhoenixTransportAudit] ${label}: ${snapshot.totalCalls} calls, ${snapshot.totalRequestBytes} B -> ${snapshot.totalResponseBytes} B`,
        );
        for (const call of snapshot.calls.slice(0, 12)) {
            console.log(
                `${call.kind} ${call.name}: count=${call.count}, total=${call.totalMs.toFixed(1)}ms, max=${call.maxMs.toFixed(1)}ms, bytes=${call.totalRequestBytes}->${call.totalResponseBytes}, errors=${call.errors}`,
            );
        }
        console.groupEnd();
    }

    private record(sample: PhoenixTransportCallSample): void {
        this.recentCalls.unshift(sample);
        if (this.recentCalls.length > 64) {
            this.recentCalls.length = 64;
        }
        const key = `${sample.kind}:${sample.name}`;
        const current = this.aggregateByKey.get(key);
        if (current) {
            current.count += 1;
            current.errors += sample.ok ? 0 : 1;
            current.totalMs += sample.durationMs;
            current.maxMs = Math.max(current.maxMs, sample.durationMs);
            current.totalRequestBytes += sample.requestBytes;
            current.totalResponseBytes += sample.responseBytes;
            mergeCounters(current.counters, sample.counters);
            return;
        }
        this.aggregateByKey.set(key, {
            name: sample.name,
            kind: sample.kind,
            count: 1,
            errors: sample.ok ? 0 : 1,
            totalMs: sample.durationMs,
            avgMs: sample.durationMs,
            maxMs: sample.durationMs,
            totalRequestBytes: sample.requestBytes,
            totalResponseBytes: sample.responseBytes,
            counters: { ...(sample.counters || {}) },
        });
    }

    private attachWindowDebug(): void {
        if (typeof window === 'undefined') {
            return;
        }
        window.kittPhoenixTransportAudit = () => this.snapshot();
        window.kittResetPhoenixTransportAudit = () => this.reset();
    }
}

function mergeCounters(target: Record<string, number>, source: Record<string, number> | undefined): void {
    if (!source) return;
    for (const [key, value] of Object.entries(source)) {
        if (typeof value === 'number' && Number.isFinite(value)) {
            target[key] = (target[key] || 0) + value;
        }
    }
}

export const phoenixTransportAudit = new PhoenixTransportAudit();
