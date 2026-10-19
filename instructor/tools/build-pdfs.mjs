#!/usr/bin/env node
// Rebuilds every exam PDF from the Markdown files with headless Chrome.
//
//   npm install            (first time only)
//   node build-pdfs.mjs     (or: node build-pdfs.mjs /path/to/student-challenges)
//
// Set CHROME_PATH if Chrome is not in a standard location.
import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import hljs from 'highlight.js';
import puppeteer from 'puppeteer-core';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(process.argv[2] ?? path.join(here, '..', '..'));
const fontsDir = path.join(here, 'fonts');

const THEMES = {
  cyan: { accent: '#0a8aa6', strong: '#035f74', soft: '#e7f5f8' },
  red: { accent: '#c9372c', strong: '#8c211b', soft: '#fcefed' },
  green: { accent: '#1f8a4c', strong: '#14603a', soft: '#eaf6ef' },
  slate: { accent: '#475569', strong: '#1e293b', soft: '#eef2f6' },
};

const DOCS = [
  {
    src: '00-setup-checklist/SETUP-CHECKLIST.md',
    out: 'PDF/00-Setup-Checklist.pdf',
    theme: 'green',
    kicker: 'یک هفته قبل از آزمون برای همه بفرستید',
    footer: 'Build & Ship Challenge · Setup checklist',
  },
  {
    src: 'version-A-minibank/README.md',
    out: 'PDF/A1-MiniBank-README.pdf',
    theme: 'cyan',
    kicker: 'نسخه‌ی A · README',
    footer: 'Build & Ship Challenge · Version A · MiniBank · README',
  },
  {
    src: 'version-A-minibank/PLAN.md',
    out: 'PDF/A2-MiniBank-PLAN.pdf',
    theme: 'cyan',
    kicker: 'نسخه‌ی A · PLAN',
    footer: 'Build & Ship Challenge · Version A · MiniBank · PLAN',
    stagePages: true,
  },
  {
    src: 'version-B-snaplink/README.md',
    out: 'PDF/B1-SnapLink-README.pdf',
    theme: 'red',
    kicker: 'نسخه‌ی B · README',
    footer: 'Build & Ship Challenge · Version B · SnapLink · README',
  },
  {
    src: 'version-B-snaplink/PLAN.md',
    out: 'PDF/B2-SnapLink-PLAN.pdf',
    theme: 'red',
    kicker: 'نسخه‌ی B · PLAN',
    footer: 'Build & Ship Challenge · Version B · SnapLink · PLAN',
    stagePages: true,
  },
  {
    src: 'instructor/INSTRUCTOR-GUIDE.md',
    out: 'instructor/Instructor-Guide-CONFIDENTIAL.pdf',
    theme: 'slate',
    kicker: 'محرمانه · فقط برای مدرس',
    footer: 'CONFIDENTIAL · Instructor only · Build & Ship Challenge',
  },
];

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  ].filter(Boolean);
  const found = candidates.find((p) => existsSync(p));
  if (!found) throw new Error('Chrome not found. Set CHROME_PATH=/path/to/chrome');
  return found;
}

const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext';
      return hljs.highlight(code, { language }).value;
    },
  }),
  { gfm: true },
);

// The .md files wrap prose in <div dir="rtl"> for GitHub; the PDF sets the
// direction on <html>, so the wrapper lines are dropped before parsing.
function stripRtlWrappers(md) {
  return md
    .split('\n')
    .filter((l) => l.trim() !== '<div dir="rtl">' && l.trim() !== '</div>')
    .join('\n');
}

async function fontFaceCss() {
  const css = await fs.readFile(path.join(fontsDir, 'fonts.css'), 'utf8');
  return css.replace(/url\((f\d+\.woff2)\)/g, (_, f) => `url(${pathToFileURL(path.join(fontsDir, f)).href})`);
}

function pageCss(theme, stagePages) {
  const t = THEMES[theme];
  return `
:root {
  --accent: ${t.accent}; --strong: ${t.strong}; --soft: ${t.soft};
  --ink: #1b2028; --muted: #5d6673; --line: #dfe4ea; --code-bg: #0f172a;
}
@page { size: A4; }
* { box-sizing: border-box; }
html { font-size: 10.4pt; }
body {
  margin: 0; color: var(--ink); background: #fff;
  font-family: 'Vazirmatn', Tahoma, sans-serif; line-height: 1.85;
  direction: rtl; text-align: right;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.cover {
  background: linear-gradient(135deg, var(--strong) 0%, var(--accent) 100%);
  color: #fff; border-radius: 14px; padding: 18px 24px 16px; margin: 0 0 16px;
}
.cover .kicker { font-size: 8.6pt; font-weight: 700; opacity: .85; margin-bottom: 2px; }
.cover h1 { color: #fff; font-size: 19pt; line-height: 1.4; margin: 0 0 10px; font-weight: 800; border: 0; padding: 0; }
.cover blockquote {
  margin: 0; padding: 8px 14px; border: 0; border-radius: 10px;
  background: rgba(255,255,255,.13); color: #fff; font-size: 9.4pt; line-height: 1.9;
}
.cover blockquote p { margin: 2px 0; }
.cover blockquote strong { color: #fff; }
.cover code { background: rgba(255,255,255,.18); border-color: transparent; color: #fff; }
.cover + hr { display: none; }
h1 { font-size: 18pt; color: var(--strong); }
h2 {
  font-size: 14.5pt; font-weight: 800; color: var(--strong); line-height: 1.5;
  margin: 22px 0 6px; padding: 2px 10px 4px 0; padding-inline-start: 10px;
  border-inline-start: 5px solid var(--accent); border-bottom: 1px solid var(--soft);
  break-after: avoid; page-break-after: avoid;
}
${stagePages ? 'h2.stage { background: var(--soft); border-radius: 8px; border-bottom: 0; padding-top: 5px; padding-bottom: 6px; margin-top: 26px; }' : ''}
h2 + p { color: var(--muted); font-size: 9.6pt; margin-top: 2px; }
h3 { font-size: 12.2pt; font-weight: 800; color: var(--strong); margin: 18px 0 6px; break-after: avoid; }
h4 { font-size: 10.8pt; font-weight: 700; color: var(--accent); margin: 14px 0 4px; break-after: avoid; }
p { margin: 6px 0; }
a { color: var(--accent); text-decoration: none; }
strong { font-weight: 700; }
hr { border: 0; border-top: 1px solid var(--line); margin: 18px 0; }
ul, ol { margin: 6px 0; padding-inline-start: 1.5em; }
ol { list-style-type: persian; }
li { margin: 3px 0; }
li > ul, li > ol { margin: 2px 0; }
li:has(> input[type="checkbox"]) { list-style: none; margin-inline-start: -1.25em; }
li:has(> input[type="checkbox"]) > ul { padding-inline-start: 2.2em; }
input[type="checkbox"] {
  appearance: none; -webkit-appearance: none; width: 11px; height: 11px; margin: 0;
  margin-inline-end: 7px; border: 1.6px solid var(--accent); border-radius: 3px;
  vertical-align: -1px; background: #fff;
}
blockquote {
  margin: 10px 0; padding: 7px 14px; background: var(--soft); color: var(--ink);
  border-inline-start: 4px solid var(--accent); border-radius: 8px; break-inside: avoid;
}
blockquote p { margin: 3px 0; }
code {
  font-family: 'JetBrains Mono', 'Vazirmatn', monospace; font-size: .84em;
  background: #f1f4f7; border: 1px solid #e3e8ee; border-radius: 5px; padding: 0 .32em;
  direction: ltr; unicode-bidi: isolate; overflow-wrap: break-word;
}
code, pre { font-variant-ligatures: none; font-feature-settings: "liga" 0, "calt" 0; }
code.short { white-space: nowrap; }
pre {
  direction: ltr; text-align: left; background: var(--code-bg); color: #e6edf3;
  border-radius: 10px; padding: 11px 14px; margin: 10px 0; font-size: 8.4pt; line-height: 1.6;
  white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; border: 1px solid #1e293b;
  unicode-bidi: plaintext;
}
pre code { background: none; border: 0; padding: 0; color: inherit; font-size: inherit; unicode-bidi: plaintext; white-space: inherit; }
pre .bidi { direction: rtl; unicode-bidi: isolate; font-family: 'Vazirmatn', sans-serif; font-style: normal; }
table {
  width: 100%; border-collapse: separate; border-spacing: 0; margin: 10px 0;
  border: 1px solid var(--line); border-radius: 9px; overflow: hidden; font-size: 9.2pt; line-height: 1.7;
}
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
th { background: var(--soft); color: var(--strong); font-weight: 800; text-align: right; padding: 6px 9px; border-bottom: 1px solid var(--line); }
td { padding: 5px 9px; border-bottom: 1px solid #eef1f4; vertical-align: top; }
tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) td { background: #fafbfc; }
.hljs-comment, .hljs-quote, .hljs-meta { color: #8b98a9; font-style: italic; }
.hljs-keyword, .hljs-selector-tag, .hljs-literal, .hljs-doctag { color: #ff7b72; }
.hljs-string, .hljs-regexp, .hljs-addition { color: #a5d6ff; }
.hljs-number, .hljs-symbol, .hljs-bullet { color: #79c0ff; }
.hljs-title, .hljs-section, .hljs-title.function_ { color: #d2a8ff; }
.hljs-built_in, .hljs-type, .hljs-class { color: #ffa657; }
.hljs-attr, .hljs-attribute, .hljs-variable, .hljs-template-variable, .hljs-property, .hljs-name, .hljs-tag { color: #7ee787; }
`;
}

function htmlPage(body, doc, fonts) {
  return `<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<style>${fonts}</style>
<style>${pageCss(doc.theme, doc.stagePages)}</style>
</head>
<body>
${body}
<script>
  // Lift the first <h1> and its meta blockquote into a colored cover block.
  const h1 = document.querySelector('h1');
  if (h1) {
    const cover = document.createElement('header');
    cover.className = 'cover';
    const kicker = document.createElement('div');
    kicker.className = 'kicker';
    kicker.textContent = ${JSON.stringify(doc.kicker)};
    h1.before(cover);
    const next = h1.nextElementSibling;
    cover.append(kicker, h1);
    if (next && next.tagName === 'BLOCKQUOTE') cover.append(next);
  }
  // In PLAN files every stage heading ("مرحله‌ی …") gets a tinted bar.
  document.querySelectorAll('h2').forEach((h) => {
    if (/^(مرحله|⭐|🎤|📊)/.test(h.textContent.trim())) h.classList.add('stage');
  });
  // Inline code: short tokens (status codes, flags) never break; long ones may
  // break after URL/JSON punctuation instead of in the middle of a word.
  document.querySelectorAll(':not(pre) > code').forEach((c) => {
    const text = c.textContent;
    if (text.length < 26) { c.classList.add('short'); return; }
    c.textContent = '';
    text.split(/(?<=[\\/?&=,@])/).forEach((part, i) => {
      if (i) c.append(document.createElement('wbr'));
      c.append(part);
    });
  });
  // Persian comments inside code blocks: isolate the Persian part so it reads
  // right-to-left while the code and the comment marker stay left-to-right.
  const persian = /[\\u0600-\\u06FF]/;
  document.querySelectorAll('pre code').forEach((block) => {
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (!persian.test(node.nodeValue)) continue;
      const frag = document.createDocumentFragment();
      node.nodeValue.split('\\n').forEach((line, i) => {
        if (i) frag.append('\\n');
        const m = line.match(/^(.*?(?:^|\\s)(?:#|\\/\\/)\\s*)(.*)$/);
        if (m && persian.test(m[2])) {
          const span = document.createElement('span');
          span.className = 'bidi';
          span.textContent = m[2];
          frag.append(m[1], span);
        } else {
          frag.append(line);
        }
      });
      node.replaceWith(frag);
    }
  });
</script>
</body>
</html>`;
}

function footer(text) {
  return `<div style="width:100%;padding:0 14mm;font-family:Helvetica,Arial,sans-serif;font-size:7.4pt;color:#8a94a3;display:flex;justify-content:space-between;">
  <span>${text}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
</div>`;
}

const fonts = await fontFaceCss();
const browser = await puppeteer.launch({ executablePath: findChrome(), headless: true, args: ['--allow-file-access-from-files'] });
// KEEP_HTML=<dir> keeps the intermediate HTML files for debugging.
const keep = process.env.KEEP_HTML;
if (keep) await fs.mkdir(keep, { recursive: true });
const tmp = keep ? path.resolve(keep) : await fs.mkdtemp(path.join(os.tmpdir(), 'exam-pdf-'));
try {
  for (const doc of DOCS) {
    const srcPath = path.join(root, doc.src);
    if (!existsSync(srcPath)) { console.warn('skip (missing):', doc.src); continue; }
    const md = stripRtlWrappers(await fs.readFile(srcPath, 'utf8'));
    const htmlPath = path.join(tmp, path.basename(doc.out, '.pdf') + '.html');
    await fs.writeFile(htmlPath, htmlPage(marked.parse(md), doc, fonts), 'utf8');
    const page = await browser.newPage();
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const outPath = path.join(root, doc.out);
    await fs.mkdir(path.dirname(outPath), { recursive: true });
    await page.pdf({
      path: outPath,
      format: 'A4',
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: '<span></span>',
      footerTemplate: footer(doc.footer),
      margin: { top: '14mm', bottom: '16mm', left: '14mm', right: '14mm' },
    });
    await page.close();
    console.log('built', doc.out);
  }
} finally {
  await browser.close();
  if (!keep) await fs.rm(tmp, { recursive: true, force: true });
}
