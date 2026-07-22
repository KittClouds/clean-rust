const CELL_SIZE_PX = 32;
const MAX_PICK_RADIUS_PX = 16;
const MAX_CELL_MEMBERS = 512;

/**
 * Resident-only screen index. Camera changes rebuild it once; pointer movement
 * examines bounded local buckets and never walks the full resident scene.
 */
export class GalaxyRendererV3ScreenPickIndex {
    private screenX: Float32Array<ArrayBufferLike> = new Float32Array(0);
    private screenY: Float32Array<ArrayBufferLike> = new Float32Array(0);
    private depth: Float32Array<ArrayBufferLike> = new Float32Array(0);
    private nodeCells: Int32Array<ArrayBufferLike> = new Int32Array(0);
    private counts: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
    private offsets: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
    private cursors: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
    private members: Uint32Array<ArrayBufferLike> = new Uint32Array(0);
    private nodeCount = 0;
    private width = 1;
    private height = 1;
    private columns = 1;
    private rows = 1;
    private sealed = false;

    lastExamined = 0;
    droppedNodeCount = 0;

    begin(nodeCount: number, width: number, height: number): void {
        this.nodeCount = Math.max(0, nodeCount | 0);
        this.width = Math.max(1, width);
        this.height = Math.max(1, height);
        this.columns = Math.max(1, Math.ceil(this.width / CELL_SIZE_PX));
        this.rows = Math.max(1, Math.ceil(this.height / CELL_SIZE_PX));
        this.screenX = ensureFloat32(this.screenX, this.nodeCount);
        this.screenY = ensureFloat32(this.screenY, this.nodeCount);
        this.depth = ensureFloat32(this.depth, this.nodeCount);
        this.nodeCells = ensureInt32(this.nodeCells, this.nodeCount);
        this.nodeCells.subarray(0, this.nodeCount).fill(-1);
        const cellCount = this.columns * this.rows;
        this.counts = ensureUint32(this.counts, cellCount);
        this.counts.subarray(0, cellCount).fill(0);
        this.offsets = ensureUint32(this.offsets, cellCount + 1);
        this.cursors = ensureUint32(this.cursors, cellCount);
        this.members = ensureUint32(this.members, this.nodeCount);
        this.lastExamined = 0;
        this.droppedNodeCount = 0;
        this.sealed = false;
    }

    project(index: number, x: number, y: number, depth: number): void {
        if (index < 0 || index >= this.nodeCount || !Number.isFinite(x)
            || !Number.isFinite(y) || !Number.isFinite(depth) || depth < -1 || depth > 1) return;
        if (x < -MAX_PICK_RADIUS_PX || x > this.width + MAX_PICK_RADIUS_PX
            || y < -MAX_PICK_RADIUS_PX || y > this.height + MAX_PICK_RADIUS_PX) return;
        this.screenX[index] = x;
        this.screenY[index] = y;
        this.depth[index] = depth;
        const column = clampInt(Math.floor(x / CELL_SIZE_PX), 0, this.columns - 1);
        const row = clampInt(Math.floor(y / CELL_SIZE_PX), 0, this.rows - 1);
        this.nodeCells[index] = row * this.columns + column;
    }

    seal(): void {
        const cellCount = this.columns * this.rows;
        for (let index = 0; index < this.nodeCount; index++) {
            const cell = this.nodeCells[index];
            if (cell < 0) continue;
            if (this.counts[cell] < MAX_CELL_MEMBERS) this.counts[cell]++;
            else this.droppedNodeCount++;
        }
        this.offsets[0] = 0;
        for (let cell = 0; cell < cellCount; cell++) {
            this.offsets[cell + 1] = this.offsets[cell] + this.counts[cell];
            this.cursors[cell] = this.offsets[cell];
        }
        for (let index = 0; index < this.nodeCount; index++) {
            const cell = this.nodeCells[index];
            if (cell < 0 || this.cursors[cell] >= this.offsets[cell + 1]) continue;
            this.members[this.cursors[cell]++] = index;
        }
        this.sealed = true;
    }

    pick(x: number, y: number, radii: Float32Array): number {
        this.lastExamined = 0;
        if (!this.sealed || !Number.isFinite(x) || !Number.isFinite(y)) return -1;
        const minColumn = clampInt(Math.floor((x - MAX_PICK_RADIUS_PX) / CELL_SIZE_PX), 0, this.columns - 1);
        const maxColumn = clampInt(Math.floor((x + MAX_PICK_RADIUS_PX) / CELL_SIZE_PX), 0, this.columns - 1);
        const minRow = clampInt(Math.floor((y - MAX_PICK_RADIUS_PX) / CELL_SIZE_PX), 0, this.rows - 1);
        const maxRow = clampInt(Math.floor((y + MAX_PICK_RADIUS_PX) / CELL_SIZE_PX), 0, this.rows - 1);
        let bestIndex = -1;
        let bestDistance = Number.POSITIVE_INFINITY;
        let bestDepth = Number.POSITIVE_INFINITY;
        for (let row = minRow; row <= maxRow; row++) {
            for (let column = minColumn; column <= maxColumn; column++) {
                const cell = row * this.columns + column;
                for (let cursor = this.offsets[cell]; cursor < this.offsets[cell + 1]; cursor++) {
                    const index = this.members[cursor];
                    this.lastExamined++;
                    const dx = x - this.screenX[index];
                    const dy = y - this.screenY[index];
                    const distance = dx * dx + dy * dy;
                    const radius = pickRadius(radii[index] || 0);
                    if (distance > radius * radius) continue;
                    const depth = this.depth[index];
                    if (distance < bestDistance || (distance === bestDistance && depth < bestDepth)) {
                        bestIndex = index;
                        bestDistance = distance;
                        bestDepth = depth;
                    }
                }
            }
        }
        return bestIndex;
    }
}

function pickRadius(radius: number): number {
    return Math.max(7, Math.min(18, Math.max(1.5, radius * 1.65)) * 0.7 + 3);
}

function ensureFloat32(current: Float32Array, length: number): Float32Array {
    return current.length >= length ? current : new Float32Array(length);
}

function ensureInt32(current: Int32Array, length: number): Int32Array {
    return current.length >= length ? current : new Int32Array(length);
}

function ensureUint32(current: Uint32Array, length: number): Uint32Array {
    return current.length >= length ? current : new Uint32Array(length);
}

function clampInt(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}
