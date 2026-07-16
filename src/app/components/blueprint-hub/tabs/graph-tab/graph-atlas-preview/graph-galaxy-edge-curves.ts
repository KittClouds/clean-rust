export interface GalaxyCurvePoint {
    x: number;
    y: number;
    z: number;
}

// Hot renderer path: write into a caller-owned point to keep edge sampling allocation-free.
export function setHopfEdgeCurvePoint(
    out: GalaxyCurvePoint,
    ax: number,
    ay: number,
    az: number,
    bx: number,
    by: number,
    bz: number,
    lift: number,
    t: number,
    edgeCurveStrength: number,
    seed: number,
    crossBase: boolean,
): void {
    const ar = Math.max(0.0001, Math.hypot(ax, ay, az));
    const br = Math.max(0.0001, Math.hypot(bx, by, bz));
    const aux = ax / ar,
        auy = ay / ar,
        auz = az / ar;
    const bux = bx / br,
        buy = by / br,
        buz = bz / br;
    const sign = seed < 0.5 ? -1 : 1;
    let nx = auy * buz - auz * buy;
    let ny = auz * bux - aux * buz;
    let nz = aux * buy - auy * bux;
    let normalLength = Math.hypot(nx, ny, nz);
    if (normalLength < 0.0001) {
        nx = auy * sign - auz * 0.38;
        ny = auz + 0.22;
        nz = -aux + auy * 0.38;
        normalLength = Math.hypot(nx, ny, nz) || 1;
    }
    nx /= normalLength;
    ny /= normalLength;
    nz /= normalLength;

    const sweep = Math.sin(Math.PI * t);
    const curveScale = Math.min(1.2, Math.max(0.25, edgeCurveStrength));
    const bend = (crossBase ? 0.36 : 0.18) * curveScale * sweep * sign;
    const baseX = aux * (1 - t) + bux * t;
    const baseY = auy * (1 - t) + buy * t;
    const baseZ = auz * (1 - t) + buz * t;
    let dx = baseX + nx * bend;
    let dy = baseY + ny * bend;
    let dz = baseZ + nz * bend;
    const directionLength = Math.hypot(dx, dy, dz) || 1;
    dx /= directionLength;
    dy /= directionLength;
    dz /= directionLength;

    const radius = ar + (br - ar) * t + lift * (crossBase ? 0.72 : 0.38) * sweep;
    out.x = dx * radius;
    out.y = dy * radius;
    out.z = dz * radius;
}
