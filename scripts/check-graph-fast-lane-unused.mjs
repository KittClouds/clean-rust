import process from 'node:process';
import path from 'node:path';
import ts from 'typescript';

const workspace = process.cwd();
const configPath = path.join(workspace, 'tsconfig.app.json');
const fastLanePrefixes = [
    'src/app/graph-rebuild/',
    'src/app/components/blueprint-hub/tabs/graph-tab/graph-atlas-preview/',
    'src/app/components/search-panel/',
    'src/app/services/atlas-capability-runtime.',
    'src/app/services/phoenix-ui-api.',
    'src/app/lib/services/nli-worker.',
];

const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
if (configFile.error) {
    report([configFile.error]);
}

const parsed = ts.parseJsonConfigFileContent(
    configFile.config,
    ts.sys,
    workspace,
    {
        noEmit: true,
        noUnusedLocals: true,
        noUnusedParameters: true,
    },
    configPath,
);
const program = ts.createProgram({ rootNames: parsed.fileNames, options: parsed.options });
const diagnostics = ts.getPreEmitDiagnostics(program).filter((diagnostic) => {
    if (!diagnostic.file) return false;
    const relative = path.relative(workspace, diagnostic.file.fileName).replaceAll('\\', '/');
    return fastLanePrefixes.some((prefix) => relative.startsWith(prefix));
});

if (diagnostics.length) {
    report(diagnostics);
}

console.log(`Graph fast-lane unused-code gate passed (${fastLanePrefixes.length} boundaries).`);

function report(diagnostics) {
    const host = {
        getCanonicalFileName: (fileName) => fileName,
        getCurrentDirectory: () => workspace,
        getNewLine: () => ts.sys.newLine,
    };
    process.stderr.write(ts.formatDiagnosticsWithColorAndContext(diagnostics, host));
    process.exit(1);
}
