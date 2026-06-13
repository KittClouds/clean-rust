import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { JSDOM } from 'jsdom';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDir, '..');
const outputDir = path.join(root, 'target', 'document-profile-corpus');
const externalDir = path.join(outputDir, 'external');

const localDocuments = [
    local('story-shortrun', 'Shortrun', 'docs/shortrun.md'),
    local('story-mother3', 'Mother of Learning chapter set', 'docs/mother3.md'),
    local('story-viewpoint', 'Omniscient Reader viewpoint sample', 'docs/viewpoint.md'),
];

const articleDocuments = [
    article(
        'article-nasa-exoplanets',
        "Webb's Impact on Exoplanet Research",
        'astronomy',
        'https://science.nasa.gov/mission/webb/science-overview/science-explainers/webbs-impact-on-exoplanet-research/',
        'U.S. government work; source page may include credited third-party media',
    ),
    article(
        'article-nist-pqc',
        'NIST Releases First 3 Finalized Post-Quantum Encryption Standards',
        'cybersecurity',
        'https://www.nist.gov/news-events/news/2024/08/nist-releases-first-3-finalized-post-quantum-encryption-standards',
        'U.S. government work',
    ),
    article(
        'article-usgs-earthquakes',
        'The Science of Earthquakes',
        'geoscience',
        'https://www.usgs.gov/programs/earthquake-hazards/science-earthquakes',
        'U.S. government work; source page marks core media public domain',
    ),
];

const wikiDocuments = [
    wiki('wiki-photosynthesis', 'Photosynthesis', 'biology'),
    wiki('wiki-byzantine-law', 'Byzantine law', 'law-history'),
    wiki('wiki-smart-contract', 'Smart contract', 'technology-law'),
];

const arxivDocuments = [
    arxiv('arxiv-mldocrag', '2602.10271', 'Multimodal Long-Context Document Retrieval Augmented Generation', 'computer-science'),
    arxiv('arxiv-open-quantum', '2601.20373', 'Miniatures on Open Quantum Systems', 'quantum-physics'),
    arxiv('arxiv-cell-communication', '2512.03497', 'Cell-cell Communication Inference and Analysis', 'computational-biology'),
    arxiv('arxiv-quantmind', '2509.21507', 'QuantMind', 'quantitative-finance'),
];

await mkdir(externalDir, { recursive: true });
const documents = [];

for (const document of localDocuments) {
    const absolutePath = path.join(root, document.repoPath);
    const text = await readFile(absolutePath, 'utf8');
    documents.push({ ...document, path: absolutePath, chars: text.length });
}

for (const document of [...articleDocuments, ...wikiDocuments, ...arxivDocuments]) {
    const text = await fetchDocument(document);
    const outputPath = path.join(externalDir, `${document.id}.md`);
    await writeFile(outputPath, text, 'utf8');
    documents.push({ ...document, path: outputPath, chars: text.length });
    process.stdout.write(`fetched ${document.id}: ${text.length.toLocaleString()} chars\n`);
}

const manifest = {
    schemaVersion: 'phoenix-document-profile-corpus/v1',
    generatedAt: new Date().toISOString(),
    documents,
};
const manifestPath = path.join(outputDir, 'manifest.json');
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
process.stdout.write(`manifest ${manifestPath}\n`);

function local(id, title, repoPath) {
    return {
        id,
        title,
        domain: 'fiction',
        sourceType: 'local_story',
        expectedProfiles: ['prose_fiction'],
        repoPath,
        license: 'local evaluation fixture; do not redistribute from generated corpus',
    };
}

function article(id, title, domain, sourceUrl, license) {
    return {
        id,
        title,
        domain,
        sourceType: 'government_article',
        expectedProfiles: ['reference_article'],
        sourceUrl,
        license,
    };
}

function wiki(id, title, domain) {
    return {
        id,
        title,
        domain,
        sourceType: 'wikipedia',
        expectedProfiles: ['reference_article'],
        sourceUrl: `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replaceAll(' ', '_'))}`,
        license: 'CC BY-SA 4.0 / GFDL; attribution retained in manifest',
    };
}

function arxiv(id, arxivId, title, domain) {
    return {
        id,
        title,
        domain,
        sourceType: 'arxiv',
        expectedProfiles: ['research_paper'],
        arxivId,
        sourceUrl: `https://arxiv.org/abs/${arxivId}`,
        license: 'See the paper license linked from its arXiv record',
    };
}

async function fetchDocument(document) {
    if (document.sourceType === 'wikipedia') return fetchWikipedia(document);
    if (document.sourceType === 'arxiv') return fetchArxiv(document);
    return fetchArticle(document);
}

async function fetchWikipedia(document) {
    const api = new URL('https://en.wikipedia.org/w/api.php');
    api.search = new URLSearchParams({
        action: 'query',
        prop: 'extracts',
        explaintext: '1',
        redirects: '1',
        format: 'json',
        titles: document.title,
        origin: '*',
    });
    const response = await fetchChecked(api);
    const payload = await response.json();
    const page = Object.values(payload.query?.pages || {})[0];
    const extract = page?.extract?.trim();
    if (!extract || extract.length < 1_000) throw new Error(`Wikipedia extract too small for ${document.id}`);
    return header(document) + extract + '\n';
}

async function fetchArxiv(document) {
    const candidates = [
        `https://arxiv.org/html/${document.arxivId}`,
        `https://ar5iv.labs.arxiv.org/html/${document.arxivId}`,
        document.sourceUrl,
    ];
    let lastError;
    for (const url of candidates) {
        try {
            const response = await fetchChecked(url);
            const markdown = htmlToMarkdown(await response.text());
            if (markdown.length >= 1_000) return header(document) + markdown;
            lastError = new Error(`extracted only ${markdown.length} chars from ${url}`);
        } catch (error) {
            lastError = error;
        }
    }
    throw lastError;
}

async function fetchArticle(document) {
    const response = await fetchChecked(document.sourceUrl);
    const markdown = htmlToMarkdown(await response.text());
    if (markdown.length < 1_000) throw new Error(`Article extract too small for ${document.id}`);
    return header(document) + markdown;
}

async function fetchChecked(url) {
    const response = await fetch(url, {
        headers: {
            'user-agent': 'PhoenixDocumentProfileAudit/1.0 (local research evaluation)',
            accept: 'text/html,application/json;q=0.9,*/*;q=0.8',
        },
        redirect: 'follow',
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${url}`);
    return response;
}

function htmlToMarkdown(html) {
    const dom = new JSDOM(html);
    const document = dom.window.document;
    const root = document.querySelector('main article, article, main, [role="main"]') || document.body;
    root.querySelectorAll('script,style,nav,aside,form,button,svg,noscript,iframe').forEach((node) => node.remove());
    const blocks = [];
    for (const node of root.querySelectorAll('h1,h2,h3,h4,p,li,pre,blockquote,figcaption')) {
        if (node.matches('p') && node.closest('li,blockquote')) continue;
        const text = normalize(node.textContent || '');
        if (!text || text.length < 2) continue;
        const tag = node.tagName.toLowerCase();
        if (tag === 'h1') blocks.push(`# ${text}`);
        else if (tag === 'h2') blocks.push(`## ${text}`);
        else if (tag === 'h3') blocks.push(`### ${text}`);
        else if (tag === 'h4') blocks.push(`#### ${text}`);
        else if (tag === 'li') blocks.push(`- ${text}`);
        else if (tag === 'pre') blocks.push(`\`\`\`\n${node.textContent.trim()}\n\`\`\``);
        else if (tag === 'blockquote') blocks.push(`> ${text}`);
        else blocks.push(text);
    }
    return `${dedupeAdjacent(blocks).join('\n\n')}\n`;
}

function header(document) {
    return [
        `# ${document.title}`,
        '',
        `Source: ${document.sourceUrl}`,
        `Source type: ${document.sourceType}`,
        `Domain: ${document.domain}`,
        `License note: ${document.license}`,
        '',
    ].join('\n');
}

function normalize(value) {
    return value.replace(/\s+/g, ' ').trim();
}

function dedupeAdjacent(values) {
    return values.filter((value, index) => !index || value !== values[index - 1]);
}
