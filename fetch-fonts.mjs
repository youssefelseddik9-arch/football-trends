import { writeFile, mkdir, stat } from 'fs/promises';
import { existsSync } from 'fs';

const ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36';
const cssUrl = 'https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400&family=Cairo:wght@400;500&display=swap';

if (!existsSync('fonts')) await mkdir('fonts');

let css = await (await fetch(cssUrl, { headers: { 'User-Agent': ua } })).text();

// Extract all woff2 URLs in order, download to fonts/ with sequential names
const urlRe = /url\((https:\/\/fonts\.gstatic\.com\/[^)]+\.woff2)\)/g;
const urls = [...new Set([...css.matchAll(urlRe)].map(m => m[1]))];
console.log(`Found ${urls.length} unique woff2 files`);

let i = 0;
const urlToLocal = {};
for (const u of urls) {
  i++;
  const name = `f${i}.woff2`;
  const buf = await (await fetch(u)).arrayBuffer();
  await writeFile(`fonts/${name}`, Buffer.from(buf));
  urlToLocal[u] = `/fonts/${name}`;
  console.log(`  ${name} = ${(buf.byteLength/1024).toFixed(1)}KB`);
}

// Rewrite CSS to use local paths
for (const [u, local] of Object.entries(urlToLocal)) {
  css = css.replaceAll(u, local);
}

await writeFile('css/fonts.css', css + '\n');
console.log('Wrote css/fonts.css');
