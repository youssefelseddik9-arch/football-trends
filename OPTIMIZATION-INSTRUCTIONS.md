# ══════ تعليمات تحويل الصور وتحميل الخطوط ══════

> اقرأ هذا الملف بالكامل قبل التنفيذ. كل الأوامر تُنفّذ من جذر المشروع (`C:\Users\HP\Desktop\messi-article`).

---

## 🅰️ تحويل الصور إلى AVIF + WebP

لدينا 5 صور JPG أصلية داخل مجلد `images/`:

| الملف الأصلي (JPG) | الأبعاد | المطلوب            |
|--------------------|---------|--------------------|
| `hero.jpg`         | 1200x896 | `.avif` + `.webp` |
| `press-conference.jpg` | 896x1200 | `.avif` + `.webp` |
| `celebration-contrast.jpg` | 896x1200 | `.avif` + `.webp` |
| `walking-away.jpg`  | 1200x1200 | `.avif` + `.webp` |
| `world-cup-trophy.jpg` | 896x1200 | `.avif` + `.webp` |

### الخيار 1: Sharp عبر Node.js (الأفضل جودة/حجم) ✅ موصى به

تأكد أولاً من تثبيت Node.js 18+ ثم نفّذ:

```powershell
# 1) ثبّت Sharp محلياً إن لم يكن مثبتاً
npm install sharp --save-dev

# 2) أنشئ ملف convert-images.mjs في جذر المشروع
# (استخدم محررك أو الأمر التالي لإنشائه)
```

أنشئ الملف `convert-images.mjs` بهذا المحتوى:

```javascript
import sharp from 'sharp';
import { readdir, writeFile, access } from 'fs/promises';
import { existsSync } from 'fs';

const imgs = [
  { src: 'images/hero.jpg',              w: 1200, h: 896  },
  { src: 'images/press-conference.jpg',   w: 896,  h: 1200 },
  { src: 'images/celebration-contrast.jpg', w: 896, h: 1200 },
  { src: 'images/walking-away.jpg',       w: 1200, h: 1200 },
  { src: 'images/world-cup-trophy.jpg',   w: 896,  h: 1200 }
];

for (const { src, w, h } of imgs) {
  const base = src.replace(/\.jpg$/, '');
  // WebP — جودة 80 (توازن مثالي)
  await sharp(src)
    .resize({ width: w, height: h, fit: 'cover', position: 'centre' })
    .webp({ quality: 80, method: 6 })
    .toFile(base + '.webp');
  // AVIF — جودة 60 (أصغر حجم للجودة نفسها)
  await sharp(src)
    .resize({ width: w, height: h, fit: 'cover', position: 'centre' })
    .avif({ quality: 60, effort: 4 })
    .toFile(base + '.avif');
  console.log('✓', base, '→ AVIF + WebP');
}
console.log('تم تحويل كل الصور بنجاح.');
```

ثم شغّل:

```powershell
node convert-images.mjs
```

نتيجة المتوقع:
```
✓ images/hero → AVIF + WebP
✓ images/press-conference → AVIF + WebP
✓ images/celebration-contrast → AVIF + WebP
✓ images/walking-away → AVIF + WebP
✓ images/world-cup-trophy → AVIF + WebP
تم تحويل كل الصور بنجاح.
```

### الخيار 2: باستخدام cwebp + ImageMagick (يدوياً)

إن لم يكن Node متاحاً، استخدم أدوات Google وImageMagick:

```powershell
# ── تثبيت cwebp (Windows) ──
# حمّله من: https://developers.google.com/speed/webp/download
# ثم أضف مساره إلى PATH

# WebP بجودة 80 لكل الصور (الأبعاد محفوظة تلقائياً من المصدر)
cwebp -q 80 images\hero.jpg               -o images\hero.webp
cwebp -q 80 images\press-conference.jpg  -o images\press-conference.webp
cwebp -q 80 images\celebration-contrast.jpg -o images\celebration-contrast.webp
cwebp -q 80 images\walking-away.jpg      -o images\walking-away.webp
cwebp -q 80 images\world-cup-trophy.jpg  -o images\world-cup-trophy.webp
```

لإنشاء AVIF تحتاج ImageMagick 7+:

```powershell
# ── تثبيت ImageMagick 7 (Windows) ──
# حمّله من: https://imagemagick.org/script/download.php#windows
# وأضف مساره إلى PATH

magick images\hero.jpg               -resize 1200x896^ -gravity center -extent 1200x896 -quality 60 images\hero.avif
magick images\press-conference.jpg   -resize 896x1200^ -gravity center -extent 896x1200 -quality 60 images\press-conference.avif
magick images\celebration-contrast.jpg -resize 896x1200^ -gravity center -extent 896x1200 -quality 60 images\celebration-contrast.avif
magick images\walking-away.jpg       -resize 1200x1200^ -gravity center -extent 1200x1200 -quality 60 images\walking-away.avif
magick images\world-cup-trophy.jpg   -resize 896x1200^ -gravity center -extent 896x1200 -quality 60 images\world-cup-trophy.avif
```

> ملاحظة: AVIF في ImageMagick يتطلب إصداراً مبني بـ libbrotli و libavif. لو فشل، استخدم Sharp (الخيار 1).

---

## 🅱️ تحميل الخطوط محلياً (Amiri + Cairo)

الموقع يستخدم خطّين من جوجل:
- **Amiri** (400, 700, 400-italic) — عربي للعناوين والاقتباسات
- **Cairo** (400, 500) — عربي للنصوص

يجب أن تكون الملفات بتنسيق `.woff2` فقط (أصغر وأسرع)، وأن نحمّل النسخ المُقَلّصة (subset) للعربية واللاتينية فقط.

### الطريقة 1: باستخدام google-webfonts-helper (موصى بها بصراحة) ✅

1. افتح: https://gwfh.mranftl.com/fonts
2. ابحث عن **Amiri**:
   - اختر الأوزان: `Regular (400)`, `Bold (700)`, `Italic (400)`
   - اختر اللغات (Character sets): `Arabic` + `Latin`
   - صفحة "Copy CSS" → نسخ قواعد `@font-face`
   - زر "Download .zip" → فكّ الضغط → ستجد ملفات `.woff2`
3. أعِد تسمية الملفات وضعها في `fonts/`:
   ```
   Amiri-Regular.woff2     → fonts/amiri-regular.woff2
   Amiri-Bold.woff2        → fonts/amiri-bold.woff2
   Amiri-Italic.woff2      → fonts/amiri-italic.woff2
   ```
4. ابحث عن **Cairo**:
   - اختر الأوزان: `Regular (400)`, `Medium (500)`
   - اختر اللغات: `Arabic` + `Latin`
   - حمّل وأعد التسمية:
   ```
   Cairo-Regular.woff2     → fonts/cairo-regular.woff2
   Cairo-Medium.woff2      → fonts/cairo-medium.woff2
   ```

### الطريقة 2: سكربت PowerShell تلقائي مباشر

أنشئ مجلد `fonts/`، ثم نفّذ سكربت يحلل Google Fonts CSS ويحمّل ملفات woff2:

```powershell
# إنشاء المجلد إن لم يكن موجوداً
New-Item -ItemType Directory -Path "fonts" -Force | Out-Null

# كرّر هذه العملية لكل ملف (المسارات تختلف حسب نسخة الخط)
# مثال لـ Amiri Regular (عربي + لاتيني):
$userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
# 1) اجلب CSS من جوجل لمعرفة روابط woff2 الفعلية
$cssUrl = "https://fonts.googleapis.com/css2?family=Amiri:ital,wght@0,400;0,700;1,400&family=Cairo:wght@400;500&display=swap"
$css = Invoke-WebRequest -Uri $cssUrl -UseBasicParsing -Headers @{ "User-Agent" = $userAgent }
$css.Content | Out-File -FilePath "fonts_raw.css" -Encoding utf8
# 2) ستجد داخل fonts_raw.css روابط مثل:
#    src: url(https://fonts.gstatic.com/s/amiri/v27/Amiri-Regular.woff2) format('woff2');
#    انسخ كل رابط يدوياً ونزّل الملف المقابل
```

روابط أمثلة واقعية (يجب التحقق من نسختها عند التحميل):

```powershell
# ── Amiri (تأكد من الرابط الفعلي من fonts_raw.css) ──
$amiri_reg = "https://fonts.gstatic.com/s/amiri/v27/Amiri-Regular.woff2"
$amiri_bold = "https://fonts.gstatic.com/s/amiri/v27/Amiri-Bold.woff2"
$amiri_ital = "https://fonts.gstatic.com/s/amiri/v27/Amiri-Italic.woff2"

# ── Cairo ──
$cairo_reg = "https://fonts.gstatic.com/s/cairo/v28/Cairo-Regular.woff2"
$cairo_med = "https://fonts.gstatic.com/s/cairo/v28/Cairo-Medium.woff2"

Invoke-WebRequest -Uri $amiri_reg -OutFile "fonts\amiri-regular.woff2"
Invoke-WebRequest -Uri $amiri_bold -OutFile "fonts\amiri-bold.woff2"
Invoke-WebRequest -Uri $amiri_ital -OutFile "fonts\amiri-italic.woff2"
Invoke-WebRequest -Uri $cairo_reg -OutFile "fonts\cairo-regular.woff2"
Invoke-WebRequest -Uri $cairo_med -OutFile "fonts\cairo-medium.woff2"
```

> تحذير: أرقام الإصدارات (`v27`, `v28`) تتغيّر مع الزمن، فإذا فشل التحميل (خطأ 404)، حمّل CSS أولاً واستخرج الرابط الفعلي ثم استبدله.

### الطريقة 3: باستخدام fonttools + Brotli للتحكم الكامل

لإنشاء ملفات مُقَلّصة ومضغوطة بأقصى درجة (متطلب Python):

```powershell
pip install fonttools brotli zopfli

# تقليل حجم الخط (حذف الصفات غير الضرورية) ثم ضغط WOFF2
pyftsubset "Amiri-Regular.ttf" --unicodes="U+0000-00FF,U+0600-06FF,U+200C-200D,unicode" --output-file="fonts/amiri-regular.woff2" --flavor=woff2 --layout-features="*"
```

### التحقق

بعد التحميل، يجب أن يكون هيكل المشروع:

```
messi-article/
├── fonts/
│   ├── amiri-regular.woff2
│   ├── amiri-bold.woff2
│   ├── amiri-italic.woff2
│   ├── cairo-regular.woff2
│   └── cairo-medium.woff2
├── images/
│   ├── hero.jpg (موجود أصلاً)
│   ├── hero.avif  ← جديد
│   ├── hero.webp   ← جديد
│   ├── press-conference.jpg (موجود أصلاً)
│   ├── press-conference.avif
│   ├── press-conference.webp
│   ├── celebration-contrast.jpg (موجود أصلاً)
│   ├── celebration-contrast.avif
│   ├── celebration-contrast.webp
│   ├── walking-away.jpg (موجود أصلاً)
│   ├── walking-away.avif
│   ├── walking-away.webp
│   ├── world-cup-trophy.jpg (موجود أصلاً)
│   ├── world-cup-trophy.avif
│   └── world-cup-trophy.webp
├── css/
│   └── style.min.css (موجود)
├── netlify.toml (موجود)
└── index.html (موجود ومحدّث)
```

تأكد بأمر:

```powershell
Get-ChildItem -Recurse -File | Select-Object FullName, @{N='KB';E={[math]::Round($_.Length/1KB,1)}}
```

---

## ⚡ ال Deploy على Netlify

```powershell
# إن لم يكن git مُهيّأ محلياً (المشروع ليس مستودع git):
git init
git add .
git commit -m "Performance: local fonts + AVIF/WebP + critical CSS + cache headers"

# ثم اربط بـ Netlify:
npm install -g netlify-cli
netlify login
netlify deploy --prod --dir=.
```

أو اسحب المجلد إلى واجهة Netlify (Build settings):
- Build command: (فارغ)
- Publish directory: `.`
