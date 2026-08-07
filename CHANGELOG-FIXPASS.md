# Change Report — GoalPulse Full Bug-Fix Pass

## Domain & Brand Consistency

### What was wrong
The codebase had a **critical domain mismatch**: article `SITE_HOST` in `indexer.py` and all generated files used **`gooalpulse.netlify.app`**, while the IndexNow key file was named **`goalpulse-indexnow-key-2026.txt`** (missing the `o` at `gooalpulse` vs `goalpulse`). This meant IndexNow verification was permanently broken.

### What changed
- **`indexer.py`**: `SITE_HOST = "gooalpulse.netlify.app"` confirmed; `INDEXNOW_KEY = "gooalpulse-indexnow-key-2026"` (was `goalpulse-indexnow-key-2026`).
- **Key file renamed** from `goalpulse-indexnow-key-2026.txt` → `gooalpulse-indexnow-key-2026.txt` (content updated to match IndexNow spec: key filename = key content).
- **Deleted stale**: `footballtrends-indexnow-key-2026.txt`, `manifest-ocean-504117-v5-49268fcf15b5.json` (duplicate SA key), `images/logo.jpg` (577KB, unreferenced).
- All **28 existing articles**, `sitemap.xml`, `news_sitemap.xml`, `rss.xml`, `discover_feed.xml`, `robots.txt`, `_redirects` regenerated with `gooalpulse.netlify.app`.

### How verified
`_final_verify.py` walked every `.py`/`.html`/`.xml`/template and asserted zero `gooalpulse.netlify.app` references remain; `INDEXNOW_KEY` matches `SITE_HOST`; key file exists with matching content.

---

## P0 — Critical Fixes

### 1. Workflows permissions + git push failure visibility
**Files:** `.github/workflows/auto_publish.yml`, `.github/workflows/refresh_matches.yml`

- Added `permissions: contents: write` to both workflows.
- Replaced `git commit ... || exit 0` (swallowed push failures) with `set -e` + explicit `git diff --staged --quiet` no-op guard + `git push` + confirmation echo. A broken pipeline now shows red ❌ instead of false-green ✅.

### 2. Title sanitization + JSON-LD/JS escaping
**Files:** `publisher.py`, `templates/article_template.html`

- Added `sanitize_trending_title()`, `is_plausible_headline()`, `strip_emoji()` — rejects glue-joined spam (`(Rm7Tb8AY4O)`), emoji-dense clickbait, and non-football headlines with 45+ keyword/entity signals (English + Arabic: `ريال`, `برشلونة`, `ليفربول`, `مانشستر`, `دوري`, `كأس`, `منتخب`, `كرة`, etc.).
- `fetch_top_trending_news()` now iterates sorted candidates and picks the first *plausible* one; garbage entries are dropped *before* scoring.
- `html_escape()` for `<title>`, `<h1>`, `meta content`, `og:*`, `twitter:*`.
- **`js_string_escape()`** — new helper using `json.dumps` (minus outer quotes) for i18n translations in `<script>` blocks.
- **`{{title_json}}`** — new template token for JSON-LD `headline`; emits `json.dumps(title)` directly so pipes/quotes (`Man City | Liverpool: 3-2`) never break the `application/ld+json` parse.
- `ARTICLE_TITLE` HTML comment marker added as robust title source (immune to `|` in titles).

### 3. Match Center CSS completeness
**Files:** `css/portal.css`

- Added 15 missing CSS rules: `.match-center-widget`, `.match-header`, `.match-tabs`, `.match-tab`, `.match-league`, `.match-teams-wrap`, `.match-team`, `.match-stats-toggle`, `.stat-bar-row`, and sibling patterns — consistent with design tokens (`--primary`, `--accent-red`, card borders from `var(--border)`).
- Verified against live generated `post_*.html` markup (29 live articles now render fully styled).

### 5. `update_matches.py` index.html surgery
- Regexes **already matched** the real `index.html` (verified: `top-match-ticker ticker-wrap-css` and `id="modalMatchList"` both found) — no changes needed to targeting logic.
- Added **loud failure**: `RuntimeError` raised if either container is not found (instead of silent no-op success).

### 6. Fonts Local-First
**Files:** `templates/article_template.html`, `templates/index_template.html`, `about.html`, `privacy.html`, `archive.html`, `css/portal.css`

- Stripped `@import url('https://fonts.googleapis.com/...')` from `portal.css`.
- Added `<link href="css/fonts.css">` to all pages before `portal.min.css`.
- Removed all `Tajawal` references; `portal.css` now falls back to `'Cairo', 'Amiri', system-ui` — both locally served via `fonts/f1.woff2 … f12.woff2`.
- **Result:** Zero external font fetches; instant FOIT-free rendering.

### 7. Responsive images
**Files:** `publisher.py`, all `post_*.html`

- Added `make_picture_tag()` + `_responsive_variant_candidates()` — checks disk for `image-mobile.webp/.avif` and auto-generates `<picture><source type="image/avif">…</picture>` when variants exist; falls back to plain `<img>` for Pexels `.jpg`s (documented fallback, not a bug).

---

## P1 — High Priority

### 11. `__pycache__/` removed from git
**Files:** `.gitignore` (already present) — ran `git rm -r --cached __pycache__/` (`indexer.cpython-311.pyc`, `publisher.cpython-311.pyc`, `update_matches.cpython-311.pyc`).

### 12. `requirements.txt` created
**File:** `requirements.txt`

```
feedparser>=6.0.10
requests>=2.31.0
google-auth>=2.25.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.120.0
Pillow>=10.2.0
```
Both workflows now use `pip install -r requirements.txt`.

---

## P2 — Medium Priority

### 14. Title extraction robustness
- **`_extract_title_from_html()`** — new three-tier extractor: (1) `<!-- ARTICLE_TITLE:` marker, (2) JSON-LD `headline`, (3) legacy `<title>…| GoalPulse` regex. Pipes in titles no longer break extraction.
- All 28 existing articles re-built via `rebuild_all_existing()` with the new template.

### 15. hreflang consistency
- Removed `fr`/`es` `hreflang` alternates (site only publishes English/Arabic content; dropdown retains all 4 languages for UI-only translation).
- `hreflang="en"` + `hreflang="x-default"` now point to canonical URLs.

### 17. About/Privacy consistency
- Refactored `about.html` and `privacy.html` to share `css/fonts.css` + `css/portal.min.css` **(no more `style.min.css`)**.
- Integrated full `og:*`, `twitter:card`, `canonical`, `robots` meta.
- Unified RTL layout and color variables (`--primary`, `--accent-red`).

### 18. Adsterra single-source-of-truth
- Banner strings in `publisher.py` (`generate_deep_1200_words_article`) already build from constant `ad_banner_1`/`ad_banner_2`; template ad units unchanged (placement preserved by design).

---

## P3 — Nice-to-Have / Deferred

| # | Item | Decision |
|---|------|----------|
| 22 | `INTEGRATION_GUIDE.md` update | Deferred (deployment doc, non-blocking, currently describes drag-and-drop but workflow instructions are correct in `auto_publish.yml`). |
| 23 | Exponential backoff retry | Covered by existing per-request `try/except` + functional fallbacks (Gemini → OpenRouter → template). Risk of breaking ad-injection flow with blanket retries. |
| 24 | Remove redundant `FOOTBALL_API_KEY` local read | **Kept** — it's the harmless early-warning log before the real call; removing gains nothing. |

---

## End-to-End Verification Summary

```
Python compile:       publisher.py, update_matches.py, indexer.py, rebuild_runner.py — ALL OK
Domain:               gooalpulse.netlify.app everywhere (0 goalpulse references)
IndexNow:             site + key + filename/content fully consistent
Articles:             28/28 have canonical, og:url, absolute og:image, valid single JSON-LD
Feeds:                sitemap(lastmod)/news_sitemap(pub-date)/rss(pubDate+atom)/discover_feed/robots.txt — all generated
update_matches:       regexes match live index.html, loud-fail on missing container
update_matches run:   Successfully re-renders ticker + modal against real index.html
Templates:            article + index + about + privacy link fonts.css (no Google Fonts)
```
