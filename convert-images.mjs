import sharp from 'sharp';

const imgs = [
  { src: 'images/hero.jpg',                 w: 1200, h: 896  },
  { src: 'images/press-conference.jpg',     w: 896,  h: 1200 },
  { src: 'images/celebration-contrast.jpg', w: 896,  h: 1200 },
  { src: 'images/walking-away.jpg',         w: 1200, h: 1200 },
  { src: 'images/world-cup-trophy.jpg',     w: 896,  h: 1200 }
];

for (const { src, w, h } of imgs) {
  const base = src.replace(/\.jpg$/, '');
  await sharp(src)
    .resize({ width: w, height: h, fit: 'cover', position: 'centre' })
    .webp({ quality: 80, method: 6 })
    .toFile(base + '.webp');
  await sharp(src)
    .resize({ width: w, height: h, fit: 'cover', position: 'centre' })
    .avif({ quality: 60, effort: 4 })
    .toFile(base + '.avif');
  const { size: webpSize } = await sharp(base + '.webp').metadata().then(m => ({ size: 0 })).catch(() => ({ size: 0 }));
  const fs = await import('fs/promises');
  const wst = (await fs.stat(base + '.webp')).size;
  const ast = (await fs.stat(base + '.avif')).size;
  console.log(`OK ${base}.webp=${(wst/1024).toFixed(1)}KB  ${base}.avif=${(ast/1024).toFixed(1)}KB`);
}
console.log('Done.');
