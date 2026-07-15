import { Injectable } from '@angular/core';
import { getSetting, setSetting } from '../dexie/settings.service';
import type {
    CanvasMultiNoteTransaction,
    CanvasNoteOperationKind,
} from './canvas-multi-note-transaction';

const TRUSTED_GRANTS_KEY = 'ai-harness:canvas-trusted-grants-v1';
const DEFAULT_TTL_MS = 30 * 60_000;
const DEFAULT_USES = 20;

export interface CanvasTrustedGrant {
    id: string;
    runId: string;
    narrativeId: string;
    noteIds: string[];
    folderIds: string[];
    operations: CanvasNoteOperationKind[];
    remainingUses: number;
    issuedAt: number;
    expiresAt: number;
    revokedAt?: number;
}

export interface CanvasGrantDecision {
    allowed: boolean;
    grantId?: string;
    reason?: string;
}

@Injectable({ providedIn: 'root' })
export class CanvasTrustedGrantService {
    issueForTransaction(
        transaction: CanvasMultiNoteTransaction,
        maxUses = DEFAULT_USES,
        ttlMs = DEFAULT_TTL_MS,
    ): CanvasTrustedGrant {
        const now = Date.now();
        const grant: CanvasTrustedGrant = {
            id: this.id(),
            runId: transaction.runId,
            narrativeId: transaction.narrativeId,
            noteIds: unique(transaction.mutations.map((mutation) => mutation.noteId)),
            folderIds: unique(transaction.mutations.flatMap((mutation) => [
                mutation.before?.folderId,
                mutation.after.folderId,
            ].filter(nonEmpty))),
            operations: unique(transaction.mutations.flatMap((mutation) => mutation.operationKinds)),
            remainingUses: Math.max(1, Math.min(100, Math.floor(maxUses))),
            issuedAt: now,
            expiresAt: now + Math.max(1_000, Math.min(24 * 60 * 60_000, ttlMs)),
        };
        this.write([...this.read(), grant]);
        return grant;
    }

    consume(transaction: CanvasMultiNoteTransaction): CanvasGrantDecision {
        const now = Date.now();
        const grants = this.read();
        const index = grants.findIndex((grant) => this.matches(grant, transaction, now));
        if (index < 0) {
            this.write(grants.filter((grant) => this.isActive(grant, now)));
            return { allowed: false, reason: 'no matching active scoped grant' };
        }
        const grant = { ...grants[index], remainingUses: grants[index].remainingUses - 1 };
        grants[index] = grant;
        this.write(grants.filter((item) => this.isActive(item, now)));
        return { allowed: true, grantId: grant.id };
    }

    listActive(): CanvasTrustedGrant[] {
        const now = Date.now();
        const active = this.read().filter((grant) => this.isActive(grant, now));
        this.write(active);
        return active;
    }

    revokeRun(runId: string): void {
        const now = Date.now();
        this.write(this.read().map((grant) => grant.runId === runId
            ? { ...grant, revokedAt: now }
            : grant));
    }

    private matches(grant: CanvasTrustedGrant, transaction: CanvasMultiNoteTransaction, now: number): boolean {
        if (!this.isActive(grant, now)) return false;
        if (grant.runId !== transaction.runId || grant.narrativeId !== transaction.narrativeId) return false;
        return transaction.mutations.every((mutation) =>
            grant.noteIds.includes(mutation.noteId)
            && mutation.operationKinds.every((operation) => grant.operations.includes(operation))
            && [mutation.before?.folderId, mutation.after.folderId]
                .filter(nonEmpty)
                .every((folderId) => grant.folderIds.includes(folderId)),
        );
    }

    private isActive(grant: CanvasTrustedGrant, now: number): boolean {
        return !grant.revokedAt && grant.remainingUses > 0 && grant.expiresAt > now;
    }

    private read(): CanvasTrustedGrant[] {
        const value = getSetting<unknown>(TRUSTED_GRANTS_KEY, []);
        if (!Array.isArray(value)) return [];
        return value.filter(isGrant);
    }

    private write(grants: CanvasTrustedGrant[]): void {
        setSetting(TRUSTED_GRANTS_KEY, grants.slice(-64));
    }

    private id(): string {
        return globalThis.crypto?.randomUUID?.() || `grant-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    }
}

function isGrant(value: unknown): value is CanvasTrustedGrant {
    const item = value && typeof value === 'object' ? value as Partial<CanvasTrustedGrant> : null;
    return !!item
        && typeof item.id === 'string'
        && typeof item.runId === 'string'
        && typeof item.narrativeId === 'string'
        && Array.isArray(item.noteIds)
        && Array.isArray(item.folderIds)
        && Array.isArray(item.operations)
        && typeof item.remainingUses === 'number'
        && typeof item.expiresAt === 'number';
}

function unique<T>(values: readonly T[]): T[] {
    return [...new Set(values)];
}

function nonEmpty(value: string | undefined | null): value is string {
    return typeof value === 'string' && value.length > 0;
}
