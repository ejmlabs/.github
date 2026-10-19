#!/usr/bin/env node
// Checks that the kit agrees with itself. Run it before sharing or publishing the kit.
//   generated files are current and contrast holds, every class used in a kit page exists,
//   every class is documented in a catalog, every class a catalog names exists, and no em dashes.
// Usage: node scripts/check-kit.mjs
import { readFileSync, readdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const kit = join(dirname(fileURLToPath(import.meta.url)), '..');
const problems = [];
const run = script => {
  try { execFileSync('node', [join(kit, 'scripts', script), '--check'], { stdio: 'pipe' }); }
  catch (e) { problems.push(`${script} --check failed:\n${String(e.stderr || e.stdout).trim().replace(/^/gm, '    ')}`); }
};
for (const script of ['build-ui.mjs', 'build-web.mjs', 'build-motifs.mjs']) run(script);

const list = (dir, ext) => readdirSync(join(kit, dir)).filter(f => f.endsWith(ext)).map(f => join(dir, f));
const read = f => readFileSync(join(kit, f), 'utf8');
const sheets = ['components/brand-components.css', 'web/site.css', 'ui/app.css'].map(read);
const docs = ['README.md', 'CATALOG.md', 'SITES.md', 'UI.md', 'COMPONENTS.md', 'MOTIFS.md', ...list('web', '.md'), ...list('ui', '.md')].map(read).join('\n');
const pages = [...list('.', '.html'), ...list('web', '.html'), ...list('ui', '.html'), ...list('components', '.html')].map(read);
const defined = new Set(sheets.flatMap(css => [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/\.(ejm-[a-z0-9]+(?:-[a-z0-9]+)*)/g)].map(m => m[1])));
// Helpers that exist only to build specimen pages, and names that document a family of names or a file.
const specimenOnly = new Set(['ejm-pattern', 'ejm-placeholder']);
const notClasses = new Set(['ejm-ui', 'ejm-term', 'ejm-syn', 'ejm-design-kit', 'ejm-harness', 'ejm-cli', 'ejm-ide', 'ejm-tui', 'ejm-theme', 'ejm-x-kit', 'ejm-brand-guide', 'ejm-primary', 'ejm-ink', 'ejm-paper', 'ejm-labs']);

const usedInPages = new Set(pages.flatMap(t => [...t.matchAll(/\sclass="([^"]*)"/g)].flatMap(m => m[1].split(/\s+/)).filter(c => c.startsWith('ejm-')).map(c => c.match(/ejm-[a-z0-9]+(?:-[a-z0-9]+)*/)[0])));
const missing = [...usedInPages].filter(c => !defined.has(c));
if (missing.length) problems.push(`classes used in kit pages but not defined: ${missing.join(', ')}`);
const undocumented = [...defined].filter(c => !specimenOnly.has(c) && !new RegExp(`${c}(?![a-z0-9]|-[a-z0-9])`).test(docs));
if (undocumented.length) problems.push(`classes defined but not documented in a catalog: ${undocumented.join(', ')}`);
const named = new Set([...docs.matchAll(/`\.?(ejm-[a-z0-9]+(?:-[a-z0-9]+)*)/g)].map(m => m[1]));
const phantom = [...named].filter(c => !defined.has(c) && !notClasses.has(c));
if (phantom.length) problems.push(`classes named in a catalog but not defined: ${phantom.join(', ')}`);

const textFiles = [...list('.', '.md'), ...list('web', '.md'), ...list('web', '.css'), ...list('web/parts', '.css'), ...list('web', '.js'), ...list('web', '.html'), ...list('ui', '.md'), ...list('ui', '.css'), ...list('ui', '.html')];
for (const f of textFiles) if (read(f).includes('\u2014')) problems.push(`em dash in ${f}`);

if (problems.length) { console.error(problems.join('\n')); process.exit(1); }
console.log(`kit is consistent (${defined.size} classes, ${docs.length > 0 ? 'catalogs complete' : ''})`);
