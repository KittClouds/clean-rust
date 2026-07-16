export function nextPathSelection(current: readonly string[], nodeId: string): string[] {
    const selected = current.filter((id, index, values) => Boolean(id) && values.indexOf(id) === index).slice(0, 2);
    if (selected.includes(nodeId)) return selected.filter((id) => id !== nodeId);
    return selected.length < 2 ? [...selected, nodeId] : [selected[1], nodeId];
}

export function boundedPathSelection(ids: readonly string[]): string[] {
    return ids.filter((id, index, values) => Boolean(id) && values.indexOf(id) === index).slice(0, 2);
}

export function pathSelectionLocksCanvasFocus(ids: readonly string[]): boolean {
    return ids.length === 2;
}
