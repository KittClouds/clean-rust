export class GraphCoalescingAsyncQueue<Key, Job> {
    private readonly pending = new Map<Key, Job>();
    private queue: Promise<void> = Promise.resolve();
    private drainScheduled = false;

    constructor(
        private readonly deferTurn: () => Promise<void>,
        private readonly handle: (job: Job) => Promise<void>,
    ) {}

    enqueue(key: Key, job: Job): Promise<void> {
        this.pending.set(key, job);
        this.scheduleDrain();
        return this.queue;
    }

    idle(): Promise<void> {
        return this.queue;
    }

    pendingCount(): number {
        return this.pending.size;
    }

    private scheduleDrain(): void {
        if (this.drainScheduled) return;
        this.drainScheduled = true;
        this.queue = this.queue.then(
            () => this.drain(),
            () => this.drain(),
        );
        void this.queue;
    }

    private async drain(): Promise<void> {
        try {
            while (true) {
                await this.deferTurn();
                const jobs = [...this.pending.values()];
                if (!jobs.length) return;
                this.pending.clear();
                for (const job of jobs) await this.handle(job);
            }
        } finally {
            this.drainScheduled = false;
            if (this.pending.size) this.scheduleDrain();
        }
    }
}
