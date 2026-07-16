export const ATLAS_RICH_SCAN_QUARANTINE_MESSAGE =
    'Legacy Atlas rich scan is quarantined. Use the content-addressed GraphRebuildPipelineService path.';

export function rejectAtlasRichScan(): never {
    throw new Error(ATLAS_RICH_SCAN_QUARANTINE_MESSAGE);
}
